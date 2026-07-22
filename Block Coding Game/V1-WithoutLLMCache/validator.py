from enum import Enum


# ── Result types ──────────────────────────────────────────────────────────────

class ValidationResult(Enum):
    CORRECT     = "CORRECT"      # right cards, right order
    WRONG_COUNT = "WRONG_COUNT"  # wrong number of cards placed
    WRONG_SLOTS = "WRONG_SLOTS"  # right count, but some positions are wrong


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slots_phrase(slots: list[int]) -> str:
    """['2','4'] → 'slot 2 and slot 4';  ['1','3','5'] → 'slot 1, slot 3 and slot 5'."""
    labels = [f"slot {s}" for s in slots]
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + f" and {labels[-1]}"


# ── Core validator ────────────────────────────────────────────────────────────

def validate(scanned: list[int], correct: list[int]) -> ValidationResult:
    if scanned == correct:
        return ValidationResult.CORRECT
    if len(scanned) != len(correct):
        return ValidationResult.WRONG_COUNT
    return ValidationResult.WRONG_SLOTS


def get_message(result: ValidationResult,
                scanned: list[int], correct: list[int]) -> str:
    """Kid-facing feedback. Never reveals which card is correct — only that a
    slot is wrong, or how many cards are needed."""
    if result == ValidationResult.CORRECT:
        return "Sequence confirmed! Let's go!"

    if result == ValidationResult.WRONG_COUNT:
        need = len(correct)
        have = len(scanned)
        return (
            f"You placed {have} card{'s' if have != 1 else ''}, "
            f"but I need exactly {need} card{'s' if need != 1 else ''}. "
            "Let's try again!"
        )

    # WRONG_SLOTS — same count, some positions don't match
    wrong = [i + 1 for i in range(len(correct)) if scanned[i] != correct[i]]
    phrase = _slots_phrase(wrong)
    verb   = "is" if len(wrong) == 1 else "are"
    return (
        f"{phrase[0].upper()}{phrase[1:]} {verb} wrong. "
        "Try another card in those positions!"
    )


def validate_and_message(scanned: list[int],
                         correct: list[int]) -> tuple[ValidationResult, str]:
    result = validate(scanned, correct)
    return result, get_message(result, scanned, correct)


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    correct = [1, 3, 1, 2, 1]

    test_cases = [
        ([1, 3, 1, 2, 1], "Exact match"),
        ([1, 2, 1, 3, 1], "Right cards, wrong order"),
        ([1, 3, 1, 1, 1], "One slot wrong"),
        ([1, 3, 1],       "Too few cards"),
        ([1, 3, 1, 2, 1, 1], "Too many cards"),
    ]

    print(f"Correct sequence: {correct}\n")
    for scanned, scenario in test_cases:
        result, message = validate_and_message(scanned, correct)
        print(f"{str(scanned):<22} {scenario:<26} {result.value:<12} {message}")
