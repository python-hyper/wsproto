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
        self._frames = []
        self._state = self.State.HEADER

        self._outbound_opcode = None

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

    def received_frames(self):
        while self._frames:
            yield self._frames.pop(0)

    def add_message_payload(self, payload, fin=False):
        if self._message_opcode is Opcode.TEXT:
            if self._message_payload is None:
                self._message_payload = ''
                self._decoder = codecs.getincrementaldecoder('utf-8')()
            try:
                self._message_payload += self._decoder.decode(payload, fin)
            except UnicodeDecodeError:
                self._frames.append(CloseReason.INVALID_FRAME_PAYLOAD_DATA)
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
            self._process_fin_rsv_opcode()

        if self._opcode is None:
            return self.State.HEADER

        state = self._process_payload_length()
        if state is not None:
            return state

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
                    self._frames.append(CloseReason.PROTOCOL_ERROR)
                    return self.State.FAILED
            return self.State.PAYLOAD

        return self.State.HEADER

    def _process_fin_rsv_opcode(self):
        flags_opcode = self._buffer[0]
        opcode = flags_opcode & 0x0f

        try:
            self._opcode = Opcode(opcode)
        except:
            self._frames.append(CloseReason.PROTOCOL_ERROR)
            return self.State.FAILED

        if self._message_opcode is None:
            if self._opcode is Opcode.CONTINUATION:
                self._frames.append(CloseReason.PROTOCOL_ERROR)
                return self.State.FAILED
            self._message_opcode = self._opcode
        else:
            if self._opcode is not Opcode.CONTINUATION and \
              not self._opcode.iscontrol():
                self._frames.append(CloseReason.PROTOCOL_ERROR)
                return self.State.FAILED

        self._fin = bool(flags_opcode & 0x80)

        if self._opcode.iscontrol() and not self._fin:
            self._frames.append(CloseReason.PROTOCOL_ERROR)
            return self.State.FAILED

        self._rsv = (
            bool(flags_opcode & 0x40),
            bool(flags_opcode & 0x20),
            bool(flags_opcode & 0x10),
        )

        self._buffer = self._buffer[1:]

    def _process_payload_length(self):
        if self._buffer and self._payload_length is None:
            self._payload_length = self._buffer[0]
            self._masked = bool(self._payload_length & 0x80)
            self._payload_length = self._payload_length & 0x7f
            self._buffer = self._buffer[1:]
        elif not self._buffer:
            return self.State.HEADER

        if self._opcode.iscontrol() and self._payload_length > 125:
            self._frames.append(CloseReason.PROTOCOL_ERROR)
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

    def _process_frame_payload(self):
        if self._masked and self._masking_key is None:
            state = self._process_masking_key()
            if state is not None:
                return state

        payload = self._consume_payload()

        if not payload and self._payload_length > 0:
            return self.State.PAYLOAD

        self._payload_length -= len(payload)

        if self._masked:
            payload = bytes(b ^ next(self._masking_key) for b in payload)

        payload = self._process_extensions(payload)

        if not self._opcode.iscontrol():
            result = self.add_message_payload(payload)
            if result is not None:
                return result

        self._payload += payload

        if self._payload_length == 0:
            return self.State.FRAME_COMPLETE

        return self.State.PAYLOAD

    def _process_masking_key(self):
        if len(self._buffer) >= 4:
            self._masking_key = itertools.cycle(self._buffer[:4])
            self._buffer = self._buffer[4:]

        if self._masked and not self._masking_key:
            return self.State.PAYLOAD

    def _consume_payload(self):
        if len(self._buffer) > self._payload_length:
            payload = self._buffer[:self._payload_length]
            self._buffer = self._buffer[self._payload_length:]
        else:
            payload = self._buffer
            self._buffer = b''

        return payload

    def _process_extensions(self, payload):
        for extension in self.extensions:
            if not extension.enabled():
                continue
            payload = extension.frame_inbound_payload_data(self, payload)
            if isinstance(payload, CloseReason):
                self._frames.append(payload)
                return self.State.FAILED

        return payload

    def _process_frame(self):
        if self._fin and self._payload_length == 0:
            if self._opcode is Opcode.CLOSE:
                state = self._process_close_frame()
                if state is not None:
                    return state

            final = self._process_extensions_final()
            if final is self.State.FAILED:
                return final

            result = self.add_message_payload(final, self._fin)
            if result is not None:
                return result

            opcode = self._opcode
            if opcode is Opcode.CONTINUATION:
                opcode = self._message_opcode
            payload = self._payload
            if not opcode.iscontrol():
                payload = self._message_payload

            self._frames.append((opcode, payload, self._fin))

            if not self._opcode.iscontrol():
                self.reset_message()
            else:
                self.reset_frame()
        elif self._payload_length == 0:
            self.reset_frame()

        return self.State.HEADER

    def _process_close_frame(self):
        if len(self._payload) == 0:
            self._payload = (CloseReason.NORMAL_CLOSURE, None)
        elif len(self._payload) == 1:
            self._frames.append(CloseReason.PROTOCOL_ERROR)
            return self.State.FAILED
        else:
            code = struct.unpack('!H', self._payload[:2])[0]
            if code < 1000:
                self._frames.append(CloseReason.PROTOCOL_ERROR)
                return self.State.FAILED
            try:
                code = CloseReason(code)
            except:
                pass
            if code in LOCAL_ONLY_CLOSE_REASONS:
                self._frames.append(CloseReason.PROTOCOL_ERROR)
                return self.State.FAILED
            if not isinstance(code, CloseReason) and code < 3000:
                self._frames.append(CloseReason.PROTOCOL_ERROR)
                return self.State.FAILED
            try:
                reason = self._payload[2:].decode('utf-8')
            except UnicodeDecodeError:
                self._frames.append(CloseReason.INVALID_FRAME_PAYLOAD_DATA)
                return self.State.FAILED
            self._payload = (code, reason)

    def _process_extensions_final(self):
        final = b''

        for extension in self.extensions:
            if not extension.enabled():
                continue
            result = extension.frame_inbound_complete(self, self._fin)
            if isinstance(result, CloseReason):
                self._frames.append(result)
                return self.State.FAILED
            if result is not None:
                final += result

        return final

    def close(self, code=None, reason=None):
        payload = b''
        if code:
            payload += struct.pack('!H', code)
        if reason is not None:
            payload += reason.encode('utf-8')

        return self._serialize_frame(Opcode.CLOSE, payload)

    def pong(self, payload=None):
        return self._serialize_frame(Opcode.PONG, payload)

    def send_data(self, payload=b'', fin=True):
        if isinstance(payload, bytes):
            opcode = Opcode.BINARY
        elif isinstance(payload, str):
            opcode = Opcode.TEXT
            payload = payload.encode('utf-8')

        if self._outbound_opcode is None:
            self._outbound_opcode = opcode
        elif self._outbound_opcode is not opcode:
            raise Exception('Data type mismatch inside message')
        else:
            opcode = Opcode.CONTINUATION

        if fin:
            self._outbound_opcode = None

        return self._serialize_frame(opcode, payload, fin)

    def _serialize_frame(self, opcode, payload=b'', fin=True):
        rsv = (False, False, False)
        for extension in reversed(self.extensions):
            if not extension.enabled():
                continue

            rsv, payload = extension.frame_outbound(self, opcode, rsv, payload)

        fin_rsv = 0
        for bit in rsv:
            fin_rsv <<= 1
            fin_rsv |= int(bit)
        fin_rsv |= (int(fin) << 3)
        fin_rsv_opcode = fin_rsv << 4 | opcode

        payload_length = len(payload)
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

        if self.client:
            first_payload |= 1 << 7

        header = bytes([fin_rsv_opcode, first_payload])
        if second_payload is not None:
            if quad_payload:
                header += struct.pack('!Q', second_payload)
            else:
                header += struct.pack('!H', second_payload)

        if self.client:
            masking_key = bytes(random_byte() for x in range(0, 4))
            maskbytes = itertools.cycle(masking_key)
            return header + masking_key + \
                bytes(b ^ next(maskbytes) for b in payload)
        else:
            return header + payload
