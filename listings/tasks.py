"""
Celery tasks for listings app.
Includes: auto-translation, WhatsApp notifications, voice-to-listing,
AI description writing, and photo-based amenity detection.

Uses Anthropic Claude for text/vision AI and Groq Whisper for transcription.
"""

import json
import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


def _get_anthropic_client():
    """Return an Anthropic client, or None if not configured."""
    api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def _claude_json(system_prompt, user_prompt, max_tokens=1024, model=None):
    """Call Claude and parse a JSON response from the text content."""
    client = _get_anthropic_client()
    if client is None:
        return None

    if model is None:
        model = getattr(settings, "CLAUDE_MODEL", "claude-haiku-4-5-20251001")

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as e:
        logger.warning("Claude API call failed for model %s: %s", model, e)
        return None

    text_block = next((block for block in response.content if getattr(block, "type", None) == "text"), None)
    if text_block is None:
        return None
    text = text_block.text.strip()

    # Claude may wrap JSON in markdown code fences — strip them
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    return json.loads(text)


# ─── Auto-Translation (spec 7.1 / 3.2) ──────────────────────────────────────

@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def translate_listing(self, listing_id):
    """
    Translates a listing into the other 3 languages and stores them
    in ListingTranslation. Called on listing verified or edited.
    Uses everyday spoken/conversational register (spec 3.2).
    """
    from .models import Listing, ListingTranslation

    client = _get_anthropic_client()
    if client is None:
        logger.warning("ANTHROPIC_API_KEY not set; skipping translation for listing %s", listing_id)
        return

    try:
        listing = Listing.objects.get(pk=listing_id)
    except Listing.DoesNotExist:
        logger.error("Listing %s not found for translation", listing_id)
        return

    try:
        languages = {
            "zh": "Chinese (Mandarin), everyday spoken/conversational register, not formal",
            "ta": "Tamil, everyday spoken/conversational register, not formal",
            "ms": "Malay (Bahasa Melayu), everyday spoken/conversational register, not formal",
        }

        # Determine source language (skip translation into source)
        source_lang = listing.posted_by.preferred_language if listing.posted_by and listing.posted_by.preferred_language != "en" else None

        system_prompt = (
            "You are a translator for a Singapore hawker stall rental marketplace. "
            "Return ONLY a JSON object with keys: title, description, amenities. "
            "The 'amenities' value must be a list of translated amenity labels in the same order as provided. "
            "No markdown, no explanation."
        )

        amenity_labels = list(listing.amenities.values_list("name_en", flat=True))

        for lang_code, lang_desc in languages.items():
            if lang_code == source_lang:
                continue

            user_prompt = (
                f"Translate the following hawker stall listing into {lang_desc}. "
                "Use everyday, plain-language, conversational tone — not formal or legal register. "
                "Keep it natural and easy to understand for someone who may not read English fluently.\n\n"
                f"Title: {listing.title}\n"
                f"Description: {listing.description}\n"
                f"Amenities: {', '.join(amenity_labels)}"
            )

            result = _claude_json(system_prompt, user_prompt)
            if result is None:
                continue

            translated_amenities = result.get("amenities")
            if not isinstance(translated_amenities, list):
                translated_amenities = amenity_labels

            ListingTranslation.objects.update_or_create(
                listing=listing,
                language=lang_code,
                defaults={
                    "title": result.get("title", listing.title),
                    "description": result.get("description", listing.description),
                    "amenities_text": translated_amenities,
                },
            )

        logger.info("Translations complete for listing %s", listing.code)

    except Exception as e:
        logger.error("Translation failed for listing %s: %s", listing_id, e)
        self.retry(exc=e)


# ─── WhatsApp Business API Notifications (spec 6) ──────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_whatsapp_notification(self, phone_number, template_name, params=None):
    """
    Sends a WhatsApp Business API template message.
    Triggered on: listing status change (verified/rejected), inquiry summaries.
    Falls back to email if WhatsApp fails (logged for manual follow-up).
    """
    token = getattr(settings, "WHATSAPP_BUSINESS_TOKEN", "")
    phone_id = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "")

    if not token or not phone_id:
        logger.warning("WhatsApp credentials not configured; skipping notification to %s", phone_number)
        return

    import requests

    url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    components = []
    if params:
        components = [{
            "type": "body",
            "parameters": [{"type": "text", "text": str(v)} for v in params.values()],
        }]

    payload = {
        "messaging_product": "whatsapp",
        "to": phone_number.replace("+", "").replace(" ", ""),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "en"},
            "components": components,
        },
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        logger.info("WhatsApp message sent to %s (template: %s)", phone_number, template_name)
    except Exception as e:
        logger.error("WhatsApp send failed to %s: %s", phone_number, e)
        self.retry(exc=e)


# ─── Voice-to-Listing Extraction (spec 7.1) ─────────────────────────────────

def transcribe_audio(audio_file_path):
    """
    Transcribe an audio clip via Groq Whisper (free tier).
    Shared by voice-to-listing and the chatbot voice input.
    Returns the transcript text, or '' when GROQ_API_KEY is not configured.
    """
    groq_key = getattr(settings, "GROQ_API_KEY", "")
    if not groq_key:
        logger.warning("GROQ_API_KEY not set; skipping transcription")
        return ""

    from groq import Groq
    groq_client = Groq(api_key=groq_key)

    with open(audio_file_path, "rb") as audio_file:
        transcript = groq_client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=audio_file,
        )

    return transcript.text


@shared_task
def transcribe_and_extract(audio_file_path):
    """
    Transcribes an audio clip via Groq Whisper, then extracts structured
    listing fields using Claude.
    Returns dict: {cost_min, cost_max, lease_duration, amenities, location, description_notes}.
    """
    try:
        # Step 1: Transcribe audio using Groq's Whisper API (free tier)
        text = transcribe_audio(audio_file_path)
        if not text:
            return {}

        # Step 2: Extract structured fields using Claude
        client = _get_anthropic_client()
        if client is None:
            return {"transcript": text}

        system_prompt = (
            "You extract structured data from hawker stall descriptions. "
            "Return ONLY a JSON object. No markdown, no explanation."
        )

        user_prompt = (
            f'Extract hawker stall listing details from this transcript:\n"{text}"\n\n'
            "Return JSON with: cost_min (number), cost_max (number or null), "
            "lease_duration (one of: <6mo, 6-12mo, 1-2yr, 2yr+), "
            "amenities (list of strings), location (string), description_notes (string), "
            "grease_trap_fee (number or null), dishwashing_cost (number or null), "
            "footfall_estimate (string or null)"
        )

        result = _claude_json(system_prompt, user_prompt)
        return result or {}

    except Exception as e:
        logger.error("Voice extraction failed: %s", e)
        return {}


# ─── AI-Assisted Description Writing (spec 7.1) ─────────────────────────────

@shared_task
def draft_listing_description(fields_json):
    """
    Generates a clean, appealing listing description from structured fields.
    Uses everyday spoken/conversational register (spec 3.2).
    Returns the draft description as a string.
    """
    fields = json.loads(fields_json) if isinstance(fields_json, str) else fields_json

    client = _get_anthropic_client()
    if client is None:
        return ""

    try:
        response = client.messages.create(
            model=getattr(settings, "CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
            max_tokens=256,
            system=(
                "You write friendly, appealing hawker stall rental listings. "
                "Use everyday, plain-language, conversational tone. "
                "Return ONLY the description text — no JSON, no markdown, no quotes."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Write a short listing description (2-4 sentences):\n"
                    f"Cost: ${fields.get('cost_min', '?')}/month"
                    + (f" to ${fields.get('cost_max')}" if fields.get('cost_max') else "")
                    + "\n"
                    f"Size: {fields.get('size_sqft', '?')} sqft\n"
                    f"Lease: {fields.get('lease_duration', 'flexible')}\n"
                    f"Location: {fields.get('postal_code', 'Singapore')}\n"
                    f"Amenities: {', '.join(fields.get('amenities', []))}\n"
                    + (f"Grease trap fee: ${fields['grease_trap_fee']}/mo\n" if fields.get('grease_trap_fee') else "")
                    + (f"Dishwashing cost: ${fields['dishwashing_cost']}/mo\n" if fields.get('dishwashing_cost') else "")
                    + (f"Estimated footfall: {fields['footfall_estimate']}\n" if fields.get('footfall_estimate') else "")
                    + "\nMake it sound like a friendly landlord describing their stall."
                ),
            }],
        )

        return response.content[0].text.strip()

    except Exception as e:
        logger.error("Description draft failed: %s", e)
        return ""


# ─── Self-Serve CSV Import Mapping (spec B11) ──────────────────────────────

# Listing fields a leasing manager's CSV can be mapped to (spec B11).
IMPORTABLE_FIELDS = [
    "title", "description", "cost_min", "cost_max", "size_sqft",
    "lease_duration", "postal_code", "contact_number", "price_display",
    "grease_trap_fee", "dishwashing_cost", "footfall_estimate",
]

# Loose-header alias table used when the AI mapping service is unavailable.
_CSV_HEADER_ALIASES = {
    "title": ["title", "stallname", "stall", "name", "listingtitle", "unit"],
    "description": ["description", "details", "notes", "remarks", "about"],
    "cost_min": ["rent", "price", "askingrent", "monthlyrent", "rentfrom", "rentmin", "cost", "costmin"],
    "cost_max": ["maxrent", "rentmax", "rentto", "rentupto", "costmax", "maxprice"],
    "size_sqft": ["size", "sqft", "area", "sizesqft", "floorspace", "squarefeet"],
    "lease_duration": ["lease", "leaseduration", "tenure", "leaselength", "term"],
    "postal_code": ["postalcode", "postcode", "zip", "zipcode", "singaporepostalcode"],
    "contact_number": ["contact", "contactnumber", "whatsapp", "phone", "phonenumber", "mobile", "hp"],
    "price_display": ["pricedisplay", "pricing", "pricingdisplay", "priceoption"],
    "grease_trap_fee": ["greasetrap", "greasetrapfee", "greasetrapcost"],
    "dishwashing_cost": ["dishwashing", "dishwashingcost", "dishwashingfee"],
    "footfall_estimate": ["footfall", "footfallestimate", "traffic", "humantraffic"],
}


def _fallback_csv_mapping(headers):
    """Deterministic alias-based header mapping when Claude is unavailable."""
    mapping = {}
    for header in headers:
        normalized = "".join(ch for ch in header.lower() if ch.isalnum())
        mapping[header] = ""
        for field_name, aliases in _CSV_HEADER_ALIASES.items():
            if normalized in aliases:
                mapping[header] = field_name
                break
    return mapping


def propose_csv_mapping(headers, sample_rows):
    """
    Ask Claude to map CSV columns to Listing fields (spec B11).
    Accepts loose headers (e.g. "Rent", "Size (sqft)") rather than a rigid
    template. Returns {header: field_name or ""} — never trusted blindly;
    the owner confirms the mapping on a review screen before anything is saved.
    Falls back to alias matching when the API is unavailable or fails.
    """
    if not headers:
        return {}

    system_prompt = (
        "You map spreadsheet columns to fields of a hawker stall rental listing. "
        f"Map each column header to exactly one of these field names: {', '.join(IMPORTABLE_FIELDS)}. "
        "If a column does not correspond to any field, map it to an empty string. "
        "Column headers may be loosely named (e.g. 'Rent', 'Size (sqft)', 'Address'). "
        "Return ONLY a JSON object mapping each header (as given) to its field name. No markdown."
    )

    user_prompt = (
        "Map these CSV columns to listing fields.\n\n"
        f"Headers: {json.dumps(headers)}\n\n"
        f"Sample data rows (first few): {json.dumps(sample_rows[:5])}"
    )

    try:
        result = _claude_json(system_prompt, user_prompt, max_tokens=1024)
    except Exception as e:
        logger.warning("CSV mapping AI call failed: %s", e)
        result = None

    if not isinstance(result, dict):
        return _fallback_csv_mapping(headers)

    # Post-process: keep only known field names, cover every header.
    mapping = {}
    for header in headers:
        value = result.get(header)
        if isinstance(value, str) and value in IMPORTABLE_FIELDS:
            mapping[header] = value
        else:
            mapping[header] = ""
    # Fill any column the AI missed using the alias fallback.
    fallback = _fallback_csv_mapping(headers)
    for header, value in mapping.items():
        if not value and fallback.get(header):
            mapping[header] = fallback[header]
    return mapping


# ─── Photo-Based Amenity Detection (spec 7.1) ───────────────────────────────

@shared_task
def detect_amenities_from_photos(listing_id):
    """
    Scans listing photos with Claude's vision capability and returns
    a list of likely amenity slugs. Pre-ticks checkboxes for owner review.
    """
    from .models import Listing, Amenity

    client = _get_anthropic_client()
    if client is None:
        logger.warning("ANTHROPIC_API_KEY not set; skipping amenity detection")
        return []

    try:
        listing = Listing.objects.get(pk=listing_id)
    except Listing.DoesNotExist:
        return []

    images = listing.images.all()[:6]
    if not images:
        return []

    try:
        import base64
        import requests

        # Download images and encode as base64 for Claude vision
        image_contents = []
        for img in images:
            url = img.image.url if hasattr(img.image, "url") else img.cloudinary_url
            if not url:
                continue

            # Download the image
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            img_b64 = base64.standard_b64encode(resp.content).decode("utf-8")

            image_contents.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": img_b64,
                },
            })

        if not image_contents:
            return []

        # Get available amenity slugs
        amenity_slugs = list(Amenity.objects.values_list("slug", flat=True))

        user_content = [
            {
                "type": "text",
                "text": (
                    "Look at these photos of a hawker stall and identify which of the "
                    f"following amenities are visible: {', '.join(amenity_slugs)}. "
                    "Return a JSON object with key 'amenities' containing a list of "
                    "matching amenity slugs. Only include amenities you can confidently see."
                ),
            },
            *image_contents,
        ]

        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=512,
            system="You identify amenities in hawker stall photos. Return ONLY valid JSON, no markdown.",
            messages=[{"role": "user", "content": user_content}],
        )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        result = json.loads(text)
        detected = [s for s in result.get("amenities", []) if s in amenity_slugs]
        logger.info("Detected amenities for listing %s: %s", listing.code, detected)
        return detected

    except Exception as e:
        logger.error("Amenity detection failed for listing %s: %s", listing_id, e)
        return []
