"""Single place that decides which language a request should render in.

The site stores the choice in two spots: signed-in users on
``User.preferred_language``, guests in ``session['preferred_language']``.
``LocaleMiddleware`` cannot see either of them (it runs before
``AuthenticationMiddleware`` and only reads ``django_language``), so both the
middleware below and the template context processor go through this helper.
"""

LEGACY_CODES = {"zh": "zh-hans"}

# The reverse, for turning an activated Django locale back into the short code
# the language selector and ListingTranslation rows use.
CHOICE_CODES = {value: key for key, value in LEGACY_CODES.items()}


def to_choice_code(lang):
    """Map an activated locale (``zh-hans``) back to the stored short code
    (``zh``), so the selector can highlight the current language and show its
    own label instead of falling back to English."""
    if not lang:
        return ""
    if lang in CHOICE_CODES:
        return CHOICE_CODES[lang]
    return lang.split("-")[0]


def resolve_language(request):
    """Return the active language code for this request, or '' if the user has
    not chosen one yet (then Django's own negotiation stands)."""
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        lang = getattr(user, "preferred_language", "") or ""
    else:
        session = getattr(request, "session", None)
        lang = session.get("preferred_language", "") if session else ""
    return LEGACY_CODES.get(lang, lang)
