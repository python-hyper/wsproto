# -*- coding: utf-8 -*-
"""
wsproto/events
~~~~~~~~~~~~~~

Events that result from processing data on a WebSocket connection.
"""


class Event(object):
    """
    Base class for wsproto events.
    """
    pass


class ConnectionRequested(Event):
    """
    The ConnectionRequested event is fired when a SERVER connection receives a
    WebSocket handshake request (HTTP with upgrade header).
    """
    def __init__(self, proposed_subprotocols, h11request):
        self.proposed_subprotocols = proposed_subprotocols
        self.h11request = h11request

    def __repr__(self):
        path = self.h11request.target

        headers = dict(self.h11request.headers)
        host = headers[b'host']
        version = headers[b'sec-websocket-version']
        subprotocol = headers.get(b'sec-websocket-protocol', None)
        extensions = []

        fmt = '<%s host=%s path=%s version=%s subprotocol=%r extensions=%r>'
        return fmt % (self.__class__.__name__, host, path, version,
                      subprotocol, extensions)


class ConnectionEstablished(Event):
    """
    The ConnectionEstablished event is fired when a CLIENT connection completes
    the WebSocket handshake and is ready to send & receive messages.
    """
    def __init__(self, subprotocol=None, extensions=None):
        self.subprotocol = subprotocol
        self.extensions = extensions
        if self.extensions is None:
            self.extensions = []

    def __repr__(self):
        return '<ConnectionEstablished subprotocol=%r extensions=%r>' % \
               (self.subprotocol, self.extensions)


class ConnectionClosed(Event):
    """
    The ConnectionClosed event is fired after the connection is considered closed.

    wsproto automatically emits a CLOSE frame when it receives one, to complete the close-handshake.
    """
    def __init__(self, code, reason=None):
        #: The close status code, see :class:`CloseReason
        #: <wsproto.frame_protocol.CloseReason>`.
        self.code = code
        self.reason = reason

    def __repr__(self):
        return '<%s code=%r reason="%s">' % (self.__class__.__name__,
                                             self.code, self.reason)


class ConnectionFailed(ConnectionClosed):
    pass


class DataReceived(Event):
    def __init__(self, data, frame_finished, message_finished):
        #: The message data as byte string, can be decoded as UTF-8 for TEXT messages.
        #: This only represents a single chunk of data and not a full WebSocket message.
        #: You need to buffer and reassemble these chunks to get the full message.
        self.data = data

        #: This has no semantic content, but is provided just in case some
        #: weird edge case user wants to be able to reconstruct the
        #: fragmentation pattern of the original stream. You don't want it:
        self.frame_finished = frame_finished

        #: True if this frame is the last one of this message, False if more frames are expected.
        self.message_finished = message_finished


class TextReceived(DataReceived):
    """
    The TextReceived event is fired when a data frame with TEXT payload is received.
    """
    pass


class BytesReceived(DataReceived):
    """
    The BytesReceived event is fired when a data frame with BINARY payload is received.
    """
    pass


class PingReceived(Event):
    """
    The PingReceived event is fired when a Ping is received.

    wsproto automatically emits a PONG frame with the same payload.
    """
    def __init__(self, payload):
        #: Optional "Application data", i.e., binary payload.
        self.payload = payload


class PongReceived(Event):
    """
    The PongReceived event is fired when a Pong is received.
    """
    def __init__(self, payload):
        #: Optional "Application data", i.e., binary payload.
        #: Make sure to verify against the orignal PING payload.
        self.payload = payload
