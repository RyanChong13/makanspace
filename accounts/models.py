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

    # Automated ACRA UEN lookup results (data.gov.sg, advisory only — never
    # auto-approves/rejects; informs the admin's manual verification decision).
    acra_verified_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Entity name returned by the ACRA UEN lookup.",
    )
    acra_status = models.CharField(
        max_length=100,
        blank=True,
        help_text="Entity status from ACRA (e.g. 'Live Company', 'Struck Off').",
    )
    acra_registration_date = models.DateField(
        null=True,
        blank=True,
        help_text="Registration/incorporation date from ACRA.",
    )
    acra_lookup_success = models.BooleanField(
        default=False,
        help_text="Whether the automated ACRA lookup completed without errors.",
    )
    acra_checked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the automated ACRA lookup last ran.",
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

    @property
    def acra_status_is_live(self):
        """True when the ACRA status indicates a live entity ('Live', 'Live Company')."""
        return self.acra_status.strip().lower().startswith("live")

    @property
    def acra_name_matches(self):
        """
        Loose comparison of the signup name against the ACRA-registered name.
        Case-insensitive, ignores punctuation and common corporate suffixes;
        passes on substring containment or a fuzzy ratio >= 0.6.
        """
        import difflib
        import re

        def normalize(name):
            name = re.sub(r"[^a-z0-9 ]", " ", name.lower())
            suffixes = {"pte", "ltd", "private", "limited", "llp", "co"}
            words = [w for w in name.split() if w not in suffixes]
            return " ".join(words)

        entered = normalize(self.name)
        registered = normalize(self.acra_verified_name)
        if not entered or not registered:
            return False
        if entered in registered or registered in entered:
            return True
        return difflib.SequenceMatcher(None, entered, registered).ratio() >= 0.6


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


# ─── SiteSettings (singleton) ───────────────────────────────────────────────

class SiteSettings(models.Model):
    """Singleton site-wide settings editable from Django Admin."""

    banner_image = models.ImageField(
        upload_to="site/banners/",
        blank=True,
        help_text="Homepage hero banner image (wide promotional image, e.g. 1200x400).",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Site Setting"
        verbose_name_plural = "Site Settings"

    def __str__(self):
        return "Site Settings"

    def save(self, *args, **kwargs):
        # Enforce singleton: only one row ever exists.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        """Return the singleton instance, creating it if necessary."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
