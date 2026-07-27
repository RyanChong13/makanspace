from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Q
from django.forms import inlineformset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
import json

from .forms import (
    ListingForm, ListingImage, ListingImageFormSet,
    ApplicationForm, TastingSlotForm,
)
from accounts.models import SiteSettings
from .models import Amenity, Listing, Application, TastingSlot
from .services import compress_image, check_property_reference, geocode_listing, SG_DISTRICT_MAP

User = get_user_model()


# ─── Mixins ──────────────────────────────────────────────────────────────────

class LeasingManagerRequiredMixin(UserPassesTestMixin):
    """Restricts to leasing managers of verified companies."""

    def test_func(self):
        return self.request.user.can_post_listings


class CompanyListingMixin(UserPassesTestMixin):
    """Restricts to users from the same company as the listing (or admin)."""

    def test_func(self):
        listing = self.get_object()
        user = self.request.user
        return user.is_staff or (
            user.is_authenticated
            and user.company is not None
            and listing.company == user.company
        )


# ─── Listing List (public, verified only) ────────────────────────────────────

class ListingListView(View):
    """
    Browse all verified listings with filter panel (spec 3.3).
    Supports HTMX partial responses for filter updates.
    """

    template_name = "listings/listing_list.html"
    partial_template = "partials/listing_results.html"

    def get_queryset(self):
        qs = Listing.objects.filter(status=Listing.Status.VERIFIED).select_related("company")

        # Cost range filter (preset buttons, spec 3.3)
        cost = self.request.GET.get("cost")
        if cost == "500-1000":
            qs = qs.filter(cost_min__gte=500, cost_min__lte=1000)
        elif cost == "1000-2000":
            qs = qs.filter(cost_min__gte=1000, cost_min__lte=2000)
        elif cost == "2000-3000":
            qs = qs.filter(cost_min__gte=2000, cost_min__lte=3000)
        elif cost == "3000+":
            qs = qs.filter(cost_min__gte=3000)

        # Size filter
        size = self.request.GET.get("size")
        if size == "<200":
            qs = qs.filter(size_sqft__lte=200)
        elif size == "200-400":
            qs = qs.filter(size_sqft__gte=200, size_sqft__lte=400)
        elif size == "400+":
            qs = qs.filter(size_sqft__gte=400)

        # Lease duration filter
        lease = self.request.GET.get("lease")
        if lease:
            qs = qs.filter(lease_duration=lease)

        # MRT/Bus distance filter
        mrt_dist = self.request.GET.get("mrt_distance")
        if mrt_dist:
            try:
                max_mins = int(mrt_dist)
                qs = qs.filter(mrt_walk_minutes__lte=max_mins)
            except ValueError:
                pass

        # Amenities filter (multi-select)
        amenities = self.request.GET.getlist("amenities")
        if amenities:
            for slug in amenities:
                qs = qs.filter(amenities__slug=slug)

        # Grease trap filter
        if self.request.GET.get("has_grease_trap"):
            qs = qs.filter(grease_trap_fee__isnull=False)

        # Location filter (postal district prefix)
        location = self.request.GET.get("location")
        if location and location in SG_DISTRICT_MAP:
            qs = qs.filter(postal_code__startswith=location)

        # Sort
        sort = self.request.GET.get("sort", "-featured")
        if sort == "cost_asc":
            qs = qs.order_by("cost_min")
        elif sort == "cost_desc":
            qs = qs.order_by("-cost_min")
        elif sort == "newest":
            qs = qs.order_by("-created_at")
        else:
            qs = qs.order_by("-featured", "-created_at")

        return qs.distinct()

    def get(self, request):
        listings = self.get_queryset()
        amenities = Amenity.objects.all()

        # HTMX partial response for filter updates
        if request.htmx:
            return render(request, self.partial_template, {
                "listings": listings,
                "count": listings.count(),
            })

        # Serialize listings for map pins (raw list for json_script filter)
        listings_data = [
            {
                "code": l.code,
                "title": l.title,
                "cost": l.cost_display,
                "lat": str(l.lat) if l.lat else None,
                "lng": str(l.lng) if l.lng else None,
            }
            for l in listings
        ]

        site_settings = SiteSettings.load()

        return render(request, self.template_name, {
            "listings": listings,
            "count": listings.count(),
            "amenities": amenities,
            "filters": request.GET.dict(),
            "selected_amenities": request.GET.getlist("amenities"),
            "listings_data": listings_data,
            "location_choices": sorted(SG_DISTRICT_MAP.items()),
            "site_settings": site_settings,
        })


# ─── Listing Detail (public) ────────────────────────────────────────────────

class ListingDetailView(View):
    template_name = "listings/listing_detail.html"

    def get(self, request, code):
        qs = Listing.objects.select_related("company", "posted_by").prefetch_related("images", "amenities")

        # Public visitors only see verified listings.
        try:
            listing = qs.get(code=code, status=Listing.Status.VERIFIED)
            is_preview = False
        except Listing.DoesNotExist:
            listing = get_object_or_404(qs, code=code)
            is_preview = self._can_preview(request, listing)
            if not is_preview:
                from django.http import Http404
                raise Http404()

        if not is_preview:
            listing.view_count += 1
            listing.save(update_fields=["view_count"])

        return render(request, self.template_name, {
            "listing": listing,
            "is_preview": is_preview,
        })

    def _can_preview(self, request, listing):
        """Owners and same-company leasing managers may preview non-verified listings."""
        if not request.user.is_authenticated:
            return False
        if request.user.is_staff:
            return True
        if listing.posted_by == request.user:
            return True
        return (
            request.user.role == User.Role.LEASING_MANAGER
            and request.user.company is not None
            and request.user.company == listing.company
        )


class WhatsAppClickView(View):
    """Track a WhatsApp click and redirect the visitor to the listing's wa.me link."""

    def get(self, request, code):
        listing = get_object_or_404(Listing, code=code, status=Listing.Status.VERIFIED)
        listing.whatsapp_click_count += 1
        listing.save(update_fields=["whatsapp_click_count"])
        if listing.whatsapp_url:
            return redirect(listing.whatsapp_url)
        messages.error(request, "No WhatsApp contact number is available for this listing.")
        return redirect("listings:listing_detail", code=code)


# ─── Listing Create (leasing manager only) ───────────────────────────────────

class ListingCreateView(LoginRequiredMixin, LeasingManagerRequiredMixin, View):
    template_name = "listings/listing_create.html"

    def get_formset(self):
        ImageFormSet = inlineformset_factory(
            Listing,
            ListingImage,
            formset=ListingImageFormSet,
            fields=["image"],
            extra=settings.MAX_LISTING_IMAGES,
            max_num=settings.MAX_LISTING_IMAGES,
            can_delete=False,
        )
        return ImageFormSet

    def get(self, request):
        form = ListingForm()
        formset = self.get_formset()()
        amenities = Amenity.objects.all()
        return render(request, self.template_name, {
            "form": form,
            "formset": formset,
            "amenities": amenities,
        })

    def post(self, request):
        form = ListingForm(request.POST, request.FILES)
        formset = self.get_formset()(request.POST, request.FILES)

        if form.is_valid() and formset.is_valid():
            listing = form.save(commit=False)
            listing.company = request.user.company
            listing.posted_by = request.user
            listing.status = Listing.Status.PENDING
            listing.save()
            form.save_m2m()

            # Geocode postal code (OneMap → Nominatim fallback)
            geocode_listing(listing)
            listing.save(update_fields=["lat", "lng", "nearest_mrt", "mrt_walk_minutes"])

            # PropertyReference cross-check (spec 5.1)
            ref_result = check_property_reference(listing.title, listing.postal_code)
            if ref_result["blocked"]:
                listing.status = Listing.Status.REJECTED
                listing.rejection_reason = ref_result["message"]
                listing.save(update_fields=["status", "rejection_reason"])
                messages.error(request, ref_result["message"])
                return redirect("listings:listing_list")

            listing.save(update_fields=["status"])
            if ref_result["needs_review"]:
                messages.info(request, "Listing submitted. It will be reviewed manually because the location could not be cross-checked.")
            else:
                messages.success(request, "Listing submitted and is pending verification.")

            # Process image uploads with compression (spec 3.4)
            for i, img_form in enumerate(formset.forms):
                if img_form.cleaned_data.get("image"):
                    compressed = compress_image(img_form.cleaned_data["image"])
                    ListingImage.objects.create(
                        listing=listing,
                        image=compressed,
                        order=i,
                    )

            return redirect("listings:listing_detail", code=listing.code)

        amenities = Amenity.objects.all()
        return render(request, self.template_name, {
            "form": form,
            "formset": formset,
            "amenities": amenities,
        })


# ─── Listing Update (same company's leasing managers or admin) ───────────────

class ListingUpdateView(LoginRequiredMixin, CompanyListingMixin, View):
    template_name = "listings/listing_update.html"

    def get_object(self):
        return get_object_or_404(Listing, code=self.kwargs["code"])

    def get_formset(self, listing):
        ImageFormSet = inlineformset_factory(
            Listing,
            ListingImage,
            formset=ListingImageFormSet,
            fields=["image"],
            extra=max(0, settings.MAX_LISTING_IMAGES - listing.images.count()),
            max_num=settings.MAX_LISTING_IMAGES,
            can_delete=True,
        )
        return ImageFormSet

    def get(self, request, code):
        listing = self.get_object()
        form = ListingForm(instance=listing)
        formset = self.get_formset(listing)(instance=listing)
        amenities = Amenity.objects.all()
        return render(request, self.template_name, {
            "form": form,
            "formset": formset,
            "listing": listing,
            "amenities": amenities,
        })

    def post(self, request, code):
        listing = self.get_object()
        form = ListingForm(request.POST, request.FILES, instance=listing)
        formset = self.get_formset(listing)(request.POST, request.FILES, instance=listing)

        if form.is_valid() and formset.is_valid():
            form.save()

            # Capture old image filenames BEFORE formset.save() mutates them,
            # otherwise replacement uploads are indistinguishable from unchanged files.
            old_images = {}
            for img_form in formset.forms:
                instance = img_form.instance
                if instance.pk:
                    old_images[instance.pk] = instance.image.name if instance.image else ""

            formset.save()

            # Compress only genuinely new or replaced images.
            for img_form in formset.forms:
                if img_form.cleaned_data.get("DELETE"):
                    continue
                instance = img_form.instance
                if instance.pk and instance.image:
                    old_name = old_images.get(instance.pk, "")
                    if instance.image.name != old_name:
                        instance.image = compress_image(instance.image)
                        instance.save(update_fields=["image"])

            return redirect("listings:listing_detail", code=listing.code)

        amenities = Amenity.objects.all()
        return render(request, self.template_name, {
            "form": form,
            "formset": formset,
            "listing": listing,
            "amenities": amenities,
        })


# ─── Application Views (spec 4.1) ───────────────────────────────────────────

class ApplicationCreateView(LoginRequiredMixin, View):
    """Hawker applicant submits an application (menu proposal + message)."""

    template_name = "listings/application_form.html"

    def get(self, request, code):
        listing = get_object_or_404(Listing, code=code, status=Listing.Status.VERIFIED)
        form = ApplicationForm()
        return render(request, self.template_name, {
            "form": form,
            "listing": listing,
        })

    def post(self, request, code):
        listing = get_object_or_404(Listing, code=code, status=Listing.Status.VERIFIED)
        form = ApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            application = form.save(commit=False)
            application.listing = listing
            application.applicant = request.user
            application.save()
            messages.success(request, "Application submitted successfully! The landlord will review your proposal.")
            return redirect("listings:listing_detail", code=listing.code)

        return render(request, self.template_name, {
            "form": form,
            "listing": listing,
        })


class ApplicationListView(LoginRequiredMixin, View):
    """Landlord views incoming applications for their listings."""

    template_name = "listings/application_list_landlord.html"

    def get(self, request, code):
        listing = get_object_or_404(Listing, code=code)
        # Only same company or admin
        if not request.user.is_staff and (not request.user.company or listing.company != request.user.company):
            messages.error(request, "You don't have access to this listing's applications.")
            return redirect("listings:listing_detail", code=code)

        applications = listing.applications.select_related("applicant", "tasting_slot").order_by("-created_at")
        return render(request, self.template_name, {
            "listing": listing,
            "applications": applications,
        })


class ApplicationActionView(LoginRequiredMixin, View):
    """Landlord approves/rejects an application."""

    def post(self, request, pk):
        application = get_object_or_404(Application, pk=pk)
        listing = application.listing

        # Only same company or admin
        if not request.user.is_staff and (not request.user.company or listing.company != request.user.company):
            messages.error(request, "Permission denied.")
            return redirect("listings:listing_detail", code=listing.code)

        action = request.POST.get("action")
        if action == "approve":
            application.status = Application.Status.APPROVED
            application.save(update_fields=["status", "updated_at"])
            messages.success(request, f"Application from {application.applicant.display_name} approved.")
        elif action == "reject":
            application.status = Application.Status.REJECTED
            application.rejection_reason = request.POST.get("reason", "")
            application.save(update_fields=["status", "rejection_reason", "updated_at"])
            messages.warning(request, f"Application from {application.applicant.display_name} rejected.")

        return redirect("listings:application_list", code=listing.code)


# ─── TastingSlot Views (spec 4.2) ───────────────────────────────────────────

class TastingSlotManageView(LoginRequiredMixin, View):
    """Landlord defines available tasting/viewing time slots for a listing."""

    template_name = "listings/tasting_slot_manage.html"

    def get(self, request, code):
        listing = get_object_or_404(Listing, code=code)
        if not request.user.is_staff and (not request.user.company or listing.company != request.user.company):
            messages.error(request, "Permission denied.")
            return redirect("listings:listing_detail", code=code)

        form = TastingSlotForm()
        slots = listing.tasting_slots.order_by("start_time")
        return render(request, self.template_name, {
            "form": form,
            "listing": listing,
            "slots": slots,
        })

    def post(self, request, code):
        listing = get_object_or_404(Listing, code=code)
        if not request.user.is_staff and (not request.user.company or listing.company != request.user.company):
            messages.error(request, "Permission denied.")
            return redirect("listings:listing_detail", code=code)

        form = TastingSlotForm(request.POST)
        if form.is_valid():
            slot = form.save(commit=False)
            slot.listing = listing
            slot.company = listing.company
            slot.save()
            messages.success(request, "Tasting slot added.")
            return redirect("listings:tasting_slot_manage", code=code)

        slots = listing.tasting_slots.order_by("start_time")
        return render(request, self.template_name, {
            "form": form,
            "listing": listing,
            "slots": slots,
        })


class TastingSlotBookView(LoginRequiredMixin, View):
    """Applicant books an available tasting slot for their application."""

    def post(self, request, slot_pk):
        slot = get_object_or_404(TastingSlot, pk=slot_pk, is_booked=False)
        application_id = request.POST.get("application_id")

        if application_id:
            try:
                application = Application.objects.get(
                    pk=application_id,
                    applicant=request.user,
                )
                # Atomic booking
                updated = TastingSlot.objects.filter(
                    pk=slot.pk, is_booked=False
                ).update(is_booked=True)
                if updated:
                    application.tasting_slot = slot
                    application.status = Application.Status.TASTING_SCHEDULED
                    application.save(update_fields=["tasting_slot", "status", "updated_at"])
                    messages.success(request, "Tasting session booked!")
                else:
                    messages.error(request, "This slot was just booked by someone else.")
            except Application.DoesNotExist:
                messages.error(request, "Application not found.")
        else:
            messages.error(request, "No application found.")

        listing_code = slot.listing.code if slot.listing else ""
        return redirect("listings:listing_detail", code=listing_code)


# ─── AI API Endpoints ────────────────────────────────────────────────────────

class VoiceUploadView(LoginRequiredMixin, View):
    """
    Accepts an audio blob upload, saves it temporarily, and dispatches
    the transcribe_and_extract Celery task. Returns extracted fields as JSON.
    """

    def post(self, request):
        audio_file = request.FILES.get("audio")
        if not audio_file:
            from django.http import JsonResponse
            return JsonResponse({"error": "No audio file provided."}, status=400)

        import tempfile
        import os
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
            for chunk in audio_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        from .tasks import transcribe_and_extract
        result = transcribe_and_extract(tmp_path)

        try:
            os.unlink(tmp_path)
        except OSError:
            pass

        from django.http import JsonResponse
        return JsonResponse(result)


class DraftDescriptionView(LoginRequiredMixin, View):
    """
    Accepts structured listing fields and returns an AI-drafted description.
    Owner reviews/edits before saving — never auto-publishes (spec 7.1).
    """

    def post(self, request):
        try:
            fields = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            fields = request.POST.dict()

        from .tasks import draft_listing_description
        description = draft_listing_description(fields)

        from django.http import JsonResponse
        return JsonResponse({"description": description})
