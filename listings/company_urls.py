from django.urls import path

from . import views

app_name = "company"

urlpatterns = [
    path("listings/", views.MyCompanyListingsView.as_view(), name="my_listings"),
    path("quick-replies/add/", views.QuickReplyCreateView.as_view(), name="quick_reply_add"),
    path("quick-replies/<int:pk>/delete/", views.QuickReplyDeleteView.as_view(), name="quick_reply_delete"),
    path("wanted/", views.WantedPostListView.as_view(), name="wanted_list"),

    # Public company profile (QR-code landing page) — keep LAST so the fixed
    # paths above are never shadowed by the catch-all UEN segment.
    path("<str:uen>/", views.PublicCompanyProfileView.as_view(), name="company_profile"),
]
