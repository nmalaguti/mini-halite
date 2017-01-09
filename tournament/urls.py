from django.conf.urls import url

from . import views

app_name = 'tournament'
urlpatterns = [
    url(r'^$', views.IndexView.as_view(), name='index'),
    url(r'^bots/(?P<bot_id>[0-9]+)/$', views.bot_view, name='bot'),
    url(r'^matches/$', views.MatchesView.as_view(), name='matches'),
    url(r'^matches/(?P<pk>[0-9]+)/$', views.MatchView.as_view(), name='match'),
]
