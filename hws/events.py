# -*- coding: utf-8 -*-
"""
hws/events
~~~~~~~~~~

Events that result from processing data on a WebSocket connection.
"""

class ConnectionEstablished(object):
    def __init__(self, subprotocol=None, extensions=None):
        self.subprotocol = subprotocol
        self.extensions = extensions
        if self.extensions is None:
            self.extensions = []

    def __repr__(self):
        return '<ConnectionEstablished subprotocol:%r extensions:%r>' % \
               (self.subprotocol, self.extensions)

class ConnectionClosed(object):
    def __init__(self, code, reason=None):
        self.code = code
        self.reason = reason

    def __repr__(self):
        return '<%s code=%r reason="%s">' % (self.__class__.__name__,
                                             self.code, self.reason)

class ConnectionFailed(ConnectionClosed):
    pass

class MessageReceived(object):
    def __init__(self, message):
        self.message = message

class BinaryMessageReceived(MessageReceived):
    pass

class TextMessageReceived(MessageReceived):
    pass
