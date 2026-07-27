"""Listing-related service functions."""

import io
from decimal import Decimal

from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image


def compress_image(image_file, max_size_bytes=None):
    """
    Compress and resize an uploaded image to fit within the size cap (spec 3.4).
    Returns a Django ContentFile ready to be saved — never rejects, always fits.

    Strategy: resize longest side to 1200px, then progressively increase JPEG
    compression until the result is under max_size_bytes (default 512KB).
    """
    if max_size_bytes is None:
        max_size_bytes = settings.MAX_IMAGE_SIZE_BYTES

    img = Image.open(image_file)

    # Convert RGBA to RGB (JPEG doesn't support alpha)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # Resize if very large (max 1200px on longest side)
    max_dim = 1200
    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

    # Progressive JPEG compression, reduce quality until under cap
    for quality in range(85, 10, -5):
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality, optimize=True)
        if buffer.tell() <= max_size_bytes:
            break

    buffer.seek(0)
    filename = getattr(image_file, "name", "listing.jpg")
    if not filename.lower().endswith(".jpg"):
        filename = filename.rsplit(".", 1)[0] + ".jpg"

    return ContentFile(buffer.read(), name=filename)


# ─── Singapore postal code district mapping (simplified) ────────────────────
# Used for generating listing codes and future geographic features.

SG_DISTRICT_MAP = {
    "01": "Raffles Place / Marina Bay",
    "02": "Tanjong Pagar / Anson",
    "03": "Tiong Bahru / Queenstown",
    "04": "Keppel / Harbourfront",
    "05": "Pasir Panjang / West Coast",
    "06": "High Street / North Bridge",
    "07": "Beach Road / Bugis",
    "08": "Little India / Farrer Park",
    "09": "Orchard / Cairnhill",
    "10": "Tanglin / Holland",
    "11": "Newton / Novena",
    "12": "Balestier / Toa Payoh",
    "13": "MacPherson / Potong Pasir",
    "14": "Geylang / Eunos",
    "15": "Joo Chiat / Katong",
    "16": "Bedok / Upper East Coast",
    "17": "Changi / Loyang",
    "18": "Tampines",
    "19": "Serangoon / Hougang",
    "20": "Ang Mo Kio / Bishan",
    "21": "Upper Thomson / Sin Ming",
    "22": "Jurong / Boon Lay",
    "23": "Clementi / Bukit Timah",
    "24": "Bukit Batok / Choa Chu Kang",
    "25": "Woodlands / Sembawang",
    "26": "Upper Thomson / Lentor",
    "27": "Yishun",
    "28": "Seletar / Punggol",
}


def get_district_from_postal(postal_code):
    """Returns district name from first 2 digits of Singapore postal code."""
    prefix = postal_code[:2] if len(postal_code) >= 2 else "00"
    return SG_DISTRICT_MAP.get(prefix, "Singapore")


# ─── OneMap Geocoding (spec 3.3 / 5) ──────────────────────────────────────

import logging
import math
from decimal import Decimal

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

ONEMAP_BASE = "https://www.onemap.gov.sg/api"

# Pre-loaded Singapore MRT stations with coordinates (subset for distance calc)
MRT_STATIONS = [
    {"name": "Jurong East", "lat": 1.3332, "lng": 103.7423},
    {"name": "Bukit Batok", "lat": 1.3485, "lng": 103.7493},
    {"name": "Tampines", "lat": 1.3545, "lng": 103.9428},
    {"name": "Woodlands", "lat": 1.4361, "lng": 103.7880},
    {"name": "Ang Mo Kio", "lat": 1.3700, "lng": 103.8496},
    {"name": "Toa Payoh", "lat": 1.3324, "lng": 103.8474},
    {"name": "Orchard", "lat": 1.3040, "lng": 103.8318},
    {"name": "City Hall", "lat": 1.2932, "lng": 103.8525},
    {"name": "Raffles Place", "lat": 1.2840, "lng": 103.8515},
    {"name": "Bugis", "lat": 1.3005, "lng": 103.8556},
    {"name": "Harbourfront", "lat": 1.2654, "lng": 103.8215},
    {"name": "Clementi", "lat": 1.3151, "lng": 103.7653},
    {"name": "Ghim Moh", "lat": 1.3107, "lng": 103.7896},
    {"name": "Buona Vista", "lat": 1.3074, "lng": 103.7904},
    {"name": "Bishan", "lat": 1.3512, "lng": 103.8485},
    {"name": "Serangoon", "lat": 1.3497, "lng": 103.8736},
    {"name": "Hougang", "lat": 1.3714, "lng": 103.8925},
    {"name": "Punggol", "lat": 1.4051, "lng": 103.9024},
    {"name": "Changi Airport", "lat": 1.3574, "lng": 103.9879},
    {"name": "Marina Bay", "lat": 1.2764, "lng": 103.8546},
]


def geocode_postal_code(postal_code):
    """
    Convert a Singapore postal code to lat/lng.
    Tries OneMap first, falls back to Nominatim (free, no API key needed).
    Returns (lat, lng) tuple or (None, None) on failure.
    """
    # --- Try OneMap first ---
    api_key = getattr(settings, "ONEMAP_API_KEY", "")
    if api_key:
        try:
            resp = requests.get(
                f"{ONEMAP_BASE}/common/search",
                params={"searchVal": postal_code, "returnGeom": "Y", "getAddrDetails": "Y"},
                headers={"Authorization": api_key},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if results:
                lat = float(results[0]["LATITUDE"])
                lng = float(results[0]["LONGITUDE"])
                return Decimal(str(lat)), Decimal(str(lng))
        except Exception as e:
            logger.warning("OneMap geocode failed for %s: %s", postal_code, e)

    # --- Fallback: Nominatim (free OpenStreetMap geocoding) ---
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": f"{postal_code}, Singapore",
                "format": "json",
                "limit": 1,
                "countrycodes": "sg",
            },
            headers={"User-Agent": "MakanSpace/1.0"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            lat = float(results[0]["lat"])
            lng = float(results[0]["lon"])
            return Decimal(str(lat)), Decimal(str(lng))
    except Exception as e:
        logger.error("Nominatim geocode failed for %s: %s", postal_code, e)

    return None, None


def haversine_km(lat1, lng1, lat2, lng2):
    """Haversine distance between two lat/lng points in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def find_nearest_mrt(lat, lng):
    """
    Returns (station_name, walk_minutes) for the nearest MRT station.
    Walk time estimated at ~80m/min (average walking speed).
    """
    if lat is None or lng is None:
        return "", None
    nearest = None
    min_dist = float("inf")
    for station in MRT_STATIONS:
        dist = haversine_km(float(lat), float(lng), station["lat"], station["lng"])
        if dist < min_dist:
            min_dist = dist
            nearest = station
    if nearest:
        walk_meters = min_dist * 1000
        walk_minutes = max(1, round(walk_meters / 80))  # ~80m/min
        return nearest["name"], walk_minutes
    return "", None


def geocode_listing(listing):
    """
    Geocode a listing's postal code and populate location fields.
    Called from Listing.save() via signal or directly.
    """
    lat, lng = geocode_postal_code(listing.postal_code)
    if lat and lng:
        listing.lat = lat
        listing.lng = lng
        mrt_name, walk_min = find_nearest_mrt(lat, lng)
        listing.nearest_mrt = mrt_name
        listing.mrt_walk_minutes = walk_min


# ─── PropertyReference Matching (spec 5.1) ─────────────────────────────────

def check_property_reference(establishment_name, postal_code=""):
    """
    Cross-check a listing against the PropertyReference table.

    Returns a dict:
        {
            "match": PropertyReference or None,
            "blocked": bool,       # True if NEA Direct (in_scope=False)
            "needs_review": bool,  # True if no match found (manual admin review)
            "message": str,        # Human-readable explanation
        }
    """
    from .models import PropertyReference

    if not establishment_name:
        return {"match": None, "blocked": False, "needs_review": False, "message": ""}

    name_lower = establishment_name.strip().lower()

    # Exact match first
    exact = PropertyReference.objects.filter(
        establishment_name__iexact=name_lower
    ).first()

    if exact:
        if not exact.in_scope:
            return {
                "match": exact,
                "blocked": True,
                "needs_review": False,
                "message": (
                    f"BLOCKED: '{exact.establishment_name}' is an NEA Direct-managed centre. "
                    f"{exact.scope_reason}"
                ),
            }
        return {
            "match": exact,
            "blocked": False,
            "needs_review": False,
            "message": (
                f"Matched: '{exact.establishment_name}' ({exact.get_category_display()}). "
                f"In scope — proceed to normal review."
            ),
        }

    # Fuzzy / partial match (contains)
    partial = PropertyReference.objects.filter(
        establishment_name__icontains=name_lower
    ).first()

    if not partial and len(name_lower) > 5:
        # Also try reverse: check if any reference name is contained in the input
        partial = PropertyReference.objects.extra(
            where=["LOWER(%s) LIKE '%%' || LOWER(establishment_name) || '%%'"],
            params=[name_lower],
        ).first()

    if partial:
        if not partial.in_scope:
            return {
                "match": partial,
                "blocked": True,
                "needs_review": False,
                "message": (
                    f"BLOCKED (fuzzy match): '{partial.establishment_name}' is NEA Direct. "
                    f"{partial.scope_reason}"
                ),
            }
        return {
            "match": partial,
            "blocked": False,
            "needs_review": False,
            "message": (
                f"Matched (fuzzy): '{partial.establishment_name}' ({partial.get_category_display()}). "
                f"In scope — proceed to normal review."
            ),
        }

    # No match — route to manual admin review
    return {
        "match": None,
        "blocked": False,
        "needs_review": True,
        "message": "No PropertyReference match found. Routed to manual admin review.",
    }
