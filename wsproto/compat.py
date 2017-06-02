import sys

PY2 = sys.version_info.major == 2
PY3 = sys.version_info.major == 3

if PY3:
    unicode = str
else:
    unicode = unicode
