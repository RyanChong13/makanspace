from django import template
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

register = template.Library()


@register.filter
def get_translation(listing, language):
    """Return a ListingTranslation for the given language code."""
    return listing.get_translation(language)


@register.filter
def index(value, arg):
    """Return value[arg] — useful for indexing a translated amenity list."""
    try:
        return value[arg]
    except (IndexError, TypeError, KeyError):
        return ""


@register.filter
def field_label(labels, token):
    """Translated label for an internal CSV field token (falls back to the token)."""
    return (labels or {}).get(token, token)


@register.filter
def msg(value):
    """
    Translate a literal msgid that the {% trans %} tag cannot resolve.

    {% trans %} templatizes its argument, so a msgid carrying a printf-style
    placeholder such as "Found %(n)s match(es):" is looked up under a key our
    catalogues do not have and silently comes back in English. gettext() on the
    raw string does hit, which is what JavaScript-side substitution needs: the
    number is filled in later, in the browser.
    """
    return _(str(value))


@register.filter(is_safe=True)
def ago_short(value):
    """
    Whole 'Listed … ago' sentence for a timestamp, shortest useful granularity.

    Django's timesince() cannot be used here: its unit words live in Django's own
    catalogues, and Tamil has none for them, so 'Listed 7 minutes ago' would leak
    English into a Tamil page. Each span is therefore an ngettext pair of our own
    catalogues. Note the extraction checker does not see ngettext calls, so these
    msgids are hand-added to TRANSLATIONS in build_translations.py.
    """
    if not value:
        return ""
    minutes = int((timezone.now() - value).total_seconds() // 60)
    if minutes < 1:
        return _("Listed just now")
    if minutes < 60:
        return ngettext(
            "Listed %(n)s minute ago", "Listed %(n)s minutes ago", minutes) % {"n": minutes}
    hours = minutes // 60
    if hours < 24:
        return ngettext(
            "Listed %(n)s hour ago", "Listed %(n)s hours ago", hours) % {"n": hours}
    days = hours // 24
    if days < 31:
        return ngettext(
            "Listed %(n)s day ago", "Listed %(n)s days ago", days) % {"n": days}
    months = days // 30
    if months < 12:
        return ngettext(
            "Listed %(n)s month ago", "Listed %(n)s months ago", months) % {"n": months}
    years = days // 365
    return ngettext(
        "Listed %(n)s year ago", "Listed %(n)s years ago", years) % {"n": years}
