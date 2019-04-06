# -*- coding: utf-8 -*-
"""
wsproto/events
~~~~~~~~~~~~~~

Events that result from processing data on a WebSocket connection.
"""
from abc import ABC
from dataclasses import dataclass, field
from typing import Generic, List, Optional, TypeVar, Union

from .extensions import Extension
from .typing import Headers


class Event(ABC):
    """
    Base class for wsproto events.
    """

    pass


@dataclass(frozen=True)
class Request(Event):
    """The beginning of a Websocket connection, the HTTP Upgrade request

    This event is fired when a SERVER connection receives a WebSocket
    handshake request (HTTP with upgrade header).

    Fields:

    .. attribute:: extensions

       The proposed extensions.

    .. attribute:: extra_headers

       The additional request headers, excluding extensions, host, subprotocols,
       and version headers.

    .. attribute:: host

       The hostname, or host header value.

    .. attribute:: subprotocols

       A list of the subprotocols proposed in the request, as a list
       of strings.

    .. attribute:: target

       The request target (path and query string)
    """

    host: str
    target: str
    extensions: Union[List[Extension], List[str]] = field(  # type: ignore
        default_factory=list
    )
    extra_headers: Headers = field(default_factory=list)
    subprotocols: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class AcceptConnection(Event):
    """The acceptance of a Websocket upgrade request.

    This event is fired when a CLIENT receives an acceptance response
    from a server. It is also used to accept an upgrade request when
    acting as a SERVER.

    Fields:

    .. attribute: extra_headers

       Any additional (non websocket related) headers present in the
       acceptance response.

    .. attribute: subprotocol

       The accepted subprotocol to use.

    """

    subprotocol: Optional[str] = None
    extensions: List[Extension] = field(default_factory=list)
    extra_headers: Headers = field(default_factory=list)


@dataclass(frozen=True)
class RejectConnection(Event):
    """The rejection of a Websocket upgrade request, the HTTP response.

    This event is fired when a CLIENT receives a rejection response
    from a server. It can be used to reject a request when sent from
    as SERVER. If has_body is False the headers must include a
    content-length or transfer encoding.

    Fields:

    .. attribute:: headers (Headers)

       The headers to send with the response.

    .. attribute:: has_body

       This defaults to False, but set to True if there is a body. See
       also :class:`~RejectData`.

    .. attribute:: status_code

       The response status code.

    """

    status_code: int = 400
    headers: Headers = field(default_factory=list)
    has_body: bool = False


@dataclass(frozen=True)
class RejectData(Event):
    """The rejection HTTP response body.

    Fields:

    .. attribute:: body_finished

       True if this is the final chunk of the body data.

    .. attribute:: data (bytes)

       The raw body data.

    """

    data: bytes
    body_finished: bool = True


@dataclass(frozen=True)
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

    code: int
    reason: Optional[str] = None

    def response(self) -> "CloseConnection":
        return CloseConnection(code=self.code, reason=self.reason)


T = TypeVar("T", bytes, str)


@dataclass(frozen=True)
class Message(Event, Generic[T]):
    """The websocket data message.

    Fields:

    .. attribute:: frame_finished

       This has no semantic content, but is provided just in case some
       weird edge case user wants to be able to reconstruct the
       fragmentation pattern of the original stream.

    .. attribute:: message_finished

       True if this frame is the last one of this message, False if
       more frames are expected.

    """

    data: T
    frame_finished: bool = True
    message_finished: bool = True


@dataclass(frozen=True)
class TextMessage(Message[str]):
    """This event is fired when a data frame with TEXT payload is received.

    Fields:

    .. attribute:: data

       The message data as string, This only represents a single chunk
       of data and not a full WebSocket message.  You need to buffer
       and reassemble these chunks to get the full message.

    """

    pass


@dataclass(frozen=True)
class BytesMessage(Message[bytes]):
    """This event is fired when a data frame with BINARY payload is
    received.

    Fields:

    .. attribute:: data

       The message data as byte string, can be decoded as UTF-8 for
       TEXT messages.  This only represents a single chunk of data and
       not a full WebSocket message.  You need to buffer and
       reassemble these chunks to get the full message.

    """

    pass


@dataclass(frozen=True)
class Ping(Event):
    """The Ping event can be sent to trigger a ping frame and is fired
    when a Ping is received.

    wsproto automatically emits a PONG frame with the same payload.

    Fields:

    .. attribute:: payload

       An optional payload to emit with the ping frame.
    """

    payload: bytes = b""

    def response(self) -> "Pong":
        return Pong(payload=self.payload)


@dataclass(frozen=True)
class Pong(Event):
    """The Pong event is fired when a Pong is received.

    Fields:

    .. attribute:: payload

       An optional payload to emit with the pong frame.

    """

    payload: bytes = b""
