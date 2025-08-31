from django.urls import path

from . import views

app_name = 'tournament'
urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('bots/<int:bot_id>/', views.bot_view, name='bot'),
    path('matches/', views.MatchesView.as_view(), name='matches'),
    path('matches/<int:pk>/', views.MatchView.as_view(), name='match'),
]
