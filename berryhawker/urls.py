"""URL configuration for berryhawker project."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView


urlpatterns = [
    # Django Admin
    path("admin/", admin.site.urls),

    # MakanSpace: public signups are company-only; redirect default allauth signup
    path("accounts/signup/", RedirectView.as_view(pattern_name="accounts:company_signup", permanent=False)),

    # django-allauth (login, logout, password reset, social accounts)
    path("accounts/", include("allauth.urls")),

    # Custom accounts (owner signup, language selection)
    path("accounts/", include("accounts.urls")),

    # Listings (browse, create, manage)
    path("", include("listings.urls")),

    # Payments (Stripe/PayNow)
    path("payments/", include("payments.urls")),

    # AI chatbot search
    path("api/chatbot/", include("chatbot.urls")),

    # Internal dashboard
    path("dashboard/", include("dashboard.urls")),

    # Company self-service portal (leasing managers)
    path("company/", include("listings.company_urls")),

    # Root redirect to listings
    path("", RedirectView.as_view(pattern_name="listings:listing_list"), name="root"),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
