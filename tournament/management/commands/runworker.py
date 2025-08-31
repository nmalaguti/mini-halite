import asyncio
import logging
from operator import itemgetter
from random import sample, choice, random

import brotli
import structlog
import trueskill
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from halite.docker import DockerAdapter
from halite.match import run_match
from tournament.models import Bot, Match, MatchResult


MAP_SIZES = [20, 25, 25, 30, 30, 30, 35, 35, 35, 35, 40, 40, 40, 45, 45, 50]
SEED_NUM_PLAYERS = [2, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 5, 5, 6]

structlog.configure(
    cache_logger_on_first_use=True,
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(
            fmt="%Y-%m-%d %H:%M:%S.%f",  # full microseconds
            utc=False,  # set to True if you want UTC timestamps
        ),
        structlog.dev.ConsoleRenderer(),  # Pretty-print to console
    ],
    logger_factory=structlog.PrintLoggerFactory(),
)


def select_bots() -> list[Bot]:
    num_players = choice(SEED_NUM_PLAYERS)
    sorted_bots = [
        pair[1]
        for pair in sorted(
            [
                (random() * bot.matches.count() ** 2, bot)
                for bot in Bot.objects.filter(enabled=True).all()
            ],
            key=itemgetter(0),
        )
    ]

    seed = sorted_bots[0]
    rest = sorted_bots[1:]
    closest = [
        pair[1]
        for pair in sorted(
            [(random() * abs(seed.mu - bot.mu), bot) for bot in rest],
            key=itemgetter(0),
        )
    ]

    size = min(num_players, len(sorted_bots)) - 1
    return [seed] + sample(closest[:size], size)


class Command(BaseCommand):
    help = "Runs a worker running matches"

    def handle(self, *args, **options):
        trueskill.setup(
            mu=25.0, sigma=25.0 / 3, beta=5.2, tau=0.01, draw_probability=0.0
        )

        while True:
            bots = select_bots()
            dimension = choice(MAP_SIZES)
            replay, (ranking, last_frame_alive) = asyncio.run(
                run_match(
                    dimension,
                    dimension,
                    [
                        DockerAdapter(bot.docker_image, bot.name, gpu=bot.use_gpu)
                        for bot in bots
                    ],
                )
            )

            with transaction.atomic():
                for bot in bots:
                    bot.refresh_from_db()

                ratings = [(trueskill.Rating(bot.mu, bot.sigma),) for bot in bots]
                updated = trueskill.rate(ratings, ranks=ranking)

                for bot, rating in zip(bots, updated):
                    bot.mu = rating[0].mu
                    bot.sigma = rating[0].sigma
                    bot.save()

                now = timezone.now()
                ts = now.strftime("%Y%m%d%H%M%S")

                json_bytes = replay.model_dump_json().encode()
                compressed_bytes = brotli.compress(
                    json_bytes, quality=10, mode=brotli.MODE_TEXT
                )

                match = Match(
                    date=now,
                    replay=ContentFile(
                        compressed_bytes, name=f"{ts}-{replay.seed}.hlt.br"
                    ),
                    seed=replay.seed,
                    width=replay.width,
                    height=replay.height,
                )
                match.save()

                for bot, rank, last_frame in zip(bots, ranking, last_frame_alive):
                    match_result = MatchResult(
                        bot=bot,
                        rank=rank + 1,
                        match=match,
                        mu=bot.mu,
                        sigma=bot.sigma,
                        last_frame_alive=last_frame,
                        error_log=None,
                    )
                    match_result.save()
