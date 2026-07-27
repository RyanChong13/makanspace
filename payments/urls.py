from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path(
        "boost/<str:code>/",
        views.CreateCheckoutView.as_view(),
        name="create_checkout",
    ),
    path(
        "success/",
        views.PaymentSuccessView.as_view(),
        name="payment_success",
    ),
    path(
        "webhook/stripe/",
        views.StripeWebhookView.as_view(),
        name="stripe_webhook",
    ),
]
