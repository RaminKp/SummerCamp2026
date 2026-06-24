from enum import Enum


# ── Result types ──────────────────────────────────────────────────────────────

class ValidationResult(Enum):
    CORRECT     = "CORRECT"      # right IDs, right order
    WRONG_ORDER = "WRONG_ORDER"  # right IDs, wrong order
    WRONG_IDS   = "WRONG_IDS"    # IDs don't match the expected set


# ── Feedback messages (Misty will speak these) ────────────────────────────────

MESSAGES = {
    ValidationResult.CORRECT: (
        "Sequence confirmed! Let's go!"
    ),
    ValidationResult.WRONG_ORDER: (
        "You have the right numbers, but not in the right order. "
        "Give it another go!"
    ),
    ValidationResult.WRONG_IDS: (
        "I don't recognise that sequence. "
        "Make sure you're using the right cards!"
    ),
}


# ── Core validator ────────────────────────────────────────────────────────────

def validate(scanned: list[int], correct: list[int]) -> ValidationResult:
    """
    Compare the player's scanned sequence against the correct sequence
    for the active map.

    Args:
        scanned: ordered list of ArUco IDs the player placed, e.g. [3, 1, 4]
        correct: the expected sequence for the active map, e.g. [1, 3, 4]

    Returns:
        A ValidationResult enum value.
    """
    if scanned == correct:
        return ValidationResult.CORRECT

    if sorted(scanned) == sorted(correct):
        return ValidationResult.WRONG_ORDER

    return ValidationResult.WRONG_IDS


def get_message(result: ValidationResult) -> str:
    """Return the speech string Misty should say for a given result."""
    return MESSAGES[result]


def validate_and_message(scanned: list[int], correct: list[int]) -> tuple[ValidationResult, str]:
    """
    Convenience function — validate and return both the result and
    the message in one call.

    Usage:
        result, message = validate_and_message(scanned_ids, correct_sequence)
    """
    result = validate(scanned, correct)
    return result, get_message(result)


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    correct = [3, 1, 4, 1, 5]

    test_cases = [
        ([3, 1, 4, 1, 5], "Exact match"),
        ([1, 3, 4, 5, 1], "Right IDs, wrong order"),
        ([9, 8, 7, 6, 5], "Completely wrong IDs"),
        ([3, 1, 4, 2, 5], "One wrong ID"),
        ([3, 1, 4],       "Subset of correct IDs"),
    ]

    print(f"Correct sequence: {correct}\n")
    print(f"{'Input':<25} {'Scenario':<30} {'Result':<15} Message")
    print("-" * 100)

    for scanned, scenario in test_cases:
        result, message = validate_and_message(scanned, correct)
        print(f"{str(scanned):<25} {scenario:<30} {result.value:<15} {message}")
