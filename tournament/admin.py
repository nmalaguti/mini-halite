from django.contrib import admin

from .models import Bot, MatchResult, Match


class BotAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "docker_image",
        "trunc_mu",
        "trunc_sigma",
        "trunc_score",
        "enabled",
        "use_gpu",
    ]

    @admin.display(description="mu")
    def trunc_mu(self, obj):
        return f"{obj.mu:0.2f}"

    @admin.display(description="sigma")
    def trunc_sigma(self, obj):
        return f"{obj.mu:0.2f}"

    @admin.display(description="Score")
    def trunc_score(self, obj):
        return f"{obj.score():0.2f}"


admin.site.register(Bot, BotAdmin)
admin.site.register(Match)
admin.site.register(MatchResult)
