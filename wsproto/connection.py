# -*- coding: utf-8 -*-
"""
wsproto/connection
~~~~~~~~~~~~~~

An implementation of a WebSocket connection.
"""

import base64
import hashlib
import random

from enum import Enum

import h11

from .events import (
    ConnectionRequested, ConnectionEstablished, ConnectionClosed,
    ConnectionFailed, TextReceived, BytesReceived
)
from .frame_protocol import FrameProtocol, CloseReason, Opcode


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
    CLIENT = 1
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

    :param host: The hostname to pass to the server when acting as a client.
    :type host: ``str``

    :param resource: The resource (aka path) to pass to the server when acting
        as a client.
    :type resource: ``str``

    :param extensions: A list of  extensions to use on this connection.
        Extensions should be instances of a subclass of
        :class:`Extension <wsproto.extensions.Extension>`.

    :param subprotocol: A nominated subprotocol to request when acting as a
        client. This has no impact on the connection itself.
    :type subprotocol: ``str``
    """

    def __init__(self, conn_type, host=None, resource=None, extensions=None,
                 subprotocol=None):
        self.client = conn_type is ConnectionType.CLIENT

        self.host = host
        self.resource = resource

        self.subprotocol = subprotocol
        self.extensions = extensions or []

        self.version = b'13'

        self._state = ConnectionState.CONNECTING
        self._close_reason = None

        self._nonce = None
        self._outgoing = b''
        self._events = []
        self._proto = FrameProtocol(self.client, self.extensions)

        if self.client:
            self._upgrade_connection = h11.Connection(h11.CLIENT)
        else:
            self._upgrade_connection = h11.Connection(h11.SERVER)

        if self.client:
            self.initiate_connection()

    def initiate_connection(self):
        self._generate_nonce()

        headers = {
            b"Host": self.host.encode('ascii'),
            b"Upgrade": b'WebSocket',
            b"Connection": b'Upgrade',
            b"Sec-WebSocket-Key": self._nonce,
            b"Sec-WebSocket-Version": self.version,
        }
        if self.extensions:
            offers = {e.name: e.offer(self) for e in self.extensions}
            extensions = []
            for name, params in offers.items():
                name = name.encode('ascii')
                if params is True:
                    extensions.append(name)
                elif params:
                    params = params.encode('ascii')
                    extensions.append(b'%s; %s' % (name, params))
            if extensions:
                headers[b'Sec-WebSocket-Extensions'] = b', '.join(extensions)

        upgrade = h11.Request(method=b'GET', target=self.resource,
                              headers=headers.items())
        self._outgoing += self._upgrade_connection.send(upgrade)

    def send_data(self, payload, final=True):
        """
        Send a message or part of a message to the remote peer.

        If ``final`` is ``False`` it indicates that this is part of a longer
        message. If ``final`` is ``True`` it indicates that this is either a
        self-contained message or the last part of a longer message.

        If ``payload`` is of type ``bytes`` then the message is flagged as
        being binary If it is of type ``str`` encoded as UTF-8 and sent as
        text.

        :param payload: The message body to send.
        :type payload: ``bytes`` or ``str``

        :param final: Whether there are more parts to this message to be sent.
        :type final: ``bool``
        """

        self._outgoing += self._proto.send_data(payload, final)

    def close(self, code=CloseReason.NORMAL_CLOSURE, reason=None):
        self._outgoing += self._proto.close(code, reason)
        self._state = ConnectionState.CLOSING

    @property
    def closed(self):
        return self._state is ConnectionState.CLOSED

    def bytes_to_send(self, amount=None):
        """
        Return any data that is to be sent to the remote peer.

        :param amount: (optional) The maximum number of bytes to be provided.
            If ``None`` or not provided it will return all available bytes.
        :type amount: ``int``
        """

        if amount is None:
            data = self._outgoing
            self._outgoing = b''
        else:
            data = self._outgoing[:amount]
            self._outgoing = self._outgoing[amount:]

        return data

    def receive_bytes(self, data):
        """
        Pass some received bytes to the connection for processing.

        :param data: The data received from the remote peer.
        :type data: ``bytes``
        """

        if data is None and self._state is ConnectionState.OPEN:
            self._events.append(ConnectionClosed(CloseReason.NORMAL_CLOSURE))
            self._state = ConnectionState.CLOSED
            return
        elif data is None:
            self._state = ConnectionState.CLOSED
            return

        if self._state is ConnectionState.CONNECTING:
            event, data = self._process_upgrade(data)
            if event is not None:
                self._events.append(event)

        if self._state is ConnectionState.OPEN:
            self._proto.receive_bytes(data)

    def _process_upgrade(self, data):
        events = self._upgrade_connection.receive_data(data)
        for event in events:
            if self.client and isinstance(event, h11.InformationalResponse):
                data = self._upgrade_connection.trailing_data[0]
                return self._establish_client_connection(event), data
            elif not self.client and isinstance(event, h11.Request):
                return self._process_connection_request(event), None

        self._incoming = b''
        return None, None

    def events(self):
        """
        Return a generator that provides any events that have been generated
        by protocol activity.

        :returns: generator
        """

        while self._events:
            yield self._events.pop(0)

        for frame in self._proto.received_frames():
            if isinstance(frame, CloseReason):
                self.close(frame)
                yield ConnectionClosed(frame)
                return

            opcode, payload, fin = frame

            if opcode is Opcode.PING:
                self._outgoing += self._proto.pong(payload)
            elif opcode is Opcode.CLOSE:
                code, reason = payload
                self.close(code, reason)
                yield ConnectionClosed(code, reason)
            elif opcode is Opcode.TEXT:
                yield TextReceived(payload, fin)
            elif opcode is Opcode.BINARY:
                yield BytesReceived(payload, fin)

    def _generate_nonce(self):
        nonce = bytes(random.getrandbits(8) for x in range(0, 16))
        self._nonce = base64.b64encode(nonce)

    def _generate_accept_token(self, token):
        accept_token = token + ACCEPT_GUID
        accept_token = hashlib.sha1(accept_token).digest()
        return base64.b64encode(accept_token)

    def _establish_client_connection(self, event):
        if event.status_code != 101:
            return ConnectionFailed(CloseReason.PROTOCOL_ERROR,
                                    "Bad status code from server")
        headers = dict(event.headers)
        if headers[b'connection'].lower() != b'upgrade':
            return ConnectionFailed(CloseReason.PROTOCOL_ERROR,
                                    "Missing Connection: Upgrade header")
        if headers[b'upgrade'].lower() != b'websocket':
            return ConnectionFailed(CloseReason.PROTOCOL_ERROR,
                                    "Missing Upgrade: WebSocket header")

        accept_token = self._generate_accept_token(self._nonce)
        if headers[b'sec-websocket-accept'] != accept_token:
            return ConnectionFailed(CloseReason.PROTOCOL_ERROR,
                                    "Bad accept token")

        subprotocol = headers.get(b'sec-websocket-protocol', None)
        extensions = headers.get(b'sec-websocket-extensions', None)
        if extensions:
            accepts = [e.strip() for e in extensions.split(b',')]

            for accept in accepts:
                accept = accept.decode('ascii')
                name = accept.split(';', 1)[0].strip()
                for extension in self.extensions:
                    if extension.name == name:
                        extension.finalize(self, accept)

        self._state = ConnectionState.OPEN
        return ConnectionEstablished(subprotocol, extensions)

    def _process_connection_request(self, event):
        if event.method != b'GET':
            return ConnectionFailed(CloseReason.PROTOCOL_ERROR,
                                    "Request method must be GET")
        headers = dict(event.headers)
        if headers[b'connection'].lower() != b'upgrade':
            return ConnectionFailed(CloseReason.PROTOCOL_ERROR,
                                    "Missing Connection: Upgrade header")
        if headers[b'upgrade'].lower() != b'websocket':
            return ConnectionFailed(CloseReason.PROTOCOL_ERROR,
                                    "Missing Upgrade: WebSocket header")

        if b'sec-websocket-version' not in headers:
            return ConnectionFailed(CloseReason.PROTOCOL_ERROR,
                                    "Missing Sec-WebSocket-Version header")

        if b'sec-websocket-key' not in headers:
            return ConnectionFailed(CloseReason.PROTOCOL_ERROR,
                                    "Missing Sec-WebSocket-Key header")

        return ConnectionRequested(event)

    def accept(self, event):
        request = event.h11request
        request_headers = dict(request.headers)

        nonce = request_headers[b'sec-websocket-key']
        accept_token = self._generate_accept_token(nonce)

        headers = {
            b"Upgrade": b'WebSocket',
            b"Connection": b'Upgrade',
            b"Sec-WebSocket-Accept": accept_token,
            b"Sec-WebSocket-Version": self.version,
        }

        extensions = request_headers.get(b'sec-websocket-extensions', None)
        accepts = {}
        if extensions:
            offers = [e.strip() for e in extensions.split(b',')]

            for offer in offers:
                offer = offer.decode('ascii')
                name = offer.split(';', 1)[0].strip()
                for extension in self.extensions:
                    if extension.name == name:
                        accept = extension.accept(self, offer)
                        if accept is True:
                            accepts[extension.name] = True
                        elif accept:
                            accepts[extension.name] = accept.encode('ascii')

        if accepts:
            extensions = []
            for name, params in accepts.items():
                name = name.encode('ascii')
                if params is True:
                    extensions.append(name)
                else:
                    extensions.append(b'%s; %s' % (name, params))
            headers[b"Sec-WebSocket-Extensions"] = b', '.join(extensions)

        response = h11.InformationalResponse(status_code=101,
                                             headers=headers.items())
        self._outgoing += self._upgrade_connection.send(response)
        self._state = ConnectionState.OPEN
