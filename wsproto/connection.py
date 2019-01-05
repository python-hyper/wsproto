# -*- coding: utf-8 -*-
"""
wsproto/connection
~~~~~~~~~~~~~~~~~~

An implementation of a WebSocket connection.
"""

from collections import deque
from enum import Enum

import h11

from .events import (
    AcceptConnection,
    BytesMessage,
    CloseConnection,
    Message,
    Ping,
    Pong,
    RejectConnection,
    RejectData,
    Request,
    TextMessage,
)
from .frame_protocol import CloseReason, FrameProtocol, Opcode, ParseFailed
from .utilities import (
    generate_accept_token,
    generate_nonce,
    LocalProtocolError,
    normed_header_dict,
    RemoteProtocolError,
    split_comma_header,
)


class ConnectionState(Enum):
    """
    RFC 6455, Section 4 - Opening Handshake
    """

    CONNECTING = 0
    OPEN = 1
    CLOSING = 2
    CLOSED = 3
    REJECTING = 4


class ConnectionType(Enum):
    #: This connection will act as client and talk to a remote server
    CLIENT = 1

    #: This connection will as as server and waits for client connections
    SERVER = 2


CLIENT = ConnectionType.CLIENT
SERVER = ConnectionType.SERVER


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
        elif isinstance(event, AcceptConnection):
            self._accept(event)
        elif isinstance(event, RejectConnection):
            self._reject(event)
        elif isinstance(event, RejectData):
            self._send_reject_data(event)
        elif isinstance(event, Message):
            self._outgoing += self._proto.send_data(event.data, event.message_finished)
        elif isinstance(event, Ping):
            self._outgoing += self._proto.ping(event.payload)
        elif isinstance(event, Pong):
            self._outgoing += self._proto.pong(event.payload)
        elif isinstance(event, CloseConnection):
            if self.state != ConnectionState.OPEN:
                raise LocalProtocolError(
                    "Connection cannot be closed in state %s" % self.state
                )
            self._outgoing += self._proto.close(event.code, event.reason)
            self._state = ConnectionState.CLOSING

    def _initiate_connection(self, request):
        # type: (Request) -> None
        self._initiating_request = request
        self._nonce = generate_nonce()

        headers = [
            (b"Host", request.host.encode("ascii")),
            (b"Upgrade", b"WebSocket"),
            (b"Connection", b"Upgrade"),
            (b"Sec-WebSocket-Key", self._nonce),
            (b"Sec-WebSocket-Version", self.version),
        ]

        if request.subprotocols:
            headers.append((b"Sec-WebSocket-Protocol", ", ".join(request.subprotocols)))

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
                headers.append((b"Sec-WebSocket-Extensions", b", ".join(extensions)))

        upgrade = h11.Request(
            method=b"GET",
            target=request.target.encode("ascii"),
            headers=headers + request.extra_headers,
        )
        self._outgoing += self._upgrade_connection.send(upgrade)

    def _accept(self, event):
        # type: (AcceptConnection) -> None
        request_headers = normed_header_dict(self._initiating_request.extra_headers)

        nonce = request_headers[b"sec-websocket-key"]
        accept_token = generate_accept_token(nonce)

        headers = [
            (b"Upgrade", b"WebSocket"),
            (b"Connection", b"Upgrade"),
            (b"Sec-WebSocket-Accept", accept_token),
        ]

        if event.subprotocol is not None:
            if event.subprotocol not in self._initiating_request.subprotocols:
                raise LocalProtocolError(
                    "unexpected subprotocol {}".format(event.subprotocol)
                )
            headers.append((b"Sec-WebSocket-Protocol", event.subprotocol))

        if event.extensions:
            accepts = self._extension_accept(event.extensions)
            if accepts:
                headers.append((b"Sec-WebSocket-Extensions", accepts))

        response = h11.InformationalResponse(
            status_code=101, headers=headers + event.extra_headers
        )
        self._outgoing += self._upgrade_connection.send(response)
        self._proto = FrameProtocol(self.client, event.extensions)
        self._state = ConnectionState.OPEN

    def _reject(self, event):
        # type: (RejectConnection) -> None:
        if self.state != ConnectionState.CONNECTING:
            raise LocalProtocolError(
                "Connection cannot be rejected in state %s" % self.state
            )

        headers = event.headers
        if not event.has_body:
            headers.append(("content-length", "0"))
        response = h11.Response(status_code=event.status_code, headers=headers)
        self._outgoing += self._upgrade_connection.send(response)
        self._state = ConnectionState.REJECTING
        if not event.has_body:
            self._outgoing += self._upgrade_connection.send(h11.EndOfMessage())
            self._state = ConnectionState.CLOSED

    def _send_reject_data(self, event):
        # type: (RejectData) -> None:
        if self.state != ConnectionState.REJECTING:
            raise LocalProtocolError(
                "Cannot send rejection data in state %s" % self.state
            )

        self._outgoing += self._upgrade_connection.send(h11.Data(data=event.data))
        if event.body_finished:
            self._outgoing += self._upgrade_connection.send(h11.EndOfMessage())
            self._state = ConnectionState.CLOSED

    @property
    def state(self):
        # type: () -> ConnectionState
        return self._state

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

        if data is None and self.state is ConnectionState.OPEN:
            # "If _The WebSocket Connection is Closed_ and no Close control
            # frame was received by the endpoint (such as could occur if the
            # underlying transport connection is lost), _The WebSocket
            # Connection Close Code_ is considered to be 1006."
            self._events.append(CloseConnection(code=CloseReason.ABNORMAL_CLOSURE))
            self._state = ConnectionState.CLOSED
            return

        if self.state in {ConnectionState.CONNECTING, ConnectionState.REJECTING}:
            event, data = self._process_upgrade(data)
            if event is not None:
                self._events.append(event)

        if self.state in (ConnectionState.OPEN, ConnectionState.CLOSING):
            self._proto.receive_bytes(data)
        elif self.state is ConnectionState.CLOSED:
            raise LocalProtocolError("Connection already closed.")

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
                    if self.state is ConnectionState.OPEN:
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

    def _process_upgrade(self, data):
        self._upgrade_connection.receive_data(data)
        while True:
            try:
                event = self._upgrade_connection.next_event()
            except h11.RemoteProtocolError:
                raise RemoteProtocolError("Bad HTTP message")
            if event is h11.NEED_DATA:
                break
            elif self.client and isinstance(
                event, (h11.InformationalResponse, h11.Response)
            ):
                if event.status_code == 101:
                    data = self._upgrade_connection.trailing_data[0]
                    return self._establish_client_connection(event), data

                self._state = ConnectionState.REJECTING
                return (
                    RejectConnection(
                        headers=event.headers,
                        status_code=event.status_code,
                        has_body=False,
                    ),
                    None,
                )
            elif self.client and isinstance(event, h11.Data):
                return RejectData(data=event.data, body_finished=False), None
            elif self.client and isinstance(event, h11.EndOfMessage):
                return RejectData(data=b"", body_finished=True), None
            elif not self.client and isinstance(event, h11.Request):
                return self._process_connection_request(event), None
            else:
                raise RemoteProtocolError("Bad HTTP message")

        self._incoming = b""
        return None, None

    def _establish_client_connection(self, event):  # noqa: MC0001
        accept = None
        connection_tokens = None
        accepts = []
        subprotocol = None
        upgrade = b""
        headers = []
        for name, value in event.headers:
            name = name.lower()
            if name == b"connection":
                connection_tokens = split_comma_header(value)
                continue  # Skip appending to headers
            elif name == b"sec-websocket-extensions":
                accepts = split_comma_header(value)
                continue  # Skip appending to headers
            elif name == b"sec-websocket-accept":
                accept = value
                continue  # Skip appending to headers
            elif name == b"sec-websocket-protocol":
                subprotocol = value
                continue  # Skip appending to headers
            elif name == b"upgrade":
                upgrade = value
                continue  # Skip appending to headers
            headers.append((name, value))

        if connection_tokens is None or not any(
            token.lower() == "upgrade" for token in connection_tokens
        ):
            raise RemoteProtocolError("Missing header, 'Connection: Upgrade'")
        if upgrade.lower() != b"websocket":
            raise RemoteProtocolError("Missing header, 'Upgrade: WebSocket'")
        accept_token = generate_accept_token(self._nonce)
        if accept != accept_token:
            raise RemoteProtocolError("Bad accept token")
        if subprotocol is not None:
            subprotocol = subprotocol.decode("ascii")
            if subprotocol not in self._initiating_request.subprotocols:
                raise RemoteProtocolError(
                    "unrecognized subprotocol {}".format(subprotocol)
                )
        extensions = []
        if accepts:
            for accept in accepts:
                name = accept.split(";", 1)[0].strip()
                for extension in self._initiating_request.extensions:
                    if extension.name == name:
                        extension.finalize(self, accept)
                        extensions.append(extension)
                        break
                else:
                    raise RemoteProtocolError("unrecognized extension {}".format(name))

        self._proto = FrameProtocol(self.client, self._initiating_request.extensions)
        self._state = ConnectionState.OPEN
        return AcceptConnection(
            extensions=extensions, extra_headers=headers, subprotocol=subprotocol
        )

    def _process_connection_request(self, event):
        if event.method != b"GET":
            raise RemoteProtocolError("Request method must be GET")
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
                continue  # Skip appending to headers
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
            raise RemoteProtocolError("Missing header, 'Connection: Upgrade'")
        # XX FIXME: need to check Sec-Websocket-Version, and respond with a
        # 400 if it's not what we expect
        if key is None:
            raise RemoteProtocolError("Missing header, 'Sec-WebSocket-Key'")
        if upgrade.lower() != b"websocket":
            raise RemoteProtocolError("Missing header, 'Upgrade: WebSocket'")
        if version is None:
            raise RemoteProtocolError("Missing header, 'Sec-WebSocket-Version'")

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
