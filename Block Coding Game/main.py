import misty
import narrator
from maps      import get_active_map
from detector  import run_detector
from validator import validate_and_message, ValidationResult


def run_game():
    active_map = get_active_map()
    total      = len(active_map.checkpoints)

    print(f"\n{'='*50}")
    print(f"  MISTY MAZE GAME")
    print(f"  Map : {active_map.name}")
    print(f"  Legs: {total} phases")
    print(f"{'='*50}\n")

    misty.disable_hazards()

    print("\nGenerating narration (this takes ~30 seconds)...")
    narration = narrator.pre_generate(active_map.checkpoints)

    misty.led_ready()
    misty.speak(
        f"Welcome to the Misty Maze! Today's map is {active_map.name}. "
        f"You have {total} legs to complete. Good luck!"
    )

    for i, checkpoint in enumerate(active_map.checkpoints, 1):
        is_last  = (i == total)

        msgs     = narration[i - 1]

        print(f"\n── Phase {i} of {total} ──────────────────────────────")
        print(f"   Location   : {checkpoint.location}")
        print(f"   Sequence   : {checkpoint.sequence}")
        print(f"   Drive map  : {checkpoint.drive_map}")
        print(f"   Return map : {checkpoint.return_map}")

        misty.led_ready()
        misty.speak(msgs["hint"])

        attempts = 0
        while True:
            print(f"\n   [Attempt {attempts + 1}] Waiting for cards — press ENTER to submit...")
            scanned = run_detector()

            if scanned is None:
                print("\nGame aborted by player.")
                misty.speak("Game cancelled. See you next time!")
                misty.led(0, 0, 0)
                misty.enable_hazards()
                return

            attempts += 1
            print(f"   Scanned : {scanned}")
            result, _ = validate_and_message(scanned, checkpoint.sequence)
            print(f"   Result  : {result.value}")

            if result == ValidationResult.CORRECT:
                misty.led_success()
                misty.speak(msgs["success"])

                print(f"\n   Driving out...")
                misty.execute_drive_map(checkpoint.drive_map)

                if checkpoint.return_map:
                    misty.speak(msgs["returning"])
                    print(f"   Returning home...")
                    misty.execute_drive_map(checkpoint.return_map)

                if is_last:
                    print("\n   Final phase complete!")
                    misty.celebrate()
                else:
                    misty.speak(f"Great work! On to leg {i + 1}.")
                break

            elif result == ValidationResult.WRONG_ORDER:
                misty.led_error()
                misty.speak(msgs["wrong_order"])
                misty.led_ready()
                print("   Try again.\n")

            else:
                misty.led_error()
                misty.speak(msgs["wrong_ids"])
                misty.led_ready()
                print("   Try again.\n")

    print(f"\n{'='*50}")
    print("  GAME COMPLETE")
    print(f"{'='*50}\n")
    misty.enable_hazards()


if __name__ == "__main__":
    run_game()