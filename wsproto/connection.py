# -*- coding: utf-8 -*-
"""
wsproto/connection
~~~~~~~~~~~~~~

An implementation of a WebSocket connection.
"""

import base64
import codecs
import hashlib
import itertools
import random
import struct

from enum import Enum, IntEnum

import h11

from .events import (
    ConnectionRequested, ConnectionEstablished, ConnectionClosed,
    ConnectionFailed, BinaryMessageReceived, TextMessageReceived
)
from .frame_protocol import FrameProtocol, Message, CloseReason, Opcode


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


class WSConnection(object):
    def __init__(self, client, host=None, resource=None, extensions=None,
                 protocols=None):
        self.client = client

        self.host = host
        self.resource = resource

        self.protocols = protocols or []
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

    def send_binary(self, message):
        message = Message(Opcode.BINARY, fin=True, payload=message)
        self._enqueue_message(message)

    def send_text(self, message):
        message = Message(Opcode.TEXT, fin=True, payload=message)
        self._enqueue_message(message)

    def close(self, code=CloseReason.NORMAL_CLOSURE, reason=None):
        message = Message(Opcode.CLOSE, fin=True, payload=(code, reason))
        self._enqueue_message(message)
        self._state = ConnectionState.CLOSING

    @property
    def closed(self):
        return self._state is ConnectionState.CLOSED

    def bytes_to_send(self, amount=None):
        if amount is None:
            data = self._outgoing
            self._outgoing = b''
        else:
            data = self._outgoing[:amount]
            self._outgoing = self._outgoing[amount:]

        return data

    def receive_bytes(self, data):
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
        while self._events:
            yield self._events.pop(0)

        for message in self._proto.messages():
            if isinstance(message, CloseReason):
                reason = message
                self.close(reason)
                yield ConnectionClosed(reason)
                return

            if message.opcode is Opcode.PING:
                response = Message(Opcode.PONG, fin=True,
                                   payload=message.payload)
                self._enqueue_message(response)
            elif message.opcode is Opcode.CLOSE:
                code, reason = message.payload
                self.close(code, reason)
                yield ConnectionClosed(code, reason)
            elif message.opcode is Opcode.TEXT:
                yield TextMessageReceived(message.payload)
            elif message.opcode is Opcode.BINARY:
                yield BinaryMessageReceived(message.payload)

    def _generate_nonce(self):
        nonce = [random.getrandbits(8) for x in range(0, 16)]
        self._nonce = base64.b64encode(bytes(nonce))

    def _enqueue_message(self, *frames):
        for f in frames:
            if f.opcode is Opcode.TEXT:
                f.payload = f.payload.encode('utf-8')
            for extension in self.extensions:
                if not extension.enabled():
                    continue

                opcode, rsv, data = \
                    extension.frame_outbound(self, f.opcode, f.rsv, f.payload)
                f.opcode = opcode
                f.rsv = rsv
                f.payload = data

            if self.client:
                f.mask()

        self._outgoing += b''.join(f.serialize() for f in frames)

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


class WSClient(WSConnection):
    def __init__(self, host, resource, extensions=None, protocols=None):
        super().__init__(True, host, resource, extensions, protocols)


class WSServer(WSConnection):
    def __init__(self, extensions=None, protocols=None):
        super().__init__(False, extensions=extensions, protocols=protocols)
