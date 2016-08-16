# -*- coding: utf-8 -*-
"""
hws/connection
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

from .events import *

# RFC6455, Section 1.3 - Opening Handshake
ACCEPT_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# RFC6455, Section 5.2 - Base Framing Protocol
MAX_FRAME_PAYLOAD = 2 ** 64

class ConnectionState(Enum):
    """
    RFC 6455, Section 4 - Opening Handshake
    """
    CONNECTING = 0
    OPEN = 1
    CLOSING = 2
    CLOSED = 3


class Opcode(IntEnum):
    """
    RFC 6455, Section 5.2 - Base Framing Protocol
    """
    CONTINUATION = 0x0
    TEXT = 0x1
    BINARY = 0x2
    CLOSE = 0x8
    PING = 0x9
    PONG = 0xA

class CloseReason(IntEnum):
    """
    RFC 6455, Section 7.4.1 - Defined Status Codes
    """
    NORMAL_CLOSURE = 1000
    GOING_AWAY = 1001
    PROTOCOL_ERROR = 1002
    UNSUPPORTED_DATA = 1003
    NO_STATUS_RCVD = 1005
    ABNORMAL_CLOSURE = 1006
    INVALID_FRAME_PAYLOAD_DATA = 1007
    POLICY_VIOLATION = 1008
    MESSAGE_TOO_BIG = 1009
    MANDATORY_EXT = 1010
    INTERNAL_ERROR = 1011
    SERVICE_RESTART = 1012
    TRY_AGAIN_LATER = 1013
    TLS_HANDHSAKE_FAILED = 1015


# RFC 6455, Section 7.4.1 - Defined Status Codes
LOCAL_ONLY_CLOSE_REASONS = (
    CloseReason.NO_STATUS_RCVD,
    CloseReason.ABNORMAL_CLOSURE,
    CloseReason.TLS_HANDHSAKE_FAILED,
    )


PROTOCOL_ERROR = object()
INVALID_FRAME_PAYLOAD_DATA = object()


class Message(object):
    def __init__(self, opcode, fin=True, rsv=None, payload=None,
                 masking_key=None):
        self.opcode = opcode
        self.rsv = rsv
        self.fin = fin
        self.payload = payload

        self.masking_key = masking_key

        if self.rsv is None:
            self.rsv = (False, False, False)

    def mask(self):
        if self.masking_key is None:
            self.masking_key = bytes(random.getrandbits(8) for x in range(0, 4))

    def serialize(self):
        rsv = 0
        for bit in self.rsv:
            rsv |= int(bit)
            rsv <<= 1
        fin_rsv = (int(self.fin) << 3) | rsv
        fin_rsv_opcode = fin_rsv << 4 | self.opcode

        if self.opcode is Opcode.CLOSE:
            code, reason = self.payload
            if reason is not None:
                reason = reason.encode('utf-8')
            else:
                reason = b''
            self.payload = struct.pack('!H', code) + reason
        elif self.opcode is Opcode.TEXT:
            self.payload = self.payload.encode('utf-8')

        payload_length = len(self.payload)
        quad_payload = False
        if payload_length <= 125:
            first_payload = payload_length
            second_payload = None
        elif payload_length <= 65535:
            first_payload = 126
            second_payload = payload_length
        else:
            first_payload = 127
            second_payload = payload_length
            quad_payload = True

        if self.masking_key is not None:
            first_payload |= 1 << 7

        header = bytes([fin_rsv_opcode, first_payload])
        if second_payload is not None:
            if quad_payload:
                header += struct.pack('!Q', second_payload)
            else:
                header += struct.pack('!H', second_payload)

        if self.masking_key:
            maskbytes = itertools.cycle(self.masking_key)
            return header + self.masking_key + \
                bytes([b ^ next(maskbytes) for b in self.payload])
        else:
            return header + self.payload

    def __repr__(self):
        payload = '%d bytes ' % len(self.payload)
        if self.masking_key:
            payload += 'masked payload'
        else:
            payload += 'payload'

        rsv = ''.join(str(int(f)) for f in self.rsv)
        return '<Frame opcode=%s rsv=%s %s>' % (self.opcode, rsv, payload)


class MessageDeserializer(object):
    def __init__(self):
        # Global state
        self._buffer = b''
        self._messages = []

        self.reset_message()

    def reset_frame(self):
        self._opcode = None
        self._fin = False
        self._rsv = (False, False, False)
        self._masking_key = None
        self._payload_length = None
        self._payload = b''

        self._masked = False
        self._control = False

    def reset_message(self):
        self.reset_frame()
        self._message_opcode = None
        self._message_payload = None
        self._decoder = None

    def messages(self):
        while self._messages:
            yield self._messages.pop(0)

    def receive_bytes(self, data):
        self._buffer += data

        while True:
            result = self._process_frame()
            if result is not None:
                break

        if result is not False:
            return result

    def _process_frame(self):
        if not self._buffer:
            return False

        if self._buffer and self._opcode is None:
            flags_opcode = self._buffer[0]
            opcode = flags_opcode & 0x0f

            try:
                self._opcode = Opcode(opcode)
            except:
                self._messages.append(CloseReason.PROTOCOL_ERROR)
                return False

            self._control = bool(opcode & 0x08)

            if not self._control and self._opcode is not Opcode.CONTINUATION:
                if self._message_opcode is None:
                    self._message_opcode = self._opcode
                else:
                    self._messages.append(CloseReason.PROTOCOL_ERROR)
                    return False
            elif self._opcode is Opcode.CONTINUATION and self._message_opcode is None:
                self._messages.append(CloseReason.PROTOCOL_ERROR)
                return False

            self._fin = bool(flags_opcode & 0x80)
            self._rsv = (
                bool(flags_opcode & 0x40),
                bool(flags_opcode & 0x20),
                bool(flags_opcode & 0x10),
                )

            self._buffer = self._buffer[1:]

        if self._control and not self._fin:
            self._messages.append(CloseReason.PROTOCOL_ERROR)
            return False
        if True in self._rsv:
            self._messages.append(CloseReason.PROTOCOL_ERROR)
            return False

        if self._buffer and self._payload_length is None:
            self._payload_length = self._buffer[0]
            self._masked = bool(self._payload_length & 0x80)
            self._payload_length = self._payload_length & 0x7f
            self._buffer = self._buffer[1:]
        elif not self._buffer:
            return False

        if self._control and self._payload_length > 125:
            self._messages.append(CloseReason.PROTOCOL_ERROR)
            return False
        elif len(self._buffer) >= 2 and self._payload_length == 126:
            self._payload_length = struct.unpack('!H', self._buffer[:2])[0]
            self._buffer = self._buffer[2:]
        elif len(self._buffer) >= 8 and self._payload_length == 127:
            self._payload_length = struct.unpack('!Q', self._buffer[:8])[0]
            self._buffer = self._buffer[8:]

        if self._payload_length is None:
            return False

        if len(self._buffer) >= 4 and self._masked and self._masking_key is None:
            self._masking_key = itertools.cycle(self._buffer[:4])
            self._buffer = self._buffer[4:]

        if len(self._buffer) > self._payload_length:
            payload = self._buffer[:self._payload_length]
            self._buffer = self._buffer[self._payload_length:]
        else:
            payload = self._buffer
            self._buffer = b''

        if not payload and self._payload_length > 0:
            return False

        self._payload_length -= len(payload)

        if self._masked:
            payload = bytes(b ^ next(self._masking_key) for b in payload)

        if not self._control and self._message_opcode is Opcode.TEXT:
            if self._message_payload is None:
                self._message_payload = ''
                self._decoder = codecs.getincrementaldecoder('utf-8')()
            try:
                self._message_payload += self._decoder.decode(payload)
            except UnicodeDecodeError:
                self._messages.append(CloseReason.INVALID_FRAME_PAYLOAD_DATA)
                return False
        elif not self._control and self._message_opcode is Opcode.BINARY:
            if self._message_payload is None:
                self._message_payload = b''
            self._message_payload += payload

        self._payload += payload

        if self._fin and self._payload_length == 0:
            if self._opcode is Opcode.CLOSE:
                if len(self._payload) == 0:
                    self._payload = (CloseReason.NORMAL_CLOSURE, None)
                elif len(self._payload) == 1:
                    self._messages.append(CloseReason.PROTOCOL_ERROR)
                    return False
                else:
                    code = struct.unpack('!H', self._payload[:2])[0]
                    if code < 1000:
                        self._messages.append(CloseReason.PROTOCOL_ERROR)
                        return False
                    try:
                        code = CloseReason(code)
                    except:
                        pass
                    if code in LOCAL_ONLY_CLOSE_REASONS:
                        self._messages.append(CloseReason.PROTOCOL_ERROR)
                        return False
                    if not isinstance(code, CloseReason) and code < 3000:
                        self._messages.append(CloseReason.PROTOCOL_ERROR)
                        return False
                    try:
                        reason = self._payload[2:].decode('utf-8')
                    except UnicodeDecodeError:
                        self._messages.append(CloseReason.INVALID_FRAME_PAYLOAD_DATA)
                        return False
                    self._payload = (code, reason)

            opcode = self._opcode
            if opcode is Opcode.CONTINUATION:
                opcode = self._message_opcode
            payload = self._payload
            if opcode is Opcode.TEXT:
                payload = self._message_payload
                try:
                    payload += self._decoder.decode(b'', True)
                except UnicodeDecodeError:
                    self._messages.append(CloseReason.INVALID_FRAME_PAYLOAD_DATA)
                    return False
            elif opcode is Opcode.BINARY:
                payload = self._message_payload

            message = Message(opcode, rsv=self._rsv, payload=payload)
            self._messages.append(message)

            if not self._control:
                self.reset_message()
            else:
                self.reset_frame()
        elif self._payload_length == 0:
            self.reset_frame()

        return None

class WSConnection(object):
    def __init__(self, host, resource, protocols=None, extensions=None):
        self.host = host
        self.resource = resource

        self.protocols = []
        self.extensions = []

        self.version = b'13'

        self._state = ConnectionState.CONNECTING
        self._close_reason = None

        self._nonce = None
        self._outgoing = b''
        self._events = []
        self._deserializer = MessageDeserializer()

        self._upgrade_connection = h11.Connection(h11.CLIENT)

    def initiate_connection(self):
        self._generate_nonce()

        headers = {
            b"Host": self.host.encode('ascii'),
            b"Upgrade": b'WebSocket',
            b"Connection": b'Upgrade',
            b"Sec-WebSocket-Key": self._nonce,
            b"Sec-WebSocket-Version": self.version,
        }
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
            self._deserializer.receive_bytes(data)

    def _process_upgrade(self, data):
        self._upgrade_connection.receive_data(data)
        event = self._upgrade_connection.next_event()
        if event is h11.NEED_DATA:
            self._incoming = b''
            return
        elif isinstance(event, h11.InformationalResponse):
            data = self._upgrade_connection.trailing_data[0]
            return self._establish_connection(event), data

    def events(self):
        while self._events:
            yield self._events.pop(0)

        for message in self._deserializer.messages():
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
            f.mask()
            print("SENDING: %r" % f)
        self._outgoing += b''.join(f.serialize() for f in frames)

    def _establish_connection(self, event):
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

        accept_token = headers[b'sec-websocket-accept']
        accept_token = self._nonce + ACCEPT_GUID
        accept_token = hashlib.sha1(accept_token).digest()
        accept_token = base64.b64encode(accept_token)
        if headers[b'sec-websocket-accept'] != accept_token:
            return ConnectionFailed(CloseReason.PROTOCOL_ERROR,
                                    "Bad accept token")

        subprotocol = headers.get(b'sec-websocket-protocol', None)
        extensions = headers.get(b'sec-websocket-exceptions', None)
        if extensions:
            extensions = [e.strip() for e in extensions.split(b',')]

        self._state = ConnectionState.OPEN
        return ConnectionEstablished(subprotocol, extensions)

if __name__ == '__main__':
    c = WSConnection()
    c.host = 'localhost'
    c.port = 9001
    c.resource = '/ws'
    c.initiate_connection()

    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(('localhost', 9001))
    while True:
        data = c.data_to_send()
        s.send(data)
        data = s.recv(65535)
        events = c.receive_data(data)
        if events and isinstance(events[0], ConnectionEstablished):
            f = TextMessage("There is no spong.")
            c.send_message(f)
