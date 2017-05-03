# -*- coding: utf-8 -*-
"""
wsproto/frame_protocol
~~~~~~~~~~~~~~

WebSocket frame protocol implementation.
"""

import os
import itertools
import struct
from codecs import getincrementaldecoder
from collections import namedtuple

from enum import Enum, IntEnum

try:
    from wsaccel.xormask import XorMaskerSimple
except ImportError:
    class XorMaskerSimple:
        def __init__(self, masking_key):
            self._maskbytes = itertools.cycle(masking_key)

        def process(self, data):
            maskbytes = self._maskbytes
            return bytes(b ^ next(maskbytes) for b in data)


class XorMaskerNull:
    def process(self, data):
        return data


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
    TLS_HANDSHAKE_FAILED = 1015


# RFC 6455, Section 7.4.1 - Defined Status Codes
LOCAL_ONLY_CLOSE_REASONS = (
    CloseReason.NO_STATUS_RCVD,
    CloseReason.ABNORMAL_CLOSURE,
    CloseReason.TLS_HANDSHAKE_FAILED,
)


NULL_MASK = struct.pack("!I", 0)


class ParseFailed(Exception):
    def __init__(self, msg, code=CloseReason.PROTOCOL_ERROR):
        super().__init__(msg)
        self.code = code


Header = namedtuple("Header", "fin rsv opcode payload_len masking_key".split())


Frame = namedtuple("Frame",
                   "opcode payload frame_finished message_finished".split())


def _truncate_utf8(data, nbytes):
    if len(data) <= nbytes:
        return data
    else:
        # Truncate
        data = data[:nbytes]
        # But we might have cut a codepoint in half, in which case we want to
        # discard the partial character so the data is at least
        # well-formed. This is a little inefficient since it processes the
        # whole message twice when in theory we could just peek at the last
        # few characters, but since this is only used for close messages (max
        # length = 125 bytes) it really doesn't matter.
        data = data.decode("utf-8", errors="ignore").encode("utf-8")
        return data

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
        self._buffer = bytearray()
        self._parse_more = self.parse_more_gen()

        self._outbound_opcode = None

    def _consume_at_most(self, nbytes):
        if not nbytes:
            return bytearray()
        while not self._buffer:
            yield
        data = self._buffer[:nbytes]
        # In CPython 3.4+, del[:n] is amortized O(n), *not* quadratic
        del self._buffer[:nbytes]
        return data

    def _consume_exactly(self, nbytes):
        while len(self._buffer) < nbytes:
            yield
        return (yield from self._consume_at_most(nbytes))

    def _parse_header(self):
        # returns a Header object
        (fin_rsv_opcode,) = yield from self._consume_exactly(1)
        fin = bool(fin_rsv_opcode & 0x80)
        rsv = (bool(fin_rsv_opcode & 0x40),
               bool(fin_rsv_opcode & 0x20),
               bool(fin_rsv_opcode & 0x10))
        opcode = fin_rsv_opcode & 0x0f
        try:
            opcode = Opcode(opcode)
        except ValueError:
            raise ParseFailed("Invalid opcode {:#x}".format(opcode))

        if opcode.iscontrol() and not fin:
            raise ParseFailed("Invalid attempt to fragment control frame")

        (mask_len,) = yield from self._consume_exactly(1)
        has_mask = bool(mask_len & 0x80)
        payload_len = mask_len & 0x7f

        if opcode.iscontrol() and payload_len > 125:
            raise ParseFailed("Control frame with payload len > 125")
        if payload_len == 126:
            data = yield from self._consume_exactly(2)
            (payload_len,) = struct.unpack("!H", data)
            if payload_len <= 125:
                raise ParseFailed(
                    "Payload length used 2 bytes when 1 would have sufficed")
        elif payload_len == 127:
            data = yield from self._consume_exactly(8)
            (payload_len,) = struct.unpack("!Q", data)
            if payload_len < 2 ** 16:
                raise ParseFailed(
                    "Payload length used 8 bytes when 2 would have sufficed")
            if payload_len >> 63:
                # I'm not sure why this is illegal, but that's what the RFC
                # says, so...
                raise ParseFailed("8-byte payload length with non-zero MSB")

        for extension in self.extensions:
            result = extension.frame_inbound_header(
                self, opcode, rsv, payload_len)
            if result is not None:
                raise ParseFailed("error in extension", result)
        if not self.extensions and True in rsv:
            raise ParseFailed("Reserved bit set unexpectedly")

        if has_mask and self.client:
            raise ParseFailed("client received unexpected masked frame")
        if not has_mask and not self.client:
            raise ParseFailed("server received unexpected unmasked frame")
        if has_mask:
            masking_key = yield from self._consume_exactly(4)
        else:
            masking_key = NULL_MASK

        return Header(fin, rsv, opcode, payload_len, masking_key)

    def _process_payload_chunk(self, masker, data):
        data = masker.process(data)
        for extension in self.extensions:
            data = extension.frame_inbound_payload_data(self, data)
            if isinstance(data, CloseReason):
                raise ParseFailed("error in extension", data)
        return data

    def _process_payload_complete(self, fin):
        final = bytearray()
        for extension in self.extensions:
            result = extension.frame_inbound_complete(self, fin)
            if isinstance(result, CloseReason):
                raise ParseFailed("error in extension", result)
            if result is not None:
                final += result
        return final

    def _process_CLOSE_payload(self, data):
        if len(data) == 0:
            # "If this Close control frame contains no status code, _The
            # WebSocket Connection Close Code_ is considered to be 1005"
            return (CloseReason.NO_STATUS_RCVD, "")
        elif len(data) == 1:
            raise ParseFailed("CLOSE with 1 byte payload")
        else:
            (code,) = struct.unpack("!H", data[:2])
            if code < 1000:
                raise ParseFailed("CLOSE with invalid code")
            try:
                code = CloseReason(code)
            except ValueError:
                pass
            if code in LOCAL_ONLY_CLOSE_REASONS:
                raise ParseFailed(
                    "remote CLOSE with local-only reason")
            if not isinstance(code, CloseReason) and code < 3000:
                raise ParseFailed(
                    "CLOSE with unknown reserved code")
            try:
                reason = data[2:].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ParseFailed(
                    "Error decoding CLOSE reason: " + str(exc),
                    CloseReason.INVALID_FRAME_PAYLOAD_DATA)
            return (code, reason)

    def parse_more_gen(self):
        # Consume as much as we can from self._buffer, yielding events, and
        # then yield None when we need more data. Or raise ParseFailed.

        # XX FIXME this should probably be refactored so that we never see
        # disabled extensions in the first place...
        self.extensions = [ext for ext in self.extensions if ext.enabled()]

        unfinished_message_opcode = None
        unfinished_message_decoder = None
        while True:
            header = yield from self._parse_header()

            if unfinished_message_opcode is None:
                if header.opcode is Opcode.CONTINUATION:
                    raise ParseFailed("unexpected CONTINUATION")
                elif not header.opcode.iscontrol():
                    # Neither CONTINUATION nor control -> starting a new
                    # unfinished message
                    unfinished_message_opcode = header.opcode
            else:
                # We're in the middle of an unfinished message
                if (not header.opcode.iscontrol()
                      and header.opcode is not Opcode.CONTINUATION):
                    raise ParseFailed("expected CONTINUATION, not {!r}"
                                      .format(header.opcode))

            effective_opcode = header.opcode
            if effective_opcode is Opcode.CONTINUATION:
                effective_opcode = unfinished_message_opcode

            if header.masking_key == NULL_MASK:
                masker = XorMaskerNull()
            else:
                masker = XorMaskerSimple(header.masking_key)

            if (unfinished_message_opcode is Opcode.TEXT
                  and unfinished_message_decoder is None):
                unfinished_message_decoder = getincrementaldecoder("utf-8")()

            remaining = header.payload_len
            frame_finished = False
            while not frame_finished:
                # For control frames, we collect all the data and return it as
                # a single lump. For message frames, we stream out chunks as
                # they arrive, to minimize buffering.
                if effective_opcode.iscontrol():
                    data = yield from self._consume_exactly(remaining)
                else:
                    data = yield from self._consume_at_most(remaining)
                remaining -= len(data)
                frame_finished = (remaining == 0)
                message_finished = (frame_finished and header.fin)

                data = self._process_payload_chunk(masker, data)
                if frame_finished:
                    data += self._process_payload_complete(header.fin)

                if effective_opcode is Opcode.CLOSE:
                    data = self._process_CLOSE_payload(data)

                if not effective_opcode.iscontrol():
                    if unfinished_message_decoder is not None:
                        try:
                            data = unfinished_message_decoder.decode(
                                data, message_finished)
                        except UnicodeDecodeError as exc:
                            raise ParseFailed(
                                str(exc),
                                CloseReason.INVALID_FRAME_PAYLOAD_DATA)
                    # This isn't a control, so if this message is finished
                    # then the unfinished message is also finished.
                    if message_finished:
                        unfinished_message_opcode = None
                        unfinished_message_decoder = None

                yield Frame(
                     effective_opcode, data, frame_finished, message_finished)

            if effective_opcode is Opcode.CLOSE:
                break

    def receive_bytes(self, data):
        self._buffer += data

    def received_frames(self):
        for event in self._parse_more:
            if event is None:
                break
            else:
                yield event

    def close(self, code=None, reason=None):
        payload = bytearray()
        if code is None and reason is not None:
            raise TypeError("cannot specify a reason without a code")
        if code in LOCAL_ONLY_CLOSE_REASONS:
            code = CloseReason.NORMAL_CLOSURE
        if code is not None:
            payload += struct.pack('!H', code)
            if reason is not None:
                payload += _truncate_utf8(reason.encode('utf-8'), 123)

        return self._serialize_frame(Opcode.CLOSE, payload)

    def pong(self, payload=None):
        return self._serialize_frame(Opcode.PONG, payload)

    def send_data(self, payload=b'', fin=True):
        if isinstance(payload, (bytes, bytearray, memoryview)):
            opcode = Opcode.BINARY
        elif isinstance(payload, str):
            opcode = Opcode.TEXT
            payload = payload.encode('utf-8')

        if self._outbound_opcode is None:
            self._outbound_opcode = opcode
        elif self._outbound_opcode is not opcode:
            raise TypeError('Data type mismatch inside message')
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

            rsv, payload = extension.frame_outbound(
                self, opcode, rsv, payload, fin)

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
            if opcode.iscontrol():
                raise ValueError("payload too long for control frame")
            if quad_payload:
                header += struct.pack('!Q', second_payload)
            else:
                header += struct.pack('!H', second_payload)

        if self.client:
            # "The masking key is a 32-bit value chosen at random by the
            # client.  When preparing a masked frame, the client MUST pick a
            # fresh masking key from the set of allowed 32-bit values.  The
            # masking key needs to be unpredictable; thus, the masking key
            # MUST be derived from a strong source of entropy, and the masking
            # key for a given frame MUST NOT make it simple for a server/proxy
            # to predict the masking key for a subsequent frame.  The
            # unpredictability of the masking key is essential to prevent
            # authors of malicious applications from selecting the bytes that
            # appear on the wire."
            #   -- https://tools.ietf.org/html/rfc6455#section-5.3
            masking_key = os.urandom(4)
            masker = XorMaskerSimple(masking_key)
            return header + masking_key + masker.process(payload)
        else:
            return header + payload
