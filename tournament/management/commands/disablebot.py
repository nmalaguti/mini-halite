from __future__ import absolute_import

from django.core.management.base import BaseCommand

from tournament.models import Bot


class Command(BaseCommand):
    help = 'Disable a bot'

    def add_arguments(self, parser):
        parser.add_argument('bot_name', type=str)

    def handle(self, *args, **options):
        bot_name = options['bot_name']

        bot = Bot.objects.get(name=bot_name)
        bot.enabled = False
        bot.save()
