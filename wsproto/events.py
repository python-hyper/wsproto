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

    _fields = []
    _defaults = {}

    def __init__(self, **kwargs):
        allowed = set(self._fields)
        for kwarg in kwargs:
            if kwarg not in allowed:
                raise TypeError(
                    "unrecognized kwarg {} for {}".format(
                        kwarg, self.__class__.__name__
                    )
                )
        required = allowed.difference(self._defaults)
        for field in required:
            if field not in kwargs:
                raise TypeError(
                    "missing required kwarg {} for {}".format(
                        field, self.__class__.__name__
                    )
                )
        defaults = {
            key: value() if callable(value) else value
            for key, value in self._defaults.items()
        }
        self.__dict__.update(defaults)
        self.__dict__.update(kwargs)

    def __repr__(self):
        name = self.__class__.__name__
        kwarg_strs = [
            "{}={}".format(field, self.__dict__[field]) for field in self._fields
        ]
        kwarg_str = ", ".join(kwarg_strs)
        return "{}({})".format(name, kwarg_str)

    def __eq__(self, other):
        return self.__class__ == other.__class__ and self.__dict__ == other.__dict__

    def __ne__(self, other):
        return not self.__eq__(other)

    # This is an unhashable type.
    __hash__ = None


class Request(Event):
    """The beginning of a Websocket connection, the HTTP Upgrade request

    This event is fired when a SERVER connection receives a WebSocket
    handshake request (HTTP with upgrade header).

    Fields:

    .. attribute:: extensions (Union[List[Extension], List[str]])

    .. attribute:: extra_headers

       The additional request headers, excluding extensions, host, subprotocols,
       and version headers.

    .. attribute:: host (str)

       The hostname, or host header value.

    .. attribute:: subprotocols List[str]

       A list of subprotocols ordered by preference.

    .. attribute:: target (str)

       A list of the subprotocols proposed in the request, as a list
       of strings.

    """

    _fields = ["extensions", "extra_headers", "host", "subprotocols", "target"]
    _defaults = {"extensions": list, "extra_headers": list, "subprotocols": list}


class AcceptConnection(Event):
    """The acceptance of a Websocket upgrade request.

    This event is fired when a CLIENT receives an acceptance response
    from a server. It is also used to accept an upgrade request when
    acting as a SERVER.

    Fields:

    .. attribute: extra_headers (List[Tuple[bytes, bytes]])

       Any additional (non websocket related) headers present in the
       acceptance response.

    .. attribute: subprotocol (Optional[str])

       The accepted subprotocol to use. Optional.

    """

    _fields = ["extensions", "extra_headers", "subprotocol"]
    _defaults = {"extensions": list, "extra_headers": list, "subprotocol": None}


class RejectConnection(Event):
    """The rejection of a Websocket upgrade request, the HTTP response.

    This event is fired when a CLIENT receives a rejection response
    from a server. It can be used to reject a request when sent from
    as SERVER. If has_body is False the headers must include a
    content-length or transfer encoding.

    Fields:

    .. attribute:: headers (List[Tuple[bytes, bytes]])

       The headers to send with the response.

    .. attribute:: has_body

       This defaults to False, but set to True if there is a body. See
       also :class:`~RejectData`.

    .. attribute:: status_code

       The response status code.

    """

    _fields = ["headers", "has_body", "status_code"]
    _defaults = {"headers": list, "has_body": False, "status_code": 400}


class RejectData(Event):
    """The rejection HTTP response body.

    Fields:

    .. attribute:: body_finished

       True if this is the final chunk of the body data.

    .. attribute:: data (bytes)

       The raw body data.

    """

    _fields = ["body_finished", "data"]
    _defaults = {"body_finished": True}


class CloseConnection(Event):

    """The end of a Websocket connection, represents a closure frame.

    This event is fired after the connection is considered closed.

    wsproto automatically emits a CLOSE frame when it receives one, to
    complete the close-handshake.

    Fields:

    .. attribute:: code

       The integer close code to indicate why the connection
       has closed.

    .. attribute:: reason

       Additional reasoning for why the connection has closed.

    """

    _fields = ["code", "reason"]
    _defaults = {"reason": None}

    def response(self):
        return CloseConnection(code=self.code, reason=self.reason)


class Message(Event):
    """The websocket data message.

    Fields:

    .. attribute:: data

       The message data as byte string, can be decoded as UTF-8 for
       TEXT messages.  This only represents a single chunk of data and
       not a full WebSocket message.  You need to buffer and
       reassemble these chunks to get the full message.

    .. attribute:: frame_finished

       This has no semantic content, but is provided just in case some
       weird edge case user wants to be able to reconstruct the
       fragmentation pattern of the original stream.

    .. attribute:: message_finished

       True if this frame is the last one of this message, False if
       more frames are expected.

    """

    _fields = ["data", "frame_finished", "message_finished"]
    _defaults = {"frame_finished": True, "message_finished": True}


class TextMessage(Message):
    """This event is fired when a data frame with TEXT payload is received."""

    pass


class BytesMessage(Message):
    """This event is fired when a data frame with BINARY payload is
    received.

    """

    pass


class Ping(Event):
    """The Ping event can be sent to trigger a ping frame and is fired
    when a Ping is received.

    wsproto automatically emits a PONG frame with the same payload.

    Fields:

    .. attribute:: payload

       An optional payload to emit with the ping frame.
    """

    _fields = ["payload"]
    _defaults = {"payload": b""}

    def response(self):
        return Pong(payload=self.payload)


class Pong(Event):
    """The Pong event is fired when a Pong is received.

    Fields:

    .. attribute:: payload

       An optional payload to emit with the pong frame.

    """

    _fields = ["payload"]
    _defaults = {"payload": b""}
