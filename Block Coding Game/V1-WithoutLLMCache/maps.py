import random
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
    map_id:      int = 0


# ── ✏️  EDIT HERE ─────────────────────────────────────────────────────────────

DISTANCE = 30
TURN     = 90

MAPS: dict[int, Map] = {
    1: Map(
        name   = "Map 1 — Out and Back",
        map_id = 1,
        checkpoints = [

            # Phase 1: School
            Checkpoint(
                sequence   = [1, 1],
                hint       = "Two cards forward to reach the School!",
                location   = "School",
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

            # Phase 2: Supermarket
            Checkpoint(
                sequence   = [1, 2, 1, 2, 1],
                hint       = "Five cards — two left turns to reach the Supermarket!",
                location   = "Supermarket",
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

            # Phase 3: Ice-cream Shop
            Checkpoint(
                sequence   = [1, 2, 1, 3, 1],
                hint       = "Five cards — a left then a right turn to the Ice-cream Shop!",
                location   = "Ice-cream Shop",
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

            # Phase 4: Restaurant
            Checkpoint(
                sequence   = [1, 2, 1, 1, 2, 1],
                hint       = "Six cards — watch for the double forward to the Restaurant!",
                location   = "Restaurant",
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

            # Phase 5: Space Center
            Checkpoint(
                sequence   = [1, 2, 1, 1, 3, 1],
                hint       = "Six cards — double forward then a right turn to the Space Center!",
                location   = "Space Center",
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
        name   = "Map 2 — Explorer",
        map_id = 2,
        # Each checkpoint is an independent out-and-back trip from Home(0,0).
        # Misty always starts and ends at Home facing North.
        #
        # Physical layout (30 cm grid, home = origin, North = up):
        #   D1 (0,60)  D3 (-30,60)  D5 (-60,60)
        #   Home(0,0)  D2 (-30,0)   D4 (-60,0)
        #
        # All drive_maps start from Home(0,0) facing North.
        # All return_maps end at Home(0,0) facing North.
        checkpoints = [

            # Phase 1: School — D1(0,60)
            # Path: forward, forward
            Checkpoint(
                sequence  = [1, 1],
                hint      = "Two Forward cards straight to the School!",
                location  = "School",
                drive_map = [
                    ("forward", DISTANCE),
                    ("forward", DISTANCE),
                ],
                return_map = [
                    ("turn_180",),
                    ("forward",  DISTANCE),
                    ("forward",  DISTANCE),
                    ("turn_180",),
                ],
            ),

            # Phase 2: Supermarket — D2(-30,0)
            # Path: turn left (→W), forward
            Checkpoint(
                sequence  = [2, 1],
                hint      = "Turn Left then Forward to the Supermarket!",
                location  = "Supermarket",
                drive_map = [
                    ("turn_left", TURN),
                    ("forward",   DISTANCE),
                ],
                # At D2 facing West → turn_180 (East) → forward (Home) → turn_left (North)
                return_map = [
                    ("turn_180",),
                    ("forward",   DISTANCE),
                    ("turn_left", TURN),
                ],
            ),

            # Phase 3: Ice-cream Shop — D3(-30,60)
            # Path: turn left (→W), forward, turn right (→N), forward, forward
            Checkpoint(
                sequence  = [2, 1, 3, 1, 1],
                hint      = "Left, Forward, Right, Forward, Forward to the Ice-cream Shop!",
                location  = "Ice-cream Shop",
                drive_map = [
                    ("turn_left",  TURN),
                    ("forward",    DISTANCE),
                    ("turn_right", TURN),
                    ("forward",    DISTANCE),
                    ("forward",    DISTANCE),
                ],
                # At D3 facing North → turn_180 (S) → fwd×2 (D2) → left (E) → fwd (Home) → left (N)
                return_map = [
                    ("turn_180",),
                    ("forward",   DISTANCE),
                    ("forward",   DISTANCE),
                    ("turn_left", TURN),
                    ("forward",   DISTANCE),
                    ("turn_left", TURN),
                ],
            ),

            # Phase 4: Restaurant — D4(-60,0)
            # Path: turn left (→W), forward, forward
            Checkpoint(
                sequence  = [2, 1, 1],
                hint      = "Turn Left then two Forwards to the Restaurant!",
                location  = "Restaurant",
                drive_map = [
                    ("turn_left", TURN),
                    ("forward",   DISTANCE),
                    ("forward",   DISTANCE),
                ],
                # At D4 facing West → turn_180 (E) → fwd×2 (Home) → turn_left (N)
                return_map = [
                    ("turn_180",),
                    ("forward",   DISTANCE),
                    ("forward",   DISTANCE),
                    ("turn_left", TURN),
                ],
            ),

            # Phase 5: Space Center — D5(-60,60)
            # Path: turn left (→W), fwd, fwd, turn right (→N), fwd, fwd
            Checkpoint(
                sequence  = [2, 1, 1, 3, 1, 1],
                hint      = "Left, two Forwards, Right, two Forwards — all the way to the Space Center!",
                location  = "Space Center",
                drive_map = [
                    ("turn_left",  TURN),
                    ("forward",    DISTANCE),
                    ("forward",    DISTANCE),
                    ("turn_right", TURN),
                    ("forward",    DISTANCE),
                    ("forward",    DISTANCE),
                ],
                # At D5 facing North → turn_180 (S) → fwd×2 (D4) → left (E) → fwd×2 (Home) → left (N)
                return_map = [
                    ("turn_180",),
                    ("forward",   DISTANCE),
                    ("forward",   DISTANCE),
                    ("turn_left", TURN),
                    ("forward",   DISTANCE),
                    ("forward",   DISTANCE),
                    ("turn_left", TURN),
                ],
            ),
        ],
    ),
}


# ── Checkpoint randomisation ──────────────────────────────────────────────────

def select_checkpoints(map_obj: Map, n: int = 3) -> list[Checkpoint]:
    """Return n checkpoints for this playthrough with per-run randomisation.

    Map 1: checkpoint[0] (School) is always first; n-1 others randomly picked
           from the rest and presented in shuffled order.
    Map 2: checkpoint[-1] (Space Center) is always last; n-1 others randomly
           picked from the rest in any order (each is out-and-back from home).
    """
    cps   = map_obj.checkpoints
    total = len(cps)

    if map_obj.map_id == 1:
        pool   = list(range(1, total))
        picked = random.sample(pool, min(n - 1, len(pool)))
        random.shuffle(picked)
        selected_indices = [0] + picked
    elif map_obj.map_id == 2:
        pool   = list(range(0, total - 1))
        picked = random.sample(pool, min(n - 1, len(pool)))
        random.shuffle(picked)
        selected_indices = picked + [total - 1]
    else:
        selected_indices = list(range(min(n, total)))

    return [cps[i] for i in selected_indices]


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
            print(f"  Phase {i} ({cp.location}): sequence={cp.sequence}")
            print(f"    drive_map  = {cp.drive_map}")
            print(f"    return_map = {cp.return_map}")
        print()
