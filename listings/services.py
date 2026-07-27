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

# Pre-loaded Singapore MRT/LRT stations with coordinates.
# Sourced from LTA/data.gov.sg "Train Station Exit" open geospatial data
# (via https://github.com/cheeaun/sgraildata, aggregated from LTA DataMall).
# Covers NSL, EWL, NEL, CCL, DTL, TEL, and Bukit Panjang/Punggol/Sengkang LRT.
MRT_STATIONS = [
    {"name": "Admiralty", "lat": 1.440637, "lng": 103.800959},
    {"name": "Aljunied", "lat": 1.316259, "lng": 103.882665},
    {"name": "Ang Mo Kio", "lat": 1.370053, "lng": 103.84954},
    {"name": "Bakau", "lat": 1.388029, "lng": 103.905458},
    {"name": "Bangkit", "lat": 1.380055, "lng": 103.772644},
    {"name": "Bartley", "lat": 1.342438, "lng": 103.880449},
    {"name": "Bayfront", "lat": 1.282535, "lng": 103.85973},
    {"name": "Bayshore", "lat": 1.313123, "lng": 103.942308},
    {"name": "Beauty World", "lat": 1.341664, "lng": 103.775936},
    {"name": "Bedok", "lat": 1.323935, "lng": 103.929995},
    {"name": "Bedok North", "lat": 1.33475, "lng": 103.918036},
    {"name": "Bedok Reservoir", "lat": 1.336284, "lng": 103.931887},
    {"name": "Bencoolen", "lat": 1.298861, "lng": 103.850369},
    {"name": "Bendemeer", "lat": 1.313583, "lng": 103.863067},
    {"name": "Bishan", "lat": 1.351455, "lng": 103.848263},
    {"name": "Boon Keng", "lat": 1.319824, "lng": 103.861521},
    {"name": "Boon Lay", "lat": 1.338472, "lng": 103.705777},
    {"name": "Botanic Gardens", "lat": 1.322559, "lng": 103.815747},
    {"name": "Braddell", "lat": 1.340599, "lng": 103.846788},
    {"name": "Bras Basah", "lat": 1.296896, "lng": 103.85055},
    {"name": "Bright Hill", "lat": 1.363449, "lng": 103.832836},
    {"name": "Buangkok", "lat": 1.383056, "lng": 103.89305},
    {"name": "Bugis", "lat": 1.30053, "lng": 103.856095},
    {"name": "Bukit Batok", "lat": 1.349057, "lng": 103.749591},
    {"name": "Bukit Gombak", "lat": 1.358893, "lng": 103.751825},
    {"name": "Bukit Panjang", "lat": 1.378296, "lng": 103.762138},
    {"name": "Buona Vista", "lat": 1.307263, "lng": 103.790705},
    {"name": "Caldecott", "lat": 1.33768, "lng": 103.839991},
    {"name": "Canberra", "lat": 1.443369, "lng": 103.829502},
    {"name": "Cantonment", "lat": 1.273115, "lng": 103.837028},
    {"name": "Cashew", "lat": 1.369661, "lng": 103.764481},
    {"name": "Changi Airport", "lat": 1.357338, "lng": 103.988565},
    {"name": "Cheng Lim", "lat": 1.39631, "lng": 103.893713},
    {"name": "Chinatown", "lat": 1.28502, "lng": 103.844003},
    {"name": "Chinese Garden", "lat": 1.34247, "lng": 103.732594},
    {"name": "Choa Chu Kang", "lat": 1.384749, "lng": 103.744534},
    {"name": "City Hall", "lat": 1.293214, "lng": 103.851835},
    {"name": "Clarke Quay", "lat": 1.288981, "lng": 103.846869},
    {"name": "Clementi", "lat": 1.3151, "lng": 103.765231},
    {"name": "Commonwealth", "lat": 1.302443, "lng": 103.798308},
    {"name": "Compassvale", "lat": 1.394518, "lng": 103.900435},
    {"name": "Coral Edge", "lat": 1.393876, "lng": 103.912643},
    {"name": "Cove", "lat": 1.399464, "lng": 103.905852},
    {"name": "Dakota", "lat": 1.308438, "lng": 103.88832},
    {"name": "Damai", "lat": 1.405282, "lng": 103.908556},
    {"name": "Dhoby Ghaut", "lat": 1.298786, "lng": 103.84502},
    {"name": "Dover", "lat": 1.311421, "lng": 103.778628},
    {"name": "Downtown", "lat": 1.279191, "lng": 103.853345},
    {"name": "Esplanade", "lat": 1.293258, "lng": 103.855974},
    {"name": "Eunos", "lat": 1.319814, "lng": 103.903058},
    {"name": "Expo", "lat": 1.33564, "lng": 103.962238},
    {"name": "Fajar", "lat": 1.38455, "lng": 103.7708},
    {"name": "Farmway", "lat": 1.397191, "lng": 103.889167},
    {"name": "Farrer Park", "lat": 1.312708, "lng": 103.854377},
    {"name": "Farrer Road", "lat": 1.317628, "lng": 103.807785},
    {"name": "Fernvale", "lat": 1.391916, "lng": 103.876297},
    {"name": "Fort Canning", "lat": 1.292393, "lng": 103.844157},
    {"name": "Gardens by the Bay", "lat": 1.279451, "lng": 103.868124},
    {"name": "Geylang Bahru", "lat": 1.321611, "lng": 103.871983},
    {"name": "Great World", "lat": 1.294625, "lng": 103.833483},
    {"name": "Gul Circle", "lat": 1.319423, "lng": 103.660415},
    {"name": "HarbourFront", "lat": 1.265391, "lng": 103.822403},
    {"name": "Havelock", "lat": 1.28749, "lng": 103.833707},
    {"name": "Haw Par Villa", "lat": 1.282654, "lng": 103.781772},
    {"name": "Hillview", "lat": 1.362451, "lng": 103.767067},
    {"name": "Holland Village", "lat": 1.312117, "lng": 103.795744},
    {"name": "Hougang", "lat": 1.371904, "lng": 103.892754},
    {"name": "Hume", "lat": 1.354339, "lng": 103.769212},
    {"name": "Jalan Besar", "lat": 1.305125, "lng": 103.85523},
    {"name": "Jelapang", "lat": 1.386683, "lng": 103.764515},
    {"name": "Joo Koon", "lat": 1.32772, "lng": 103.678285},
    {"name": "Jurong East", "lat": 1.333115, "lng": 103.742297},
    {"name": "Kadaloor", "lat": 1.399601, "lng": 103.916445},
    {"name": "Kaki Bukit", "lat": 1.335024, "lng": 103.908611},
    {"name": "Kallang", "lat": 1.311448, "lng": 103.871339},
    {"name": "Kangkar", "lat": 1.383922, "lng": 103.902202},
    {"name": "Katong Park", "lat": 1.297832, "lng": 103.886179},
    {"name": "Keat Hong", "lat": 1.378599, "lng": 103.74903},
    {"name": "Kembangan", "lat": 1.321055, "lng": 103.912762},
    {"name": "Kent Ridge", "lat": 1.293301, "lng": 103.784413},
    {"name": "Keppel", "lat": 1.27043, "lng": 103.830693},
    {"name": "Khatib", "lat": 1.417316, "lng": 103.832998},
    {"name": "King Albert Park", "lat": 1.33566, "lng": 103.78416},
    {"name": "Kovan", "lat": 1.359977, "lng": 103.884874},
    {"name": "Kranji", "lat": 1.425219, "lng": 103.761989},
    {"name": "Kupang", "lat": 1.398204, "lng": 103.881244},
    {"name": "Labrador Park", "lat": 1.272328, "lng": 103.802782},
    {"name": "Lakeside", "lat": 1.344303, "lng": 103.720801},
    {"name": "Lavender", "lat": 1.307445, "lng": 103.86303},
    {"name": "Layar", "lat": 1.392114, "lng": 103.880074},
    {"name": "Lentor", "lat": 1.384738, "lng": 103.836626},
    {"name": "Little India", "lat": 1.306571, "lng": 103.849299},
    {"name": "Lorong Chuan", "lat": 1.351488, "lng": 103.863395},
    {"name": "MacPherson", "lat": 1.326728, "lng": 103.890102},
    {"name": "Marina Bay", "lat": 1.275171, "lng": 103.854751},
    {"name": "Marina South Pier", "lat": 1.27175, "lng": 103.862723},
    {"name": "Marine Parade", "lat": 1.302612, "lng": 103.904983},
    {"name": "Marine Terrace", "lat": 1.306665, "lng": 103.915107},
    {"name": "Marsiling", "lat": 1.432542, "lng": 103.774216},
    {"name": "Marymount", "lat": 1.348614, "lng": 103.839238},
    {"name": "Mattar", "lat": 1.326969, "lng": 103.882958},
    {"name": "Maxwell", "lat": 1.280685, "lng": 103.844008},
    {"name": "Mayflower", "lat": 1.372151, "lng": 103.836789},
    {"name": "Meridian", "lat": 1.396976, "lng": 103.908874},
    {"name": "Mountbatten", "lat": 1.306249, "lng": 103.882496},
    {"name": "Napier", "lat": 1.307087, "lng": 103.819006},
    {"name": "Newton", "lat": 1.31296, "lng": 103.838864},
    {"name": "Nibong", "lat": 1.411831, "lng": 103.900305},
    {"name": "Nicoll Highway", "lat": 1.299671, "lng": 103.8635},
    {"name": "Novena", "lat": 1.320084, "lng": 103.843492},
    {"name": "Oasis", "lat": 1.402317, "lng": 103.912684},
    {"name": "one-north", "lat": 1.299607, "lng": 103.787241},
    {"name": "Orchard", "lat": 1.303223, "lng": 103.831982},
    {"name": "Orchard Boulevard", "lat": 1.302406, "lng": 103.824014},
    {"name": "Outram Park", "lat": 1.280685, "lng": 103.840241},
    {"name": "Pasir Panjang", "lat": 1.276177, "lng": 103.791614},
    {"name": "Pasir Ris", "lat": 1.373031, "lng": 103.949255},
    {"name": "Paya Lebar", "lat": 1.31805, "lng": 103.892318},
    {"name": "Pending", "lat": 1.376184, "lng": 103.771259},
    {"name": "Petir", "lat": 1.377756, "lng": 103.766634},
    {"name": "Phoenix", "lat": 1.378616, "lng": 103.758008},
    {"name": "Pioneer", "lat": 1.337575, "lng": 103.697354},
    {"name": "Potong Pasir", "lat": 1.331254, "lng": 103.869093},
    {"name": "Prince Edward Road", "lat": 1.273316, "lng": 103.847408},
    {"name": "Promenade", "lat": 1.293854, "lng": 103.860151},
    {"name": "Punggol", "lat": 1.405255, "lng": 103.902354},
    {"name": "Punggol Coast", "lat": 1.415018, "lng": 103.910329},
    {"name": "Punggol Point", "lat": 1.416845, "lng": 103.906664},
    {"name": "Queenstown", "lat": 1.294552, "lng": 103.806052},
    {"name": "Raffles Place", "lat": 1.284409, "lng": 103.85147},
    {"name": "Ranggung", "lat": 1.38403, "lng": 103.897349},
    {"name": "Redhill", "lat": 1.289653, "lng": 103.816757},
    {"name": "Renjong", "lat": 1.386708, "lng": 103.890485},
    {"name": "Riviera", "lat": 1.394581, "lng": 103.916135},
    {"name": "Rochor", "lat": 1.303951, "lng": 103.852634},
    {"name": "Rumbia", "lat": 1.391509, "lng": 103.905937},
    {"name": "Sam Kee", "lat": 1.40975, "lng": 103.904583},
    {"name": "Samudera", "lat": 1.415976, "lng": 103.90219},
    {"name": "Segar", "lat": 1.387792, "lng": 103.769593},
    {"name": "Sembawang", "lat": 1.449093, "lng": 103.820056},
    {"name": "Sengkang", "lat": 1.39133, "lng": 103.895294},
    {"name": "Senja", "lat": 1.382678, "lng": 103.762382},
    {"name": "Serangoon", "lat": 1.349807, "lng": 103.873771},
    {"name": "Shenton Way", "lat": 1.277661, "lng": 103.850548},
    {"name": "Siglap", "lat": 1.310009, "lng": 103.930026},
    {"name": "Simei", "lat": 1.343179, "lng": 103.953376},
    {"name": "Sixth Avenue", "lat": 1.330591, "lng": 103.797225},
    {"name": "Somerset", "lat": 1.300328, "lng": 103.838504},
    {"name": "Soo Teck", "lat": 1.405394, "lng": 103.897237},
    {"name": "South View", "lat": 1.38026, "lng": 103.745285},
    {"name": "Springleaf", "lat": 1.397771, "lng": 103.817932},
    {"name": "Stadium", "lat": 1.302946, "lng": 103.87539},
    {"name": "Stevens", "lat": 1.320192, "lng": 103.825461},
    {"name": "Sumang", "lat": 1.408532, "lng": 103.898534},
    {"name": "Tai Seng", "lat": 1.334866, "lng": 103.88815},
    {"name": "Tampines", "lat": 1.353374, "lng": 103.945084},
    {"name": "Tampines East", "lat": 1.356084, "lng": 103.954976},
    {"name": "Tampines West", "lat": 1.345519, "lng": 103.93856},
    {"name": "Tan Kah Kee", "lat": 1.325701, "lng": 103.807753},
    {"name": "Tanah Merah", "lat": 1.327262, "lng": 103.946513},
    {"name": "Tanjong Katong", "lat": 1.299319, "lng": 103.897369},
    {"name": "Tanjong Pagar", "lat": 1.276574, "lng": 103.845884},
    {"name": "Tanjong Rhu", "lat": 1.297265, "lng": 103.873453},
    {"name": "Teck Lee", "lat": 1.412705, "lng": 103.906653},
    {"name": "Teck Whye", "lat": 1.37667, "lng": 103.753647},
    {"name": "Telok Ayer", "lat": 1.282123, "lng": 103.848744},
    {"name": "Telok Blangah", "lat": 1.270586, "lng": 103.809863},
    {"name": "Thanggam", "lat": 1.397434, "lng": 103.875645},
    {"name": "Tiong Bahru", "lat": 1.286095, "lng": 103.827642},
    {"name": "Toa Payoh", "lat": 1.332297, "lng": 103.847327},
    {"name": "Tongkang", "lat": 1.389445, "lng": 103.885807},
    {"name": "Tuas Crescent", "lat": 1.320811, "lng": 103.649575},
    {"name": "Tuas Link", "lat": 1.340429, "lng": 103.636961},
    {"name": "Tuas West Road", "lat": 1.329495, "lng": 103.640149},
    {"name": "Ubi", "lat": 1.329763, "lng": 103.899379},
    {"name": "Upper Changi", "lat": 1.34169, "lng": 103.961263},
    {"name": "Upper Thomson", "lat": 1.354486, "lng": 103.832819},
    {"name": "Woodlands", "lat": 1.43718, "lng": 103.786961},
    {"name": "Woodlands North", "lat": 1.448646, "lng": 103.785519},
    {"name": "Woodlands South", "lat": 1.427145, "lng": 103.794295},
    {"name": "Woodleigh", "lat": 1.339197, "lng": 103.870754},
    {"name": "Yew Tee", "lat": 1.397461, "lng": 103.747401},
    {"name": "Yio Chu Kang", "lat": 1.38178, "lng": 103.844965},
    {"name": "Yishun", "lat": 1.429384, "lng": 103.835028},
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
