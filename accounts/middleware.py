"""Middleware that activates the visitor's saved language for the whole request."""

from django.utils import translation

from accounts.language import resolve_language


class UserLanguageMiddleware:
    """Activate the chosen language before the view runs.

    LocaleMiddleware sits before AuthenticationMiddleware, so it never sees
    User.preferred_language, and the site keeps guests on their own
    session['preferred_language'] key. Activating here is what makes gettext()
    calls inside views — every flash message, every CSV row error — come out
    in the same language as the page that renders them a moment later.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lang = resolve_language(request)
        if lang:
            translation.activate(lang)
        return self.get_response(request)
