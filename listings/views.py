from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Q
from django.forms import inlineformset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.utils import timezone
from django.views import View
from datetime import timedelta
import csv
import json
import re

from .forms import (
    ListingForm, ListingImage, ListingImageFormSet,
    ApplicationForm, TastingSlotForm, WantedPostForm,
    ListingReportForm, BulkImportCSVForm,
)
from accounts.models import Company, SiteSettings
from .models import (
    Amenity, Listing, Application, TastingSlot,
    WhatsAppClickEvent, QuickReplyTemplate, WantedPost,
    ListingReport, SupplierListing, LEASE_DURATION_CHOICES,
)
from .services import compress_image, check_property_reference, geocode_listing, SG_DISTRICT_MAP
from .tasks import IMPORTABLE_FIELDS, propose_csv_mapping

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


class CompanyMemberRequiredMixin(UserPassesTestMixin):
    """Restricts to users attached to a company (any role)."""

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.company is not None


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

        # Sort — featured listings always float to the top of any order.
        sort = self.request.GET.get("sort", "-featured")
        if sort == "cost_asc":
            qs = qs.order_by("-featured", "cost_min")
        elif sort == "cost_desc":
            qs = qs.order_by("-featured", "-cost_min")
        elif sort == "newest":
            qs = qs.order_by("-featured", "-created_at")
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

        # Open Graph context for rich link previews (crawlers need absolute URLs)
        translation = listing.get_translation(getattr(request, "LANGUAGE_CODE", "en"))
        og_title = f"{translation.title if translation else listing.title} — {listing.company.name} | MakanSpace"
        images = listing.images.all()
        og_image_url = (
            request.build_absolute_uri(images[0].image.url)
            if images
            else request.build_absolute_uri(static("img/og-default.png"))
        )
        og_parts = [listing.cost_display]
        if listing.size_display:
            og_parts.append(listing.size_display)
        if listing.mrt_display:
            og_parts.append(listing.mrt_display)
        og_parts.append(f"Postal code {listing.postal_code}")

        return render(request, self.template_name, {
            "listing": listing,
            "is_preview": is_preview,
            "og_title": og_title,
            "og_description": " · ".join(og_parts),
            "og_image_url": og_image_url,
            "og_url": request.build_absolute_uri(request.path),
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
        # Timestamped event for rolling-window stats (running counter unchanged)
        WhatsAppClickEvent.objects.create(listing=listing)
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
        form = ListingForm(require_nea_attestation=True)
        formset = self.get_formset()()
        amenities = Amenity.objects.all()
        return render(request, self.template_name, {
            "form": form,
            "formset": formset,
            "amenities": amenities,
        })

    def post(self, request):
        form = ListingForm(request.POST, request.FILES, require_nea_attestation=True)
        formset = self.get_formset()(request.POST, request.FILES)

        if form.is_valid() and formset.is_valid():
            listing = form.save(commit=False)
            listing.company = request.user.company
            listing.posted_by = request.user
            listing.status = Listing.Status.VERIFIED
            listing.needs_audit = True
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
                messages.info(request, "Listing is live. The location could not be auto-cross-checked and has been flagged for audit.")
            else:
                messages.success(request, "Listing submitted and is now live!")

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

            # Compress new/replaced uploads BEFORE formset.save() writes to storage.
            # construct_instance (run during is_valid()) has already bound the raw
            # upload to img_form.instance.image, so the compressed file must be
            # assigned to the instance too — rewriting cleaned_data alone would
            # still persist the uncompressed original. Untouched file fields
            # resolve to the existing FieldFile (not an UploadedFile) and are
            # skipped so text-only edits never re-compress stored photos.
            for img_form in formset.forms:
                if img_form.cleaned_data.get("DELETE"):
                    continue
                raw_image = img_form.cleaned_data.get("image")
                if raw_image and isinstance(raw_image, UploadedFile):
                    compressed = compress_image(raw_image)
                    img_form.cleaned_data["image"] = compressed
                    img_form.instance.image = compressed

            formset.save()

            return redirect("listings:listing_detail", code=listing.code)

        amenities = Amenity.objects.all()
        return render(request, self.template_name, {
            "form": form,
            "formset": formset,
            "listing": listing,
            "amenities": amenities,
        })


# ─── My Company Listings (leasing manager self-service, /company/ namespace) ───

class MyCompanyListingsView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Self-service page: all listings belonging to the user's own company."""

    template_name = "listings/company_listings.html"

    def test_func(self):
        return self.request.user.company is not None

    def get(self, request):
        listings = (
            Listing.objects.filter(company=request.user.company)
            .prefetch_related("images")
            .order_by("-created_at")
        )

        # Code search: accepts BOOTH-XXXXXX (hawker-facing) or SG-XXXXXX (stored)
        query = request.GET.get("code", "").strip().upper()
        if query:
            normalized = query
            if normalized.startswith("BOOTH-"):
                normalized = "SG-" + normalized[len("BOOTH-"):]
            match = listings.filter(code=normalized).first()
            if match:
                return redirect("listings:listing_detail", code=match.code)
            messages.error(request, f"No listing with code {query} found for your company.")

        # Rolling 7-day WhatsApp click aggregate across all company listings
        weekly_clicks = WhatsAppClickEvent.objects.filter(
            listing__company=request.user.company,
            clicked_at__gte=timezone.now() - timedelta(days=7),
        ).count()

        return render(request, self.template_name, {
            "listings": listings,
            "company": request.user.company,
            "search_query": query,
            "weekly_clicks": weekly_clicks,
            "quick_replies": request.user.company.quick_replies.all(),
        })


# ─── Listing Delete (same company's leasing managers or admin) ───────────────

class ListingDeleteView(LoginRequiredMixin, CompanyListingMixin, View):
    """Delete a listing after explicit confirmation (same check as Edit Listing)."""

    template_name = "listings/listing_confirm_delete.html"

    def get_object(self):
        return get_object_or_404(Listing, code=self.kwargs["code"])

    def get(self, request, code):
        return render(request, self.template_name, {"listing": self.get_object()})

    def post(self, request, code):
        listing = self.get_object()
        title = listing.title
        listing.delete()  # pre_delete signal removes images from storage first
        messages.success(request, f"Listing '{title}' has been permanently deleted.")
        return redirect("company:my_listings")


# ─── Quick Reply Templates (company self-service) ───────────────────────────

class QuickReplyCreateView(LoginRequiredMixin, CompanyMemberRequiredMixin, View):
    """Save a pre-written WhatsApp reply for the user's company."""

    def post(self, request):
        label = request.POST.get("label", "").strip()
        message = request.POST.get("message", "").strip()
        if label and message:
            QuickReplyTemplate.objects.create(
                company=request.user.company, label=label, message=message,
            )
            messages.success(request, "Quick reply saved.")
        else:
            messages.error(request, "Both a label and a message are required.")
        return redirect("company:my_listings")


class QuickReplyDeleteView(LoginRequiredMixin, CompanyMemberRequiredMixin, View):
    """Delete one of the user's own company's quick replies."""

    def post(self, request, pk):
        template = get_object_or_404(QuickReplyTemplate, pk=pk)
        if template.company != request.user.company:
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden("You can only delete your own company's quick replies.")
        template.delete()
        messages.success(request, "Quick reply deleted.")
        return redirect("company:my_listings")


# ─── Public Company Profile (QR-code landing page) ──────────────────────────

class PublicCompanyProfileView(View):
    """
    Public (no login) portfolio page showing all of a company's verified
    listings — QR codes on physical signage point here so a hawker scanning
    one vacant stall sees the company's entire portfolio.
    """

    template_name = "listings/company_profile.html"

    def get(self, request, uen):
        company = get_object_or_404(Company, uen__iexact=uen)
        listings = (
            Listing.objects.filter(company=company, status=Listing.Status.VERIFIED)
            .prefetch_related("images", "amenities")
            .order_by("-featured", "-created_at")
        )

        # Open Graph: use the first listing photo as the preview image
        first_image = None
        for listing in listings:
            imgs = listing.images.all()
            if imgs:
                first_image = imgs[0]
                break
        og_image_url = (
            request.build_absolute_uri(first_image.image.url)
            if first_image
            else request.build_absolute_uri(static("img/og-default.png"))
        )

        return render(request, self.template_name, {
            "company": company,
            "listings": listings,
            "og_image_url": og_image_url,
            "og_url": request.build_absolute_uri(request.path),
        })


# ─── Stall Wanted (reverse listings) ─────────────────────────────────────────

class WantedPostCreateView(View):
    """Public 'stall wanted' form — no login required, matching the hawker model."""

    template_name = "listings/wanted_post_form.html"

    def get(self, request):
        return render(request, self.template_name, {"form": WantedPostForm()})

    def post(self, request):
        form = WantedPostForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                "Your stall-wanted post is live. Landlords will reach out to you on WhatsApp.",
            )
            return redirect("listings:listing_list")
        return render(request, self.template_name, {"form": form})


class WantedPostListView(LoginRequiredMixin, CompanyMemberRequiredMixin, View):
    """Open stall-wanted posts, visible to logged-in company members."""

    template_name = "listings/wanted_list.html"

    def get(self, request):
        return render(request, self.template_name, {
            "posts": WantedPost.objects.all(),
        })


# ─── Listing Report (public flagging, spec 13.2) ────────────────────────────

class ListingReportCreateView(View):
    """Public 'Report this listing' form — no login required."""

    template_name = "listings/listing_report.html"

    def get(self, request, code):
        listing = get_object_or_404(Listing, code=code, status=Listing.Status.VERIFIED)
        form = ListingReportForm()
        return render(request, self.template_name, {"form": form, "listing": listing})

    def post(self, request, code):
        listing = get_object_or_404(Listing, code=code, status=Listing.Status.VERIFIED)
        form = ListingReportForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.listing = listing
            report.save()
            # Bump the listing to the top of the audit queue
            if not listing.needs_audit:
                listing.needs_audit = True
                listing.save(update_fields=["needs_audit"])
            messages.success(
                request,
                "Thank you — your report has been submitted and the listing has been flagged for review.",
            )
            return redirect("listings:listing_detail", code=code)
        return render(request, self.template_name, {"form": form, "listing": listing})


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


# ─── Supplier Directory (public, spec B9) ────────────────────────────────────

class SupplierListView(View):
    """
    Public supplier directory — groups suppliers by category.
    No login required.
    """

    template_name = "listings/supplier_list.html"

    def get(self, request):
        from collections import OrderedDict

        all_suppliers = SupplierListing.objects.filter(is_active=True)

        # Optional category filter via query param
        category = request.GET.get("category", "")
        if category:
            all_suppliers = all_suppliers.filter(category=category)

        # Group by category for tabbed display
        grouped = OrderedDict()
        for cat_value, cat_label in SupplierListing.Category.choices:
            suppliers = [s for s in all_suppliers if s.category == cat_value]
            if suppliers:
                grouped[cat_value] = {
                    "label": cat_label,
                    "suppliers": suppliers,
                }

        return render(request, self.template_name, {
            "grouped": grouped,
            "all_suppliers": all_suppliers,
            "active_category": category,
            "category_choices": SupplierListing.Category.choices,
        })


# ─── Self-Serve CSV Mass Upload (spec B11) ──────────────────────────────────

SELF_SERVE_IMPORT_SESSION_KEY = "self_serve_import"
SELF_SERVE_IMPORT_MAX_ROWS = 500
SELF_SERVE_IMPORT_MAX_BYTES = 2 * 1024 * 1024  # 2MB


def _import_safe_decimal(value):
    """Parse a CSV numeric cell ('$1,500', '1500.50') into a Decimal or None."""
    v = (value or "").strip().replace("$", "").replace(",", "")
    if not v:
        return None
    try:
        from decimal import Decimal
        return Decimal(v)
    except Exception:
        return None


def _import_safe_int(value):
    """Parse a CSV integer cell ('$200', '200.0') into an int or None."""
    v = (value or "").strip().replace("$", "").replace(",", "")
    if not v:
        return None
    try:
        return int(float(v))
    except Exception:
        return None


def _normalize_lease_duration(value):
    """Map a free-text lease term to the model's choice value, or '' if unmatched."""
    v = (value or "").strip().lower()
    if not v:
        return ""
    for choice_val, choice_label in LEASE_DURATION_CHOICES:
        if v in (choice_val, choice_label.lower()):
            return choice_val
    m = re.match(r"^(\d+)", v)
    if not m:
        if "less than" in v or "under" in v or "short" in v:
            return "<6mo"
        if "more than" in v or "over" in v or "long" in v:
            return "2yr+"
        return ""
    n = int(m.group(1))
    in_months = "month" in v or "mth" in v or v.endswith("mo")
    if in_months:
        if n < 6:
            return "<6mo"
        if n <= 12:
            return "6-12mo"
        return "1-2yr"
    # Years (or a bare number, assumed months below)
    if "year" in v or "yr" in v:
        if n < 1:
            return "<6mo"
        if n == 1:
            return "6-12mo"
        if n == 2:
            return "1-2yr"
        return "2yr+"
    if n < 6:
        return "<6mo"
    if n <= 12:
        return "6-12mo"
    if n <= 24:
        return "1-2yr"
    return "2yr+"


class SelfServeImportView(LoginRequiredMixin, LeasingManagerRequiredMixin, View):
    """
    Self-serve AI-assisted CSV mass upload for leasing managers (spec B11).

    Three-step flow with the parsed CSV held in the session:
      1. Upload a CSV (any reasonable column headers).
      2. AI proposes a header→field mapping; the owner confirms/edits it —
         nothing is created before confirmation.
      3. Every confirmed row runs the exact same pipeline as a manual
         submission: OneMap geocoding, PropertyReference NEA-Direct
         hard-block (never skipped), status=VERIFIED + needs_audit=True.
    Company is fixed to the logged-in user's own company for every row.
    """

    upload_template = "listings/self_serve_import.html"
    review_template = "listings/self_serve_import_review.html"
    results_template = "listings/self_serve_import_results.html"

    def get(self, request):
        # Fresh visit: drop any stale upload state
        request.session.pop(SELF_SERVE_IMPORT_SESSION_KEY, None)
        return render(request, self.upload_template)

    def post(self, request):
        if request.POST.get("confirm_import"):
            return self._process_confirmed(request)
        return self._parse_upload(request)

    # ── Step 2: parse the uploaded CSV and propose a mapping ──────────────

    def _parse_upload(self, request):
        def fail(msg):
            messages.error(request, msg)
            return render(request, self.upload_template)

        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            return fail("Please choose a CSV file to upload.")
        if not csv_file.name.lower().endswith(".csv"):
            return fail("Please upload a .csv file.")
        if csv_file.size > SELF_SERVE_IMPORT_MAX_BYTES:
            return fail("CSV file is too large (maximum 2MB).")

        try:
            decoded = csv_file.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            return fail("CSV must be UTF-8 encoded.")

        rows = [row for row in csv.reader(decoded.splitlines()) if any(cell.strip() for cell in row)]
        if len(rows) < 2:
            return fail("The CSV needs a header row and at least one data row.")

        headers = [h.strip() for h in rows[0]]
        data_rows = rows[1:]
        if len(data_rows) > SELF_SERVE_IMPORT_MAX_ROWS:
            return fail(f"CSV has too many rows (maximum {SELF_SERVE_IMPORT_MAX_ROWS}).")

        # AI proposes the header→field mapping (alias fallback if unavailable)
        mapping = propose_csv_mapping(headers, data_rows[:5])

        request.session[SELF_SERVE_IMPORT_SESSION_KEY] = {
            "headers": headers,
            "rows": data_rows,
            "mapping": mapping,
        }

        return render(request, self.review_template, self._review_context(data_rows, mapping))

    def _review_context(self, data_rows, mapping):
        """Build template context for the mapping-confirmation screen."""
        headers = self._session_headers()
        columns = []
        for i, header in enumerate(headers):
            columns.append({
                "header": header,
                "mapped": mapping.get(header, ""),
                "values": [r[i] for r in data_rows[:3] if i < len(r) and r[i].strip()],
            })
        return {
            "columns": columns,
            "preview_rows": data_rows[:3],
            "importable_fields": IMPORTABLE_FIELDS,
            "total_rows": len(data_rows),
        }

    def _session_headers(self):
        data = self.request.session.get(SELF_SERVE_IMPORT_SESSION_KEY, {})
        return data.get("headers", [])

    # ── Step 3: confirmed mapping → create listings ────────────────────────

    def _process_confirmed(self, request):
        data = request.session.get(SELF_SERVE_IMPORT_SESSION_KEY)
        if not data:
            messages.error(request, "Your upload session expired. Please upload the CSV again.")
            return redirect("listings:self_serve_import")

        headers = data["headers"]
        data_rows = data["rows"]
        mapping = data["mapping"]

        # Adopt the user-confirmed mapping from the review screen's selects.
        selected = request.POST.getlist("column_map")
        if len(selected) == len(headers):
            mapping = {h: (s if s in IMPORTABLE_FIELDS else "") for h, s in zip(headers, selected)}

        context = self._review_context(data_rows, mapping)

        # Bulk NEA attestation — the create-page checkbox, applied per batch
        if not request.POST.get("nea_attestation"):
            context["attestation_error"] = (
                "You must confirm none of these stalls are part of an NEA Direct-managed hawker centre."
            )
            return render(request, self.review_template, context)

        results = {"created": 0, "skipped": []}
        for row_num, row in enumerate(data_rows, start=2):  # row 1 is the header
            errors = self._process_row(request, row, headers, mapping, results)
            if errors:
                results["skipped"].append({"row": row_num, "reasons": errors})

        request.session.pop(SELF_SERVE_IMPORT_SESSION_KEY, None)

        return render(request, self.results_template, {
            "created": results["created"],
            "skipped": results["skipped"],
            "total_rows": len(data_rows),
        })

    def _process_row(self, request, row, headers, mapping, results):
        """Create one Listing from a mapped CSV row. Returns a list of error strings."""
        record = {}
        for i, header in enumerate(headers):
            field = mapping.get(header, "")
            if field:
                record[field] = row[i].strip() if i < len(row) else ""

        errors = []
        title = record.get("title", "")
        postal_code = record.get("postal_code", "")
        if not title:
            errors.append("missing title")
        if not postal_code:
            errors.append("missing postal_code")
        elif len(postal_code) != 6 or not postal_code.isdigit():
            errors.append(f"invalid postal_code '{postal_code}'")
        if errors:
            return errors

        # Fall back to the company's own WhatsApp number for contactless rows
        contact_number = record.get("contact_number", "") or (request.user.company.whatsapp_number or "")
        if not contact_number:
            return ["missing contact_number"]

        price_display_raw = (record.get("price_display") or "").strip().lower()
        price_display = "on_request" if ("request" in price_display_raw or price_display_raw == "poa") else "exact"

        listing = Listing(
            company=request.user.company,
            posted_by=request.user,
            title=title,
            description=record.get("description") or title,
            cost_min=_import_safe_decimal(record.get("cost_min")),
            cost_max=_import_safe_decimal(record.get("cost_max")),
            price_display=price_display,
            size_sqft=_import_safe_int(record.get("size_sqft")),
            lease_duration=_normalize_lease_duration(record.get("lease_duration")),
            postal_code=postal_code,
            contact_number=contact_number,
            grease_trap_fee=_import_safe_decimal(record.get("grease_trap_fee")),
            dishwashing_cost=_import_safe_decimal(record.get("dishwashing_cost")),
            footfall_estimate=record.get("footfall_estimate") or None,
            status=Listing.Status.VERIFIED,
            needs_audit=True,
            nea_attestation=True,  # owner attested to the whole batch on the review screen
        )
        listing.save()

        # Geocode postal code (OneMap → Nominatim fallback) — same as manual flow
        geocode_listing(listing)
        listing.save(update_fields=["lat", "lng", "nearest_mrt", "mrt_walk_minutes"])

        # PropertyReference cross-check (NEA-Direct hard-block — no exceptions)
        ref_result = check_property_reference(listing.title, listing.postal_code)
        if ref_result["blocked"]:
            listing.status = Listing.Status.REJECTED
            listing.rejection_reason = ref_result["message"]
            listing.save(update_fields=["status", "rejection_reason"])
            return [f"blocked — {ref_result['message']}"]

        results["created"] += 1
        return []
