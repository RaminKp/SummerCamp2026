import threading
import time

import misty
import narrator
import id_scanner
from recorder     import GameRecorder
from maps         import MAPS, select_checkpoints, Checkpoint
from detector     import run_detector, wait_for_tags_removed, wait_for_button
from validator    import validate_and_message, ValidationResult
from game_logger  import GameLogger

GAME_DURATION = 8 * 60   # 480 seconds


def select_map():
    available = {mid: m for mid, m in MAPS.items() if m.checkpoints or m.paths}
    if not available:
        raise RuntimeError("No maps with checkpoints defined in maps.py.")

    print("\nAvailable maps:")
    for mid, m in available.items():
        print(f"  [{mid}] {m.name}  ({len(m.checkpoints)} checkpoints)")

    while True:
        choice = input("\nSelect a map number: ").strip()
        if choice.isdigit() and int(choice) in available:
            mid = int(choice)
            return mid, available[mid]
        print(f"  Please enter one of: {list(available.keys())}")


def _return_misty_home(cp: Checkpoint, map_id: int, drove_out: bool = False):
    """Bring Misty back to Home(0,0) after a timer expiry."""
    if drove_out and cp.return_map:
        misty.execute_drive_map(cp.return_map)
    if map_id == 2 and cp.home_on_timeout:
        misty.speak("Time is up! I am heading back home now.")
        misty.execute_drive_map(cp.home_on_timeout)


def run_game(map_id: int, active_map, players: list[dict]):
    checkpoints = select_checkpoints(active_map, n=3)
    total = len(checkpoints)
    p1    = players[0]["name"]
    p2    = players[1]["name"]

    logger   = GameLogger(players=players, map_name=active_map.name)
    logger.start()

    # Only record if every player has consent=true
    _record = not any(p.get("no_video") for p in players)
    if _record:
        recorder = GameRecorder(session_id=logger.session_id)
        recorder.start()
    else:
        recorder = None
        print("  [recorder] Skipped — one or more players have consent=false.")

    print(f"\n{'='*50}")
    print(f"  MISTY MAZE GAME")
    print(f"  Map     : {active_map.name}")
    print(f"  Players : {p1} & {p2}")
    print(f"  Rounds  : {total}")
    print(f"  Order   : {[cp.location for cp in checkpoints]}")
    print(f"{'='*50}\n")

    misty.set_volume()
    misty.disable_hazards()

    # ── Timer setup ───────────────────────────────────────────────────────────
    first_tag_event = threading.Event()
    game_over_event = threading.Event()

    def _timer_thread():
        first_tag_event.wait()
        print(f"\n  [TIMER] 8-minute game clock started.")
        game_over_event.wait(timeout=GAME_DURATION)
        if not game_over_event.is_set():
            print("\n  [TIMER] Time's up!")
            game_over_event.set()

    threading.Thread(target=_timer_thread, daemon=True).start()

    # ── Intro narration ───────────────────────────────────────────────────────
    print("\nLoading intro narration...")

    narrator.prefetch_all(checkpoints)

    misty.led_ready()
    misty.speak(f"Welcome {p1} and {p2}! I am SO excited to play with you today — let's gooo!")
    misty.speak(f"We are playing Misty Maze today — {total} missions ahead!")

    misty.speak(
        f"{p1} and {p2}, today we are going on {total} special missions to reach "
        "different destinations. I need your help to find the right path! "
        "Once each mission starts, use the cards to guide me step by step across the map. "
        "The Straight card moves me one cell ahead. Left and Right cards turn me in that direction. "
        "Please do not touch the black walls — they are part of the maze! "
        "Let's work together, choose the best route, and help me reach each destination. "
        "Ready, mission team? Let's gooooo!"
    )

    misty.head(pitch=0, yaw=0)   # neutral before turning to maze
    misty.speak("Let me take my position in the maze!")
    misty.turn_180()              # face the maze

    # ── Game loop ─────────────────────────────────────────────────────────────
    outcome              = "Completed"
    last_completed_cp: Checkpoint | None = None

    for i, checkpoint in enumerate(checkpoints, 1):
        is_last = (i == total)

        if game_over_event.is_set():
            outcome = "TimeUp"
            break

        print(f"\n── Mission {i} of {total} ──────────────────────────────")
        print(f"   Location   : {checkpoint.location}")
        print(f"   Sequence   : {checkpoint.sequence}")

        misty.led_ready()
        misty.speak(narrator.live(i, total, checkpoint.location, checkpoint.sequence, "hint"))
        misty.speak("Place your cards in the slots and press the green button when you are ready!")

        # Live per-card feedback
        _move_names = {1: "Straight", 2: "Turn Left", 3: "Turn Right"}
        _alerted_slots: set[int] = set()

        def _on_card_placed(slot_idx: int, game_id: int,
                            seq=checkpoint.sequence):
            if slot_idx in _alerted_slots:
                return
            if slot_idx >= len(seq) or game_id == 0:
                return
            if game_id != seq[slot_idx]:
                _alerted_slots.add(slot_idx)
                expected_name = _move_names.get(seq[slot_idx], "the right card")
                misty.speak(
                    f"Hmm, slot {slot_idx + 1} might be wrong! "
                    f"Try {expected_name} there!"
                )

        attempts = 0
        while True:
            if game_over_event.is_set():
                outcome = "TimeUp"
                break

            _alerted_slots.clear()
            print(f"\n   [Attempt {attempts + 1}] Waiting for cards — press green button to submit...")
            logger.begin_checkpoint_attempt()

            _location = checkpoint.location
            scanned = run_detector(
                first_tag_event=first_tag_event,
                game_over_event=game_over_event,
                inactivity_callback=lambda loc=_location: misty.speak(
                    f"Remember, I need to reach the {loc}! "
                    "Place your cards in the slots and press the green button!"
                ),
                inactivity_secs=10.0,
                card_placed_callback=_on_card_placed,
                no_cards_callback=lambda: misty.speak(
                    "I don't see any cards! Place your cards in the slots and try again."
                ),
            )

            if game_over_event.is_set():
                outcome = "TimeUp"
                break

            if scanned is None:
                print("\nGame aborted by player.")
                misty.speak("Game cancelled. See you next time!")
                misty.led(0, 0, 0)
                misty.enable_hazards()
                logger.end(outcome="Aborted")
                if recorder: recorder.stop()
                id_scanner.update_play_counts(players)
                return

            attempts += 1
            print(f"   Scanned : {scanned}")
            result, _ = validate_and_message(scanned, checkpoint.sequence)
            print(f"   Result  : {result.value}")
            logger.log_attempt(
                checkpoint_label=checkpoint.location,
                attempt_num=attempts,
                scanned=scanned,
                expected=checkpoint.sequence,
                result=result.value,
            )

            if result == ValidationResult.CORRECT:
                misty.led_success()
                misty.speak(narrator.live(i, total, checkpoint.location,
                                          checkpoint.sequence, "success"))

                print(f"\n   Driving out...")
                misty.execute_drive_map(checkpoint.drive_map)

                # ── Arrived at checkpoint ─────────────────────────────────
                misty.wave()
                misty.speak(narrator.live(i, total, checkpoint.location,
                                          checkpoint.sequence, "returning"))

                if game_over_event.is_set():
                    _return_misty_home(checkpoint, map_id, drove_out=True)
                    outcome = "TimeUp"
                    break

                if checkpoint.return_map:
                    # ── Happy journey home ────────────────────────────────
                    misty.speak("Woohoooo! Now I am heading back home — home sweet home, here I come!")
                    print(f"   Returning...")
                    misty.execute_drive_map(checkpoint.return_map)
                    last_completed_cp = checkpoint

                    if game_over_event.is_set():
                        _return_misty_home(checkpoint, map_id, drove_out=False)
                        outcome = "TimeUp"
                        break

                    # ── Back at home ──────────────────────────────────────
                    misty.wave()
                    misty.speak("YESSSSS! I am back at base! You are an INCREDIBLE mission team!")

                    # ── Remove cards ──────────────────────────────────────
                    removal = wait_for_tags_removed(speak_fn=misty.speak)
                    if removal == "powerdown":
                        print("\n  [RFID] Tags not removed — ending session.")
                        misty.speak("Please remove all cards and come back for another game!")
                        misty.led(0, 0, 0)
                        misty.enable_hazards()
                        logger.end(outcome="RFIDTimeout")
                        if recorder: recorder.stop()
                        id_scanner.update_play_counts(players)
                        return

                    # ── Place Misty in red box + buzzer ───────────────────
                    misty.speak(
                        "Now please place me in the red box and press the buzzer "
                        "when I am in position!"
                    )
                    wait_for_button(game_over_event=game_over_event)

                    if game_over_event.is_set():
                        outcome = "TimeUp"
                        break

                    misty.turn_180()  # face the maze

                if game_over_event.is_set():
                    outcome = "TimeUp"
                    break

                if is_last:
                    print("\n   Final mission complete!")
                    game_over_event.set()
                    misty.celebrate()
                else:
                    misty.speak(f"Woohoo! Great work, team! Get ready for Mission {i + 1} — let's keep going!")
                break

            elif result == ValidationResult.WRONG_ORDER:
                misty.led_error()
                misty.speak(narrator.live(i, total, checkpoint.location,
                                          checkpoint.sequence, "wrong_order"))
                misty.led_ready()

            else:
                misty.led_error()
                misty.speak(narrator.live(i, total, checkpoint.location,
                                          checkpoint.sequence, "wrong_ids"))
                misty.led_ready()

        if game_over_event.is_set():
            outcome = "TimeUp"
            break

    # ── End of game ───────────────────────────────────────────────────────────
    if outcome == "TimeUp":
        print(f"\n{'='*50}")
        print("  TIME'S UP — GAME OVER")
        print(f"{'='*50}\n")
        if map_id == 2 and last_completed_cp is not None:
            _return_misty_home(last_completed_cp, map_id, drove_out=False)
        misty.led_error()
        misty.turn_180()
        misty.head(pitch=-40, yaw=-45)
        misty.speak(f"Time is up! You were an AMAZING mission team, {p1} and {p2}!")
        misty.speak("See you next time — byeee!")
        misty.bye_gesture()
        misty.head(pitch=0, yaw=0)
        misty.led(0, 0, 0)
        logger.end(outcome="TimeUp")
    else:
        print(f"\n{'='*50}")
        print("  GAME COMPLETE")
        print(f"{'='*50}\n")
        logger.end(outcome="Completed")

    if recorder:
        recorder.stop()
    misty.enable_hazards()
    id_scanner.update_play_counts(players)

    # Final reset turn so run_forever always starts the between-game flow
    # with Misty in a known maze-facing orientation.
    misty.turn_180()


def run_forever():
    """Main loop: scan IDs → play game → repeat."""
    print("\n" + "="*50)
    print("  MISTY MAZE — STARTING UP")
    print("="*50)

    misty.connect_ws()

    map_id, active_map = select_map()

    misty.turn_180()
    misty.head(pitch=-40, yaw=-45)
    misty.speak("Hello! I am Misty and I am SO excited for today's missions!")
    misty.speak("When you are ready to play, press the green button to get started!")

    while True:
        players = id_scanner.wait_for_players(n=2)

        try:
            run_game(map_id, active_map, players)
        except Exception as e:
            print(f"\n[ERROR] Game crashed: {e}")
            misty.led_error()
            misty.speak("Oops, something went wrong. Please ask a grown-up for help.")

        print("\n  Game over. Ready for the next players!")
        misty.led_ready()
        # run_game leaves Misty facing the maze; turn to face kids for next check-in
        misty.turn_180()
        misty.head(pitch=-40, yaw=-45)
        misty.speak("That was AMAZING! Who is ready to play next?")
        misty.speak("Step up and show me your ID card!")
        time.sleep(3)


if __name__ == "__main__":
    run_forever()
