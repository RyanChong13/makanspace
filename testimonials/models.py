from django.conf import settings
from django.db import models


class Testimonial(models.Model):
    """
    Private testimonial collected after a listing is marked 'taken' (spec 5.3).
    Admin-only visibility in v1; is_public defaults to False.
    Public display is KIV — revisit post-launch based on demand/dispute risk.
    """

    listing = models.ForeignKey(
        "listings.Listing",
        on_delete=models.CASCADE,
        related_name="testimonials",
    )
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="testimonials",
        help_text="Nullable — guest applicants can also leave testimonials.",
    )
    text = models.TextField()
    rating = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="1-5 rating, optional.",
    )
    is_public = models.BooleanField(
        default=False,
        help_text="Not shown publicly in v1. Flip when public testimonials go live.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Testimonial for {self.listing.code} (rating={self.rating})"
