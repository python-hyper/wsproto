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
import zlib

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

    def iscontrol(self):
        return bool(self & 0x08)

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


class Extension(object):
    name = None

    def enabled(self):
        return False

    def offer(self, connection):
        return None

    def accept(self, connection, offer):
        return None

    def frame_inbound_header(self, proto, opcode, rsv, payload_length):
        pass

    def frame_inbound_payload_data(self, proto, data):
        return data

    def frame_inbound_complete(self, proto, fin):
        pass

    def frame_outbound(self, proto, opcode, rsv, data):
        return (opcode, rsv, data)


class PerMessageDeflate(Extension):
    name = 'permessage-deflate'

    def __init__(self, client_no_context_takeover=False,
                 client_max_window_bits=15, server_no_context_takeover=False,
                 server_max_window_bits=15):
        self.client_no_context_takeover = client_no_context_takeover
        self.client_max_window_bits = client_max_window_bits
        self.server_no_context_takeover = server_no_context_takeover
        self.server_max_window_bits = server_max_window_bits

        self._compressor = None
        self._decompressor = None
        self._inbound_compressed = None

        self._enabled = False

    def enabled(self):
        return self._enabled

    def offer(self, connection):
        parameters = [
            'client_max_window_bits=%d' % self.client_max_window_bits,
            'server_max_window_bits=%d' % self.server_max_window_bits,
            ]

        if self.client_no_context_takeover:
            parameters.append('client_no_context_takeover')
        if self.server_no_context_takeover:
            parameters.append('server_no_context_takeover')

        return '; '.join(parameters)

    def finalize(self, connection, offer):
        bits = [b.strip() for b in offer.split(';')]
        for bit in bits[1:]:
            if bit.startswith('client_no_context_takeover'):
                self.client_no_context_takeover = True
            elif bit.startswith('server_no_context_takeover'):
                self.server_no_context_takeover = True
            elif bit.startswith('client_max_window_bits'):
                self.client_max_window_bits = int(bit.split('=', 1)[1].strip())
            elif bit.startswith('server_max_window_bits'):
                self.server_max_window_bits = int(bit.split('=', 1)[1].strip())

        self._enabled = True

    def accept(self, connection, offer):
        client_max_window_bits = None
        server_max_window_bits = None

        bits = [b.strip() for b in offer.split(';')]
        for bit in bits[1:]:
            if bit.startswith('client_no_context_takeover'):
                self.client_no_context_takeover = True
            elif bit.startswith('server_no_context_takeover'):
                self.server_no_context_takeover = True
            elif bit.startswith('client_max_window_bits'):
                if '=' in bit:
                    client_max_window_bits = int(bit.split('=', 1)[1].strip())
                else:
                    client_max_window_bits = self.client_max_window_bits
            elif bit.startswith('server_max_window_bits'):
                if '=' in bit:
                    server_max_window_bits = int(bit.split('=', 1)[1].strip())
                else:
                    server_max_window_bits = self.server_max_window_bits

        self._enabled = True

        parameters = []

        if self.client_no_context_takeover:
            parameters.append('client_no_context_takeover')
        if client_max_window_bits is not None:
            parameters.append('client_max_window_bits=%d' % \
                              client_max_window_bits)
            self.client_max_window_bits = client_max_window_bits
        if self.server_no_context_takeover:
            parameters.append('server_no_context_takeover')
        if server_max_window_bits is not None:
            parameters.append('server_max_window_bits=%d' % \
                              server_max_window_bits)
            self.server_max_window_bits = server_max_window_bits

        return '; '.join(parameters)

    def frame_inbound_header(self, proto, opcode, rsv, payload_length):
        if True in rsv[1:]:
            return CloseReason.PROTOCOL_ERROR
        elif rsv[0] and opcode.iscontrol():
            return CloseReason.PROTOCOL_ERROR
        elif rsv[0] and opcode is Opcode.CONTINUATION:
            return CloseReason.PROTOCOL_ERROR

        if self._inbound_compressed is None:
            self._inbound_compressed = rsv[0]
            if self._inbound_compressed:
                if proto.client:
                    bits = self.server_max_window_bits
                else:
                    bits = self.client_max_window_bits
                if self._decompressor is None:
                    self._decompressor = zlib.decompressobj(-bits)

    def frame_inbound_payload_data(self, proto, data):
        if not self._inbound_compressed:
            return data

        try:
            return self._decompressor.decompress(data)
        except zlib.error:
            return CloseReason.INVALID_FRAME_PAYLOAD_DATA

    def frame_inbound_complete(self, proto, fin):
        if not fin or not self._inbound_compressed:
            return

        try:
            data = self._decompressor.decompress(b'\x00\x00\xff\xff')
            data += self._decompressor.flush()
            if isinstance(data, CloseReason):
                return result
        except zlib.error:
            return CloseReason.INVALID_FRAME_PAYLOAD_DATA

        if fin:
            if proto.client:
                no_context_takeover = self.server_no_context_takeover
            else:
                no_context_takeover = self.client_no_context_takeover

            if no_context_takeover:
                self._decompressor = None

            self._inbound_compressed = None

        return data

    def frame_outbound(self, proto, opcode, rsv, data):
        if opcode not in (Opcode.TEXT, Opcode.BINARY):
            return (opcode, rsv, data)

        if self._compressor is None:
            if proto.client:
                bits = self.client_max_window_bits
            else:
                bits = self.server_max_window_bits
            self._compressor = zlib.compressobj(wbits=-bits)

        data = self._compressor.compress(data)
        data += self._compressor.flush(zlib.Z_SYNC_FLUSH)
        data = data[:-4]

        rsv = list(rsv)
        rsv[0] = True

        if proto.client:
            no_context_takeover = self.client_no_context_takeover
        else:
            no_context_takeover = self.server_no_context_takeover

        if no_context_takeover:
            self._compressor = None

        return (opcode, rsv, data)

    def __repr__(self):
        descr = ['client_max_window_bits=%d' % self.client_max_window_bits]
        if self.client_no_context_takeover:
            descr.append('client_no_context_takeover')
        descr.append('server_max_window_bits=%d' % self.server_max_window_bits)
        if self.server_no_context_takeover:
            descr.append('server_no_context_takeover')

        descr = '; '.join(descr)

        return '<%s %s>' % (self.__class__.__name__, descr)

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
            rsv <<= 1
            rsv |= int(bit)
        fin_rsv = (int(self.fin) << 3) | rsv
        fin_rsv_opcode = fin_rsv << 4 | self.opcode

        if self.opcode is Opcode.CLOSE:
            code, reason = self.payload
            if reason is not None:
                reason = reason.encode('utf-8')
            else:
                reason = b''
            self.payload = struct.pack('!H', code) + reason

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
    class State(Enum):
        HEADER = 1
        PAYLOAD = 2
        FRAME_COMPLETE = 3
        FAILED = 4

    def __init__(self, client, extensions):
        self.client = client
        self.extensions = extensions

        # Global state
        self._buffer = b''
        self._messages = []
        self._state = self.State.HEADER

        self.reset_message()

    def reset_frame(self):
        self._opcode = None
        self._fin = False
        self._rsv = (False, False, False)
        self._masking_key = None
        self._payload_length = None
        self._payload = b''
        self._masked = False

    def reset_message(self):
        self.reset_frame()
        self._message_opcode = None
        self._message_payload = None
        self._decoder = None

    def messages(self):
        while self._messages:
            yield self._messages.pop(0)

    def add_message_payload(self, payload, fin=False):
        if self._message_opcode is Opcode.TEXT:
            if self._message_payload is None:
                self._message_payload = ''
                self._decoder = codecs.getincrementaldecoder('utf-8')()
            try:
                self._message_payload += self._decoder.decode(payload, fin)
            except UnicodeDecodeError:
                self._messages.append(CloseReason.INVALID_FRAME_PAYLOAD_DATA)
                return self.State.FAILED
        elif self._message_opcode is Opcode.BINARY:
            if self._message_payload is None:
                self._message_payload = b''
            self._message_payload += payload

    def receive_bytes(self, data):
        self._buffer += data

        while self._buffer:
            available_bytes = len(self._buffer)

            if self._state is self.State.HEADER:
                self._state = self._process_frame_header()

            if self._state is self.State.PAYLOAD:
                self._state = self._process_frame_payload()

            if self._state is self.State.FRAME_COMPLETE:
                self._state = self._process_frame()

            if self._state is self.State.FAILED:
                break

            if len(self._buffer) == available_bytes:
                break

    def _process_frame_header(self):
        if self._buffer and self._opcode is None:
            flags_opcode = self._buffer[0]
            opcode = flags_opcode & 0x0f

            try:
                self._opcode = Opcode(opcode)
            except:
                self._messages.append(CloseReason.PROTOCOL_ERROR)
                return self.State.FAILED

            if not self._opcode.iscontrol() and self._opcode is not Opcode.CONTINUATION:
                if self._message_opcode is None:
                    self._message_opcode = self._opcode
                else:
                    self._messages.append(CloseReason.PROTOCOL_ERROR)
                    return self.State.FAILED
            elif self._opcode is Opcode.CONTINUATION and self._message_opcode is None:
                self._messages.append(CloseReason.PROTOCOL_ERROR)
                return self.State.FAILED

            self._fin = bool(flags_opcode & 0x80)
            self._rsv = (
                bool(flags_opcode & 0x40),
                bool(flags_opcode & 0x20),
                bool(flags_opcode & 0x10),
                )

            self._buffer = self._buffer[1:]

        if self._opcode.iscontrol() and not self._fin:
            self._messages.append(CloseReason.PROTOCOL_ERROR)
            return self.State.FAILED

        if self._buffer and self._payload_length is None:
            self._payload_length = self._buffer[0]
            self._masked = bool(self._payload_length & 0x80)
            self._payload_length = self._payload_length & 0x7f
            self._buffer = self._buffer[1:]
        elif not self._buffer:
            return self.State.HEADER

        if self._opcode.iscontrol() and self._payload_length > 125:
            self._messages.append(CloseReason.PROTOCOL_ERROR)
            return self.State.FAILED
        elif self._payload_length == 126:
            if len(self._buffer) < 2:
                return self.State.HEADER
            self._payload_length = struct.unpack('!H', self._buffer[:2])[0]
            self._buffer = self._buffer[2:]
        elif self._payload_length == 127:
            if len(self._buffer) < 8:
                return self.State.HEADER
            self._payload_length = struct.unpack('!Q', self._buffer[:8])[0]
            self._buffer = self._buffer[8:]

        if self._payload_length is not None:
            extension_ran = False
            for extension in self.extensions:
                if not extension.enabled():
                    continue
                extension_ran = True
                result = extension.frame_inbound_header(self, self._opcode,
                                                        self._rsv,
                                                        self._payload_length)
                if result is not None:
                    return result
            if not extension_ran:
                if True in self._rsv:
                    self._messages.append(CloseReason.PROTOCOL_ERROR)
                    return self.State.FAILED
            return self.State.PAYLOAD

        return self.State.HEADER

    def _process_frame_payload(self):
        if len(self._buffer) >= 4 and self._masked and self._masking_key is None:
            self._masking_key = itertools.cycle(self._buffer[:4])
            self._buffer = self._buffer[4:]

        if self._masked and not self._masking_key:
            return self.State.PAYLOAD

        if len(self._buffer) > self._payload_length:
            payload = self._buffer[:self._payload_length]
            self._buffer = self._buffer[self._payload_length:]
        else:
            payload = self._buffer
            self._buffer = b''

        if not payload and self._payload_length > 0:
            return self.State.PAYLOAD

        self._payload_length -= len(payload)

        if self._masked:
            payload = bytes(b ^ next(self._masking_key) for b in payload)

        for extension in self.extensions:
            if not extension.enabled():
                continue
            payload = extension.frame_inbound_payload_data(self, payload)
            if isinstance(payload, CloseReason):
                self._messages.append(payload)
                return self.State.FAILED

        if not self._opcode.iscontrol():
            result = self.add_message_payload(payload)
            if result is not None:
                return result

        self._payload += payload

        if self._payload_length == 0:
            return self.State.FRAME_COMPLETE

        return self.State.PAYLOAD

    def _process_frame(self):
        if self._fin and self._payload_length == 0:
            if self._opcode is Opcode.CLOSE:
                if len(self._payload) == 0:
                    self._payload = (CloseReason.NORMAL_CLOSURE, None)
                elif len(self._payload) == 1:
                    self._messages.append(CloseReason.PROTOCOL_ERROR)
                    return self.State.FAILED
                else:
                    code = struct.unpack('!H', self._payload[:2])[0]
                    if code < 1000:
                        self._messages.append(CloseReason.PROTOCOL_ERROR)
                        return self.State.FAILED
                    try:
                        code = CloseReason(code)
                    except:
                        pass
                    if code in LOCAL_ONLY_CLOSE_REASONS:
                        self._messages.append(CloseReason.PROTOCOL_ERROR)
                        return self.State.FAILED
                    if not isinstance(code, CloseReason) and code < 3000:
                        self._messages.append(CloseReason.PROTOCOL_ERROR)
                        return self.State.FAILED
                    try:
                        reason = self._payload[2:].decode('utf-8')
                    except UnicodeDecodeError:
                        self._messages.append(CloseReason.INVALID_FRAME_PAYLOAD_DATA)
                        return self.State.FAILED
                    self._payload = (code, reason)

            final = b''

            for extension in self.extensions:
                if not extension.enabled():
                    continue
                result = extension.frame_inbound_complete(self, self._fin)
                if isinstance(result, CloseReason):
                    self._messages.append(result)
                    return self.State.FAILED
                if result is not None:
                    final += result

            result = self.add_message_payload(final, self._fin)
            if result is not None:
                return result

            opcode = self._opcode
            if opcode is Opcode.CONTINUATION:
                opcode = self._message_opcode
            payload = self._payload
            if not opcode.iscontrol():
                payload = self._message_payload

            message = Message(opcode, rsv=self._rsv, payload=payload)
            self._messages.append(message)

            if not self._opcode.iscontrol():
                self.reset_message()
            else:
                self.reset_frame()
        elif self._payload_length == 0:
            self.reset_frame()

        return self.State.HEADER

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
        self._proto = MessageDeserializer(self.client, self.extensions)

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
        self._upgrade_connection.receive_data(data)
        event = self._upgrade_connection.next_event()
        if event is h11.NEED_DATA:
            self._incoming = b''
        elif self.client and isinstance(event, h11.InformationalResponse):
            data = self._upgrade_connection.trailing_data[0]
            return self._establish_client_connection(event), data
        elif not self.client and isinstance(event, h11.Request):
            return self._process_connection_request(event), None

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
