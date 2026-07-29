"""
AI Search Chatbot (spec 7.1).
Natural-language → filter translation using Anthropic Claude.
Calls the same Django ORM query as the UI filters.
"""

import json
import logging
import os
import tempfile

from django.conf import settings
from django.db import models
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from listings.models import Listing
from listings.services import SG_DISTRICT_MAP

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([AllowAny])
def chatbot_transcribe(request):
    """
    POST /api/chatbot/transcribe/
    Multipart body with an 'audio' blob. Returns {"text": "..."} transcribed
    via the same Groq Whisper pipeline used for voice-to-listing.
    """
    audio_file = request.FILES.get("audio")
    if not audio_file:
        return Response({"error": "No audio file provided."}, status=status.HTTP_400_BAD_REQUEST)

    if not getattr(settings, "GROQ_API_KEY", ""):
        return Response(
            {"error": "Voice input is not configured yet."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
        for chunk in audio_file.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        from listings.tasks import transcribe_audio
        text = transcribe_audio(tmp_path)
    except Exception as e:
        logger.error("Chatbot transcription failed: %s", e)
        text = ""
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if not text.strip():
        return Response(
            {"error": "Sorry, I couldn't hear that. Please try again."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return Response({"text": text.strip()})


@api_view(["POST"])
@permission_classes([AllowAny])
def chatbot_search(request):
    """
    POST /api/chatbot/search/
    Body: {"message": "I'm looking for something near Ghim Moh under $2000"}
    Returns matching listings as JSON.
    """
    message = request.data.get("message", "").strip()
    if not message:
        return Response({"error": "Please enter a search query."}, status=status.HTTP_400_BAD_REQUEST)

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
    if not api_key:
        return Response(
            {"error": "AI search is not configured yet."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        # Extract filter parameters using Claude
        response = client.messages.create(
            model=getattr(settings, "CLAUDE_CHATBOT_MODEL", "claude-sonnet-5"),
            max_tokens=256,
            system=(
                "You are a hawker stall search assistant for Singapore. "
                "Extract search filters from the user's message. "
                "Return ONLY a JSON object with these optional keys: "
                "location (string, e.g. 'Jurong', 'Tampines', 'Orchard'), "
                "cost_max (number), cost_min (number), "
                "size_min (number in sqft), lease_duration (one of: <6mo, 6-12mo, 1-2yr, 2yr+), "
                "amenities (list of strings), has_grease_trap (boolean), "
                "mrt_max_walk (number, minutes). Only include keys the user explicitly mentions. "
                "No markdown, no explanation."
            ),
            messages=[{"role": "user", "content": message}],
        )

        text_block = next((block for block in response.content if getattr(block, "type", None) == "text"), None)
        if text_block is None:
            return Response(
                {"error": "AI search returned an unexpected response."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        text = text_block.text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.splitlines()
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        filters = json.loads(text)

        # Build ORM query from extracted filters
        qs = Listing.objects.filter(status=Listing.Status.VERIFIED).select_related("company")

        if filters.get("cost_max"):
            qs = qs.filter(cost_min__lte=filters["cost_max"])
        if filters.get("cost_min"):
            qs = qs.filter(cost_min__gte=filters["cost_min"])
        if filters.get("size_min"):
            qs = qs.filter(size_sqft__gte=filters["size_min"])
        if filters.get("lease_duration"):
            qs = qs.filter(lease_duration=filters["lease_duration"])
        if filters.get("amenities"):
            for amenity_name in filters["amenities"]:
                qs = qs.filter(amenities__name_en__icontains=amenity_name)
        if filters.get("has_grease_trap"):
            qs = qs.filter(grease_trap_fee__isnull=False)
        # Location filtering — map town/district intent to postal prefixes, MRT, title, description
        if filters.get("location"):
            loc = filters["location"].lower()
            loc_q = (
                models.Q(nearest_mrt__icontains=loc)
                | models.Q(title__icontains=loc)
                | models.Q(description__icontains=loc)
            )
            for prefix, label in SG_DISTRICT_MAP.items():
                if loc in label.lower():
                    loc_q |= models.Q(postal_code__startswith=prefix)
            qs = qs.filter(loc_q)

        if filters.get("mrt_max_walk"):
            try:
                qs = qs.filter(mrt_walk_minutes__lte=int(filters["mrt_max_walk"]))
            except (ValueError, TypeError):
                pass

        qs = qs.distinct()[:10]

        results = []
        for listing in qs:
            results.append({
                "code": listing.code,
                "title": listing.title,
                "cost": listing.cost_display,
                "size": listing.size_display,
                "lease": listing.lease_display,
                "mrt": listing.mrt_display,
                "company": listing.company.name if listing.company else "",
                "url": f"/listing/{listing.code}/",
            })

        return Response({
            "filters_applied": filters,
            "count": len(results),
            "results": results,
            "message": f"Found {len(results)} stall{'s' if len(results) != 1 else ''} matching your search.",
        })

    except Exception as e:
        logger.error("Chatbot search failed: %s", e)
        return Response(
            {"error": "Sorry, I couldn't process your search right now. Please try again."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
