from django.conf import settings
from django.utils import translation
from accounts.language import resolve_language, to_choice_code
from accounts.models import LANG_CHOICES


def language_context(request):
    """Activates the user's preferred language and adds context for templates.

    UserLanguageMiddleware already activates the same language before the view
    runs; this keeps working for pages rendered without that middleware (and
    supplies the template context below).
    """
    lang = resolve_language(request) or "en"

    # Activate Django translation for this request
    translation.activate(lang)

    # Show language modal only on first visit (no session key set yet)
    show_modal = "preferred_language" not in request.session and not request.user.is_authenticated

    display_map = dict(LANG_CHOICES)
    # Templates compare against, and look up, the short code the selector posts
    # ('zh'), while translation.activate() needs the Django locale ('zh-hans').
    choice = to_choice_code(lang)

    return {
        "current_language": choice,
        "current_language_display": display_map.get(choice, "English"),
        "active_language": lang,
        "show_language_modal": show_modal,
        "LANG_CHOICES": LANG_CHOICES,
        "GOOGLE_MAPS_API_KEY": getattr(settings, "GOOGLE_MAPS_API_KEY", ""),
    }
