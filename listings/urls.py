from django.urls import path

from . import views

app_name = "listings"

urlpatterns = [
    # Public
    path("", views.ListingListView.as_view(), name="listing_list"),
    path("listing/<str:code>/", views.ListingDetailView.as_view(), name="listing_detail"),

    # Public WhatsApp contact (tracks click count)
    path("listing/<str:code>/whatsapp/", views.WhatsAppClickView.as_view(), name="whatsapp_click"),

    # Public 'stall wanted' reverse listing form (no login)
    path("wanted/post/", views.WantedPostCreateView.as_view(), name="wanted_post"),

    # Leasing manager actions
    path("post/", views.ListingCreateView.as_view(), name="listing_create"),
    path("listing/<str:code>/edit/", views.ListingUpdateView.as_view(), name="listing_update"),
    path("listing/<str:code>/delete/", views.ListingDeleteView.as_view(), name="listing_delete"),
]
