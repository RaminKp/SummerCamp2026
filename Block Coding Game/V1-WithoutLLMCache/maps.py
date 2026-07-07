import random
from dataclasses import dataclass, field

from misty import turn_180


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class Checkpoint:
    sequence:        list[int]
    hint:            str
    drive_map:       list[tuple]
    return_map:      list[tuple] = field(default_factory=list)
    location:        str = "destination"
    # Map 2 only: path back to Home(0,0) from this checkpoint's resting
    # position (after return_map has run). Empty = already at home.
    home_on_timeout: list[tuple] = field(default_factory=list)


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
        name   = "Map 2 — Waypoints",
        map_id = 2,
        # Fixed continuous path: School → Ice-cream Shop → Space Center → Home.
        # Misty never returns to Home between checkpoints; each leg picks up
        # exactly where the last one left off.  Home is the final puzzle —
        # children must solve the route back.
        #
        # Physical layout (30 cm grid, home = origin, North = up):
        #   D1 (0,60)  D3 (-30,60)  D5 (-60,60)
        #   Home(0,0)  D2 (-30,0)   D4 (-60,0)
        #
        # Direction Misty faces at the START of each leg:
        #   Leg 1 (Home→D1):  North  (start of game)
        #   Leg 2 (D1→D3):    South  (after turn_180 return_map on leg 1)
        #   Leg 3 (D3→D5):    North  (after turn_right return_map on leg 2, W→N)
        #   Leg 4 (D5→Home):  East   (after turn_180 return_map on leg 3, W→E)
        checkpoints = [

            # Leg 1: School — Home(N) → D1(0,60)
            # fwd, fwd
            Checkpoint(
                sequence        = [1, 1],
                hint            = "Two Forwards to reach the School!",
                location        = "School",
                drive_map       = [
                    ("forward", DISTANCE),
                    ("forward", DISTANCE),
                ],
                # At D1 facing North → turn_180 → faces South (ready for Leg 2)
                return_map      = [("turn_180",)],
                # After return_map: D1(0,60) facing South → fwd×2 → Home → turn_180 (N)
                home_on_timeout = [
                    ("forward",  DISTANCE),
                    ("forward",  DISTANCE),
                    ("turn_180",),
                ],
            ),

            # Leg 2: Ice-cream Shop — D1(S) → D3(-30,60)
            # right(S→W), fwd
            Checkpoint(
                sequence        = [3, 1],
                hint            = "Turn Right then Forward to the Ice-cream Shop!",
                location        = "Ice-cream Shop",
                drive_map       = [
                    ("turn_right", TURN),
                    ("forward",    DISTANCE),
                ],
                # At D3 facing West → turn_right(W→N) → faces North (ready for Leg 3)
                return_map      = [("turn_right", TURN)],
                # After return_map: D3(-30,60) facing North
                # → right(N→E), fwd×2(→D1), right(E→S), fwd×2(→Home), turn_180(→N)
                home_on_timeout = [
                    ("turn_right", TURN),
                    ("forward",    DISTANCE),
                    ("forward",    DISTANCE),
                    ("turn_right", TURN),
                    ("forward",    DISTANCE),
                    ("forward",    DISTANCE),
                    ("turn_180",),
                ],
            ),

            # Leg 3: Space Center — D3(N) → D5(-60,60)
            # left(N→W), fwd
            Checkpoint(
                sequence        = [2, 1],
                hint            = "Turn Left then Forward to the Space Center!",
                location        = "Space Center",
                drive_map       = [
                    ("turn_left", TURN),
                    ("forward",   DISTANCE),
                ],
                # At D5 facing West → turn_180 → faces East (ready for Leg 4)
                return_map      = [("turn_180",)],
                # After return_map: D5(-60,60) facing East
                # → fwd×2(→D1(0,60)), right(E→S), fwd×2(→Home), turn_180(→N)
                home_on_timeout = [
                    ("forward",    DISTANCE),
                    ("forward",    DISTANCE),
                    ("turn_right", TURN),
                    ("forward",    DISTANCE),
                    ("forward",    DISTANCE),
                    ("turn_180",),
                ],
            ),

            # Leg 4: Home — D5(E) → Home(0,0)
            # fwd, fwd (→D1), right(E→S), fwd, fwd (→Home)
            Checkpoint(
                sequence        = [1, 1, 3, 1, 1],
                hint            = "Forward, Forward, Right, Forward, Forward — guide me all the way home!",
                location        = "Home",
                drive_map       = [
                    ("forward",    DISTANCE),
                    ("forward",    DISTANCE),
                    ("turn_right", TURN),
                    ("forward",    DISTANCE),
                    ("forward",    DISTANCE),
                ],
                # At Home facing South → turn_180 → faces North (ready for next game)
                return_map      = [("turn_180",)],
                home_on_timeout = [],  # already home
            ),
        ],
    ),
}


# ── Checkpoint randomisation ──────────────────────────────────────────────────

def select_checkpoints(map_obj: Map, n: int = 3) -> list[Checkpoint]:
    """Return the checkpoints to play this session.

    Map 1: checkpoint[0] (School) is always first; n-1 others randomly picked
           from the rest in shuffled order (each is independent out-and-back).
    Map 2: fixed path — all 4 checkpoints in order, n is ignored.
    """
    cps   = map_obj.checkpoints
    total = len(cps)

    if map_obj.map_id == 1:
        pool   = list(range(1, total))
        picked = random.sample(pool, min(n - 1, len(pool)))
        random.shuffle(picked)
        return [cps[i] for i in ([0] + picked)]

    # Map 2 (and any other map): play all checkpoints in order
    return list(cps)


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
