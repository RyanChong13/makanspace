from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Listing
from .services import geocode_listing
from .tasks import translate_listing


@receiver(pre_save, sender=Listing)
def cache_listing_status(sender, instance, **kwargs):
    """Remember the previous status so post_save can detect transitions."""
    if instance.pk:
        try:
            instance._previous_status = Listing.objects.get(pk=instance.pk).status
        except Listing.DoesNotExist:
            instance._previous_status = None
    else:
        instance._previous_status = None


@receiver(post_save, sender=Listing)
def geocode_on_save(sender, instance, created, **kwargs):
    """
    Auto-geocode listing postal code via OneMap on creation or postal_code change.
    Runs post-save so the listing pk is available for code generation.
    """
    # Only geocode if we have a postal code but no coordinates yet
    if instance.postal_code and not instance.lat:
        geocode_listing(instance)
        # Update only the geocoding fields to avoid triggering save() recursion
        Listing.objects.filter(pk=instance.pk).update(
            lat=instance.lat,
            lng=instance.lng,
            nearest_mrt=instance.nearest_mrt,
            mrt_walk_minutes=instance.mrt_walk_minutes,
        )


@receiver(post_save, sender=Listing)
def translate_on_verify(sender, instance, **kwargs):
    """
    Trigger AI translation once when a listing becomes verified.
    Skips repeat calls on view-count updates or unrelated edits.
    """
    if instance.status != Listing.Status.VERIFIED:
        return
    previous = getattr(instance, "_previous_status", None)
    if previous == Listing.Status.VERIFIED:
        return
    translate_listing.delay(instance.pk)
