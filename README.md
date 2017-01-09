# Mini Halite

Mini Halite is a Django application that will run local [Halite](http://halite.io/) tournaments for your bots.

## Requirements

 - Python 3.5 or higher

## Installation

1. (optional) create a [virtualenv](https://docs.python.org/3/library/venv.html) for python and activate it
2. install dependencies: `pip install -rrequirements.txt`
3. create database: `python manage.py migrate`
4. create an admin account: `python manage.py createsuperuser`
5. install `halite` executable from https://halite.io/downloads.php
6. configure settings in `lite/settings.py` (see below for details)
7. run the server: `python manage.py runserver`
8. add some bots (see below)
9. run the worker: `python manage.py runworker`
10. visit http://127.0.0.1:8000/lite/tournament/ and watch your bots compete

### Settings

 - `TIME_ZONE`: the [time zone](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) you want your times to be in. By default it is US EST.
 - `BOT_DIR`: the directory your bots will live in
 - `BOT_EXEC`: the command to run your bots. You should have a single executable script like `run.sh` or `run.cmd` in each bot folder.
 - `HALITE_EXEC`: the path to the `halite` executable. By default it assumes that it is in the root directory.
 - `PAGE_SIZE`: if you want larger pages of results. The default size is 10.

### Adding Bots

1. create a directory in the `bots/` directory (e.g. `firstbot`)
2. copy all the files into the directory needed to run your bot
3. make a `run.sh` or `run.cmd` file that will execute your bot (so that all bots can be launched the same way with a single command)
4. login to the admin site http://127.0.0.1:8000/lite/admin/ and add your bot. You should just need to specify the bot's name (make sure it matches the directory name)
5. your new bot will automatically start competing. To disable it, go to it on the admin site and uncheck the Enabled box and save.

## How does it work?

All of the worker logic is contained within `tournament/management/commands/runworker.py`.

### Seed Selection

The bots with the fewest games will be selected to seed games. Bots are sorted by `random() * bot.matches.count()**2` which means that there is still
some randomness in the selection process.

### Competitor Selection

Bots with nearby `mu` are selected to compete with the seeded player. Bots are sorted by `random() * abs(seed.mu - bot.mu)` which means there is still
some randomness in the selection process.

## Replays

Replay files are stored in the `hlt/` directory at the root. They are automatically gzipped to save space. You can delete them if the
directory gets too large, but then you won't be able to watch replays for those matches.
