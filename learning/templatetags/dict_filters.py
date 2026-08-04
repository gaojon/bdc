"""Custom template filters for dictionary lookups."""

from django import template

register = template.Library()


@register.filter
def get_item(dictionary: dict, key):
    """Get an item from a dictionary by key in a Django template.

    Usage: {{ my_dict|get_item:key_variable }}
    """
    if dictionary is None:
        return None
    return dictionary.get(str(key))
