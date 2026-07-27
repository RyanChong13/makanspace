from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "listing",
        "amount",
        "provider",
        "status",
        "created_at",
    )
    list_filter = ("status", "provider")
    search_fields = ("user__email", "listing__code", "webhook_ref")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"
