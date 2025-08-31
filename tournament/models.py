from django.db import models


class Bot(models.Model):
    name = models.CharField(max_length=255, unique=True)
    docker_image = models.CharField(max_length=255)
    mu = models.FloatField(default=25.0)
    sigma = models.FloatField(default=25.0 / 3)
    enabled = models.BooleanField(default=True)
    use_gpu = models.BooleanField(default=False)

    def score(self):
        return self.mu - (self.sigma * 3)

    def __str__(self):
        return self.name


class Match(models.Model):
    date = models.DateTimeField()
    replay = models.FileField(upload_to="hlt/")
    seed = models.CharField(max_length=255)
    width = models.IntegerField()
    height = models.IntegerField()

    def __str__(self):
        return self.replay.name

    class Meta:
        verbose_name_plural = "matches"


class MatchResult(models.Model):
    bot = models.ForeignKey(Bot, related_name="matches", on_delete=models.CASCADE)
    rank = models.IntegerField()
    match = models.ForeignKey(Match, related_name="results", on_delete=models.CASCADE)
    mu = models.FloatField()
    sigma = models.FloatField()
    last_frame_alive = models.IntegerField()
    error_log = models.FileField(upload_to="error_logs", blank=True, null=True)

    def __str__(self):
        return "{0} - {1}: {2}".format(self.match, self.bot.name, self.rank)
