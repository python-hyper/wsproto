# -*- coding: utf-8 -*-
"""
wsproto/utilities
~~~~~~~~~~~~~~~~~

Utility functions that do not belong in a separate module.
"""

# Some convenience utilities for working with HTTP headers
def normed_header_dict(h11_headers):
    # This mangles Set-Cookie headers. But it happens that we don't care about
    # any of those, so it's OK. For every other HTTP header, if there are
    # multiple instances then you're allowed to join them together with
    # commas.
    name_to_values = {}
    for name, value in h11_headers:
        name_to_values.setdefault(name, []).append(value)
    name_to_normed_value = {}
    for name, values in name_to_values.items():
        name_to_normed_value[name] = b", ".join(values)
    return name_to_normed_value


# We use this for parsing the proposed protocol list, and for parsing the
# proposed and accepted extension lists. For the proposed protocol list it's
# fine, because the ABNF is just 1#token. But for the extension lists, it's
# wrong, because those can contain quoted strings, which can in turn contain
# commas. XX FIXME
def split_comma_header(value):
    return [piece.decode('ascii').strip() for piece in value.split(b',')]
