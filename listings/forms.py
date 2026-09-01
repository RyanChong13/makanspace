from django import forms
from django.conf import settings

from .models import Amenity, Listing, ListingImage, Application, TastingSlot, WantedPost, ListingReport


class ListingForm(forms.ModelForm):
    """Form for creating/editing a hawker stall listing (spec 3.4)."""

    # NEA attestation checkbox (spec 9) — required at creation time only.
    # The requirement is enforced via the require_nea_attestation form kwarg
    # (see __init__), so the edit form — which never renders this checkbox —
    # never fails validation on a hidden required field (spec A0).
    nea_attestation = forms.BooleanField(
        required=False,
        label="I confirm this stall is NOT part of an NEA Direct-managed hawker centre.",
        help_text=(
            "NEA's directly-tendered centres (~32) are excluded from MakanSpace. "
            "SEHC and private centres are fine."
        ),
    )

    class Meta:
        model = Listing
        fields = [
            "title",
            "description",
            "price_display",
            "cost_min",
            "cost_max",
            "size_sqft",
            "lease_duration",
            "amenities",
            "postal_code",
            "contact_number",
            "grease_trap_fee",
            "dishwashing_cost",
            "footfall_estimate",
            "nea_attestation",
        ]
        widgets = {
            "title": forms.TextInput(attrs={
                "placeholder": "e.g. Bright corner stall near Ghim Moh Market",
                "class": "form-input",
            }),
            "description": forms.Textarea(attrs={
                "placeholder": "Describe your stall — location highlights, foot traffic, what makes it special...",
                "rows": 4,
                "class": "form-textarea",
            }),
            "price_display": forms.RadioSelect(),
            "cost_min": forms.NumberInput(attrs={
                "placeholder": "1500",
                "class": "form-input",
                "min": "0",
            }),
            "cost_max": forms.NumberInput(attrs={
                "placeholder": "Optional",
                "class": "form-input",
                "min": "0",
            }),
            "size_sqft": forms.NumberInput(attrs={
                "placeholder": "200",
                "class": "form-input",
                "min": "0",
            }),
            "lease_duration": forms.Select(attrs={"class": "form-select"}),
            "amenities": forms.CheckboxSelectMultiple(),
            "postal_code": forms.TextInput(attrs={
                "placeholder": "e.g. 270001",
                "class": "form-input",
                "maxlength": "6",
            }),
            "contact_number": forms.TextInput(attrs={
                "placeholder": "+65 9123 4567",
                "class": "form-input",
                "title": "Enter 8 digits (e.g. 91234567) or with country code (e.g. +65 9123 4567)",
            }),
            "grease_trap_fee": forms.NumberInput(attrs={
                "placeholder": "Optional",
                "class": "form-input",
                "min": "0",
            }),
            "dishwashing_cost": forms.NumberInput(attrs={
                "placeholder": "Optional",
                "class": "form-input",
                "min": "0",
            }),
            "footfall_estimate": forms.TextInput(attrs={
                "placeholder": "e.g. ~500/day",
                "class": "form-input",
            }),
        }

    def __init__(self, *args, require_nea_attestation=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.require_nea_attestation = require_nea_attestation
        if not require_nea_attestation:
            # Edit form never renders this checkbox — remove the field entirely
            # so form.save() can't silently clear an existing attestation.
            self.fields.pop("nea_attestation", None)
        # cost_min/cost_max are only required when price_display == "exact".
        # The requirement is enforced in clean() so the fields themselves are
        # never hard-required at the widget level.
        self.fields["cost_min"].required = False
        self.fields["cost_max"].required = False

    def clean_postal_code(self):
        code = self.cleaned_data.get("postal_code", "").strip()
        if code and (len(code) != 6 or not code.isdigit()):
            raise forms.ValidationError("Singapore postal codes must be exactly 6 digits.")
        return code

    def clean_contact_number(self):
        number = self.cleaned_data.get("contact_number", "").strip()
        if number:
            digits = "".join(ch for ch in number if ch.isdigit())
            if len(digits) == 8:
                pass  # Accept bare 8-digit SG numbers (auto-prefixed with 65)
            elif number.startswith("+65") or number.startswith("65"):
                pass
            else:
                raise forms.ValidationError(
                    "Please enter a Singapore number: either 8 digits (e.g. 9123 4567) "
                    "or with country code (e.g. +65 9123 4567)."
                )
        return number

    def clean(self):
        cleaned_data = super().clean()
        price_display = cleaned_data.get("price_display")
        cost_min = cleaned_data.get("cost_min")
        cost_max = cleaned_data.get("cost_max")

        # NEA attestation is mandatory on the create flow only (spec 9 / A0).
        if self.require_nea_attestation and not cleaned_data.get("nea_attestation"):
            self.add_error(
                "nea_attestation",
                "You must confirm this stall is not part of an NEA Direct-managed hawker centre.",
            )

        # Only require cost_min when exact pricing is selected.
        if price_display == "exact" and not cost_min:
            self.add_error("cost_min", "Minimum rent is required when exact pricing is selected.")

        if cost_min and cost_max and cost_max < cost_min:
            self.add_error("cost_max", "Maximum rent cannot be less than minimum rent.")

        return cleaned_data


class ListingImageForm(forms.ModelForm):
    """Single image upload form — auto-compressed server-side to 512KB cap."""

    class Meta:
        model = ListingImage
        fields = ["image"]
        widgets = {
            "image": forms.FileInput(attrs={"accept": "image/*"}),
        }


class ListingImageFormSet(forms.BaseInlineFormSet):
    """Formset for up to 6 listing images (spec 3.4)."""

    def clean(self):
        super().clean()
        total = sum(1 for f in self.forms if f.has_changed() and not f.empty_permitted)
        if total > settings.MAX_LISTING_IMAGES:
            raise forms.ValidationError(
                f"You can upload at most {settings.MAX_LISTING_IMAGES} photos per listing."
            )


# ─── Application Form (spec 4.1) ────────────────────────────────────────────

class ApplicationForm(forms.ModelForm):
    """Hawker applicant submits menu proposal + optional message."""

    class Meta:
        model = Application
        fields = ["menu_proposal_doc", "message"]
        widgets = {
            "menu_proposal_doc": forms.FileInput(attrs={
                "accept": ".pdf,.jpg,.jpeg,.png",
                "class": "form-input",
            }),
            "message": forms.Textarea(attrs={
                "placeholder": "Tell the landlord about your concept, experience, and why you'd be a great fit...",
                "rows": 4,
                "class": "form-textarea",
            }),
        }


# ─── TastingSlot Form (spec 4.2) ────────────────────────────────────────────

class TastingSlotForm(forms.ModelForm):
    """Landlord defines available tasting/viewing time slots."""

    class Meta:
        model = TastingSlot
        fields = ["start_time", "end_time"]
        widgets = {
            "start_time": forms.DateTimeInput(attrs={
                "type": "datetime-local",
                "class": "form-input",
            }),
            "end_time": forms.DateTimeInput(attrs={
                "type": "datetime-local",
                "class": "form-input",
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("start_time")
        end = cleaned_data.get("end_time")
        if start and end and end <= start:
            raise forms.ValidationError("End time must be after start time.")
        return cleaned_data


# ─── WantedPost Form (reverse listing) ──────────────────────────────────────

class WantedPostForm(forms.ModelForm):
    """Public 'stall wanted' form for hawkers — no account needed."""

    class Meta:
        model = WantedPost
        fields = [
            "contact_name",
            "contact_whatsapp",
            "preferred_town",
            "preferred_district",
            "cuisine_type",
            "budget_min",
            "budget_max",
            "lease_duration",
        ]
        widgets = {
            "contact_name": forms.TextInput(attrs={
                "placeholder": "e.g. Ah Hock",
                "class": "form-input",
            }),
            "contact_whatsapp": forms.TextInput(attrs={
                "placeholder": "+65 9123 4567",
                "class": "form-input",
            }),
            "preferred_town": forms.TextInput(attrs={
                "placeholder": "e.g. Jurong West",
                "class": "form-input",
            }),
            "preferred_district": forms.TextInput(attrs={
                "placeholder": "e.g. West, Central",
                "class": "form-input",
            }),
            "cuisine_type": forms.TextInput(attrs={
                "placeholder": "e.g. Chicken rice, Western",
                "class": "form-input",
            }),
            "budget_min": forms.NumberInput(attrs={
                "placeholder": "Optional",
                "class": "form-input",
                "min": "0",
            }),
            "budget_max": forms.NumberInput(attrs={
                "placeholder": "Optional",
                "class": "form-input",
                "min": "0",
            }),
            "lease_duration": forms.Select(attrs={"class": "form-select"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        budget_min = cleaned_data.get("budget_min")
        budget_max = cleaned_data.get("budget_max")
        if budget_min and budget_max and budget_max < budget_min:
            self.add_error("budget_max", "Maximum budget cannot be less than minimum budget.")
        return cleaned_data

    def clean_contact_whatsapp(self):
        number = self.cleaned_data.get("contact_whatsapp", "").strip()
        digits = "".join(ch for ch in number if ch.isdigit())
        if len(digits) < 8:
            raise forms.ValidationError("Please enter a valid WhatsApp number with country code.")
        return number


# ─── ListingReport Form (spec 13.2) ──────────────────────────────────────────

class ListingReportForm(forms.ModelForm):
    """Public report form — no login required, minimal friction."""

    class Meta:
        model = ListingReport
        fields = ["reason_category", "details"]
        widgets = {
            "reason_category": forms.Select(attrs={"class": "form-select"}),
            "details": forms.Textarea(attrs={
                "placeholder": "Optional: any extra detail that helps us review this listing...",
                "rows": 3,
                "class": "form-textarea",
            }),
        }


# ─── CSV Bulk Import Form (spec 14) ─────────────────────────────────────────

class BulkImportCSVForm(forms.Form):
    """Admin-only CSV upload for bulk listing creation."""

    csv_file = forms.FileField(
        label="CSV File",
        help_text=(
            "Columns: company_name, uen (optional), title, description, "
            "cost_min, cost_max, price_display, size_sqft, lease_duration, "
            "postal_code, contact_number, grease_trap_fee, dishwashing_cost, "
            "footfall_estimate"
        ),
        widget=forms.FileInput(attrs={"accept": ".csv"}),
    )
