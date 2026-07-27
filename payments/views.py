"""
Stripe/PayNow payment integration (spec 5.2 / 10).
Self-serve featured listing boosts via Stripe Checkout.
Webhook-driven auto-upgrade on successful payment.
"""

import json
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from listings.models import Listing
from .models import Payment

logger = logging.getLogger(__name__)

# Featured listing pricing (SGD)
FEATURED_PRICES = {
    "14days": {"amount": 1990, "duration_days": 14, "label": "14 days boost"},
    "30days": {"amount": 3490, "duration_days": 30, "label": "30 days boost"},
}


class CreateCheckoutView(LoginRequiredMixin, View):
    """Creates a Stripe Checkout session for a featured listing boost (B2B)."""

    def post(self, request, code):
        listing = get_object_or_404(Listing, code=code)
        # Only same company's leasing managers or admin can boost
        if not request.user.is_staff and (
            not request.user.company or listing.company != request.user.company
        ):
            return JsonResponse({"error": "Permission denied."}, status=403)

        plan = request.POST.get("plan", "14days")
        price_info = FEATURED_PRICES.get(plan)

        if not price_info:
            return JsonResponse({"error": "Invalid plan."}, status=400)

        stripe_key = getattr(settings, "STRIPE_SECRET_KEY", "")
        if not stripe_key:
            return JsonResponse({"error": "Payments not configured."}, status=503)

        import stripe
        stripe.api_key = stripe_key

        try:
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency": "sgd",
                        "product_data": {
                            "name": f"MakanSpace Featured Boost — {price_info['label']}",
                            "description": f"Listing/matching service fee for {listing.code} ({listing.company.name})",
                        },
                        "unit_amount": price_info["amount"],
                    },
                    "quantity": 1,
                }],
                mode="payment",
                success_url=request.build_absolute_uri(f"/payments/success/?listing={listing.code}"),
                cancel_url=request.build_absolute_uri(f"/listing/{listing.code}/"),
                metadata={
                    "listing_id": listing.pk,
                    "user_id": request.user.pk,
                    "plan": plan,
                },
            )

            # Create pending payment record
            Payment.objects.create(
                user=request.user,
                company=listing.company,
                listing=listing,
                fee_type=Payment.FeeType.FEATURED_LISTING,
                amount=price_info["amount"] / 100,
                provider=Payment.Provider.STRIPE,
                status=Payment.Status.PENDING,
                webhook_ref=session.id,
                description=price_info["label"],
            )

            return redirect(session.url)

        except Exception as e:
            logger.error("Stripe checkout creation failed: %s", e)
            return JsonResponse({"error": "Could not create payment session."}, status=500)


class PaymentSuccessView(LoginRequiredMixin, View):
    """Redirect target after successful Stripe payment."""

    def get(self, request):
        listing_code = request.GET.get("listing", "")
        return render(request, "payments/success.html", {"listing_code": listing_code})


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(View):
    """
    Stripe webhook endpoint. Verifies signature and processes payment events.
    On checkout.session.completed → auto-upgrades listing to featured.
    """

    def post(self, request):
        stripe_key = getattr(settings, "STRIPE_SECRET_KEY", "")
        webhook_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")

        if not stripe_key or not webhook_secret:
            return HttpResponse(status=503)

        import stripe
        stripe.api_key = stripe_key

        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except (ValueError, stripe.error.SignatureVerificationError) as e:
            logger.warning("Stripe webhook signature verification failed: %s", e)
            return HttpResponse(status=400)

        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            self._process_successful_payment(session)

        return HttpResponse(status=200)

    def _process_successful_payment(self, session):
        """Auto-upgrade listing to featured on successful payment (spec 5.2)."""
        metadata = session.get("metadata", {})
        listing_id = metadata.get("listing_id")
        plan = metadata.get("plan", "14days")
        session_id = session.get("id", "")

        if not listing_id:
            logger.warning("Stripe webhook: no listing_id in metadata for session %s", session_id)
            return

        try:
            listing = Listing.objects.get(pk=listing_id)
        except Listing.DoesNotExist:
            logger.error("Stripe webhook: listing %s not found", listing_id)
            return

        price_info = FEATURED_PRICES.get(plan, FEATURED_PRICES["14days"])
        duration_days = price_info["duration_days"]

        # Update listing to featured
        listing.featured = True
        listing.featured_until = timezone.now() + timedelta(days=duration_days)
        listing.save(update_fields=["featured", "featured_until"])

        # Update payment record
        Payment.objects.filter(webhook_ref=session_id).update(
            status=Payment.Status.SUCCEEDED,
        )

        logger.info(
            "Listing %s boosted to featured until %s (plan: %s)",
            listing.code, listing.featured_until, plan,
        )
