from django.conf import settings
from django.utils import translation
from accounts.models import LANG_CHOICES


def language_context(request):
    """Activates the user's preferred language and adds context for templates."""
    if request.user.is_authenticated:
        lang = request.user.preferred_language
    else:
        lang = request.session.get("preferred_language", "en")

    # Normalise legacy codes
    if lang == "zh":
        lang = "zh-hans"

    # Activate Django translation for this request
    translation.activate(lang)

    # Show language modal only on first visit (no session key set yet)
    show_modal = "preferred_language" not in request.session and not request.user.is_authenticated

    display_map = dict(LANG_CHOICES)
    lang_display = display_map.get(lang, "English")

    return {
        "current_language": lang,
        "current_language_display": lang_display,
        "show_language_modal": show_modal,
        "LANG_CHOICES": LANG_CHOICES,
        "GOOGLE_MAPS_API_KEY": getattr(settings, "GOOGLE_MAPS_API_KEY", ""),
    }
