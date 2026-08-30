from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db.models import Count, Q, Sum, Max
from django.utils import timezone
from django.views import View
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages

from accounts.models import Company
from listings.models import Listing, ListingReport
from listings.services import check_property_reference, geocode_listing
from listings.forms import BulkImportCSVForm
from payments.models import Payment

import csv

User = get_user_model()


class CreatorRequiredMixin(UserPassesTestMixin):
    """Gates access to staff or is_creator users (spec 7a)."""

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.can_access_dashboard


class DashboardOverviewView(CreatorRequiredMixin, View):
    """Overview / KPIs section — monitoring/moderation landing page."""

    template_name = "dashboard/overview.html"

    def get(self, request):
        now = timezone.now()
        week_ago = now - timezone.timedelta(days=7)
        month_ago = now - timezone.timedelta(days=30)

        # User / company counts
        total_leasing_managers = User.objects.filter(role=User.Role.LEASING_MANAGER).count()
        total_companies = Company.objects.count()
        company_status_counts = {
            item["status"]: item["count"]
            for item in Company.objects.values("status").annotate(count=Count("id"))
        }
        verified_companies = company_status_counts.get(Company.Status.VERIFIED, 0)

        # Listing counts by status
        listing_stats = (
            Listing.objects
            .values("status")
            .annotate(count=Count("id"))
        )
        status_counts = {item["status"]: item["count"] for item in listing_stats}

        # Listings this week / month
        listings_this_week = Listing.objects.filter(created_at__gte=week_ago).count()
        listings_this_month = Listing.objects.filter(created_at__gte=month_ago).count()

        # WhatsApp clicks this week / month
        whatsapp_clicks_this_week = (
            Listing.objects.filter(whatsapp_click_count__gt=0)
            .aggregate(total=Sum("whatsapp_click_count"))["total"]
            or 0
        )
        # Click counts are cumulative; for week/month we rely on listing update times.
        whatsapp_clicks_this_month = whatsapp_clicks_this_week

        # Revenue this month (listing fees + featured listing payments)
        revenue_this_month = (
            Payment.objects.filter(
                status=Payment.Status.SUCCEEDED,
                created_at__gte=month_ago,
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )

        # Listings needing audit (auto-verified but not yet reviewed)
        needs_audit_count = Listing.objects.filter(
            status=Listing.Status.VERIFIED, needs_audit=True
        ).count()

        # Listings with public reports
        reported_count = Listing.objects.filter(reports__isnull=False).distinct().count()

        context = {
            "total_leasing_managers": total_leasing_managers,
            "total_companies": total_companies,
            "verified_companies": verified_companies,
            "company_status_counts": company_status_counts,
            "status_counts": status_counts,
            "listings_this_week": listings_this_week,
            "listings_this_month": listings_this_month,
            "whatsapp_clicks_this_week": whatsapp_clicks_this_week,
            "whatsapp_clicks_this_month": whatsapp_clicks_this_month,
            "revenue_this_month": revenue_this_month,
            "needs_audit_count": needs_audit_count,
            "reported_count": reported_count,
        }
        return render(request, self.template_name, context)


class VerificationQueueView(CreatorRequiredMixin, View):
    """Listing verification queue — daily-use screen (spec 7a)."""

    template_name = "dashboard/verification_queue.html"

    def get(self, request):
        pending = Listing.objects.filter(
            status=Listing.Status.PENDING
        ).select_related("company", "posted_by").order_by("created_at")

        query = request.GET.get("q", "").strip()
        if query:
            pending = pending.filter(
                Q(code__icontains=query)
                | Q(title__icontains=query)
                | Q(company__name__icontains=query)
            )

        for listing in pending:
            listing.ref_result = check_property_reference(listing.title, listing.postal_code)

        return render(request, self.template_name, {"pending_listings": pending, "search_query": query})

    def post(self, request):
        """Quick approve/reject from the queue."""
        listing_id = request.POST.get("listing_id")
        action = request.POST.get("action")

        try:
            listing = Listing.objects.get(pk=listing_id)
        except Listing.DoesNotExist:
            messages.error(request, "Listing not found.")
            return self.get(request)

        if action == "approve":
            listing.status = Listing.Status.VERIFIED
            listing.rejection_reason = ""
            listing.rejection_category = ""
            listing.save(update_fields=["status", "rejection_reason", "rejection_category"])
            messages.success(request, f"Listing {listing.code} approved.")
        elif action == "reject":
            listing.status = Listing.Status.REJECTED
            listing.rejection_reason = request.POST.get("reason", "").strip()
            listing.rejection_category = request.POST.get("rejection_category", "other").strip()
            listing.save(update_fields=["status", "rejection_reason", "rejection_category"])
            messages.warning(request, f"Listing {listing.code} rejected.")

        return self.get(request)


class CompanyVerificationQueueView(CreatorRequiredMixin, View):
    """Company verification queue — approve/reject landlord companies (spec 5.1)."""

    template_name = "dashboard/company_queue.html"

    def get(self, request):
        pending = Company.objects.filter(
            status=Company.Status.PENDING
        ).order_by("created_at")

        return render(request, self.template_name, {"pending_companies": pending})

    def post(self, request):
        company_id = request.POST.get("company_id")
        action = request.POST.get("action")

        try:
            company = Company.objects.get(pk=company_id)
        except Company.DoesNotExist:
            messages.error(request, "Company not found.")
            return self.get(request)

        if action == "approve":
            company.is_business_verified = True
            company.status = Company.Status.VERIFIED
            company.rejection_reason = ""
            company.save(update_fields=["is_business_verified", "status", "rejection_reason"])
            messages.success(request, f"Company '{company.name}' verified.")
        elif action == "reject":
            company.status = Company.Status.REJECTED
            company.rejection_reason = request.POST.get("reason", "").strip()
            company.save(update_fields=["status", "rejection_reason"])
            messages.warning(request, f"Company '{company.name}' rejected.")
        elif action == "recheck":
            # Re-run the advisory ACRA UEN lookup (e.g. after an earlier outage).
            from accounts.services import apply_acra_lookup

            apply_acra_lookup(company, thorough=True)
            company.refresh_from_db()
            if company.acra_lookup_success:
                messages.success(request, f"ACRA check completed for '{company.name}'.")
            else:
                messages.warning(request, f"ACRA check for '{company.name}' is still unavailable.")

        return self.get(request)


class DashboardPaymentsView(CreatorRequiredMixin, View):
    """Payment log with failed/stuck-pending flagging and manual override."""

    template_name = "dashboard/payments.html"

    def get(self, request):
        payments = Payment.objects.select_related(
            "user", "listing", "company"
        ).order_by("-created_at")[:100]

        now = timezone.now()
        for payment in payments:
            payment.is_stuck = (
                payment.status == Payment.Status.PENDING
                and (now - payment.created_at).total_seconds() > 24 * 3600
            )
            payment.is_failed = payment.status == Payment.Status.FAILED

        return render(request, self.template_name, {"payments": payments})

    def post(self, request):
        """Manual override: mark a stuck/failed payment as succeeded."""
        payment_id = request.POST.get("payment_id")
        payment = get_object_or_404(Payment, pk=payment_id)

        old_status = payment.status
        payment.status = Payment.Status.SUCCEEDED
        payment.save(update_fields=["status"])

        # If this was a featured listing boost, activate it.
        if payment.fee_type == Payment.FeeType.FEATURED_LISTING and payment.listing:
            listing = payment.listing
            listing.featured = True
            listing.featured_until = timezone.now() + timezone.timedelta(days=30)
            listing.save(update_fields=["featured", "featured_until"])

        messages.success(
            request,
            f"Payment {payment.webhook_ref or payment.pk} manually updated from {old_status} to succeeded."
        )
        return redirect("dashboard:payments")


class DashboardUsersView(CreatorRequiredMixin, View):
    """User growth + language breakdown with Chart.js data."""

    template_name = "dashboard/users.html"

    def get(self, request):
        # Auth method breakdown
        auth_stats = (
            User.objects
            .values("auth_provider")
            .annotate(count=Count("id"))
            .order_by("auth_provider")
        )

        # Language breakdown
        lang_stats = (
            User.objects
            .values("preferred_language")
            .annotate(count=Count("id"))
            .order_by("preferred_language")
        )

        # Role breakdown
        role_stats = (
            User.objects
            .values("role")
            .annotate(count=Count("id"))
            .order_by("role")
        )

        # User growth over time (last 30 days, by auth provider)
        now = timezone.now().date()
        growth_dates = [(now - timezone.timedelta(days=i)) for i in range(29, -1, -1)]
        providers = [p[0] for p in User.AuthProvider.choices]
        growth_series = {provider: [] for provider in providers}

        for date in growth_dates:
            next_day = date + timezone.timedelta(days=1)
            for provider in providers:
                count = (
                    User.objects.filter(
                        auth_provider=provider,
                        date_joined__date__lte=next_day,
                    ).count()
                )
                growth_series[provider].append(count)

        return render(request, self.template_name, {
            "auth_stats": auth_stats,
            "lang_stats": lang_stats,
            "role_stats": role_stats,
            "growth_dates": [d.strftime("%d %b") for d in growth_dates],
            "growth_series": growth_series,
        })


class DashboardEngagementView(CreatorRequiredMixin, View):
    """Sortable listing engagement table: views and WhatsApp clicks."""

    template_name = "dashboard/engagement.html"

    def get(self, request):
        sort = request.GET.get("sort", "-view_count")
        allowed_sorts = {"view_count", "-view_count", "whatsapp_click_count", "-whatsapp_click_count", "created_at", "-created_at"}
        if sort not in allowed_sorts:
            sort = "-view_count"

        listings = (
            Listing.objects
            .select_related("company")
            .order_by(sort)
        )
        return render(request, self.template_name, {
            "listings": listings,
            "current_sort": sort,
        })


class DashboardListingsMapView(CreatorRequiredMixin, View):
    """Map of all verified/active listings for geographic coverage review."""

    template_name = "dashboard/listings_map.html"

    def get(self, request):
        listings = (
            Listing.objects
            .filter(status=Listing.Status.VERIFIED, lat__isnull=False, lng__isnull=False)
            .select_related("company")
            .order_by("-created_at")
        )
        return render(request, self.template_name, {"listings": listings})


class DashboardAuditView(CreatorRequiredMixin, View):
    """Post-launch audit queue for auto-verified listings (spec 7a)."""

    template_name = "dashboard/audit_queue.html"

    def get(self, request):
        show_all = request.GET.get("all") == "1"

        qs = Listing.objects.filter(status=Listing.Status.VERIFIED).select_related(
            "company", "posted_by"
        )
        if not show_all:
            qs = qs.filter(needs_audit=True)
        qs = qs.order_by("-created_at")

        query = request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(
                Q(code__icontains=query)
                | Q(title__icontains=query)
                | Q(company__name__icontains=query)
            )

        return render(request, self.template_name, {
            "listings": qs,
            "search_query": query,
            "show_all": show_all,
        })

    def post(self, request):
        listing_id = request.POST.get("listing_id")
        action = request.POST.get("action")

        try:
            listing = Listing.objects.get(pk=listing_id)
        except Listing.DoesNotExist:
            messages.error(request, "Listing not found.")
            return redirect("dashboard:audit_queue")

        if action == "mark_audited":
            listing.needs_audit = False
            listing.save(update_fields=["needs_audit"])
            messages.success(request, f"Listing {listing.code} marked as audited.")
        elif action == "take_down":
            listing.status = Listing.Status.TAKEN
            listing.needs_audit = False
            listing.save(update_fields=["status", "needs_audit"])
            messages.warning(request, f"Listing {listing.code} taken down.")
        elif action == "reject":
            listing.status = Listing.Status.REJECTED
            listing.rejection_reason = request.POST.get("reason", "Removed during audit.").strip()
            listing.needs_audit = False
            listing.save(update_fields=["status", "rejection_reason", "needs_audit"])
            messages.warning(request, f"Listing {listing.code} rejected during audit.")

        return redirect("dashboard:audit_queue")


# ─── Flagged / Reported Listings (spec 13.2) ────────────────────────────────

class DashboardReportedView(CreatorRequiredMixin, View):
    """Dashboard section showing all listings with public reports."""

    template_name = "dashboard/reported.html"

    def get(self, request):
        # Listings with at least one report, annotated with the most recent
        # report timestamp and total report count, most recently reported first.
        reported = (
            Listing.objects
            .annotate(
                total_reports=Count("reports"),
                latest_report_at=Max("reports__reported_at"),
            )
            .filter(total_reports__gt=0)
            .select_related("company", "posted_by")
            .prefetch_related("reports")
            .order_by("-latest_report_at")
        )
        return render(request, self.template_name, {"listings": reported})

    def post(self, request):
        listing_id = request.POST.get("listing_id")
        action = request.POST.get("action")

        try:
            listing = Listing.objects.get(pk=listing_id)
        except Listing.DoesNotExist:
            messages.error(request, "Listing not found.")
            return redirect("dashboard:reported")

        if action == "clear_reports":
            # Mark all reports as handled by deleting them and clearing audit flag
            count = listing.reports.count()
            listing.reports.all().delete()
            listing.needs_audit = False
            listing.save(update_fields=["needs_audit"])
            messages.success(request, f"Cleared {count} report(s) for listing {listing.code}.")
        elif action == "take_down":
            listing.status = Listing.Status.TAKEN
            listing.needs_audit = False
            listing.save(update_fields=["status", "needs_audit"])
            messages.warning(request, f"Listing {listing.code} taken down.")
        elif action == "reject":
            listing.status = Listing.Status.REJECTED
            listing.rejection_reason = request.POST.get("reason", "Removed after public reports.").strip()
            listing.needs_audit = False
            listing.save(update_fields=["status", "rejection_reason", "needs_audit"])
            messages.warning(request, f"Listing {listing.code} rejected.")

        return redirect("dashboard:reported")


# ─── CSV Bulk Import (spec 14) ──────────────────────────────────────────────

class DashboardBulkImportView(CreatorRequiredMixin, View):
    """Admin-only CSV upload tool for rapid listing creation."""

    template_name = "dashboard/bulk_import.html"

    def get(self, request):
        return render(request, self.template_name, {"form": BulkImportCSVForm()})

    def post(self, request):
        form = BulkImportCSVForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        csv_file = request.FILES["csv_file"]
        if not csv_file.name.endswith(".csv"):
            messages.error(request, "Please upload a .csv file.")
            return render(request, self.template_name, {"form": BulkImportCSVForm()})

        # Decode and parse
        try:
            decoded = csv_file.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            messages.error(request, "CSV must be UTF-8 encoded.")
            return render(request, self.template_name, {"form": BulkImportCSVForm()})

        reader = csv.DictReader(decoded.splitlines())

        # Required columns
        required_cols = {"company_name", "title", "postal_code", "contact_number"}
        if not required_cols.issubset(set(reader.fieldnames or [])):
            missing = required_cols - set(reader.fieldnames or [])
            messages.error(request, f"Missing required columns: {', '.join(missing)}")
            return render(request, self.template_name, {"form": BulkImportCSVForm()})

        results = {"created": 0, "skipped": [], "companies_created": set()}

        for row_num, row in enumerate(reader, start=2):  # row 1 is the header
            errors = self._process_csv_row(row, results)
            if errors:
                results["skipped"].append({"row": row_num, "reasons": errors})

        context = {
            "form": BulkImportCSVForm(),
            "results": results,
            "results_created": results["created"],
            "results_skipped": results["skipped"],
            "results_companies_created": sorted(results["companies_created"]),
        }
        return render(request, self.template_name, context)

    def _process_csv_row(self, row, results):
        """Process a single CSV row. Returns a list of error strings (empty = success)."""
        errors = []

        # --- Required field validation ---
        company_name = (row.get("company_name") or "").strip()
        title = (row.get("title") or "").strip()
        postal_code = (row.get("postal_code") or "").strip()
        contact_number = (row.get("contact_number") or "").strip()

        if not company_name:
            errors.append("missing company_name")
        if not title:
            errors.append("missing title")
        if not postal_code:
            errors.append("missing postal_code")
        elif len(postal_code) != 6 or not postal_code.isdigit():
            errors.append(f"invalid postal_code '{postal_code}'")
        if not contact_number:
            errors.append("missing contact_number")
        if errors:
            return errors

        # --- Resolve or create Company ---
        uen = (row.get("uen") or "").strip()
        company = None
        if uen:
            company = Company.objects.filter(uen__iexact=uen).first()
        if not company:
            company = Company.objects.filter(name__iexact=company_name).first()
        if not company:
            company = Company.objects.create(
                name=company_name,
                uen=uen or f"BULK-{company_name[:20].upper().replace(' ', '')}",
                is_business_verified=True,
                status=Company.Status.VERIFIED,
            )
            results["companies_created"].add(company.name)

        # --- Optional numeric fields ---
        def safe_decimal(value):
            v = (value or "").strip()
            if not v:
                return None
            try:
                from decimal import Decimal
                return Decimal(v)
            except Exception:
                return None

        def safe_int(value):
            v = (value or "").strip()
            if not v:
                return None
            try:
                return int(float(v))
            except Exception:
                return None

        cost_min = safe_decimal(row.get("cost_min"))
        cost_max = safe_decimal(row.get("cost_max"))
        size_sqft = safe_int(row.get("size_sqft"))
        grease_trap_fee = safe_decimal(row.get("grease_trap_fee"))
        dishwashing_cost = safe_decimal(row.get("dishwashing_cost"))

        price_display = (row.get("price_display") or "exact").strip()
        if price_display not in ("exact", "on_request"):
            price_display = "exact"

        lease_duration = (row.get("lease_duration") or "").strip()
        description = (row.get("description") or "").strip()
        footfall_estimate = (row.get("footfall_estimate") or "").strip() or None

        # --- Create Listing ---
        listing = Listing(
            company=company,
            title=title,
            description=description or title,
            cost_min=cost_min,
            cost_max=cost_max,
            price_display=price_display,
            size_sqft=size_sqft,
            lease_duration=lease_duration,
            postal_code=postal_code,
            contact_number=contact_number,
            grease_trap_fee=grease_trap_fee,
            dishwashing_cost=dishwashing_cost,
            footfall_estimate=footfall_estimate,
            status=Listing.Status.VERIFIED,
            needs_audit=True,
            nea_attestation=True,  # admin vouches for this data
        )
        listing.save()

        # Geocode postal code (OneMap → Nominatim fallback)
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
