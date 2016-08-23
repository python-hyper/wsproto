# -*- coding: utf-8 -*-
"""
wsproto/frame_protocol
~~~~~~~~~~~~~~

WebSocket frame protocol implementation.
"""

import codecs
import itertools
import random
import struct

from enum import Enum, IntEnum

import h11

from .events import (
    ConnectionRequested, ConnectionEstablished, ConnectionClosed,
    ConnectionFailed, BinaryMessageReceived, TextMessageReceived
)


# RFC6455, Section 1.3 - Opening Handshake
ACCEPT_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# RFC6455, Section 5.2 - Base Framing Protocol
MAX_FRAME_PAYLOAD = 2 ** 64


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


def random_byte():
    return random.getrandbits(8)


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
            self.masking_key = bytes(random_byte() for x in range(0, 4))

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


class FrameProtocol(object):
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
        if self._masked and self._masking_key is None:
            if len(self._buffer) >= 4:
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

