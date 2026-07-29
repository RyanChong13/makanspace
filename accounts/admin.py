from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User, Company, SiteSettings


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ("__str__", "updated_at")

    def has_add_permission(self, request):
        # Singleton: only one settings row is allowed.
        return not SiteSettings.objects.exists()


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "uen", "region", "whatsapp_number", "is_business_verified", "status", "referred_by", "created_at")
    list_filter = ("status", "is_business_verified", "region")
    search_fields = ("name", "uen")
    readonly_fields = ("created_at", "referred_by")
    actions = ["verify_companies", "reject_companies"]

    @admin.action(description="Mark selected companies as verified")
    def verify_companies(self, request, queryset):
        queryset.update(is_business_verified=True, status=Company.Status.VERIFIED)

    @admin.action(description="Reject selected companies")
    def reject_companies(self, request, queryset):
        queryset.update(status=Company.Status.REJECTED)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "email",
        "display_name",
        "role",
        "auth_provider",
        "company",
        "is_creator",
        "is_staff",
        "date_joined",
    )
    list_filter = (
        "role",
        "auth_provider",
        "is_creator",
        "is_staff",
        "preferred_language",
    )
    search_fields = ("email", "first_name", "last_name", "phone")
    ordering = ("-date_joined",)

    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "MakanSpace Profile",
            {
                "fields": (
                    "phone",
                    "auth_provider",
                    "role",
                    "company",
                    "is_creator",
                    "preferred_language",
                ),
            },
        ),
        (
            "Reserved Fields",
            {
                "classes": ("collapse",),
                "fields": (
                    "pre_screen_status",
                ),
            },
        ),
    )

    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (
            "MakanSpace Profile",
            {
                "fields": (
                    "email",
                    "phone",
                    "auth_provider",
                    "role",
                    "company",
                ),
            },
        ),
    )
