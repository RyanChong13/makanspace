from django import template


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
