from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("company/signup/", views.CompanySignupView.as_view(), name="company_signup"),
    path("invite/", views.LeasingManagerInviteView.as_view(), name="invite_leasing_manager"),
    path("language/<str:lang_code>/", views.LanguageSelectView.as_view(), name="language_select"),
    path("profile/", views.ProfileView.as_view(), name="profile"),
]
