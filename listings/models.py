from django.conf import settings
from django.db import models

from accounts.models import LANG_CHOICES, Company


# ─── Choices ────────────────────────────────────────────────────────────────

COST_RANGE_CHOICES = [
    ("500-1000", "$500–1,000"),
    ("1000-2000", "$1,000–2,000"),
    ("2000-3000", "$2,000–3,000"),
    ("3000+", "$3,000+"),
]

LEASE_DURATION_CHOICES = [
    ("<6mo", "Less than 6 months"),
    ("6-12mo", "6 to 12 months"),
    ("1-2yr", "1 to 2 years"),
    ("2yr+", "More than 2 years"),
]


# ─── Amenity ─────────────────────────────────────────────────────────────────

class Amenity(models.Model):
    """
    Amenity available for a hawker stall (fridge, exhaust hood, sink, etc.).
    Displayed with icon + plain-language label (spec 3.3 / 3.4).
    """

    slug = models.SlugField(unique=True)
    name_en = models.CharField(max_length=100, help_text="Plain-language label, e.g. 'Fridge included'")
    icon = models.CharField(
        max_length=50,
        blank=True,
        help_text="CSS icon class or emoji, e.g. 'fridge' or '🧊'",
    )

    class Meta:
        ordering = ["name_en"]
        verbose_name_plural = "amenities"

    def __str__(self):
        return self.name_en


# ─── PropertyReference (spec 5.1) ───────────────────────────────────────────

class PropertyReference(models.Model):
    """
    Reference table seeded from hawker_centre_reference_seed.csv.
    Used to cross-check listings against NEA Direct / SEHC / Private tiers.
    Admin can add new entries over time.
    """

    class Category(models.TextChoices):
        NEA_DIRECT = "nea_direct", "Government (NEA Direct)"
        SEHC = "sehc", "Government (SEHC)"
        PRIVATE_FOOD_COURT = "private_food_court", "Private (Food Court)"
        PRIVATE_COFFEESHOP = "private_coffeeshop", "Private (Coffeeshop)"
        PRIVATE_THEMATIC = "private_thematic", "Private (Thematic)"

    category = models.CharField(max_length=30, choices=Category.choices)
    operator = models.CharField(max_length=200, help_text="Operating company name.")
    establishment_name = models.CharField(max_length=300, help_text="Name of the hawker centre / food court.")
    region = models.CharField(max_length=20, blank=True)
    in_scope = models.BooleanField(
        help_text="FALSE only for NEA Direct tier — the one legal no-go zone.",
    )
    scope_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["establishment_name"]

    def __str__(self):
        return f"{self.establishment_name} ({self.get_category_display()})"


# ─── Listing ─────────────────────────────────────────────────────────────────

class Listing(models.Model):
    """A hawker/coffee-shop stall available for rent (private, non-NEA only)."""

    class Status(models.TextChoices):
        PENDING = "pending_verification", "Pending Verification"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"
        TAKEN = "taken", "Taken"

    # Company ownership (spec 2): only verified landlord companies can list
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="listings",
        help_text="The landlord company that owns/manages this stall.",
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="posted_listings",
        help_text="The leasing manager who created this listing.",
    )

    # Short unique code
    code = models.CharField(max_length=30, unique=True, blank=True)

    # Core details
    title = models.CharField(max_length=200)
    description = models.TextField()
    cost_min = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Minimum monthly rent in SGD. Not required when 'Rental on request' is selected.",
    )
    cost_max = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Maximum monthly rent in SGD (leave blank if fixed price).",
    )
    price_display = models.CharField(
        max_length=20,
        choices=[
            ("exact", "Exact price"),
            ("on_request", "Rental on request"),
        ],
        default="exact",
        help_text="'Exact price' is recommended for transparency. 'Rental on request' hides the numeric range.",
    )
    size_sqft = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Stall size in square feet.",
    )
    lease_duration = models.CharField(
        max_length=10,
        choices=LEASE_DURATION_CHOICES,
        blank=True,
    )
    amenities = models.ManyToManyField(
        Amenity,
        blank=True,
        related_name="listings",
    )

    # F&B-specific operational fields (spec 3.4)
    grease_trap_fee = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Monthly grease-trap maintenance fee in SGD (optional).",
    )
    dishwashing_cost = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Monthly dishwashing/cleaning cost in SGD (optional).",
    )
    footfall_estimate = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Estimated daily footfall, e.g. '~500/day' (optional).",
    )

    # Location (geocoded from postal_code via OneMap, spec 3.3 / 5)
    postal_code = models.CharField(max_length=6)
    lat = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    nearest_mrt = models.CharField(max_length=100, blank=True)
    mrt_walk_minutes = models.PositiveIntegerField(blank=True, null=True)
    nearest_bus_stop = models.CharField(max_length=100, blank=True)
    bus_walk_minutes = models.PositiveIntegerField(blank=True, null=True)

    # Contact
    contact_number = models.CharField(
        max_length=20,
        help_text="Leasing team contact number (with country code, e.g. +65).",
    )

    # Status & moderation
    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.PENDING,
    )
    rejection_reason = models.TextField(
        blank=True,
        help_text="Admin-visible reason when status is 'rejected'.",
    )
    rejection_category = models.CharField(
        max_length=30,
        blank=True,
        choices=[
            ("business_verification", "Business verification issue"),
            ("property_tier_failure", "Property tier failure (NEA Direct / in-scope block)"),
            ("other", "Other"),
        ],
        help_text="Type of rejection for moderation reporting.",
    )

    # Featured / boosted listing (spec 5.2)
    featured = models.BooleanField(default=False)
    featured_until = models.DateTimeField(blank=True, null=True)

    # NEA exclusion attestation (spec 9) — mandatory at listing creation
    nea_attestation = models.BooleanField(
        default=False,
        help_text="Landlord confirms this stall is NOT part of an NEA Direct-managed centre.",
    )

    # Reserved dormant field (spec 7.2): future fraud/duplicate detection
    flagged_reason = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Reserved for future AI fraud detection. Unused in v1.",
    )

    # Auto-verification audit flag: every listing is now auto-verified on
    # submission (no manual queue). This flag lets creators retroactively
    # audit newly live listings. Set to True on creation; cleared when audited.
    needs_audit = models.BooleanField(
        default=True,
        help_text="True for newly auto-verified listings; cleared after a creator audits them.",
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    taken_at = models.DateTimeField(blank=True, null=True)

    # Analytics / reserved counters (spec 8 / 10)
    view_count = models.PositiveIntegerField(default=0)
    whatsapp_click_count = models.PositiveIntegerField(default=0)

    @property
    def report_count(self):
        """How many public reports exist for this listing."""
        return self.reports.count()

    # Reserved dormant field (spec 7.2): future AI document pre-screening
    pre_screen_status = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Reserved for future AI doc pre-screening. Unused in v1.",
    )

    class Meta:
        ordering = ["-featured", "-created_at"]

    def __str__(self):
        return f"{self.code} — {self.title}"

    def save(self, *args, **kwargs):
        # Auto-generate a brand-independent, non-sequential code on first insert.
        # The code is stored once and never regenerated so it stays stable across
        # every hawker contact and can be searched in the dashboard.
        if not self.code:
            import random
            import string

            while True:
                suffix = "".join(
                    random.choices(string.ascii_uppercase + string.digits, k=6)
                )
                candidate = f"SG-{suffix}"
                if not Listing.objects.filter(code=candidate).exists():
                    self.code = candidate
                    break
        super().save(*args, **kwargs)

    @property
    def is_public(self):
        return self.status == self.Status.VERIFIED

    @property
    def cost_display(self):
        if self.price_display == "on_request":
            return "Rental on Request"
        if self.cost_max and self.cost_max != self.cost_min:
            return f"${self.cost_min:,.0f}–${self.cost_max:,.0f}/mo"
        return f"${self.cost_min:,.0f}/mo"

    @property
    def size_display(self):
        return f"{self.size_sqft:,} sqft" if self.size_sqft else None

    @property
    def lease_display(self):
        return dict(LEASE_DURATION_CHOICES).get(self.lease_duration, self.lease_duration)

    @property
    def mrt_display(self):
        if self.nearest_mrt and self.mrt_walk_minutes:
            return f"{self.mrt_walk_minutes} min walk to {self.nearest_mrt}"
        return None

    @property
    def bus_display(self):
        if self.nearest_bus_stop and self.bus_walk_minutes:
            return f"{self.bus_walk_minutes} min walk to {self.nearest_bus_stop}"
        return None

    @property
    def whatsapp_number(self):
        """Best contact number for WhatsApp: company first, then listing contact."""
        return (self.company.whatsapp_number or self.contact_number or "").strip()

    @property
    def whatsapp_url(self):
        """Generate a wa.me deep link with a pre-filled message."""
        raw = self.whatsapp_number
        if not raw:
            return ""
        digits = "".join(ch for ch in raw if ch.isdigit())
        if not digits:
            return ""
        suffix = self.code[3:] if self.code.startswith("SG-") else self.code
        message = f"Hi! I would like to enquire more about BOOTH-{suffix}."
        from urllib.parse import quote
        return f"https://wa.me/{digits}?text={quote(message)}"

    def get_translation(self, language):
        """Return the ListingTranslation for a language code (normalises zh-hans → zh)."""
        if language == "zh-hans":
            language = "zh"
        return self.translations.filter(language=language).first()


# ─── ListingTranslation ──────────────────────────────────────────────────────

class ListingTranslation(models.Model):
    """
    Translated version of a listing (spec 3.2).
    Stored per-language to avoid translating on every page load.
    """

    listing = models.ForeignKey(
        Listing,
        on_delete=models.CASCADE,
        related_name="translations",
    )
    language = models.CharField(max_length=5, choices=LANG_CHOICES)
    title = models.CharField(max_length=200)
    description = models.TextField()
    amenities_text = models.JSONField(
        default=list,
        help_text="List of translated amenity labels.",
    )

    class Meta:
        unique_together = ("listing", "language")
        ordering = ["language"]

    def __str__(self):
        return f"{self.listing.code} [{self.language}]"


# ─── ListingImage ────────────────────────────────────────────────────────────

class ListingImage(models.Model):
    """
    Photo for a listing, stored on Cloudinary (spec 1 / 3.4).
    Auto-compressed server-side to 512KB cap — owner never sees a size error.
    """

    listing = models.ForeignKey(
        Listing,
        on_delete=models.CASCADE,
        related_name="images",
    )
    image = models.ImageField(upload_to="listings/")
    cloudinary_url = models.URLField(blank=True)
    order = models.PositiveIntegerField(default=0)

    # Set when listing marked 'taken' — Celery task deletes after grace period (spec 6)
    expires_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.listing.code} — image {self.order}"


# ─── TastingSlot (spec 4.2) ─────────────────────────────────────────────────

class TastingSlot(models.Model):
    """
    Available time slot for food-tasting/viewing session.
    Can be per-listing or reusable across a company's listings.
    """

    listing = models.ForeignKey(
        Listing,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tasting_slots",
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tasting_slots",
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    is_booked = models.BooleanField(default=False)

    class Meta:
        ordering = ["start_time"]

    def __str__(self):
        target = self.listing.code if self.listing else self.company.name
        return f"{target} — {self.start_time:%d %b %H:%M}"


# ─── Application (spec 4.1) ─────────────────────────────────────────────────

class Application(models.Model):
    """
    Hawker applicant submits a menu proposal + books a tasting session
    for a specific listing.
    """

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        TASTING_SCHEDULED = "tasting_scheduled", "Tasting Scheduled"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    listing = models.ForeignKey(
        Listing,
        on_delete=models.CASCADE,
        related_name="applications",
    )
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="applications",
    )
    menu_proposal_doc = models.FileField(
        upload_to="menu_proposals/",
        blank=True,
        null=True,
        help_text="Menu proposal (PDF or image).",
    )
    message = models.TextField(
        blank=True,
        help_text="Optional message to the landlord.",
    )
    tasting_slot = models.ForeignKey(
        TastingSlot,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="applications",
    )
    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.SUBMITTED,
    )
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.applicant.display_name} → {self.listing.code} ({self.status})"


# ─── WhatsAppClickEvent ──────────────────────────────────────────────────────

class WhatsAppClickEvent(models.Model):
    """
    Timestamped log of a single 'Connect via WhatsApp' click.
    Enables rolling-window stats (e.g. clicks in the last 7 days) that the
    running whatsapp_click_count counter cannot answer.
    """

    listing = models.ForeignKey(
        Listing,
        on_delete=models.CASCADE,
        related_name="click_events",
    )
    clicked_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-clicked_at"]

    def __str__(self):
        return f"{self.listing.code} @ {self.clicked_at:%d %b %H:%M}"


# ─── QuickReplyTemplate ──────────────────────────────────────────────────────

class QuickReplyTemplate(models.Model):
    """
    Pre-written WhatsApp response a leasing manager can copy-paste when
    replying to hawker enquiries (never auto-sent).
    """

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="quick_replies",
    )
    label = models.CharField(max_length=100, help_text="Short name, e.g. 'Still available'.")
    message = models.TextField(help_text="The reply text to copy into WhatsApp.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.company.name} — {self.label}"


# ─── WantedPost (reverse listing) ────────────────────────────────────────────

class WantedPost(models.Model):
    """
    'Stall wanted' post from a hawker describing what they're looking for.
    No user account required — matches the no-login hawker model; leasing
    managers respond directly via WhatsApp.
    """

    contact_name = models.CharField(max_length=100)
    contact_whatsapp = models.CharField(
        max_length=20,
        help_text="WhatsApp number with country code, e.g. +65 9123 4567.",
    )
    preferred_town = models.CharField(max_length=100, blank=True)
    preferred_district = models.CharField(max_length=100, blank=True)
    cuisine_type = models.CharField(max_length=100, blank=True)
    budget_min = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    budget_max = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    lease_duration = models.CharField(
        max_length=10,
        choices=LEASE_DURATION_CHOICES,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.contact_name} — {self.preferred_town or 'anywhere'}"

    @property
    def budget_display(self):
        if self.budget_min and self.budget_max:
            return f"${self.budget_min:,.0f}–${self.budget_max:,.0f}/mo"
        if self.budget_min:
            return f"From ${self.budget_min:,.0f}/mo"
        if self.budget_max:
            return f"Up to ${self.budget_max:,.0f}/mo"
        return ""

    @property
    def whatsapp_url(self):
        """wa.me deep link to the hawker who posted, with a pre-filled opener."""
        digits = "".join(ch for ch in self.contact_whatsapp if ch.isdigit())
        if not digits:
            return ""
        from urllib.parse import quote
        message = "Hi! I saw your stall-wanted post on MakanSpace."
        return f"https://wa.me/{digits}?text={quote(message)}"


# ─── ListingReport (public flagging, spec 13.2) ──────────────────────────────

class ListingReport(models.Model):
    """
    Public report/flag submitted against a live listing — no login required.
    A proper log of independent reports over time (multiple reports per listing
    are allowed), distinct from the dormant flagged_reason CharField reserved
    for future automated fraud-detection signals.
    """

    class ReasonCategory(models.TextChoices):
        NEA_MANAGED = "nea_managed", "This looks like an NEA-managed centre"
        SCAM = "scam", "Scam / fake listing"
        INCORRECT = "incorrect", "Incorrect information"
        OTHER = "other", "Other"

    listing = models.ForeignKey(
        Listing,
        on_delete=models.CASCADE,
        related_name="reports",
        help_text="The listing being reported.",
    )
    reason_category = models.CharField(
        max_length=20,
        choices=ReasonCategory.choices,
        default=ReasonCategory.OTHER,
    )
    details = models.TextField(
        blank=True,
        help_text="Optional free-text detail — no contact info required.",
    )
    reported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-reported_at"]
        verbose_name = "Listing Report"
        verbose_name_plural = "Listing Reports"

    def __str__(self):
        return f"Report on {self.listing.code} — {self.get_reason_category_display()}"
