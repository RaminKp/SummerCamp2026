import random
from dataclasses import dataclass, field


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class Checkpoint:
    sequence:        list[int]
    hint:            str
    drive_map:       list[tuple]
    return_map:      list[tuple] = field(default_factory=list)
    location:        str = "destination"
    # Map 2 only: path back to Home(0,0) from this checkpoint's resting
    # position (after return_map has run, i.e. after turn_180). Empty = home.
    home_on_timeout: list[tuple] = field(default_factory=list)


@dataclass
class Map:
    name:        str
    checkpoints: list[Checkpoint]       # Map 1: pool of out-and-back checkpoints
    paths:       list[list[Checkpoint]] = field(default_factory=list)  # Map 2: random paths
    map_id:      int = 0


# ── ✏️  EDIT HERE ─────────────────────────────────────────────────────────────

DISTANCE = 30   # cm per forward step
TURN     = 90   # degrees per turn

# ── Grid reference (1 unit = DISTANCE = 30 cm, Home = origin, North = up) ──
#
#   Space Center(-2,2)  Ice-cream(-1,2)  School(0,2)
#        J2(-2,1)   ──   J1(-1,1)   ──   J0(0,1)      ← junction row (horizontal highway)
#   Restaurant(-2,0)  Supermarket(-1,0)  Home(0,0)
#
# All horizontal movement is via the junction row only.
# No top-row or bottom-row horizontal corridors exist.
# Each column segment (bottom↔junction↔top) = 1 step each.


MAPS: dict[int, Map] = {
    1: Map(
        name   = "Map 1 — Out and Back",
        map_id = 1,
        checkpoints = [

            # Phase 1: School  (0,2)  sequence 2
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

            # Phase 2: Supermarket  (-1,0)  sequence 5
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

            # Phase 3: Ice-cream Shop  (-1,2)  sequence 5
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

            # Phase 4: Restaurant  (-2,0)  sequence 6
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

            # Phase 5: Space Center  (-2,2)  sequence 6
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
        checkpoints = [],   # unused for Map 2; paths is used instead
        # ── Map 2 rules ────────────────────────────────────────────────────────
        # • One of the 3 paths below is picked randomly each game.
        # • Misty does NOT return home between checkpoints — only a turn_180
        #   in place after each arrival (the next leg starts from that spot).
        # • Home is always the final puzzle (kids solve the return route).
        # • home_on_timeout = path back to Home(0,0) if the 8-min timer fires
        #   while Misty is resting at that checkpoint (after its turn_180).
        #
        # Facing at game start:   North
        # Facing after each leg:  depends on arrival direction (always North
        #                         for top-row nodes, South for bottom-row)
        #                         → turn_180 flips it before the next leg.
        #
        # Path 1:  Home → School → Supermarket → Ice-cream  → Home  (max 5 steps)
        # Path 2:  Home → School → Restaurant  → Ice-cream  → Home  (max 6 steps)
        # Path 3:  Home → School → Restaurant  → Space Center → Home (max 6 steps)
        # ───────────────────────────────────────────────────────────────────────
        paths = [

            # ── Path 1: School → Supermarket → Ice-cream → Home ───────────────
            [
                # Leg 1 — Home(N) → School(0,2)
                # fwd→J0, fwd→School  |  arrive facing N
                Checkpoint(
                    sequence        = [1, 1],
                    hint            = "Two Forwards to reach the School!",
                    location        = "School",
                    drive_map       = [
                        ("forward", DISTANCE),
                        ("forward", DISTANCE),
                    ],
                    return_map      = [("turn_180",)],       # now faces S
                    home_on_timeout = [                      # School(S) → Home → face N
                        ("forward", DISTANCE),
                        ("forward", DISTANCE),
                        ("turn_180",),
                    ],
                ),

                # Leg 2 — School(0,2)(S) → Supermarket(-1,0)
                # fwd→J0(S), right(S→W), fwd→J1(W), left(W→S), fwd→Supermarket
                # arrive facing S
                Checkpoint(
                    sequence        = [1, 3, 1, 2, 1],
                    hint            = "Forward, Right, Forward, Left, Forward to the Supermarket!",
                    location        = "Supermarket",
                    drive_map       = [
                        ("forward",    DISTANCE),
                        ("turn_right", TURN),
                        ("forward",    DISTANCE),
                        ("turn_left",  TURN),
                        ("forward",    DISTANCE),
                    ],
                    return_map      = [("turn_180",)],       # now faces N
                    home_on_timeout = [                      # Supermarket(N) → Home → face N
                        ("forward",    DISTANCE),
                        ("turn_right", TURN),
                        ("forward",    DISTANCE),
                        ("turn_right", TURN),
                        ("forward",    DISTANCE),
                        ("turn_180",),
                    ],
                ),

                # Leg 3 — Supermarket(-1,0)(N) → Ice-cream(-1,2)
                # fwd→J1(N), fwd→Ice-cream  |  arrive facing N
                Checkpoint(
                    sequence        = [1, 1],
                    hint            = "Two Forwards straight up to the Ice-cream Shop!",
                    location        = "Ice-cream Shop",
                    drive_map       = [
                        ("forward", DISTANCE),
                        ("forward", DISTANCE),
                    ],
                    return_map      = [("turn_180",)],       # now faces S
                    home_on_timeout = [                      # Ice-cream(S) → Home → face N
                        ("forward",    DISTANCE),
                        ("turn_left",  TURN),
                        ("forward",    DISTANCE),
                        ("turn_right", TURN),
                        ("forward",    DISTANCE),
                        ("turn_180",),
                    ],
                ),

                # Leg 4 — Ice-cream(-1,2)(S) → Home(0,0)  [final puzzle]
                # fwd→J1(S), left(S→E), fwd→J0(E), right(E→S), fwd→Home
                # arrive facing S → turn_180 → face N (ready for next game)
                Checkpoint(
                    sequence        = [1, 2, 1, 3, 1],
                    hint            = "Forward, Left, Forward, Right, Forward — bring me home!",
                    location        = "Home",
                    drive_map       = [
                        ("forward",    DISTANCE),
                        ("turn_left",  TURN),
                        ("forward",    DISTANCE),
                        ("turn_right", TURN),
                        ("forward",    DISTANCE),
                    ],
                    return_map      = [("turn_180",)],       # face N at Home
                    home_on_timeout = [],                    # already home
                ),
            ],

            # ── Path 2: School → Restaurant → Ice-cream → Home ────────────────
            [
                # Leg 1 — same as Path 1
                Checkpoint(
                    sequence        = [1, 1],
                    hint            = "Two Forwards to reach the School!",
                    location        = "School",
                    drive_map       = [
                        ("forward", DISTANCE),
                        ("forward", DISTANCE),
                    ],
                    return_map      = [("turn_180",)],
                    home_on_timeout = [
                        ("forward", DISTANCE),
                        ("forward", DISTANCE),
                        ("turn_180",),
                    ],
                ),

                # Leg 2 — School(0,2)(S) → Restaurant(-2,0)
                # fwd→J0(S), right(S→W), fwd→J1(W), fwd→J2(W), left(W→S), fwd→Restaurant
                # arrive facing S
                Checkpoint(
                    sequence        = [1, 3, 1, 1, 2, 1],
                    hint            = "Forward, Right, Forward, Forward, Left, Forward to the Restaurant!",
                    location        = "Restaurant",
                    drive_map       = [
                        ("forward",    DISTANCE),
                        ("turn_right", TURN),
                        ("forward",    DISTANCE),
                        ("forward",    DISTANCE),
                        ("turn_left",  TURN),
                        ("forward",    DISTANCE),
                    ],
                    return_map      = [("turn_180",)],       # now faces N
                    home_on_timeout = [                      # Restaurant(N) → Home → face N
                        ("forward",    DISTANCE),
                        ("turn_right", TURN),
                        ("forward",    DISTANCE),
                        ("forward",    DISTANCE),
                        ("turn_right", TURN),
                        ("forward",    DISTANCE),
                        ("turn_180",),
                    ],
                ),

                # Leg 3 — Restaurant(-2,0)(N) → Ice-cream(-1,2)
                # fwd→J2(N), right(N→E), fwd→J1(E), left(E→N), fwd→Ice-cream
                # arrive facing N
                Checkpoint(
                    sequence        = [1, 3, 1, 2, 1],
                    hint            = "Forward, Right, Forward, Left, Forward to the Ice-cream Shop!",
                    location        = "Ice-cream Shop",
                    drive_map       = [
                        ("forward",    DISTANCE),
                        ("turn_right", TURN),
                        ("forward",    DISTANCE),
                        ("turn_left",  TURN),
                        ("forward",    DISTANCE),
                    ],
                    return_map      = [("turn_180",)],       # now faces S
                    home_on_timeout = [                      # Ice-cream(S) → Home → face N
                        ("forward",    DISTANCE),
                        ("turn_left",  TURN),
                        ("forward",    DISTANCE),
                        ("turn_right", TURN),
                        ("forward",    DISTANCE),
                        ("turn_180",),
                    ],
                ),

                # Leg 4 — Ice-cream(-1,2)(S) → Home  [same as Path 1 final]
                Checkpoint(
                    sequence        = [1, 2, 1, 3, 1],
                    hint            = "Forward, Left, Forward, Right, Forward — bring me home!",
                    location        = "Home",
                    drive_map       = [
                        ("forward",    DISTANCE),
                        ("turn_left",  TURN),
                        ("forward",    DISTANCE),
                        ("turn_right", TURN),
                        ("forward",    DISTANCE),
                    ],
                    return_map      = [("turn_180",)],
                    home_on_timeout = [],
                ),
            ],

            # ── Path 3: School → Restaurant → Space Center → Home ─────────────
            [
                # Leg 1 — same as Path 1
                Checkpoint(
                    sequence        = [1, 1],
                    hint            = "Two Forwards to reach the School!",
                    location        = "School",
                    drive_map       = [
                        ("forward", DISTANCE),
                        ("forward", DISTANCE),
                    ],
                    return_map      = [("turn_180",)],
                    home_on_timeout = [
                        ("forward", DISTANCE),
                        ("forward", DISTANCE),
                        ("turn_180",),
                    ],
                ),

                # Leg 2 — School(0,2)(S) → Restaurant(-2,0)  [same as Path 2 leg 2]
                Checkpoint(
                    sequence        = [1, 3, 1, 1, 2, 1],
                    hint            = "Forward, Right, Forward, Forward, Left, Forward to the Restaurant!",
                    location        = "Restaurant",
                    drive_map       = [
                        ("forward",    DISTANCE),
                        ("turn_right", TURN),
                        ("forward",    DISTANCE),
                        ("forward",    DISTANCE),
                        ("turn_left",  TURN),
                        ("forward",    DISTANCE),
                    ],
                    return_map      = [("turn_180",)],
                    home_on_timeout = [
                        ("forward",    DISTANCE),
                        ("turn_right", TURN),
                        ("forward",    DISTANCE),
                        ("forward",    DISTANCE),
                        ("turn_right", TURN),
                        ("forward",    DISTANCE),
                        ("turn_180",),
                    ],
                ),

                # Leg 3 — Restaurant(-2,0)(N) → Space Center(-2,2)
                # fwd→J2(N), fwd→Space Center  |  arrive facing N
                Checkpoint(
                    sequence        = [1, 1],
                    hint            = "Two Forwards straight up to the Space Center!",
                    location        = "Space Center",
                    drive_map       = [
                        ("forward", DISTANCE),
                        ("forward", DISTANCE),
                    ],
                    return_map      = [("turn_180",)],       # now faces S
                    home_on_timeout = [                      # SpaceCenter(S) → Home → face N
                        ("forward",    DISTANCE),
                        ("turn_left",  TURN),
                        ("forward",    DISTANCE),
                        ("forward",    DISTANCE),
                        ("turn_right", TURN),
                        ("forward",    DISTANCE),
                        ("turn_180",),
                    ],
                ),

                # Leg 4 — Space Center(-2,2)(S) → Home  [final puzzle]
                # fwd→J2(S), left(S→E), fwd→J1(E), fwd→J0(E), right(E→S), fwd→Home
                Checkpoint(
                    sequence        = [1, 2, 1, 1, 3, 1],
                    hint            = "Forward, Left, Forward, Forward, Right, Forward — bring me home!",
                    location        = "Home",
                    drive_map       = [
                        ("forward",    DISTANCE),
                        ("turn_left",  TURN),
                        ("forward",    DISTANCE),
                        ("forward",    DISTANCE),
                        ("turn_right", TURN),
                        ("forward",    DISTANCE),
                    ],
                    return_map      = [("turn_180",)],
                    home_on_timeout = [],
                ),
            ],
        ],
    ),
}


# ── Checkpoint selection ──────────────────────────────────────────────────────

def select_checkpoints(map_obj: Map, n: int = 3) -> list[Checkpoint]:
    """Return the ordered list of checkpoints to play this session.

    Map 1: checkpoint[0] (School) is always first; n-1 others randomly chosen
           from the remaining pool in shuffled order (out-and-back, so order
           doesn't affect physical continuity).
    Map 2: one of the 3 pre-defined paths is picked at random; n is ignored.
           Each path is a continuous 4-leg journey ending at Home.
    """
    if map_obj.map_id == 1:
        cps    = map_obj.checkpoints
        pool   = list(range(1, len(cps)))
        picked = random.sample(pool, min(n - 1, len(pool)))
        random.shuffle(picked)
        return [cps[i] for i in ([0] + picked)]

    # Map 2: randomly pick one complete path
    return list(random.choice(map_obj.paths))


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
        if m.map_id == 2:
            for pi, path in enumerate(m.paths, 1):
                print(f"  Path {pi}: {' → '.join(cp.location for cp in path)}")
                for cp in path:
                    print(f"    {cp.location:16s} seq={cp.sequence}")
        else:
            for i, cp in enumerate(m.checkpoints, 1):
                print(f"  Phase {i} ({cp.location}): sequence={cp.sequence}")
                print(f"    drive_map  = {cp.drive_map}")
                print(f"    return_map = {cp.return_map}")
        print()
