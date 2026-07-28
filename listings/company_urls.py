from django.urls import path

from . import views

app_name = "company"

urlpatterns = [
    path("listings/", views.MyCompanyListingsView.as_view(), name="my_listings"),
]
