from django.contrib.auth.models import AbstractUser
from django.db import models


LANG_CHOICES = [
    ("en", "English"),
    ("zh", "中文 (Chinese)"),
    ("ta", "தமிழ் (Tamil)"),
    ("ms", "Bahasa Melayu (Malay)"),
]

REGION_CHOICES = [
    ("north", "North"),
    ("south", "South"),
    ("east", "East"),
    ("west", "West"),
    ("central", "Central"),
    ("north-east", "North-East"),
]


# ─── Company (spec section 2 / 5.1) ─────────────────────────────────────────

class Company(models.Model):
    """
    A verified corporate F&B landlord/operator (e.g. Kimly, Kopitiam, Koufu).
    Only verified companies can create listings through their Leasing Managers.
    """

    class Status(models.TextChoices):
        PENDING = "pending_verification", "Pending Verification"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    name = models.CharField(max_length=200, help_text="Company legal name.")
    uen = models.CharField(
        max_length=50,
        unique=True,
        help_text="Unique Entity Number (ACRA business registration).",
    )
    region = models.CharField(
        max_length=20,
        choices=REGION_CHOICES,
        blank=True,
        help_text="Primary operating region (matches landlord leasing-team structures).",
    )
    whatsapp_number = models.CharField(
        max_length=20,
        blank=True,
        help_text="Company WhatsApp number for the Connect via WhatsApp button (with country code, e.g. +65).",
    )
    is_business_verified = models.BooleanField(default=False)
    business_reg_doc = models.FileField(
        upload_to="company_docs/",
        blank=True,
        null=True,
        help_text="ACRA/UEN business registration proof (PDF or image).",
    )
    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.PENDING,
    )
    rejection_reason = models.TextField(
        blank=True,
        help_text="Admin-visible reason when status is 'rejected'.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "companies"

    def __str__(self):
        return self.name

    @property
    def is_verified(self):
        return self.is_business_verified and self.status == self.Status.VERIFIED


# ─── User (spec section 2) ──────────────────────────────────────────────────

class User(AbstractUser):
    """Custom user model for MakanSpace B2B marketplace."""

    class Role(models.TextChoices):
        LEASING_MANAGER = "leasing_manager", "Leasing Manager"
        ADMIN = "admin", "Admin"

    class AuthProvider(models.TextChoices):
        EMAIL = "email", "Email"
        GOOGLE = "google", "Google"
        FACEBOOK = "facebook", "Facebook"

    # Core fields
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True)
    auth_provider = models.CharField(
        max_length=20,
        choices=AuthProvider.choices,
        default=AuthProvider.EMAIL,
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.LEASING_MANAGER,
    )

    # Company affiliation — set only for LEASING_MANAGER role.
    company = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
        help_text="Company this user belongs to (leasing managers only).",
    )

    # Dashboard access (spec 7a): separate from is_staff so co-creators
    # can access the internal dashboard without full Django Admin/DB access.
    is_creator = models.BooleanField(default=False)

    # Reserved dormant field (spec 7.2): future AI document pre-screening.
    pre_screen_status = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Reserved for future AI doc pre-screening. Unused in v1.",
    )

    # Language preference (spec 3.1)
    preferred_language = models.CharField(
        max_length=5,
        choices=LANG_CHOICES,
        default="en",
    )

    # Timestamps
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_joined"]

    def __str__(self):
        return self.email

    @property
    def display_name(self):
        return self.get_full_name() or self.username or self.email.split("@")[0]

    @property
    def can_post_listings(self):
        """Only leasing managers of verified companies can create listings."""
        return (
            self.is_authenticated
            and self.role == self.Role.LEASING_MANAGER
            and self.company is not None
            and self.company.is_verified
        )

    @property
    def can_access_dashboard(self):
        return self.is_staff or self.is_creator
