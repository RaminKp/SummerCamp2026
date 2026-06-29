from dataclasses import dataclass, field

from misty import turn_180


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class Checkpoint:
    sequence:   list[int]
    hint:       str
    drive_map:  list[tuple]
    return_map: list[tuple] = field(default_factory=list)
    location:   str = "destination"


@dataclass
class Map:
    name:        str
    checkpoints: list[Checkpoint]


# ── ✏️  EDIT HERE ─────────────────────────────────────────────────────────────

DISTANCE = 30
TURN     = 90

MAPS: dict[int, Map] = {
    1: Map(
        name = "Map 1 — Out and Back",
        checkpoints = [

            # Phase 1: forward, forward
            Checkpoint(
                sequence   = [1, 1],
                hint       = "Leg one — place two cards to send me forward.",
                drive_map  = [
                    ("forward",  DISTANCE),
                    ("forward",  DISTANCE),
                ],
                return_map = [
                    ("turn_180",),
                    ("forward",  DISTANCE),
                    ("forward",  DISTANCE),
                    ("turn_180",),
                ],
            ),

            # Phase 2: forward, left, forward, left, forward
            Checkpoint(
                sequence   = [1, 2, 1, 2, 1],
                hint       = "Leg two — five cards. Two left turns! Heading to the supermarket.",
                location   = "supermarket",
                drive_map  = [
                    ("forward",   DISTANCE),
                    ("turn_left", TURN),
                    ("forward",   DISTANCE),
                    ("turn_left", TURN),
                    ("forward",   DISTANCE),
                ],
                return_map = [
                    ("turn_180",),
                    ("forward",    DISTANCE),
                    ("turn_right", TURN),
                    ("forward",    DISTANCE),
                    ("turn_right", TURN),
                    ("forward",    DISTANCE),
                    ("turn_180",),
                ],
            ),

            # Phase 3: forward, left, forward, right, forward
            Checkpoint(
                sequence   = [1, 2, 1, 3, 1],
                hint       = "Leg three — five cards. A left then a right turn!",
                drive_map  = [
                    ("forward",    DISTANCE),
                    ("turn_left",  TURN),
                    ("forward",    DISTANCE),
                    ("turn_right", TURN),
                    ("forward",    DISTANCE),
                ],
                return_map = [
                    ("turn_180",),
                    ("forward",    DISTANCE),
                    ("turn_left",  TURN),
                    ("forward",    DISTANCE),
                    ("turn_right", TURN),
                    ("forward",    DISTANCE),
                    ("turn_180",),
                ],
            ),

            # Phase 4: forward, left, forward, forward, left, forward
            Checkpoint(
                sequence   = [1, 2, 1, 1, 2, 1],
                hint       = "Leg four — six cards. Watch for the double forward! Heading to school.",
                location   = "school",
                drive_map  = [
                    ("forward",   DISTANCE),
                    ("turn_left", TURN),
                    ("forward",   DISTANCE),
                    ("forward",   DISTANCE),
                    ("turn_left", TURN),
                    ("forward",   DISTANCE),
                ],
                return_map = [
                    ("turn_180",),
                    ("forward",    DISTANCE),
                    ("turn_right", TURN),
                    ("forward",    DISTANCE),
                    ("forward",    DISTANCE),
                    ("turn_right", TURN),
                    ("forward",    DISTANCE),
                    ("turn_180",),
                ],
            ),

            # Phase 5: forward, left, forward, forward, right, forward
            Checkpoint(
                sequence   = [1, 2, 1, 1, 3, 1],
                hint       = "Final leg — six cards. Double forward then a right turn!",
                drive_map  = [
                    ("forward",    DISTANCE),
                    ("turn_left",  TURN),
                    ("forward",    DISTANCE),
                    ("forward",    DISTANCE),
                    ("turn_right", TURN),
                    ("forward",    DISTANCE),
                ],
                return_map = [
                    ("turn_180",),
                    ("forward",    DISTANCE),
                    ("turn_left",  TURN),
                    ("forward",    DISTANCE),
                    ("forward",    DISTANCE),
                    ("turn_right", TURN),
                    ("forward",    DISTANCE),
                    ("turn_180",),
                ],
            ),
        ],
    ),

    2: Map(
        name = "Map 2 — Placeholder",
        checkpoints = [],
    ),
}

ACTIVE_MAP_ID = 1


def get_active_map() -> Map:
    if ACTIVE_MAP_ID not in MAPS:
        raise ValueError(
            f"ACTIVE_MAP_ID={ACTIVE_MAP_ID} not found. "
            f"Available IDs: {list(MAPS.keys())}"
        )
    return MAPS[ACTIVE_MAP_ID]


if __name__ == "__main__":
    for map_id, m in MAPS.items():
        marker = " ← active" if map_id == ACTIVE_MAP_ID else ""
        print(f"[{map_id}] {m.name}{marker}")
        for i, cp in enumerate(m.checkpoints, 1):
            print(f"  Phase {i}: sequence={cp.sequence}")
            print(f"    drive_map  = {cp.drive_map}")
            print(f"    return_map = {cp.return_map}")
        print()