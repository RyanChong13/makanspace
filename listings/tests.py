"""
End-to-end verification tests for master spec v4 reconciliation.

Covers:
- A0:  editing a listing with a text-only change saves successfully
       (nea_attestation no longer breaks the edit form)
- A0b: a malformed postal code shows a field-level error under the field,
       not just the generic banner
- A1:  replacing a photo via the edit form saves a valid compressed image
- B11: self-serve AI-assisted CSV mass upload — loose headers, mapping
       review screen, confirmation, creation pipeline, skipped-row reporting
"""

import io
import os
import re
import tempfile
from unittest.mock import patch

from django.conf import settings
from django.template import Context, Template
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext, ngettext
from PIL import Image

from accounts.models import Company, User
from .models import Listing, ListingImage

# Keep test uploads out of the real media/ directory.
_TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="makanspace-test-media-")


def _png_bytes(color=(200, 30, 120), size=(600, 400)):
    """Build a small in-memory PNG for upload tests."""
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


@override_settings(MEDIA_ROOT=_TEST_MEDIA_ROOT, ANTHROPIC_API_KEY="")
class ListingEditVerificationTests(TestCase):
    """A0 / A0b / A1 — the edit form must actually save."""

    def setUp(self):
        # Neutralise external calls triggered by signals and views:
        # geocoding (OneMap/Nominatim HTTP) and Celery translation tasks.
        self._patchers = [
            patch("listings.signals.geocode_listing", lambda listing: None),
            patch("listings.signals.translate_listing"),
            patch("listings.views.geocode_listing", lambda listing: None),
        ]
        for p in self._patchers:
            p.start()
            self.addCleanup(p.stop)

        self.company = Company.objects.create(
            name="Test Kopitiam Pte Ltd",
            uen="TESTV4A",
            is_business_verified=True,
            status=Company.Status.VERIFIED,
        )
        self.user = User.objects.create_user(
            username="lm@test.local",
            email="lm@test.local",
            password="s3cretpass",
            role=User.Role.LEASING_MANAGER,
            company=self.company,
        )
        self.listing = Listing.objects.create(
            company=self.company,
            posted_by=self.user,
            title="Original Stall Title",
            description="Original description.",
            cost_min=1800,
            price_display="exact",
            postal_code="120001",
            contact_number="+65 9123 4567",
            status=Listing.Status.VERIFIED,
            nea_attestation=True,
        )
        self.client = Client()
        self.client.force_login(self.user)

    def _edit_post_data(self, **overrides):
        data = {
            "title": self.listing.title,
            "description": self.listing.description,
            "price_display": "exact",
            "cost_min": "1800",
            "cost_max": "",
            "size_sqft": "",
            "lease_duration": "",
            "postal_code": self.listing.postal_code,
            "contact_number": self.listing.contact_number,
            "grease_trap_fee": "",
            "dishwashing_cost": "",
            "footfall_estimate": "",
            # Inline image formset (prefix "images", no existing photos)
            "images-TOTAL_FORMS": "6",
            "images-INITIAL_FORMS": "0",
            "images-MIN_NUM_FORMS": "0",
            "images-MAX_NUM_FORMS": "6",
        }
        data.update(overrides)
        return data

    def _edit_url(self):
        return reverse("listings:listing_update", args=[self.listing.code])

    # ── A0: text-only edit saves ────────────────────────────────────────────

    def test_a0_text_only_edit_saves(self):
        """Change only the title — must save with no validation error (A0)."""
        resp = self.client.post(self._edit_url(), self._edit_post_data(
            title="Renamed Stall Title",
        ))
        self.assertRedirects(resp, reverse("listings:listing_detail", args=[self.listing.code]))
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.title, "Renamed Stall Title")
        # The hidden attestation field must not be wiped by the edit.
        self.assertTrue(self.listing.nea_attestation)

    def test_a0_edit_form_no_hidden_required_field(self):
        """The edit form must not carry a required nea_attestation field."""
        resp = self.client.get(self._edit_url())
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'name="nea_attestation"')

    # ── A0b: field-level errors render under the field ─────────────────────

    def test_a0b_malformed_postal_code_shows_field_error(self):
        """Invalid postal code → specific red error under the field, not a bare banner."""
        resp = self.client.post(self._edit_url(), self._edit_post_data(
            postal_code="12",
        ))
        self.assertEqual(resp.status_code, 200)  # form re-rendered
        self.assertContains(resp, "form-error")
        self.assertContains(resp, "Singapore postal codes must be exactly 6 digits.")
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.postal_code, "120001")  # unchanged

    # ── A1: photo replacement saves an uncorrupted image ───────────────────

    def test_a1_photo_replacement_saves_valid_image(self):
        original = _png_bytes(color=(10, 10, 10))
        img = ListingImage.objects.create(
            listing=self.listing,
            image=SimpleUploadedFile("original.png", original, content_type="image/png"),
            order=0,
        )
        replacement = _png_bytes(color=(250, 200, 40))

        resp = self.client.post(self._edit_url(), self._edit_post_data(
            **{
                "images-INITIAL_FORMS": "1",
                "images-0-id": str(img.pk),
                "images-0-image": SimpleUploadedFile(
                    "replacement.png", replacement, content_type="image/png"
                ),
            },
        ))
        self.assertRedirects(resp, reverse("listings:listing_detail", args=[self.listing.code]))

        self.listing.refresh_from_db()
        self.assertEqual(self.listing.images.count(), 1)

        img.refresh_from_db()
        saved = img.image.read()
        # The saved file must be a valid, openable image — not corrupted data.
        reopened = Image.open(io.BytesIO(saved))
        reopened.verify()
        # Compression happened (converted to JPEG under the size cap).
        self.assertLessEqual(len(saved), 512 * 1024)
        self.assertNotEqual(saved, replacement)
        self.assertTrue(saved.startswith(b"\xff\xd8"), "saved image is not a JPEG")

    def test_a1_text_only_edit_leaves_existing_photo_untouched(self):
        """A text-only edit must not re-compress or rewrite stored photos."""
        original = _png_bytes(color=(10, 10, 10))
        img = ListingImage.objects.create(
            listing=self.listing,
            image=SimpleUploadedFile("original.png", original, content_type="image/png"),
            order=0,
        )

        resp = self.client.post(self._edit_url(), self._edit_post_data(
            title="Renamed Without Photo Change",
            **{
                "images-INITIAL_FORMS": "1",
                "images-0-id": str(img.pk),
                # no images-0-image upload — the existing photo is untouched
            },
        ))
        self.assertRedirects(resp, reverse("listings:listing_detail", args=[self.listing.code]))

        img.refresh_from_db()
        # Stored bytes are byte-identical — no re-compression churn on plain edits.
        self.assertEqual(img.image.read(), original)

    # ── Create flow still enforces the attestation (regression guard) ─────

    def test_create_still_requires_nea_attestation(self):
        """The create form keeps requiring the attestation checkbox."""
        url = reverse("listings:listing_create")
        data = {
            "title": "Brand New Stall",
            "description": "A brand new stall.",
            "price_display": "exact",
            "cost_min": "1500",
            "cost_max": "",
            "size_sqft": "",
            "lease_duration": "",
            "postal_code": "560234",
            "contact_number": "+65 9123 4567",
            "grease_trap_fee": "",
            "dishwashing_cost": "",
            "footfall_estimate": "",
            "images-TOTAL_FORMS": "6",
            "images-INITIAL_FORMS": "0",
            "images-MIN_NUM_FORMS": "0",
            "images-MAX_NUM_FORMS": "6",
            # nea_attestation deliberately NOT set
        }
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 200)  # form re-rendered with errors
        self.assertContains(
            resp, "You must confirm this stall is not part of an NEA Direct-managed hawker centre."
        )
        self.assertEqual(Listing.objects.count(), 1)  # only the fixture listing

    def test_create_with_attestation_succeeds(self):
        url = reverse("listings:listing_create")
        data = {
            "title": "Brand New Stall",
            "description": "A brand new stall.",
            "price_display": "exact",
            "cost_min": "1500",
            "cost_max": "",
            "size_sqft": "",
            "lease_duration": "",
            "postal_code": "560234",
            "contact_number": "+65 9123 4567",
            "grease_trap_fee": "",
            "dishwashing_cost": "",
            "footfall_estimate": "",
            "images-TOTAL_FORMS": "6",
            "images-INITIAL_FORMS": "0",
            "images-MIN_NUM_FORMS": "0",
            "images-MAX_NUM_FORMS": "6",
            "nea_attestation": "on",
        }
        resp = self.client.post(url, data)
        self.assertEqual(Listing.objects.count(), 2)
        new_listing = Listing.objects.exclude(pk=self.listing.pk).get()
        self.assertRedirects(
            resp, reverse("listings:listing_detail", args=[new_listing.code])
        )
        self.assertTrue(new_listing.nea_attestation)
        self.assertEqual(new_listing.status, Listing.Status.VERIFIED)


@override_settings(MEDIA_ROOT=_TEST_MEDIA_ROOT, ANTHROPIC_API_KEY="")
class SelfServeImportVerificationTests(TestCase):
    """B11 — self-serve AI-assisted CSV mass upload."""

    def setUp(self):
        self._patchers = [
            patch("listings.signals.geocode_listing", lambda listing: None),
            patch("listings.signals.translate_listing"),
            patch("listings.views.geocode_listing", lambda listing: None),
        ]
        for p in self._patchers:
            p.start()
            self.addCleanup(p.stop)

        self.company = Company.objects.create(
            name="Bulk Foods Pte Ltd",
            uen="BULKV4B",
            is_business_verified=True,
            status=Company.Status.VERIFIED,
            whatsapp_number="+65 8765 4321",
        )
        self.user = User.objects.create_user(
            username="bulk@test.local",
            email="bulk@test.local",
            password="s3cretpass",
            role=User.Role.LEASING_MANAGER,
            company=self.company,
        )
        self.client = Client()
        self.client.force_login(self.user)

    def _upload_csv(self):
        """Step 1+2: upload a loosely-headed CSV, land on the mapping review."""
        csv_content = (
            "Stall Name,Rent,Size (sqft),Postal Code,WhatsApp\n"
            "Corner Stall at Bedok 216,\"$2,300\",180,469211,+65 9123 4567\n"
            "Bazaar Booth Jurong East,1500,120,609727,89787274\n"
            "Broken Row,999,50,12345,81112222\n"
        )
        csv_file = SimpleUploadedFile(
            "stalls.csv", csv_content.encode("utf-8"), content_type="text/csv"
        )
        return self.client.post(reverse("listings:self_serve_import"), {"csv_file": csv_file})

    def test_b11_upload_shows_mapping_review(self):
        """Upload with loose headers → review page shows proposed mapping."""
        resp = self._upload_csv()
        self.assertEqual(resp.status_code, 200)
        # Column table renders with the AI/alias-proposed mapping pre-selected
        self.assertContains(resp, "Stall Name")
        self.assertContains(resp, 'value="title" selected')
        self.assertContains(resp, 'value="cost_min" selected')
        self.assertContains(resp, 'value="size_sqft" selected')
        self.assertContains(resp, 'value="postal_code" selected')
        # Attestation checkbox + confirm button present; nothing created yet
        self.assertContains(resp, 'name="nea_attestation"')
        self.assertContains(resp, 'name="confirm_import"')
        self.assertEqual(Listing.objects.count(), 0)

    def test_b11_confirm_requires_attestation(self):
        """Confirming without the NEA attestation re-renders the review with an error."""
        self._upload_csv()
        resp = self.client.post(reverse("listings:self_serve_import"), {
            "confirm_import": "1",
            "column_map": ["title", "cost_min", "size_sqft", "postal_code", "contact_number"],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "You must confirm none of these stalls are part of an NEA Direct-managed hawker centre.")
        self.assertEqual(Listing.objects.count(), 0)

    def test_b11_full_import_flow(self):
        """Confirm → good rows created, bad row skipped with its reason."""
        self._upload_csv()
        resp = self.client.post(reverse("listings:self_serve_import"), {
            "confirm_import": "1",
            "nea_attestation": "on",
            "column_map": ["title", "cost_min", "size_sqft", "postal_code", "contact_number"],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "2 listings created and are now live.")
        self.assertContains(resp, "Invalid Postal Code: 12345")

        # Exactly two listings created from the three data rows
        self.assertEqual(Listing.objects.count(), 2)
        created = {l.title: l for l in Listing.objects.all()}

        corner = created["Corner Stall at Bedok 216"]
        self.assertEqual(str(corner.cost_min), "2300.00")  # '$2,300' parsed
        self.assertEqual(corner.size_sqft, 180)
        self.assertEqual(corner.postal_code, "469211")
        self.assertEqual(corner.company, self.company)  # scoped to own company
        self.assertEqual(corner.posted_by, self.user)
        self.assertEqual(corner.status, Listing.Status.VERIFIED)
        self.assertTrue(corner.needs_audit)  # auto-approval + retroactive audit
        self.assertTrue(corner.nea_attestation)

        bazaar = created["Bazaar Booth Jurong East"]
        self.assertEqual(str(bazaar.cost_min), "1500.00")
        self.assertEqual(bazaar.contact_number, "89787274")

        # Session state cleared after processing — a retry bounces to upload
        retry = self.client.post(reverse("listings:self_serve_import"), {
            "confirm_import": "1",
            "nea_attestation": "on",
            "column_map": ["title", "cost_min", "size_sqft", "postal_code", "contact_number"],
        })
        self.assertEqual(Listing.objects.count(), 2)  # nothing re-created

    def test_b11_rejects_non_csv_file(self):
        resp = self.client.post(reverse("listings:self_serve_import"), {
            "csv_file": SimpleUploadedFile("stalls.xlsx", b"not a csv", content_type="text/plain"),
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Please upload a .csv file.")
        self.assertEqual(Listing.objects.count(), 0)

    def test_b11_requires_leasing_manager(self):
        """Anonymous and non-company users cannot reach the tool."""
        anon = Client()
        resp = anon.get(reverse("listings:self_serve_import"))
        self.assertEqual(resp.status_code, 302)  # redirected to login

        plain = User.objects.create_user(
            username="plain@test.local", email="plain@test.local", password="s3cretpass"
        )
        c = Client()
        c.force_login(plain)
        resp = c.get(reverse("listings:self_serve_import"))
        self.assertEqual(resp.status_code, 403)  # UserPassesTest failure → forbidden


class TranslationPluralBuildTests(TestCase):
    """A7 / F1 — the plural build path.

    build_translations.py stores a plural msgid as a ``(singular, plural)``
    tuple; Babel then writes as many ``msgstr[n]`` slots as the locale has
    plural forms. zh_Hans has one (so a second form would be dropped), ta and
    ms have two. A missing msgstr[1] makes gettext fall back to the English
    msgid_plural at runtime, so both the generated .po and the resolved .mo
    are asserted here.
    """

    # A plural the catalogue must carry for every locale.
    SINGULAR = "%(n)s listing"
    PLURAL = "%(n)s listings"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import build_translations
        build_translations.build()  # regenerate locale/**/django.{po,mo}

    def _po_entry(self, lang):
        po = os.path.join(settings.BASE_DIR, "locale", lang, "LC_MESSAGES", "django.po")
        text = io.open(po, encoding="utf-8").read()
        block = 'msgid "%s"\nmsgid_plural "%s"\n' % (self.SINGULAR, self.PLURAL)
        self.assertIn(block, text, "no plural entry for %s" % lang)
        return text[text.index(block) + len(block):].split("\n\n")[0]

    def test_ta_po_has_both_plural_forms(self):
        entry = self._po_entry("ta")
        self.assertIn('msgstr[0] "', entry)
        self.assertIn('msgstr[1] "', entry)

    def test_ms_po_has_both_plural_forms(self):
        entry = self._po_entry("ms")
        self.assertIn('msgstr[0] "', entry)
        self.assertIn('msgstr[1] "', entry)

    def test_zh_hans_po_has_a_single_plural_form(self):
        entry = self._po_entry("zh_Hans")
        self.assertIn('msgstr[0] "', entry)
        self.assertNotIn("msgstr[1]", entry)  # nplurals=1 — second form is dropped

    def test_runtime_resolves_singular_and_plural(self):
        """Django must serve a translated string for both forms in each locale."""
        for lang in ("zh-hans", "ta", "ms"):
            with translation.override(lang):
                one = ngettext(self.SINGULAR, self.PLURAL, 1) % {"n": 1}
                many = ngettext(self.SINGULAR, self.PLURAL, 5) % {"n": 5}
            self.assertNotIn(self.SINGULAR, one, lang)
            self.assertNotIn(self.PLURAL, many, lang)
            self.assertIn("1", one)
            self.assertIn("5", many)

    def test_runtime_plurals_differ_where_the_locale_has_two_forms(self):
        with translation.override("ta"):
            ta_one = ngettext(self.SINGULAR, self.PLURAL, 1)
            ta_many = ngettext(self.SINGULAR, self.PLURAL, 5)
        self.assertNotEqual(ta_one, ta_many)
        # A singular-only catalogue (Chinese) legitimately renders one form.
        with translation.override("zh-hans"):
            self.assertEqual(
                ngettext(self.SINGULAR, self.PLURAL, 1),
                ngettext(self.SINGULAR, self.PLURAL, 5),
            )

    def test_singular_gettext_reaches_the_catalogue(self):
        with translation.override("zh-hans"):
            self.assertEqual(gettext("Browse Stalls"), "浏览摊位")
        with translation.override("ms"):
            self.assertEqual(gettext("Browse Stalls"), "Layari Gerai")


class JavascriptMessageTranslationTests(TestCase):
    """A7 / F5 — the strings the chatbot writes into the page from JavaScript.

    {% trans %} rewrites its argument before the lookup, so a msgid carrying a
    printf-style placeholder ("Found %(n)s match(es):") never hits the catalogue
    and ships English onto a Chinese, Tamil or Malay page. gettext() on the raw
    string does hit, which is what the |msg filter in listing_extras does; the
    number itself is substituted later, in the browser.
    """

    MSGIDS = [
        "Found %(n)s match(es):",
        "Searching...",
        "No matches found. Try different criteria!",
        "Sorry, something went wrong. Please try again.",
        "Transcribing...",
        "Voice input is not supported in this browser.",
        "Microphone access was denied.",
    ]

    def test_msg_filter_resolves_every_chatbot_string(self):
        source = "".join('{{ "%s"|msg }}|' % m for m in self.MSGIDS)
        template = Template("{% load i18n listing_extras %}" + source)
        for lang in ("zh-hans", "ta", "ms"):
            with translation.override(lang):
                rendered = template.render(Context({}))
            for msgid in self.MSGIDS:
                self.assertNotIn(msgid, rendered, "%s still English" % lang)

    def test_placeholder_survives_for_javascript_substitution(self):
        """JS replaces '%(n)s' itself, so the marker must reach the page intact."""
        with translation.override("zh-hans"):
            out = Template('{% load i18n listing_extras %}{{ x|msg }}').render(
                Context({"x": "Found %(n)s match(es):"}))
        self.assertIn("%(n)s", out)

    def test_no_template_marks_a_placeholder_msgid_with_trans(self):
        """Guard the whole bug class: trans/blocktrans cannot resolve %(...)s."""
        pattern = re.compile(
            r"\{%(?:trans|translate|blocktrans|blocktranslate)\b[^%]*%\(\w+\)[sd]")
        root = os.path.join(settings.BASE_DIR, "templates")
        offenders = []
        for dirpath, _dirs, files in os.walk(root):
            for name in sorted(files):
                if not name.endswith(".html"):
                    continue
                path = os.path.join(dirpath, name)
                with io.open(path, encoding="utf-8") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if pattern.search(line):
                            offenders.append("%s:%d" % (path, lineno))
        self.assertEqual([], offenders)
