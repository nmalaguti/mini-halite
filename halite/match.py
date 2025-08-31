import asyncio
from contextlib import AsyncExitStack
import numpy as np
import structlog

from halite.docker import DockerAdapter
from halite.game import process_next_frame
from halite.map import GameMap

from pydantic import BaseModel, conlist


log = structlog.get_logger()

Cell = conlist(int, min_length=2, max_length=2)


class ReplayModel(BaseModel):
    version: int
    height: int
    width: int
    num_players: int
    num_frames: int
    player_names: list[str]
    productions: list[list[int]]
    frames: list[list[list[Cell]]]
    moves: list[list[list[int]]]
    seed: int

    @property
    def production(self) -> list[list[int]]:
        return self.productions


async def run_match(
    width: int,
    height: int,
    bots: list[DockerAdapter],
    *,
    seed: int = None,
    init_timeout: float | None = 30.0,
    frame_timeout: float | None = 5.0,
) -> tuple[ReplayModel, tuple[list[int], list[int]]]:
    log.debug("Generating game map")
    log.info("Running match", bots=[bot.name for bot in bots])
    game_map = GameMap(width, height, num_players=len(bots), seed=seed)
    gm_view = game_map.to_tuple()

    _log = log.bind(
        width=game_map.width,
        height=game_map.height,
        num_players=game_map.num_players,
        seed=game_map.seed,
    )

    players = np.arange(1, game_map.num_players + 1)

    empty = np.zeros_like(game_map.owner, dtype=np.int16)

    moves = []
    frames = []

    frame = np.dstack((game_map.owner, game_map.strength))
    frames.append(frame)

    async with AsyncExitStack() as stack:
        _log.debug("Starting bot async enter context")
        bot_handles = await asyncio.gather(
            *[stack.enter_async_context(bot) for bot in bots]
        )

        _log.debug("Sending init")
        bot_names = await asyncio.gather(
            *[
                bot.send_init(
                    bot_id=bot_id,
                    dims=(game_map.width, game_map.height),
                    production=game_map.production,
                    first_frame=frame,
                    timeout=init_timeout,
                )
                for bot_id, bot in zip(players, bot_handles)
            ]
        )
        _log.debug("Init complete")

        for _ in range(game_map.max_turns):
            frame_num = len(frames)
            _log.debug("loop start", frame_num=frame_num)
            alive = np.isin(players, game_map.owner.ravel())
            if np.sum(alive) <= 1:
                break

            _log.debug("Getting moves", frame_num=frame_num)
            bot_moves = await asyncio.gather(
                *[
                    bot_handle.send_frame(frame, timeout=frame_timeout)
                    if bot_alive
                    else asyncio.sleep(0, result=empty)
                    for bot_alive, bot_handle in zip(alive, bot_handles)
                ]
            )
            _log.debug("Moves received", frame_num=frame_num)

            moves_array = np.stack(bot_moves, axis=-1)
            moves.append(np.max(moves_array, axis=-1))

            process_next_frame(gm_view, moves_array)

            frame = np.dstack((game_map.owner, game_map.strength))
            frames.append(frame)

            _log.debug("process_next_frame complete", frame_num=frame_num)

    replay_model = ReplayModel(
        version=11,
        width=game_map.width,
        height=game_map.height,
        num_players=game_map.num_players,
        num_frames=len(frames),
        player_names=bot_names,
        productions=game_map.production.tolist(),
        frames=[f.tolist() for f in frames],
        moves=[m.tolist() for m in moves],
        seed=game_map.seed,
    )

    return replay_model, ranking(frames)


def ranking(frames: list[np.ndarray]) -> tuple[list[int], list[int]]:
    """
    owners: int array (F, H, W). 0=neutral, players numbered 1..P

    Returns:
      ranks: np.ndarray shape (P,), where ranks[i] is the finishing position of player (i+1)
             (0 = first/best, 1 = second, ...)
      last_alive: np.ndarray shape (P,), last frame index per player with the C++ visualizer adjustment
                  = alive_count - 2 + alive_at_end
    """
    frames = np.array(frames)
    owners = frames[..., 0]
    F, H, W = owners.shape
    players = np.arange(1, owners.max() + 1)  # [1..P]
    P = players.size

    # territory[f, i] = cell count for player (i+1) at frame f
    territory = (
        (owners[None, ...] == players[:, None, None, None]).sum(axis=(2, 3)).T
    )  # (F, P)
    alive = territory > 0
    alive_counts = alive.sum(axis=0)  # (P,)
    tc_cum = territory.cumsum(axis=0)  # (F, P)

    # Elimination sequence
    elim_seq = []
    for f in range(F - 1):
        died = np.where(alive[f] & ~alive[f + 1])[0]
        if died.size:
            last_f = f
            elim_seq.extend(
                sorted(
                    died.tolist(),
                    key=lambda i: (
                        int(territory[last_f, i]),
                        int(tc_cum[last_f, i]),
                        i + 1,
                    ),  # player id for tie-break
                )
            )

    # Survivors at end
    survivors = np.where(alive[-1])[0].tolist()
    elim_seq.extend(
        sorted(
            survivors, key=lambda i: (int(territory[-1, i]), int(tc_cum[-1, i]), i + 1)
        )
    )

    # Best-first indices into [0..P-1]
    best_first = elim_seq[::-1]

    # Ranks aligned with player order (0 = best)
    ranks = np.empty(P, dtype=int)
    for pos, idx in enumerate(best_first):
        ranks[idx] = pos

    # Last frame alive
    last_alive = (alive_counts - 1).astype(int)

    return ranks.tolist(), last_alive.tolist()
