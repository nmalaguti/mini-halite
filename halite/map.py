from math import isqrt, sqrt
from typing import NamedTuple

import numpy as np


def max_frames(width: int, height: int) -> int:
    return isqrt(width * height) * 10


class GameMapTuple(NamedTuple):
    owner: np.ndarray  # (H, W)
    production: np.ndarray  # (H, W)
    strength: np.ndarray  # (H, W)
    shape: np.ndarray  # (3,)


class GameMap:
    width: int
    height: int
    num_players: int
    seed: int

    owner: np.ndarray  # (H, W)
    production: np.ndarray  # (H, W)
    strength: np.ndarray  # (H, W)

    def __init__(
        self,
        width: int,
        height: int,
        num_players: int,
        seed: int = None,
    ):
        self.num_players = num_players

        if seed is None:
            self.seed = np.random.randint(0, 2**32 - 1)
        else:
            self.seed = seed

        self.owner, self.production, self.strength = _generate_map(
            width, height, num_players, seed
        )

        self.height, self.width = self.owner.shape

    @property
    def max_turns(self) -> int:
        return max_frames(self.width, self.height)

    def to_tuple(self):
        return GameMapTuple(
            self.owner,
            self.production,
            self.strength,
            np.array([self.height, self.width, self.num_players]),
        )


def new_map(height, width, num_players, seed) -> GameMap:
    return GameMap(height, width, num_players, seed)


def _generate_map(width: int, height: int, num_players: int, seed: int):
    rng = np.random.default_rng(seed)

    # 1) choose tiling dimensions dw × dh
    prefer_horizontal = bool(rng.integers(0, 2))
    if prefer_horizontal:
        dh = isqrt(num_players)
        while num_players % dh != 0:
            dh -= 1
        dw = num_players // dh
    else:
        dw = isqrt(num_players)
        while num_players % dw != 0:
            dw -= 1
        dh = num_players // dw

    # 2) figure out chunk sizes (cw × ch) and trim to divisible
    cw = width // dw
    ch = height // dh
    if prefer_horizontal:
        while ch % num_players != 0:
            ch -= 1
    else:
        while cw % num_players != 0:
            cw -= 1

    self_width = cw * dw
    self_height = ch * dh

    # 3) build two “factor” grids via recursive Region
    prod_chunk = _Region(cw, ch, rng).get_factors()
    str_chunk = _Region(cw, ch, rng).get_factors()

    # 4) tesselate: plant production/strength kernels and one owner seed per chunk
    owner = np.zeros((self_height, self_width), dtype=int)
    prod = np.zeros((self_height, self_width), dtype=float)
    strg = np.zeros((self_height, self_width), dtype=float)

    for a in range(dh):
        for b in range(dw):
            base_y, base_x = a * ch, b * cw
            for c in range(ch):
                for d in range(cw):
                    y, x = base_y + c, base_x + d
                    prod[y, x] = prod_chunk[c][d]
                    strg[y, x] = str_chunk[c][d]
            # seed the owner in the center of the chunk
            cy = base_y + ch // 2
            cx = base_x + cw // 2
            owner[cy, cx] = a * dw + b + 1

    # 5) reflect chunks to get symmetry
    reflect_v = dh % 2 == 0
    reflect_h = dw % 2 == 0
    r_owner = np.zeros_like(owner)
    r_prod = np.zeros_like(prod)
    r_str = np.zeros_like(strg)

    for a in range(dh):
        for b in range(dw):
            vref = reflect_v and (a % 2 == 1)
            href = reflect_h and (b % 2 == 1)
            base_y, base_x = a * ch, b * cw
            for c in range(ch):
                for d in range(cw):
                    y, x = base_y + c, base_x + d
                    y0 = base_y + (ch - 1 - c if vref else c)
                    x0 = base_x + (cw - 1 - d if href else d)
                    r_owner[y, x] = owner[y0, x0]
                    r_prod[y, x] = prod[y0, x0]
                    r_str[y, x] = strg[y0, x0]

    # 6) optionally shift rows or columns
    if num_players == 6:
        s_owner, s_prod, s_str = r_owner.copy(), r_prod.copy(), r_str.copy()
    elif prefer_horizontal:
        shift = rng.integers(0, dw) * (self_height // dw)
        s_owner = np.zeros_like(r_owner)
        s_prod = np.zeros_like(r_prod)
        s_str = np.zeros_like(r_str)
        for a in range(dh):
            for b in range(dw):
                base_y, base_x = a * ch, b * cw
                for c in range(ch):
                    y = base_y + c
                    y0 = (base_y + b * shift + c) % self_height
                    for d in range(cw):
                        x = base_x + d
                        s_owner[y, x] = r_owner[y0, x]
                        s_prod[y, x] = r_prod[y0, x]
                        s_str[y, x] = r_str[y0, x]
    else:
        shift = rng.integers(0, dh) * (self_width // dh)
        s_owner = np.zeros_like(r_owner)
        s_prod = np.zeros_like(r_prod)
        s_str = np.zeros_like(r_str)
        for a in range(dh):
            for b in range(dw):
                base_y, base_x = a * ch, b * cw
                for c in range(ch):
                    y = base_y + c
                    for d in range(cw):
                        x = base_x + d
                        x0 = (base_x + a * shift + d) % self_width
                        s_owner[y, x] = r_owner[y, x0]
                        s_prod[y, x] = r_prod[y, x0]
                        s_str[y, x] = r_str[y, x0]

    # 7) blur via convolution with wraparound (vectorized)
    prod = s_prod
    strg = s_str
    owner = s_owner
    OWN_WEIGHT = 0.66667
    n_iter = int(2 * sqrt(self_width * self_height) / 10)
    for _ in range(n_iter + 1):
        prod = OWN_WEIGHT * prod + (1 - OWN_WEIGHT) / 4 * (
            np.roll(prod, 1, axis=0)
            + np.roll(prod, -1, axis=0)
            + np.roll(prod, 1, axis=1)
            + np.roll(prod, -1, axis=1)
        )
        strg = OWN_WEIGHT * strg + (1 - OWN_WEIGHT) / 4 * (
            np.roll(strg, 1, axis=0)
            + np.roll(strg, -1, axis=0)
            + np.roll(strg, 1, axis=1)
            + np.roll(strg, -1, axis=1)
        )

    # 8) normalize to [0,1]
    prod /= prod.max()
    strg /= strg.max()

    # 9) scale up to integer TOP_PROD and TOP_STR
    TOP_PROD = int(rng.integers(0, 10)) + 6
    TOP_STR = int(rng.integers(0, 106)) + 150
    prod = np.rint(prod * TOP_PROD).astype(int)
    strg = np.rint(strg * TOP_STR).astype(int)

    # 10) ensure owned cells have at least production=1
    mask = (owner != 0) & (prod == 0)
    prod[mask] = 1

    return owner, prod, strg


class _Region:
    CHUNK_SIZE = 4
    OWN_WEIGHT = 0.75

    def __init__(self, w: int, h: int, rng: np.random.Generator):
        # initialize my “seed” factor
        self.factor = rng.random() ** 1.5
        self.children = []

        # base case
        if w == 1 and h == 1:
            return

        cw, ch = divmod(w, self.CHUNK_SIZE)[0], divmod(h, self.CHUNK_SIZE)[0]
        difW = w - self.CHUNK_SIZE * cw
        difH = h - self.CHUNK_SIZE * ch

        # subdivide into a 4×4 grid (some cells may be size zero and get skipped)
        for a in range(self.CHUNK_SIZE):
            tch = ch + 1 if a < difH else ch
            if tch <= 0:
                continue
            row = []
            for b in range(self.CHUNK_SIZE):
                tcw = cw + 1 if b < difW else cw
                if tcw > 0:
                    row.append(_Region(tcw, tch, rng))
            if row:
                self.children.append(row)

        # one pass of “blur” on the child factors
        for _ in range(1):
            rows = len(self.children)
            cols = len(self.children[0])
            blurred = [[0.0] * cols for _ in range(rows)]
            for a in range(rows):
                mh = (a - 1) % rows
                ph = (a + 1) % rows
                for b in range(cols):
                    mw = (b - 1) % cols
                    pw = (b + 1) % cols
                    blurred[a][b] = self.children[a][b].factor * self.OWN_WEIGHT + (
                        1 - self.OWN_WEIGHT
                    ) / 4 * (
                        self.children[mh][b].factor
                        + self.children[ph][b].factor
                        + self.children[a][mw].factor
                        + self.children[a][pw].factor
                    )
            for a in range(rows):
                for b in range(cols):
                    self.children[a][b].factor = blurred[a][b]

    def get_factors(self) -> list[list[float]]:
        # leaf
        if not self.children:
            return [[self.factor]]

        # recurse
        children_factors = [
            [child.get_factors() for child in row] for row in self.children
        ]
        # figure out the full width/height
        total_h = sum(len(children_factors[a][0]) for a in range(len(self.children)))
        total_w = sum(
            len(children_factors[0][b][0]) for b in range(len(self.children[0]))
        )

        # build the full grid
        factors: list[list[float]] = [[0.0] * total_w for _ in range(total_h)]
        y = 0
        for a in range(len(self.children)):
            block_rows = len(children_factors[a][0])
            for iy in range(block_rows):
                x = 0
                for b in range(len(self.children[0])):
                    block = children_factors[a][b]
                    for ix in range(len(block[iy])):
                        factors[y][x] = block[iy][ix] * self.factor
                        x += 1
                y += 1

        return factors
