from __future__ import absolute_import

import gzip
from collections import namedtuple
from glob import glob
from itertools import chain
from operator import itemgetter
from os import path
from os import remove
from random import sample, choice, random
from shutil import copyfileobj
from subprocess import check_output

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from tournament.models import Bot, Match, MatchResult

from trueskill import Rating, rate

GZIP_EXT = '.gz'

MAP_SIZES = [20, 25, 25, 30, 30, 30, 35, 35, 35, 35, 40, 40, 40, 45, 45, 50]
SEED_NUM_PLAYERS = [2, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 5, 5, 6]
NON_SEED_NUM_PLAYERS = [2] * 5 + [3] * 8 + [4] * 9 + [5] * 8 + [6] * 5

Result = namedtuple('Result', 'player_id rank last_frame_alive')
Output = namedtuple('Output', 'width height hlt_file seed results timeout_bots timeout_logs')


class Command(BaseCommand):
    help = 'Runs a worker running matches'

    def handle(self, *args, **options):
        while True:
            self._run_match()

    @staticmethod
    def _parse_output(result, num_bots, dimension):
        lines = result.splitlines()

        # older versions of the halite exe don't output the dimensions
        try:
            [width, height] = [int(x) for x in lines[0].split()]
            lines.pop(0)
        except ValueError:
            width = height = dimension

        [hlt_file, seed] = lines.pop(0).split()
        results = [Result(*(int(part) - 1 for part in parts))
                   for parts in (line.split() for line in lines[:num_bots])]
        lines = lines[num_bots:]
        timeout_bots = []
        timeout_logs = []
        if lines:
            # timeouts
            timeout_bots = [int(player_id) - 1 for player_id in lines.pop(0).split()]
            timeout_logs = [line.strip() for line in lines]

        return Output(width, height, hlt_file, seed, results, timeout_bots, timeout_logs)

    def _run_halite(self, bots):
        dimension = choice(MAP_SIZES)

        commands = chain.from_iterable(
            ((settings.BOT_EXEC.format(path.join(settings.BOT_DIR, bot.name)), bot.name) for bot in bots)
        )
        run_command = [settings.HALITE_EXEC, '-q', '-d', '%s %s' % (dimension, dimension), '-o'] + list(commands)

        self.stdout.write(str(timezone.now()) + ' ' + ' '.join(run_command))
        output = check_output(run_command, universal_newlines=True, cwd=settings.BASE_DIR)

        return self._parse_output(output, len(bots), dimension)

    @staticmethod
    def _select_bots():
        num_players = choice(SEED_NUM_PLAYERS)
        sorted_bots = [pair[1] for pair in
                       sorted(
                           [(random() * bot.matches.count()**2, bot) for bot in Bot.objects.filter(enabled=True).all()],
                           key=itemgetter(0)
                       )]

        seed = sorted_bots[0]
        rest = sorted_bots[1:]
        closest = [pair[1] for pair in
                   sorted(
                       [(random() * abs(seed.mu - bot.mu), bot) for bot in rest],
                       key=itemgetter(0)
                   )]

        size = min(num_players, len(sorted_bots)) - 1
        return [seed] + sample(closest[:size], size)

    @staticmethod
    def _store_output(bots, output):
        with transaction.atomic():
            for bot in bots:
                bot.refresh_from_db()

            ratings = [tuple([Rating(bot.mu, bot.sigma)]) for bot in bots]
            updated = rate(ratings, ranks=[result.rank for result in output.results])

            for bot, rating in zip(bots, updated):
                bot.mu = rating[0].mu
                bot.sigma = rating[0].sigma
                bot.save()

            compressed_replay_filename = output.hlt_file + GZIP_EXT
            with open(compressed_replay_filename, 'rb') as replay_file:
                match = Match(date=timezone.now(),
                              replay=File(replay_file),
                              seed=output.seed,
                              width=output.width,
                              height=output.height)
                match.save()

            remove(compressed_replay_filename)

            for i, bot in enumerate(bots):
                error_log = None
                if output.results[i].player_id in output.timeout_bots:
                    # timeout
                    index = output.timeout_bots.index(output.results[i].player_id)
                    error_log = output.timeout_logs[index]

                error_file = None
                error_file_wrapped = None
                try:
                    if error_log:
                        error_file = open(error_log, 'rb')
                        error_file_wrapped = File(error_file)

                    match_result = MatchResult(bot=bot,
                                               rank=output.results[i].rank + 1,
                                               match=match,
                                               mu=bot.mu,
                                               sigma=bot.sigma,
                                               last_frame_alive=output.results[i].last_frame_alive,
                                               error_log=error_file_wrapped)
                    match_result.save()
                finally:
                    if error_file:
                        error_file.close()

                if error_log:
                    remove(error_log)

            for log in glob('*.log*'):
                remove(log)

    @staticmethod
    def _compress_hlt(output):
        with open(output.hlt_file, 'rb') as f_in:
            with gzip.open(output.hlt_file + GZIP_EXT, 'wb') as f_out:
                copyfileobj(f_in, f_out)

        remove(output.hlt_file)

    def _run_match(self):
        bots = self._select_bots()
        output = self._run_halite(bots)

        self._compress_hlt(output)

        self._store_output(bots, output)
