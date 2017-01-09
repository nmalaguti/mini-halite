from django.conf import settings
from django.shortcuts import render
from django.views import generic
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import F

from .models import Bot, Match


class IndexView(generic.ListView):
    template_name = 'tournament/index.html'

    def get_queryset(self):
        return Bot.objects.order_by(F('mu')-(F('sigma') * 3)).reverse()


class MatchesView(generic.ListView):
    template_name = 'tournament/matches.html'
    paginate_by = settings.PAGE_SIZE

    def get_queryset(self):
        return Match.objects.order_by('-date')


def bot_view(request, bot_id):
    bot = Bot.objects.get(id=bot_id)
    paginator = Paginator(bot.matches.order_by('-match__date').all(), settings.PAGE_SIZE)

    page = request.GET.get('page')
    try:
        match_list = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        match_list = paginator.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        match_list = paginator.page(paginator.num_pages)

    return render(request, 'tournament/bot.html', {
        'bot': bot,
        'match_list': match_list,
    })


class MatchView(generic.DetailView):
    model = Match
    template_name = 'tournament/match.html'
