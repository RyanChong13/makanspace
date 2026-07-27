from django.contrib import admin

from .models import Testimonial


@admin.register(Testimonial)
class TestimonialAdmin(admin.ModelAdmin):
    list_display = ("listing", "applicant", "rating", "is_public", "created_at")
    list_filter = ("is_public", "rating")
    search_fields = ("listing__code", "text")
    readonly_fields = ("created_at",)
