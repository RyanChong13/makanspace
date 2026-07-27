from django.conf import settings
from django.db import models


class Payment(models.Model):
    """
    B2B payment record for listing/matching service fees or featured boosts (spec 5.2).
    Supports Stripe via webhook-driven updates.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    class Provider(models.TextChoices):
        STRIPE = "stripe", "Stripe"
        PAYNOW = "paynow", "PayNow"

    class FeeType(models.TextChoices):
        LISTING_FEE = "listing_fee", "Listing / Matching Service Fee"
        FEATURED_LISTING = "featured_listing", "Featured Listing Boost"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payments",
        help_text="User who initiated the payment.",
    )
    company = models.ForeignKey(
        "accounts.Company",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
        help_text="The landlord company being charged.",
    )
    listing = models.ForeignKey(
        "listings.Listing",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    fee_type = models.CharField(
        max_length=30,
        choices=FeeType.choices,
        default=FeeType.FEATURED_LISTING,
    )
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    currency = models.CharField(max_length=3, default="SGD")
    provider = models.CharField(max_length=20, choices=Provider.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    webhook_ref = models.CharField(
        max_length=200,
        blank=True,
        help_text="Payment gateway transaction/event ID.",
    )
    description = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        label = self.company.name if self.company else self.user.email
        return f"{label} — ${self.amount} ({self.get_fee_type_display()})"
