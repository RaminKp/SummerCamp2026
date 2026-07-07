import threading
import time

import misty
import narrator
import id_scanner
from recorder     import GameRecorder
from maps         import MAPS, select_checkpoints, Checkpoint
from detector     import run_detector, wait_for_tags_removed
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
    """Bring Misty back to Home(0,0) after a timer expiry.

    drove_out: True when drive_map ran but return_map hasn't yet — execute
               return_map first, then home_on_timeout (Map 2 only).
    """
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
    recorder = GameRecorder(session_id=logger.session_id)
    recorder.start()

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
    intro = narrator.load_intro()

    misty.led_ready()
    misty.speak(f"Welcome {p1} and {p2}! I am so excited to play with you today!")
    misty.speak(f"Today's map is {active_map.name} with {total} rounds.")
    misty.speak(intro["how_to_play"])
    misty.speak(intro["good_luck"])

    narrator.prefetch(1, total, checkpoints[0].location, checkpoints[0].sequence)

    # ── Game loop ─────────────────────────────────────────────────────────────
    outcome              = "Completed"
    last_completed_cp: Checkpoint | None = None   # Map 2: last fully-returned cp

    for i, checkpoint in enumerate(checkpoints, 1):
        is_last = (i == total)

        if game_over_event.is_set():
            outcome = "TimeUp"
            break

        print(f"\n── Round {i} of {total} ──────────────────────────────")
        print(f"   Location   : {checkpoint.location}")
        print(f"   Sequence   : {checkpoint.sequence}")

        misty.led_ready()
        misty.speak(narrator.live(i, total, checkpoint.location, checkpoint.sequence, "hint"))

        attempts = 0
        while True:
            if game_over_event.is_set():
                outcome = "TimeUp"
                break

            print(f"\n   [Attempt {attempts + 1}] Waiting for cards — press SPACE to submit...")
            logger.begin_checkpoint_attempt()

            scanned = run_detector(
                first_tag_event=first_tag_event,
                game_over_event=game_over_event,
                inactivity_callback=lambda: misty.speak(
                    "Don't forget to place your cards on the readers!"
                ),
                inactivity_secs=30.0,
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
                recorder.stop()
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

                if not is_last:
                    next_cp = checkpoints[i]
                    narrator.prefetch(i + 1, total, next_cp.location, next_cp.sequence)

                print(f"\n   Driving out...")
                misty.execute_drive_map(checkpoint.drive_map)

                if game_over_event.is_set():
                    _return_misty_home(checkpoint, map_id, drove_out=True)
                    outcome = "TimeUp"
                    break

                if checkpoint.return_map:
                    misty.speak(narrator.live(i, total, checkpoint.location,
                                              checkpoint.sequence, "returning"))
                    print(f"   Returning...")
                    misty.execute_drive_map(checkpoint.return_map)
                    last_completed_cp = checkpoint

                    if game_over_event.is_set():
                        _return_misty_home(checkpoint, map_id, drove_out=False)
                        outcome = "TimeUp"
                        break

                    removal = wait_for_tags_removed(speak_fn=misty.speak)
                    if removal == "powerdown":
                        print("\n  [RFID] Tags not removed — ending session.")
                        misty.speak("Please remove all cards and come back for another game!")
                        misty.led(0, 0, 0)
                        misty.enable_hazards()
                        logger.end(outcome="RFIDTimeout")
                        recorder.stop()
                        id_scanner.update_play_counts(players)
                        return

                if game_over_event.is_set():
                    outcome = "TimeUp"
                    break

                if is_last:
                    print("\n   Final round complete!")
                    misty.celebrate()
                else:
                    misty.speak(f"Great work! On to Round {i + 1}.")
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
        # Map 2: if timer fired while Misty was waiting for RFID input (not
        # mid-drive), she is at last_completed_cp's resting position — drive home.
        if map_id == 2 and last_completed_cp is not None:
            _return_misty_home(last_completed_cp, map_id, drove_out=False)
        misty.led_error()
        misty.speak(f"Time is up! Amazing effort {p1} and {p2}. Goodbye!")
        misty.led(0, 0, 0)
        logger.end(outcome="TimeUp")
    else:
        print(f"\n{'='*50}")
        print("  GAME COMPLETE")
        print(f"{'='*50}\n")
        logger.end(outcome="Completed")

    recorder.stop()
    misty.enable_hazards()
    id_scanner.update_play_counts(players)


def run_forever():
    """Main loop: scan IDs → play game → repeat."""
    print("\n" + "="*50)
    print("  MISTY MAZE — STARTING UP")
    print("="*50)

    map_id, active_map = select_map()

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
        time.sleep(3)


if __name__ == "__main__":
    run_forever()
