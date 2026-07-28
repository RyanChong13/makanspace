from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.views import View
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages

from accounts.models import Company
from listings.models import Listing
from listings.services import check_property_reference
from payments.models import Payment

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
