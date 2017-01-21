from __future__ import absolute_import

from django.core.management.base import BaseCommand

from tournament.models import Bot


class Command(BaseCommand):
    help = 'Adds a new bot'

    def add_arguments(self, parser):
        parser.add_argument('bot_name', type=str)

        parser.add_argument(
            '--mu',
            action='store',
            dest='mu',
            type=float,
            default=None,
            help='Set the starting mu for the bot',
        )

        parser.add_argument(
            '--sigma',
            action='store',
            dest='sigma',
            type=float,
            default=None,
            help='Set the starting sigma for the bot',
        )

        parser.add_argument(
            '--disabled',
            action='store_true',
            dest='disabled',
            default=False,
            help='Create bot as disabled',
        )

    def handle(self, *args, **options):
        bot_name = options['bot_name']
        mu = options['mu']
        sigma = options['sigma']
        disabled = options['disabled']

        bot = Bot(name=bot_name)
        if mu:
            bot.mu = mu
        if sigma:
            bot.sigma = sigma
        if disabled:
            bot.enabled = False

        bot.save()
