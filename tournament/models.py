from django.db import models

# Create your models here.


class Bot(models.Model):
    name = models.CharField(max_length=255, unique=True)
    mu = models.FloatField(default=25.00000)
    sigma = models.FloatField(default=8.33333)
    enabled = models.BooleanField(default=True)

    def score(self):
        return self.mu - (self.sigma * 3)

    def __str__(self):
        return self.name


class Match(models.Model):
    date = models.DateTimeField()
    replay = models.FileField(upload_to='hlt/')
    seed = models.CharField(max_length=255)
    width = models.IntegerField()
    height = models.IntegerField()

    def __str__(self):
        return self.replay.name

    class Meta:
        verbose_name_plural = "matches"


class MatchResult(models.Model):
    bot = models.ForeignKey(Bot, related_name='matches')
    rank = models.IntegerField()
    match = models.ForeignKey(Match, related_name='results')
    mu = models.FloatField()
    sigma = models.FloatField()
    last_frame_alive = models.IntegerField()
    error_log = models.FileField(upload_to='error_logs', default=None)

    def __str__(self):
        return "{0} - {1}: {2}".format(self.match, self.bot.name, self.rank)


