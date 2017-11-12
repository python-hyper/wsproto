# -*- coding: utf-8 -*-
"""
wsproto
~~~

A WebSocket implementation.
"""

from enum import Enum


__version__ = "0.10.0"


class ConnectionRole(Enum):
    CLIENT = 0
    SERVER = 1
