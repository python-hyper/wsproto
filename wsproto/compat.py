import sys


PY2 = sys.version_info.major == 2
PY3 = sys.version_info.major == 3

if PY3:
    unicode = str

    def Utf8Validator():
        return None
else:
    unicode = unicode
    from .utf8validator import Utf8Validator
