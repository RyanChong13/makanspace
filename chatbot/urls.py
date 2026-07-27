from django.urls import path

from . import views

app_name = "chatbot"

urlpatterns = [
    path("search/", views.chatbot_search, name="search"),
]
