# -*- coding: utf-8 -*-
"""
wsproto/connection
~~~~~~~~~~~~~~~~~~

An implementation of a WebSocket connection.
"""

import base64
import hashlib
import os
from collections import deque
from enum import Enum

import h11

from .events import (
    AcceptConnection,
    BytesMessage,
    CloseConnection,
    Data,
    Fail,
    Ping,
    Pong,
    Request,
    TextMessage,
)
from .frame_protocol import CloseReason, FrameProtocol, Opcode, ParseFailed
from .utilities import normed_header_dict, split_comma_header

# RFC6455, Section 1.3 - Opening Handshake
ACCEPT_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class ConnectionState(Enum):
    """
    RFC 6455, Section 4 - Opening Handshake
    """

    CONNECTING = 0
    OPEN = 1
    CLOSING = 2
    CLOSED = 3


class ConnectionType(Enum):
    #: This connection will act as client and talk to a remote server
    CLIENT = 1

    #: This connection will as as server and waits for client connections
    SERVER = 2


CLIENT = ConnectionType.CLIENT
SERVER = ConnectionType.SERVER


class ConnectionStateError(Exception):
    def __init__(self, msg, state):
        super(ConnectionStateError, self).__init__(msg)
        self.state = state


class WSConnection(object):
    """
    A low-level WebSocket connection object.

    This wraps two other protocol objects, an HTTP/1.1 protocol object used
    to do the initial HTTP upgrade handshake and a WebSocket frame protocol
    object used to exchange messages and other control frames.

    :param conn_type: Whether this object is on the client- or server-side of
        a connection. To initialise as a client pass ``CLIENT`` otherwise
        pass ``SERVER``.
    :type conn_type: ``ConnectionType``
    """

    def __init__(self, conn_type):
        self.client = conn_type is ConnectionType.CLIENT

        self.version = b"13"

        self._state = ConnectionState.CONNECTING
        self._close_reason = None

        self._nonce = None
        self._outgoing = b""
        self._events = deque()
        self._proto = None

        if self.client:
            self._upgrade_connection = h11.Connection(h11.CLIENT)
        else:
            self._upgrade_connection = h11.Connection(h11.SERVER)

        # The request that initiated the websocket connection
        self._initiating_request = None  # type: Optional[Request]

    def initiate_upgrade_connection(self, headers, path):
        # type: (List[Tuple[bytes, bytes]], str) -> None
        upgrade_request = h11.Request(method=b"GET", target=path, headers=headers)
        h11_client = h11.Connection(h11.CLIENT)
        self.receive_bytes(h11_client.send(upgrade_request))

    def send(self, event):
        # type: (wsproto.events.Event) -> None:
        if isinstance(event, Request):
            self._initiate_connection(event)
        if isinstance(event, AcceptConnection):
            self._accept(event)
        elif isinstance(event, Data):
            self._outgoing += self._proto.send_data(event.data, event.message_finished)
        elif isinstance(event, Ping):
            self._outgoing += self._proto.ping(event.payload)
        elif isinstance(event, Pong):
            self._outgoing += self._proto.pong(event.payload)
        elif isinstance(event, CloseConnection):
            if not self.opened:
                raise ConnectionStateError(
                    'Must be in OPEN state to perform a CloseConnection', self._state)
            self._outgoing += self._proto.close(event.code, event.reason)
            self._state = ConnectionState.CLOSING

    def _initiate_connection(self, request):
        # type: (Request) -> None
        self._initiating_request = request
        self._generate_nonce()

        headers = {
            b"Host": request.host.encode("ascii"),
            b"Upgrade": b"WebSocket",
            b"Connection": b"Upgrade",
            b"Sec-WebSocket-Key": self._nonce,
            b"Sec-WebSocket-Version": self.version,
        }

        if request.subprotocols:
            headers[b"Sec-WebSocket-Protocol"] = ", ".join(request.subprotocols)

        if request.extensions:
            offers = {e.name: e.offer(self) for e in request.extensions}
            extensions = []
            for name, params in offers.items():
                if params is True:
                    extensions.append(name.encode("ascii"))
                elif params:
                    # py34 annoyance: doesn't support bytestring formatting
                    extensions.append(("%s; %s" % (name, params)).encode("ascii"))
            if extensions:
                headers[b"Sec-WebSocket-Extensions"] = b", ".join(extensions)

        upgrade = h11.Request(
            method=b"GET",
            target=request.target.encode("ascii"),
            headers=headers.items(),
        )
        self._outgoing += self._upgrade_connection.send(upgrade)

    def _accept(self, event):
        # type: (Accept) -> None
        request_headers = normed_header_dict(self._initiating_request.extra_headers)

        nonce = request_headers[b"sec-websocket-key"]
        accept_token = self._generate_accept_token(nonce)

        headers = {
            b"Upgrade": b"WebSocket",
            b"Connection": b"Upgrade",
            b"Sec-WebSocket-Accept": accept_token,
        }

        if event.subprotocol is not None:
            if event.subprotocol not in self._initiating_request.subprotocols:
                raise ValueError(
                    "unexpected subprotocol {!r}".format(event.subprotocol)
                )
            headers[b"Sec-WebSocket-Protocol"] = event.subprotocol

        if event.extensions:
            accepts = self._extension_accept(event.extensions)
            if accepts:
                headers[b"Sec-WebSocket-Extensions"] = accepts

        response = h11.InformationalResponse(status_code=101, headers=headers.items())
        self._outgoing += self._upgrade_connection.send(response)
        self._proto = FrameProtocol(self.client, event.extensions)
        self._state = ConnectionState.OPEN

    @property
    def closed(self):
        return self._state is ConnectionState.CLOSED

    @property
    def opened(self):
        return self._state is ConnectionState.OPEN

    def bytes_to_send(self, amount=None):
        """
        Returns some data for sending out of the internal data buffer.

        This method is analogous to ``read`` on a file-like object, but it
        doesn't block. Instead, it returns as much data as the user asks for,
        or less if that much data is not available. It does not perform any
        I/O, and so uses a different name.

        :param amount: (optional) The maximum amount of data to return. If not
            set, or set to ``None``, will return as much data as possible.
        :type amount: ``int``
        :returns: A bytestring containing the data to send on the wire.
        :rtype: ``bytes``
        """
        if amount is None:
            data = self._outgoing
            self._outgoing = b""
        else:
            data = self._outgoing[:amount]
            self._outgoing = self._outgoing[amount:]
        return data

    def receive_bytes(self, data):
        """
        Pass some received data to the connection for handling.

        A list of events that the remote peer triggered by sending this data can
        be retrieved with :meth:`~wsproto.connection.WSConnection.events`.

        :param data: The data received from the remote peer on the network.
        :type data: ``bytes``
        """

        if data is None and self._state is ConnectionState.OPEN:
            # "If _The WebSocket Connection is Closed_ and no Close control
            # frame was received by the endpoint (such as could occur if the
            # underlying transport connection is lost), _The WebSocket
            # Connection Close Code_ is considered to be 1006."
            self._events.append(CloseConnection(code=CloseReason.ABNORMAL_CLOSURE))
            self._state = ConnectionState.CLOSED
            return

        if self._state is ConnectionState.CONNECTING:
            event, data = self._process_upgrade(data)
            if event is not None:
                self._events.append(event)

        if self._state in (ConnectionState.OPEN, ConnectionState.CLOSING):
            self._proto.receive_bytes(data)
        elif self._state is ConnectionState.CLOSED:
            raise ValueError("Connection already closed.")

    def events(self):
        """
        Return a generator that provides any events that have been generated
        by protocol activity.

        :returns: generator of :class:`Event <wsproto.events.Event>` subclasses
        """

        while self._events:
            yield self._events.popleft()

        if self._proto is None:
            return

        try:
            for frame in self._proto.received_frames():
                if frame.opcode is Opcode.PING:
                    assert frame.frame_finished and frame.message_finished
                    self._outgoing += self._proto.pong(frame.payload)
                    yield Ping(payload=frame.payload)

                elif frame.opcode is Opcode.PONG:
                    assert frame.frame_finished and frame.message_finished
                    yield Pong(payload=frame.payload)

                elif frame.opcode is Opcode.CLOSE:
                    code, reason = frame.payload
                    if self._state is ConnectionState.OPEN:
                        self.send(CloseConnection(code=code, reason=reason))
                    self._state = ConnectionState.CLOSED
                    yield CloseConnection(code=code, reason=reason)

                elif frame.opcode is Opcode.TEXT:
                    yield TextMessage(
                        data=frame.payload,
                        frame_finished=frame.frame_finished,
                        message_finished=frame.message_finished,
                    )

                elif frame.opcode is Opcode.BINARY:
                    yield BytesMessage(
                        data=frame.payload,
                        frame_finished=frame.frame_finished,
                        message_finished=frame.message_finished,
                    )
        except ParseFailed as exc:
            # XX FIXME: apparently autobahn intentionally deviates from the
            # spec in that on protocol errors it just closes the connection
            # rather than trying to send a CLOSE frame. Investigate whether we
            # should do the same.
            self.send(CloseConnection(code=exc.code, reason=str(exc)))
            yield CloseConnection(code=exc.code, reason=str(exc))

    def _generate_nonce(self):
        # os.urandom may be overkill for this use case, but I don't think this
        # is a bottleneck, and better safe than sorry...
        self._nonce = base64.b64encode(os.urandom(16))

    def _generate_accept_token(self, token):
        accept_token = token + ACCEPT_GUID
        accept_token = hashlib.sha1(accept_token).digest()
        return base64.b64encode(accept_token)

    def _process_upgrade(self, data):
        self._upgrade_connection.receive_data(data)
        while True:
            try:
                event = self._upgrade_connection.next_event()
            except h11.RemoteProtocolError:
                return (
                    Fail(code=CloseReason.PROTOCOL_ERROR, reason="Bad HTTP message"),
                    b"",
                )
            if event is h11.NEED_DATA:
                break
            elif self.client and isinstance(
                event, (h11.InformationalResponse, h11.Response)
            ):
                data = self._upgrade_connection.trailing_data[0]
                return self._establish_client_connection(event), data
            elif not self.client and isinstance(event, h11.Request):
                return self._process_connection_request(event), None
            else:
                return (
                    Fail(code=CloseReason.PROTOCOL_ERROR, reason="Bad HTTP message"),
                    b"",
                )

        self._incoming = b""
        return None, None

    def _establish_client_connection(self, event):
        if event.status_code != 101:
            return Fail(
                code=CloseReason.PROTOCOL_ERROR, reason="Bad status code from server"
            )
        headers = normed_header_dict(event.headers)
        connection_tokens = split_comma_header(headers[b"connection"])
        if not any(token.lower() == "upgrade" for token in connection_tokens):
            return Fail(
                code=CloseReason.PROTOCOL_ERROR,
                reason="Missing Connection: Upgrade header",
            )
        if headers[b"upgrade"].lower() != b"websocket":
            return Fail(
                code=CloseReason.PROTOCOL_ERROR,
                reason="Missing Upgrade: WebSocket header",
            )

        accept_token = self._generate_accept_token(self._nonce)
        if headers[b"sec-websocket-accept"] != accept_token:
            return Fail(code=CloseReason.PROTOCOL_ERROR, reason="Bad accept token")

        subprotocol = headers.get(b"sec-websocket-protocol", None)
        if subprotocol is not None:
            subprotocol = subprotocol.decode("ascii")
            if subprotocol not in self._initiating_request.subprotocols:
                return Fail(
                    code=CloseReason.PROTOCOL_ERROR,
                    reason="unrecognized subprotocol {!r}".format(subprotocol),
                )

        extensions = headers.get(b"sec-websocket-extensions", None)
        if extensions:
            accepts = split_comma_header(extensions)

            for accept in accepts:
                name = accept.split(";", 1)[0].strip()
                for extension in self._initiating_request.extensions:
                    if extension.name == name:
                        extension.finalize(self, accept)
                        break
                else:
                    return Fail(
                        code=CloseReason.PROTOCOL_ERROR,
                        reason="unrecognized extension {!r}".format(name),
                    )

        self._proto = FrameProtocol(self.client, self._initiating_request.extensions)
        self._state = ConnectionState.OPEN
        return AcceptConnection(extensions=extensions, subprotocol=subprotocol)

    def _process_connection_request(self, event):
        if event.method != b"GET":
            return Fail(
                code=CloseReason.PROTOCOL_ERROR, reason="Request method must be GET"
            )
        connection_tokens = None
        extensions = []
        host = None
        key = None
        subprotocols = []
        upgrade = b""
        version = None
        headers = []
        for name, value in event.headers:
            name = name.lower()
            if name == b"connection":
                connection_tokens = split_comma_header(value)
            elif name == b"host":
                host = value.decode("ascii")
            elif name == b"sec-websocket-extensions":
                extensions = split_comma_header(value)
                continue  # Skip appending to headers
            elif name == b"sec-websocket-key":
                key = value
            elif name == b"sec-websocket-protocol":
                subprotocols = split_comma_header(value)
                continue  # Skip appending to headers
            elif name == b"sec-websocket-version":
                version = value
            elif name == b"upgrade":
                upgrade = value
            headers.append((name, value))
        if connection_tokens is None or not any(
            token.lower() == "upgrade" for token in connection_tokens
        ):
            return Fail(
                code=CloseReason.PROTOCOL_ERROR,
                reason="Missing Connection: Upgrade header",
            )
        # XX FIXME: need to check Sec-Websocket-Version, and respond with a
        # 400 if it's not what we expect
        if key is None:
            return Fail(
                code=CloseReason.PROTOCOL_ERROR,
                reason="Missing Sec-WebSocket-Key header",
            )
        if upgrade.lower() != b"websocket":
            return Fail(
                code=CloseReason.PROTOCOL_ERROR,
                reason="Missing Upgrade: WebSocket header",
            )
        if version is None:
            return Fail(
                code=CloseReason.PROTOCOL_ERROR,
                reason="Missing Sec-WebSocket-Version header",
            )

        self._initiating_request = Request(
            extensions=extensions,
            extra_headers=headers,
            host=host,
            subprotocols=subprotocols,
            target=event.target.decode("ascii"),
        )
        return self._initiating_request

    def _extension_accept(self, supported):
        accepts = {}

        for offer in self._initiating_request.extensions:
            name = offer.split(";", 1)[0].strip()
            for extension in supported:
                if extension.name == name:
                    accept = extension.accept(self, offer)
                    if accept is True:
                        accepts[extension.name] = True
                    elif accept is not False and accept is not None:
                        accepts[extension.name] = accept.encode("ascii")

        if accepts:
            extensions = []
            for name, params in accepts.items():
                if params is True:
                    extensions.append(name.encode("ascii"))
                else:
                    # py34 annoyance: doesn't support bytestring formatting
                    params = params.decode("ascii")
                    if params == "":
                        extensions.append(("%s" % (name)).encode("ascii"))
                    else:
                        extensions.append(("%s; %s" % (name, params)).encode("ascii"))
            return b", ".join(extensions)

        return None
