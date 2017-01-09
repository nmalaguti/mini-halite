from django.contrib import admin

# Register your models here.

from .models import Bot, MatchResult, Match

admin.site.register(Bot)
admin.site.register(Match)
admin.site.register(MatchResult)
