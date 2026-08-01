from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.DashboardOverviewView.as_view(), name="overview"),
    path("verification/", views.VerificationQueueView.as_view(), name="verification_queue"),
    path("companies/", views.CompanyVerificationQueueView.as_view(), name="company_queue"),
    path("engagement/", views.DashboardEngagementView.as_view(), name="engagement"),
    path("payments/", views.DashboardPaymentsView.as_view(), name="payments"),
    path("map/", views.DashboardListingsMapView.as_view(), name="listings_map"),
    path("users/", views.DashboardUsersView.as_view(), name="users"),
    path("audit/", views.DashboardAuditView.as_view(), name="audit_queue"),
]
