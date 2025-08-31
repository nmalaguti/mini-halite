import numpy as np
from numba import njit

from halite.map import GameMapTuple

STATS_STRENGTH_LOSS_TO_MOVEMENT_CAP = 0
STATS_STRENGTH_LOSS_TO_PRODUCTION_CAP = 1
STATS_DAMAGE_TAKEN = 2
STATS_OVERKILL_DAMAGE = 3
STATS_OVERKILL_DAMAGE_TAKEN = 4
STATS_REALIZED_PRODUCTION = 5
STATS_TERRITORY = 6
STATS_PRODUCTION = 7
STATS_STRENGTH = 8

STILL, NORTH, EAST, SOUTH, WEST = 0, 1, 2, 3, 4

DIR_TO_DELTA = (
    (0, 0),
    (-1, 0),
    (0, 1),
    (1, 0),
    (0, -1),
)
MAX_PLAYERS = 6


@njit(cache=True)
def apply_player_moves_dense(
    gm_view: GameMapTuple, moves_array: np.ndarray, stats: np.ndarray
) -> np.ndarray:
    """
    stats: (P, len(GameStats))
    """
    H, W, P = gm_view.shape
    pieces = np.full((H, W, P), -1, dtype=np.int16)  # (H, W, P)
    moved = np.zeros((H, W, P), dtype=np.uint8)  # (H, W, P)

    for y in range(H):
        for x in range(W):
            for p in range(P):
                direction = moves_array[y, x, p]
                if direction == STILL:
                    continue

                moved[y, x, p] = 1
                strength = gm_view.strength[y, x]
                if pieces[y, x, p] == -1:
                    pieces[y, x, p] = 0  # mark move origin

                gm_view.strength[y, x] = 0
                gm_view.owner[y, x] = 0

                dy, dx = DIR_TO_DELTA[direction]
                ny, nx = (y + dy) % H, (x + dx) % W
                if pieces[ny, nx, p] == -1:
                    pieces[ny, nx, p] = 0

                pieces[ny, nx, p] = pieces[ny, nx, p] + strength
                if pieces[ny, nx, p] > 255:
                    lost_strength = max(0, pieces[ny, nx, p] - 255)
                    stats[p, STATS_STRENGTH_LOSS_TO_MOVEMENT_CAP] += lost_strength
                    pieces[ny, nx, p] = 255

    for y in range(H):
        for x in range(W):
            for p in range(P):
                if moved[y, x, p] == 1:
                    continue

                if gm_view.owner[y, x] != p + 1:
                    continue

                if pieces[y, x, p] == -1:
                    pieces[y, x, p] = 0

                # Apply production and strength
                pieces[y, x, p] = (
                    pieces[y, x, p] + gm_view.production[y, x] + gm_view.strength[y, x]
                )
                stats[p, STATS_REALIZED_PRODUCTION] += gm_view.production[y, x]
                if pieces[y, x, p] > 255:
                    lost_production = max(0, pieces[y, x, p] - 255)
                    stats[p, STATS_STRENGTH_LOSS_TO_PRODUCTION_CAP] += lost_production
                    stats[p, STATS_REALIZED_PRODUCTION] -= lost_production

                    pieces[y, x, p] = 255

                # Clear map state
                gm_view.strength[y, x] = 0
                gm_view.owner[y, x] = 0

    return pieces


@njit(cache=True)
def compute_injuries_dense(gm_view: GameMapTuple, pieces, stats: np.ndarray):
    H, W, P = pieces.shape

    # -1 sentinel: cell not damaged at all
    injuries = np.full((H, W, P), -1, dtype=np.int16)
    injure_map = np.zeros((H, W), dtype=np.int16)

    overkill_damage = np.zeros((H, W, P), dtype=np.int16)
    overkill_taken = np.zeros((H, W, P), dtype=np.int16)

    for y in range(H):
        for x in range(W):
            for p in range(P):
                strength = pieces[y, x, p]
                if strength < 0:
                    continue

                # Damage to neighboring cells
                for dy, dx in DIR_TO_DELTA:
                    ny, nx = (y + dy) % H, (x + dx) % W
                    for d in range(P):
                        if d != p:
                            if injuries[ny, nx, d] == -1:
                                injuries[ny, nx, d] = 0
                            injuries[ny, nx, d] += strength
                            if dy != 0 or dx != 0:
                                overkill_damage[ny, nx, p] += strength
                                overkill_taken[ny, nx, d] += strength

                # Retaliation from environment (neutral site)
                site_strength = gm_view.strength[y, x]
                if site_strength > 0:
                    if injuries[y, x, p] == -1:
                        injuries[y, x, p] = 0
                    injuries[y, x, p] += site_strength
                    injure_map[y, x] += strength

    for y in range(H):
        for x in range(W):
            for p in range(P):
                if overkill_damage[y, x, p] > 0:
                    for d in range(P):
                        if d == p:
                            continue

                        if pieces[y, x, d] > 0:
                            stats[p, STATS_OVERKILL_DAMAGE] += min(
                                pieces[y, x, d], overkill_damage[y, x, p]
                            )

                if pieces[y, x, p] > 0 and overkill_taken[y, x, p] > 0:
                    stats[p, STATS_OVERKILL_DAMAGE_TAKEN] += min(
                        pieces[y, x, p], overkill_taken[y, x, p]
                    )

    return injuries, injure_map


@njit(cache=True)
def resolve_combat_dense(pieces, injuries, stats):
    H, W, P = pieces.shape
    for y in range(H):
        for x in range(W):
            for p in range(P):
                piece = pieces[y, x, p]
                injury = injuries[y, x, p]
                if piece < 0:
                    continue
                if injury >= piece:
                    stats[p, STATS_DAMAGE_TAKEN] += piece
                    pieces[y, x, p] = -1
                elif injury >= 0:
                    stats[p, STATS_DAMAGE_TAKEN] += injury
                    pieces[y, x, p] -= injury


@njit(cache=True)
def rebuild_map_dense(gm_view: GameMapTuple, pieces, injure_map, stats):
    # Apply environmental damage
    np.maximum(0, gm_view.strength - injure_map, gm_view.strength)

    H, W, P = pieces.shape
    for y in range(H):
        for x in range(W):
            for p in range(P):
                if pieces[y, x, p] > -1:
                    stats[p, STATS_PRODUCTION] += gm_view.production[y, x]
                    stats[p, STATS_TERRITORY] += 1
                    gm_view.owner[y, x] = p + 1

                    stats[p, STATS_STRENGTH] += pieces[y, x, p]
                    gm_view.strength[y, x] = pieces[y, x, p]


@njit(cache=True)
def process_next_frame(gm_view: GameMapTuple, moves_array: np.ndarray):
    """
    moves_array: (H, W, P)
    """
    stats = np.zeros((MAX_PLAYERS, 9), dtype=np.int32)

    pieces = apply_player_moves_dense(gm_view, moves_array, stats)
    injuries, injure_map = compute_injuries_dense(gm_view, pieces, stats)
    resolve_combat_dense(pieces, injuries, stats)
    rebuild_map_dense(gm_view, pieces, injure_map, stats)

    return stats
