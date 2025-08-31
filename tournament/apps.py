from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _configure_sqlite(connection, **kwargs):
    if connection.vendor == "sqlite":
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")  # better throughput than FULL
        cursor.execute("PRAGMA busy_timeout=10000;")  # ms to wait on locks
        cursor.execute("PRAGMA wal_autocheckpoint=1000;")  # tune as needed


class TournamentConfig(AppConfig):
    name = "tournament"

    def ready(self):
        connection_created.connect(_configure_sqlite)
