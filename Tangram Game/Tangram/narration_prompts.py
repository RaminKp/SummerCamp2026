"""
narration_prompts.py
====================

Single source of truth for the offline narration cache.

Each entry below represents ONE spoken line the robot may say during a tangram
round. The same dict is used by:

  * generate_narration_cache.py - rephrases each DEFAULT line into N variations
    with an LLM and writes them to narration_cache.json.
  * narration.py               - loads that JSON at game startup and uses the
    DEFAULTS here as the in-code fallback whenever the cache is missing a key
    (or the cache file itself isn't present).

Placeholders use Python str.format() syntax (e.g. {name}, {score}). The
generator instructs the LLM to preserve them verbatim and rejects any
variation that loses them, so the runtime can always safely call .format().
"""

# --------------------------------------------------------------------------
#  LLM persona (used for every generation call)
# --------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are writing one short line of spoken dialogue for a friendly robot "
    "that helps children aged 6 to 12 build tangram puzzles. The robot speaks "
    "the line aloud through text-to-speech, so:\n"
    " - Keep it ONE or TWO short sentences (max ~30 words total).\n"
    " - Be warm, encouraging, and age-appropriate. Never sarcastic, never scolding.\n"
    " - Use plain everyday words a 6-year-old understands.\n"
    " - Do NOT use emojis, lists, bullet points, parentheses, stage directions,\n"
    "   or surrounding quotation marks.\n"
    " - Output ONLY the line itself - no preamble like 'Here is...', no labels,\n"
    "   no commentary, no formatting."
)

# --------------------------------------------------------------------------
#  Hardcoded defaults  (also serve as the source line shown to the LLM)
# --------------------------------------------------------------------------
DEFAULTS = {
    # ---- intro / welcome ----
    "welcome":
        "Hello friends! Welcome to Tangram Quest! Let's build the {name} together!",
    "instructions":
        "Place the seven pieces inside the outline, then {button_word} and "
        "I'll check your work!",
    "timer_intro":
        "You have {duration} to build the {name}. Finish in time to earn a "
        "point. Ready, set, go!",

    # ---- buzzer / board feedback ----
    "buzz_no_board":
        "I can't see the board yet. Let's show all four corners!",
    "empty_board":
        "I don't see any pieces on the board yet. Put some on, then press "
        "the button!",
    "newly_correct_single":
        "Yes! {names} is in the right place!",
    "newly_correct_multi":
        "Wow, great teamwork! {names} are all in the perfect spot!",
    "progress":
        "Keep going - you already have {n} pieces right!",
    "rotate_single":
        "{names} is in the right spot - just give it a little turn!",
    "rotate_multi":
        "{names} are in the right spot - just give them a little turn!",
    "misplaced_single":
        "{names} needs to move to a different spot.",
    "misplaced_multi":
        "{names} need to move to a different spot.",

    # ---- hints ----
    "hint_no_board":
        "I can't see the board corners. Let's make sure all four corner "
        "markers are showing!",
    "hint_missing":
        "I don't see the {label} yet. Can you find it and place it?",
    "hint_misplaced":
        "The {label} is on the board, but it belongs in a different spot. "
        "Try moving it!",
    "hint_rotate":
        "The {label} is in the right place! Just give it a little turn.",
    "hint_all_good":
        "Everything looks great! Press the button to check!",

    # ---- inactivity nudges ----
    "nudge":
        "Don't be shy - put a piece on the board and give it a try!",

    # ---- timer reminders ----
    "time_left_minutes":
        "{n} minutes left! You're doing great!",
    "time_left_one_minute":
        "One minute left! Keep building!",
    "time_left_final":
        "Only {seconds} seconds left! Hurry, you can do it!",
    "time_up":
        "Time's up! You didn't finish this one in time, so no point this "
        "round. But you worked so hard - let's try again!",

    # ---- completion ----
    "complete_intro":
        "Incredible! You built the whole {name}! That was wonderful work!",
    "complete_with_timer":
        "You finished the {name} in time! That's one point! Your score is "
        "now {score}.",
    "complete_no_timer":
        "You built the whole {name}! That's one point! Your score is now "
        "{score}.",
    "goodbye":
        "Goodbye for now, and great job, builders! See you next time!",
}

# --------------------------------------------------------------------------
#  Placeholder vocabulary  (per-key rules surfaced to the LLM and validated
#  before a variation is accepted into the cache).
# --------------------------------------------------------------------------
PLACEHOLDERS = {
    "welcome":              ["{name}"],
    "instructions":         ["{button_word}"],
    "timer_intro":          ["{duration}", "{name}"],
    "newly_correct_single": ["{names}"],
    "newly_correct_multi":  ["{names}"],
    "progress":             ["{n}"],
    "rotate_single":        ["{names}"],
    "rotate_multi":         ["{names}"],
    "misplaced_single":     ["{names}"],
    "misplaced_multi":      ["{names}"],
    "hint_missing":         ["{label}"],
    "hint_misplaced":       ["{label}"],
    "hint_rotate":          ["{label}"],
    "time_left_minutes":    ["{n}"],
    "time_left_final":      ["{seconds}"],
    "complete_intro":       ["{name}"],
    "complete_with_timer":  ["{name}", "{score}"],
    "complete_no_timer":    ["{name}", "{score}"],
}

# --------------------------------------------------------------------------
#  Optional per-key style notes appended to the LLM prompt.
# --------------------------------------------------------------------------
STYLE_NOTES = {
    "newly_correct_single":
        "Celebrating ONE piece the child just placed correctly. Excited but brief.",
    "newly_correct_multi":
        "Celebrating two or more pieces placed correctly in the same press.",
    "rotate_single":
        "The piece is in the right SPOT but turned the wrong way; ask for a small turn.",
    "rotate_multi":
        "Same as rotate_single but for several pieces - use plural ('them', 'are').",
    "misplaced_single":
        "Gentle redirection: the piece is in the wrong location. Never scolding.",
    "misplaced_multi":
        "Plural form of misplaced_single.",
    "time_left_final":
        "Final warning before time runs out - urgent but still encouraging.",
    "time_up":
        "Sympathetic and upbeat. No shame, just inviting another try.",
    "nudge":
        "Spoken when the child has been still/quiet for a while. Inviting, not pushy.",
    "progress":
        "Encouraging mid-round status update. {n} is a small number (2-7).",
}


def build_user_prompt(key: str, n_so_far: int = 0) -> str:
    """Compose the per-key instruction sent as the 'user' message to Ollama."""
    default = DEFAULTS[key]
    lines = [
        "Rephrase this robot line for children aged 6 to 12:",
        "",
        f"Original: {default}",
    ]
    ph = PLACEHOLDERS.get(key, [])
    if ph:
        lines += [
            "",
            f"Your version MUST include {', '.join(ph)} exactly as written, "
            f"including the curly braces. They are template placeholders that "
            f"will be filled in at game time - do NOT translate or rename them.",
        ]
    note = STYLE_NOTES.get(key)
    if note:
        lines += ["", f"Note: {note}"]
    lines += [""]
    if n_so_far == 0:
        lines.append("Keep the meaning and tone; vary the wording.")
    else:
        lines.append(
            f"This is variation {n_so_far + 1}. Make it noticeably different "
            f"from the original (and any previous variations) in wording and "
            f"rhythm, while keeping the same meaning and tone."
        )
    lines += ["", "Your line:"]
    return "\n".join(lines)
