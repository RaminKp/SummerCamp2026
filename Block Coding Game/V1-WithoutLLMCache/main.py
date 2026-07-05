import threading
import time

import misty
import narrator
from maps         import MAPS
from detector     import run_detector, wait_for_tags_removed
from validator    import validate_and_message, ValidationResult
from game_logger  import GameLogger

GAME_DURATION = 8 * 60   # 480 seconds


def select_map():
    available = {mid: m for mid, m in MAPS.items() if m.checkpoints}
    if not available:
        raise RuntimeError("No maps with checkpoints defined in maps.py.")

    print("\nAvailable maps:")
    for mid, m in available.items():
        print(f"  [{mid}] {m.name}  ({len(m.checkpoints)} rounds)")

    while True:
        choice = input("\nSelect a map number: ").strip()
        if choice.isdigit() and int(choice) in available:
            return available[int(choice)]
        print(f"  Please enter one of: {list(available.keys())}")


def run_game():
    active_map = select_map()
    total      = len(active_map.checkpoints)

    player_name = input("Player name: ").strip() or "Unknown"
    logger = GameLogger(player_name=player_name, map_name=active_map.name)
    logger.start()
    print(f"  Logging this playthrough as Player ID #{logger.player_id}")

    print(f"\n{'='*50}")
    print(f"  MISTY MAZE GAME")
    print(f"  Map    : {active_map.name}")
    print(f"  Rounds : {total}")
    print(f"{'='*50}\n")

    misty.set_volume()
    misty.disable_hazards()

    # ── Timer setup ───────────────────────────────────────────────────────────
    # Timer starts once the intro speech finishes AND the first RFID tag is placed.
    first_tag_event = threading.Event()
    game_over_event = threading.Event()

    def _timer_thread():
        first_tag_event.wait()          # wait for first card placement
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
    misty.speak(intro["welcome"])
    misty.speak(f"Today's map is {active_map.name} with {total} rounds.")
    misty.speak(intro["how_to_play"])
    misty.speak(intro["good_luck"])

    # Prefetch narration for phase 1 while Misty finishes speaking
    cp0 = active_map.checkpoints[0]
    narrator.prefetch(1, total, cp0.location, cp0.sequence)

    # ── Game loop ─────────────────────────────────────────────────────────────
    for i, checkpoint in enumerate(active_map.checkpoints, 1):
        is_last = (i == total)

        # If timer already expired before this phase even starts, end now
        if game_over_event.is_set():
            break

        print(f"\n── Phase {i} of {total} ──────────────────────────────")
        print(f"   Location   : {checkpoint.location}")
        print(f"   Sequence   : {checkpoint.sequence}")
        print(f"   Drive map  : {checkpoint.drive_map}")
        print(f"   Return map : {checkpoint.return_map}")

        misty.led_ready()
        misty.speak(narrator.live(i, total, checkpoint.location, checkpoint.sequence, "hint"))

        attempts = 0
        while True:
            if game_over_event.is_set():
                break

            print(f"\n   [Attempt {attempts + 1}] Waiting for cards — press SPACE to submit...")
            logger.begin_checkpoint_attempt()

            scanned = run_detector(
                first_tag_event=first_tag_event,
                game_over_event=game_over_event,
            )

            # Timer expired mid-wait
            if game_over_event.is_set():
                break

            # Player aborted (pressed Enter with no cards)
            if scanned is None:
                print("\nGame aborted by player.")
                misty.speak("Game cancelled. See you next time!")
                misty.led(0, 0, 0)
                misty.enable_hazards()
                logger.end(outcome="Aborted")
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

                # Prefetch next phase's narration while driving
                if not is_last:
                    next_cp = active_map.checkpoints[i]
                    narrator.prefetch(i + 1, total, next_cp.location, next_cp.sequence)

                print(f"\n   Driving out...")
                misty.execute_drive_map(checkpoint.drive_map)

                if game_over_event.is_set():
                    break

                if checkpoint.return_map:
                    misty.speak(narrator.live(i, total, checkpoint.location,
                                              checkpoint.sequence, "returning"))
                    print(f"   Returning home...")
                    misty.execute_drive_map(checkpoint.return_map)
                    misty.speak("Remove all the RFID tags now", True)
                    wait_for_tags_removed()

                if game_over_event.is_set():
                    break

                if is_last:
                    print("\n   Final phase complete!")
                    misty.celebrate()
                else:
                    misty.speak(f"Great work! On to Round {i + 1}.")
                break

            elif result == ValidationResult.WRONG_ORDER:
                misty.led_error()
                misty.speak(narrator.live(i, total, checkpoint.location,
                                          checkpoint.sequence, "wrong_order"))
                misty.led_ready()
                print("   Try again.\n")

            else:
                misty.led_error()
                misty.speak(narrator.live(i, total, checkpoint.location,
                                          checkpoint.sequence, "wrong_ids"))
                misty.led_ready()
                print("   Try again.\n")

        if game_over_event.is_set():
            break

    # ── End of game ───────────────────────────────────────────────────────────
    if game_over_event.is_set():
        print(f"\n{'='*50}")
        print("  TIME'S UP — GAME OVER")
        print(f"{'='*50}\n")
        misty.led_error()
        misty.speak("Time is up! Goodbye everyone, you did a great job today!")
        misty.led(0, 0, 0)
        logger.end(outcome="TimeUp")
    else:
        print(f"\n{'='*50}")
        print("  GAME COMPLETE")
        print(f"{'='*50}\n")
        logger.end(outcome="Completed")

    misty.enable_hazards()


if __name__ == "__main__":
    run_game()
