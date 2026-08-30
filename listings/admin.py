from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path

from .models import (
    Amenity, Listing, ListingImage, ListingTranslation,
    PropertyReference, Application, TastingSlot,
    WhatsAppClickEvent, QuickReplyTemplate, WantedPost,
    ListingReport, SupplierListing,
)


# ─── Inlines ─────────────────────────────────────────────────────────────────

class ListingImageInline(admin.TabularInline):
    model = ListingImage
    extra = 0
    readonly_fields = ("image", "order", "expires_at")


class ListingTranslationInline(admin.TabularInline):
    model = ListingTranslation
    extra = 0
    readonly_fields = ("language", "title", "description")


class ApplicationInline(admin.TabularInline):
    model = Application
    extra = 0
    readonly_fields = ("applicant", "status", "created_at")


class TastingSlotInline(admin.TabularInline):
    model = TastingSlot
    extra = 0
    readonly_fields = ("is_booked",)


class ListingReportInline(admin.TabularInline):
    model = ListingReport
    extra = 0
    readonly_fields = ("reason_category", "details", "reported_at")
    can_delete = True


# ─── Reject reason form ──────────────────────────────────────────────────────

class RejectReasonForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Reason shown to the leasing manager (not public).",
    )


# ─── PropertyReference Admin (spec 5.1) ─────────────────────────────────────

@admin.register(PropertyReference)
class PropertyReferenceAdmin(admin.ModelAdmin):
    list_display = ("establishment_name", "operator", "category", "region", "in_scope")
    list_filter = ("category", "in_scope", "region")
    search_fields = ("establishment_name", "operator")


# ─── Listing Admin ────────────────────────────────────────────────────────────

@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "company",
        "title",
        "cost_display",
        "status",
        "needs_audit",
        "featured",
        "created_at",
    )
    list_filter = (
        "status",
        "needs_audit",
        "featured",
        "lease_duration",
        "nea_attestation",
    )
    search_fields = ("code", "title", "company__name", "postal_code", "description")
    readonly_fields = ("code", "lat", "lng", "nearest_mrt", "mrt_walk_minutes",
                       "nearest_bus_stop", "bus_walk_minutes",
                       "created_at", "updated_at", "taken_at")
    date_hierarchy = "created_at"
    inlines = [ListingImageInline, ListingTranslationInline, ApplicationInline, TastingSlotInline, ListingReportInline]

    fieldsets = (
        (None, {
            "fields": ("code", "company", "posted_by", "status", "needs_audit", "rejection_reason"),
        }),
        ("Listing Details", {
            "fields": (
                "title", "description", "cost_min", "cost_max",
                "size_sqft", "lease_duration", "amenities",
            ),
        }),
        ("F&B Operational Fields", {
            "fields": ("grease_trap_fee", "dishwashing_cost", "footfall_estimate"),
        }),
        ("Location", {
            "fields": (
                "postal_code", "lat", "lng",
                "nearest_mrt", "mrt_walk_minutes",
                "nearest_bus_stop", "bus_walk_minutes",
            ),
        }),
        ("Contact & Moderation", {
            "fields": ("contact_number", "nea_attestation"),
        }),
        ("Featured / Boosted", {
            "fields": ("featured", "featured_until"),
        }),
        ("Flags (reserved dormant)", {
            "classes": ("collapse",),
            "fields": ("flagged_reason",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at", "taken_at"),
        }),
    )

    actions = ["approve_listings", "reject_listings", "mark_taken", "toggle_featured", "mark_audited"]

    def cost_display(self, obj):
        return obj.cost_display
    cost_display.short_description = "Cost"

    @admin.action(description="Approve selected listings")
    def approve_listings(self, request, queryset):
        count = queryset.filter(status=Listing.Status.PENDING).update(
            status=Listing.Status.VERIFIED
        )
        self.message_user(request, f"{count} listing(s) approved and now live.", messages.SUCCESS)

    @admin.action(description="Reject selected listings (with reason)")
    def reject_listings(self, request, queryset):
        if "apply" in request.POST:
            form = RejectReasonForm(request.POST)
            if form.is_valid():
                reason = form.cleaned_data["reason"]
                count = queryset.update(
                    status=Listing.Status.REJECTED,
                    rejection_reason=reason,
                )
                self.message_user(request, f"{count} listing(s) rejected.", messages.WARNING)
                return None

        form = RejectReasonForm()
        return render(request, "admin/reject_confirm.html", {
            "listings": queryset,
            "form": form,
            "title": "Reject listings",
            "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
            "opts": self.model._meta,
        })

    @admin.action(description="Mark selected listings as taken")
    def mark_taken(self, request, queryset):
        from django.utils import timezone
        count = queryset.filter(status=Listing.Status.VERIFIED).update(
            status=Listing.Status.TAKEN,
            taken_at=timezone.now(),
        )
        self.message_user(request, f"{count} listing(s) marked as taken.", messages.INFO)

    @admin.action(description="Toggle featured status")
    def toggle_featured(self, request, queryset):
        for listing in queryset:
            listing.featured = not listing.featured
            listing.save(update_fields=["featured"])
        self.message_user(request, f"Toggled featured for {queryset.count()} listing(s).")

    @admin.action(description="Mark selected listings as audited")
    def mark_audited(self, request, queryset):
        count = queryset.filter(needs_audit=True).update(needs_audit=False)
        self.message_user(request, f"{count} listing(s) marked as audited.", messages.SUCCESS)


# ─── Application Admin ───────────────────────────────────────────────────────

@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("listing", "applicant", "status", "tasting_slot", "created_at")
    list_filter = ("status",)
    search_fields = ("listing__code", "applicant__email")
    readonly_fields = ("created_at", "updated_at")


# ─── TastingSlot Admin ───────────────────────────────────────────────────────

@admin.register(TastingSlot)
class TastingSlotAdmin(admin.ModelAdmin):
    list_display = ("listing", "company", "start_time", "end_time", "is_booked")
    list_filter = ("is_booked",)


# ─── Amenity Admin ────────────────────────────────────────────────────────────

@admin.register(Amenity)
class AmenityAdmin(admin.ModelAdmin):
    list_display = ("slug", "name_en", "icon")
    search_fields = ("slug", "name_en")
    prepopulated_fields = {"slug": ("name_en",)}


# ─── WhatsAppClickEvent Admin ────────────────────────────────────────────────

@admin.register(WhatsAppClickEvent)
class WhatsAppClickEventAdmin(admin.ModelAdmin):
    list_display = ("listing", "clicked_at")
    list_filter = ("clicked_at",)
    search_fields = ("listing__code", "listing__title")
    readonly_fields = ("listing", "clicked_at")
    date_hierarchy = "clicked_at"


# ─── QuickReplyTemplate Admin ────────────────────────────────────────────────

@admin.register(QuickReplyTemplate)
class QuickReplyTemplateAdmin(admin.ModelAdmin):
    list_display = ("company", "label", "created_at")
    search_fields = ("company__name", "label", "message")


# ─── WantedPost Admin ────────────────────────────────────────────────────────

@admin.register(WantedPost)
class WantedPostAdmin(admin.ModelAdmin):
    list_display = ("contact_name", "preferred_town", "cuisine_type", "budget_display", "created_at")
    search_fields = ("contact_name", "preferred_town", "preferred_district", "cuisine_type")
    date_hierarchy = "created_at"

    def budget_display(self, obj):
        return obj.budget_display
    budget_display.short_description = "Budget"


# ─── ListingReport Admin ──────────────────────────────────────────────────

@admin.register(ListingReport)
class ListingReportAdmin(admin.ModelAdmin):
    list_display = ("listing", "reason_category", "reported_at")
    list_filter = ("reason_category",)
    search_fields = ("listing__code", "listing__title", "details")
    readonly_fields = ("listing", "reason_category", "details", "reported_at")
    date_hierarchy = "reported_at"


# ─── SupplierListing Admin (spec B9) ───────────────────────────────────────

@admin.register(SupplierListing)
class SupplierListingAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "contact_whatsapp", "is_active", "created_at")
    list_filter = ("category", "is_active")
    search_fields = ("name", "description", "contact_whatsapp")
