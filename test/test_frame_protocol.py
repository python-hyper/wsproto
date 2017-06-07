# -*- coding: utf-8 -*-

import itertools
from binascii import unhexlify
from codecs import getincrementaldecoder
import struct

import pytest

import wsproto.frame_protocol as fp
import wsproto.extensions as wpext


class FakeValidator(object):
    def __init__(self):
        self.validated = b''

        self.valid = True
        self.ends_on_complete = True
        self.octet = 0
        self.code_point = 0

    def validate(self, data):
        self.validated += data
        return (self.valid, self.ends_on_complete, self.octet,
                self.code_point)


class TestBuffer(object):
    def test_consume_at_most_zero_bytes(self):
        buf = fp.Buffer(b'xxyyy')
        assert buf.consume_at_most(0) == bytearray()

    def test_consume_at_most_with_no_data(self):
        buf = fp.Buffer()
        assert buf.consume_at_most(1) == bytearray()

    def test_consume_at_most_with_sufficient_data(self):
        buf = fp.Buffer(b'xx')
        assert buf.consume_at_most(2) == b'xx'

    def test_consume_at_most_with_more_than_sufficient_data(self):
        buf = fp.Buffer(b'xxyyy')
        assert buf.consume_at_most(2) == b'xx'

    def test_consume_at_most_with_insufficient_data(self):
        buf = fp.Buffer(b'xx')
        assert buf.consume_at_most(3) == b'xx'

    def test_consume_exactly_with_sufficient_data(self):
        buf = fp.Buffer(b'xx')
        assert buf.consume_exactly(2) == b'xx'

    def test_consume_exactly_with_more_than_sufficient_data(self):
        buf = fp.Buffer(b'xxyyy')
        assert buf.consume_exactly(2) == b'xx'

    def test_consume_exactly_with_insufficient_data(self):
        buf = fp.Buffer(b'xx')
        assert buf.consume_exactly(3) is None

    def test_feed(self):
        buf = fp.Buffer()
        assert buf.consume_at_most(1) == b''
        assert buf.consume_exactly(1) is None
        buf.feed(b'xy')
        assert buf.consume_at_most(1) == b'x'
        assert buf.consume_exactly(1) == b'y'

    def test_rollback(self):
        buf = fp.Buffer()
        buf.feed(b'xyz')
        assert buf.consume_exactly(2) == b'xy'
        assert buf.consume_exactly(1) == b'z'
        assert buf.consume_at_most(1) == b''
        buf.rollback()
        assert buf.consume_at_most(3) == b'xyz'

    def test_commit(self):
        buf = fp.Buffer()
        buf.feed(b'xyz')
        assert buf.consume_exactly(2) == b'xy'
        assert buf.consume_exactly(1) == b'z'
        assert buf.consume_at_most(1) == b''
        buf.commit()
        assert buf.consume_at_most(3) == b''

    def test_length(self):
        buf = fp.Buffer()
        data = b'xyzabc'
        buf.feed(data)
        assert len(buf) == len(data)


class TestMessageDecoder(object):
    def test_single_binary_frame(self):
        payload = b'x' * 23
        decoder = fp.MessageDecoder()
        frame = fp.Frame(
            opcode=fp.Opcode.BINARY,
            payload=payload,
            frame_finished=True,
            message_finished=True,
        )

        frame = decoder.process_frame(frame)
        assert frame.opcode is fp.Opcode.BINARY
        assert frame.message_finished is True
        assert frame.payload == payload

    def test_follow_on_binary_frame(self):
        payload = b'x' * 23
        decoder = fp.MessageDecoder()
        decoder.opcode = fp.Opcode.BINARY
        decoder.seen_first_frame = True
        frame = fp.Frame(
            opcode=fp.Opcode.CONTINUATION,
            payload=payload,
            frame_finished=True,
            message_finished=False,
        )

        frame = decoder.process_frame(frame)
        assert frame.opcode is fp.Opcode.BINARY
        assert frame.message_finished is False
        assert frame.payload == payload

    def test_single_text_frame(self):
        text_payload = u'fñör∂'
        binary_payload = text_payload.encode('utf8')
        decoder = fp.MessageDecoder()
        frame = fp.Frame(
            opcode=fp.Opcode.TEXT,
            payload=binary_payload,
            frame_finished=True,
            message_finished=True,
        )

        frame = decoder.process_frame(frame)
        assert frame.opcode is fp.Opcode.TEXT
        assert frame.message_finished is True
        assert frame.payload == text_payload

    def test_follow_on_text_frame(self):
        text_payload = u'fñör∂'
        binary_payload = text_payload.encode('utf8')
        decoder = fp.MessageDecoder()
        decoder.opcode = fp.Opcode.TEXT
        decoder.seen_first_frame = True
        decoder.decoder = getincrementaldecoder("utf-8")()

        assert decoder.decoder.decode(binary_payload[:4]) == text_payload[:2]
        binary_payload = binary_payload[4:-2]
        text_payload = text_payload[2:-1]

        frame = fp.Frame(
            opcode=fp.Opcode.CONTINUATION,
            payload=binary_payload,
            frame_finished=True,
            message_finished=False,
        )

        frame = decoder.process_frame(frame)
        assert frame.opcode is fp.Opcode.TEXT
        assert frame.message_finished is False
        assert frame.payload == text_payload

    def test_final_text_frame(self):
        text_payload = u'fñör∂'
        binary_payload = text_payload.encode('utf8')
        decoder = fp.MessageDecoder()
        decoder.opcode = fp.Opcode.TEXT
        decoder.seen_first_frame = True
        decoder.decoder = getincrementaldecoder("utf-8")()

        assert decoder.decoder.decode(binary_payload[:-2]) == text_payload[:-1]
        binary_payload = binary_payload[-2:]
        text_payload = text_payload[-1:]

        frame = fp.Frame(
            opcode=fp.Opcode.CONTINUATION,
            payload=binary_payload,
            frame_finished=True,
            message_finished=True,
        )

        frame = decoder.process_frame(frame)
        assert frame.opcode is fp.Opcode.TEXT
        assert frame.message_finished is True
        assert frame.payload == text_payload

    def test_start_with_continuation(self):
        payload = b'x' * 23
        decoder = fp.MessageDecoder()
        frame = fp.Frame(
            opcode=fp.Opcode.CONTINUATION,
            payload=payload,
            frame_finished=True,
            message_finished=True,
        )

        with pytest.raises(fp.ParseFailed):
            decoder.process_frame(frame)

    def test_missing_continuation_1(self):
        payload = b'x' * 23
        decoder = fp.MessageDecoder()
        decoder.opcode = fp.Opcode.BINARY
        decoder.seen_first_frame = True
        frame = fp.Frame(
            opcode=fp.Opcode.BINARY,
            payload=payload,
            frame_finished=True,
            message_finished=True,
        )

        with pytest.raises(fp.ParseFailed):
            decoder.process_frame(frame)

    def test_missing_continuation_2(self):
        payload = b'x' * 23
        decoder = fp.MessageDecoder()
        decoder.opcode = fp.Opcode.TEXT
        frame = fp.Frame(
            opcode=fp.Opcode.BINARY,
            payload=payload,
            frame_finished=True,
            message_finished=True,
        )

        with pytest.raises(fp.ParseFailed):
            decoder.process_frame(frame)

    def test_incomplete_unicode(self):
        payload = u'fñör∂'
        payload = payload.encode('utf8')
        payload = payload[:4]

        decoder = fp.MessageDecoder()
        frame = fp.Frame(
            opcode=fp.Opcode.TEXT,
            payload=payload,
            frame_finished=True,
            message_finished=True,
        )

        with pytest.raises(fp.ParseFailed) as excinfo:
            decoder.process_frame(frame)
        assert excinfo.value.code is fp.CloseReason.INVALID_FRAME_PAYLOAD_DATA

    def test_not_even_unicode(self):
        payload = u'fñörd'
        payload = payload.encode('iso-8859-1')

        decoder = fp.MessageDecoder()
        frame = fp.Frame(
            opcode=fp.Opcode.TEXT,
            payload=payload,
            frame_finished=True,
            message_finished=False,
        )

        with pytest.raises(fp.ParseFailed) as excinfo:
            decoder.process_frame(frame)
        assert excinfo.value.code is fp.CloseReason.INVALID_FRAME_PAYLOAD_DATA

    def test_bad_unicode(self):
        payload = unhexlify('cebae1bdb9cf83cebcceb5eda080656469746564')

        decoder = fp.MessageDecoder()
        frame = fp.Frame(
            opcode=fp.Opcode.TEXT,
            payload=payload,
            frame_finished=True,
            message_finished=True,
        )

        with pytest.raises(fp.ParseFailed) as excinfo:
            decoder.process_frame(frame)
        assert excinfo.value.code is fp.CloseReason.INVALID_FRAME_PAYLOAD_DATA

    def test_split_message(self):
        text_payload = u'x' * 65535
        payload = text_payload.encode('utf-8')
        split = 32777

        decoder = fp.MessageDecoder()

        frame = fp.Frame(
            opcode=fp.Opcode.TEXT,
            payload=payload[:split],
            frame_finished=False,
            message_finished=True
        )
        frame = decoder.process_frame(frame)
        assert frame.opcode is fp.Opcode.TEXT
        assert frame.message_finished is False
        assert frame.payload == text_payload[:split]

        frame = fp.Frame(
            opcode=fp.Opcode.CONTINUATION,
            payload=payload[split:],
            frame_finished=True,
            message_finished=True
        )
        frame = decoder.process_frame(frame)
        assert frame.opcode is fp.Opcode.TEXT
        assert frame.message_finished is True
        assert frame.payload == text_payload[split:]

    def test_split_unicode_message(self):
        text_payload = u'∂' * 64
        payload = text_payload.encode('utf-8')
        split = 64

        decoder = fp.MessageDecoder()

        frame = fp.Frame(
            opcode=fp.Opcode.TEXT,
            payload=payload[:split],
            frame_finished=False,
            message_finished=True
        )
        frame = decoder.process_frame(frame)
        assert frame.opcode is fp.Opcode.TEXT
        assert frame.message_finished is False
        assert frame.payload == text_payload[:(split // 3)]

        frame = fp.Frame(
            opcode=fp.Opcode.CONTINUATION,
            payload=payload[split:],
            frame_finished=True,
            message_finished=True
        )
        frame = decoder.process_frame(frame)
        assert frame.opcode is fp.Opcode.TEXT
        assert frame.message_finished is True
        assert frame.payload == text_payload[(split // 3):]

    def send_frame_to_validator(self, payload, finished):
        decoder = fp.MessageDecoder()
        frame = fp.Frame(
            opcode=fp.Opcode.TEXT,
            payload=payload,
            frame_finished=finished,
            message_finished=True,
        )
        frame = decoder.process_frame(frame)

    def test_text_message_hits_validator(self, monkeypatch):
        validator = FakeValidator()
        monkeypatch.setattr(fp, 'Utf8Validator', lambda: validator)

        text_payload = u'fñör∂'
        binary_payload = text_payload.encode('utf8')
        self.send_frame_to_validator(binary_payload, True)

        assert validator.validated == binary_payload

    def test_message_validation_failure_fails_properly(self, monkeypatch):
        validator = FakeValidator()
        validator.valid = False

        monkeypatch.setattr(fp, 'Utf8Validator', lambda: validator)

        with pytest.raises(fp.ParseFailed):
            self.send_frame_to_validator(b'', True)

    def test_message_validation_finish_on_incomplete(self, monkeypatch):
        validator = FakeValidator()
        validator.valid = True
        validator.ends_on_complete = False

        monkeypatch.setattr(fp, 'Utf8Validator', lambda: validator)

        with pytest.raises(fp.ParseFailed):
            self.send_frame_to_validator(b'', True)

    def test_message_validation_unfinished_on_incomplete(self, monkeypatch):
        validator = FakeValidator()
        validator.valid = True
        validator.ends_on_complete = False

        monkeypatch.setattr(fp, 'Utf8Validator', lambda: validator)

        self.send_frame_to_validator(b'', False)

    def test_message_no_validation_can_still_fail(self, monkeypatch):
        validator = FakeValidator()
        monkeypatch.setattr(fp, 'Utf8Validator', lambda: validator)

        payload = u'fñörd'
        payload = payload.encode('iso-8859-1')

        with pytest.raises(fp.ParseFailed) as exc:
            self.send_frame_to_validator(payload, True)
        assert exc.value.code == fp.CloseReason.INVALID_FRAME_PAYLOAD_DATA


class TestFrameDecoder(object):
    def _single_frame_test(self, client, frame_bytes, opcode, payload,
                           frame_finished, message_finished):
        decoder = fp.FrameDecoder(client=client)
        decoder.receive_bytes(frame_bytes)
        frame = decoder.process_buffer()
        assert frame is not None
        assert frame.opcode is opcode
        assert frame.payload == payload
        assert frame.frame_finished is frame_finished
        assert frame.message_finished is message_finished

    def _split_frame_test(self, client, frame_bytes, opcode, payload,
                          frame_finished, message_finished, split):
        decoder = fp.FrameDecoder(client=client)
        decoder.receive_bytes(frame_bytes[:split])
        assert decoder.process_buffer() is None
        decoder.receive_bytes(frame_bytes[split:])
        frame = decoder.process_buffer()
        assert frame is not None
        assert frame.opcode is opcode
        assert frame.payload == payload
        assert frame.frame_finished is frame_finished
        assert frame.message_finished is message_finished

    def _split_message_test(self, client, frame_bytes, opcode, payload, split):
        decoder = fp.FrameDecoder(client=client)

        decoder.receive_bytes(frame_bytes[:split])
        frame = decoder.process_buffer()
        assert frame is not None
        assert frame.opcode is opcode
        assert frame.payload == payload[:len(frame.payload)]
        assert frame.frame_finished is False
        assert frame.message_finished is True

        decoder.receive_bytes(frame_bytes[split:])
        frame = decoder.process_buffer()
        assert frame is not None
        assert frame.opcode is fp.Opcode.CONTINUATION
        assert frame.payload == payload[-len(frame.payload):]
        assert frame.frame_finished is True
        assert frame.message_finished is True

    def _parse_failure_test(self, client, frame_bytes, close_reason):
        decoder = fp.FrameDecoder(client=client)
        with pytest.raises(fp.ParseFailed) as excinfo:
            decoder.receive_bytes(frame_bytes)
            decoder.process_buffer()
        assert excinfo.value.code is close_reason

    def test_zero_length_message(self):
        self._single_frame_test(
            client=True,
            frame_bytes=b'\x81\x00',
            opcode=fp.Opcode.TEXT,
            payload=b'',
            frame_finished=True,
            message_finished=True,
        )

    def test_short_server_message_frame(self):
        self._single_frame_test(
            client=True,
            frame_bytes=b'\x81\x02xy',
            opcode=fp.Opcode.TEXT,
            payload=b'xy',
            frame_finished=True,
            message_finished=True,
        )

    def test_short_client_message_frame(self):
        self._single_frame_test(
            client=False,
            frame_bytes=b'\x81\x82abcd\x19\x1b',
            opcode=fp.Opcode.TEXT,
            payload=b'xy',
            frame_finished=True,
            message_finished=True,
        )

    def test_reject_masked_server_frame(self):
        self._parse_failure_test(
            client=True,
            frame_bytes=b'\x81\x82abcd\x19\x1b',
            close_reason=fp.CloseReason.PROTOCOL_ERROR,
        )

    def test_reject_unmasked_client_frame(self):
        self._parse_failure_test(
            client=False,
            frame_bytes=b'\x81\x02xy',
            close_reason=fp.CloseReason.PROTOCOL_ERROR,
        )

    def test_reject_bad_opcode(self):
        self._parse_failure_test(
            client=True,
            frame_bytes=b'\x8e\x02xy',
            close_reason=fp.CloseReason.PROTOCOL_ERROR,
        )

    def test_reject_unfinished_control_frame(self):
        self._parse_failure_test(
            client=True,
            frame_bytes=b'\x09\x02xy',
            close_reason=fp.CloseReason.PROTOCOL_ERROR,
        )

    def test_reject_reserved_bits(self):
        self._parse_failure_test(
            client=True,
            frame_bytes=b'\x91\x02xy',
            close_reason=fp.CloseReason.PROTOCOL_ERROR,
        )
        self._parse_failure_test(
            client=True,
            frame_bytes=b'\xa1\x02xy',
            close_reason=fp.CloseReason.PROTOCOL_ERROR,
        )
        self._parse_failure_test(
            client=True,
            frame_bytes=b'\xc1\x02xy',
            close_reason=fp.CloseReason.PROTOCOL_ERROR,
        )

    def test_long_message_frame(self):
        payload = b'x' * 512
        payload_len = struct.pack('!H', len(payload))
        frame_bytes = b'\x81\x7e' + payload_len + payload

        self._single_frame_test(
            client=True,
            frame_bytes=frame_bytes,
            opcode=fp.Opcode.TEXT,
            payload=payload,
            frame_finished=True,
            message_finished=True,
        )

    def test_very_long_message_frame(self):
        payload = b'x' * (128 * 1024)
        payload_len = struct.pack('!Q', len(payload))
        frame_bytes = b'\x81\x7f' + payload_len + payload

        self._single_frame_test(
            client=True,
            frame_bytes=frame_bytes,
            opcode=fp.Opcode.TEXT,
            payload=payload,
            frame_finished=True,
            message_finished=True,
        )

    def test_insufficiently_long_message_frame(self):
        payload = b'x' * 64
        payload_len = struct.pack('!H', len(payload))
        frame_bytes = b'\x81\x7e' + payload_len + payload

        self._parse_failure_test(
            client=True,
            frame_bytes=frame_bytes,
            close_reason=fp.CloseReason.PROTOCOL_ERROR,
        )

    def test_insufficiently_very_long_message_frame(self):
        payload = b'x' * 512
        payload_len = struct.pack('!Q', len(payload))
        frame_bytes = b'\x81\x7f' + payload_len + payload

        self._parse_failure_test(
            client=True,
            frame_bytes=frame_bytes,
            close_reason=fp.CloseReason.PROTOCOL_ERROR,
        )

    def test_very_insufficiently_very_long_message_frame(self):
        payload = b'x' * 64
        payload_len = struct.pack('!Q', len(payload))
        frame_bytes = b'\x81\x7f' + payload_len + payload

        self._parse_failure_test(
            client=True,
            frame_bytes=frame_bytes,
            close_reason=fp.CloseReason.PROTOCOL_ERROR,
        )

    def test_not_enough_for_header(self):
        payload = b'xy'
        frame_bytes = b'\x81\x02' + payload

        self._split_frame_test(
            client=True,
            frame_bytes=frame_bytes,
            opcode=fp.Opcode.TEXT,
            payload=payload,
            frame_finished=True,
            message_finished=True,
            split=1,
        )

    def test_not_enough_for_long_length(self):
        payload = b'x' * 512
        payload_len = struct.pack('!H', len(payload))
        frame_bytes = b'\x81\x7e' + payload_len + payload

        self._split_frame_test(
            client=True,
            frame_bytes=frame_bytes,
            opcode=fp.Opcode.TEXT,
            payload=payload,
            frame_finished=True,
            message_finished=True,
            split=3,
        )

    def test_not_enough_for_very_long_length(self):
        payload = b'x' * (128 * 1024)
        payload_len = struct.pack('!Q', len(payload))
        frame_bytes = b'\x81\x7f' + payload_len + payload

        self._split_frame_test(
            client=True,
            frame_bytes=frame_bytes,
            opcode=fp.Opcode.TEXT,
            payload=payload,
            frame_finished=True,
            message_finished=True,
            split=7,
        )

    def test_eight_byte_length_with_msb_set(self):
        frame_bytes = b'\x81\x7f\x80\x80\x80\x80\x80\x80\x80\x80'

        self._parse_failure_test(
            client=True,
            frame_bytes=frame_bytes,
            close_reason=fp.CloseReason.PROTOCOL_ERROR,
        )

    def test_not_enough_for_mask(self):
        payload = bytearray(b'xy')
        mask = bytearray(b'abcd')
        masked_payload = bytearray([
            payload[0] ^ mask[0],
            payload[1] ^ mask[1]
        ])
        frame_bytes = b'\x81\x82' + mask + masked_payload

        self._split_frame_test(
            client=False,
            frame_bytes=frame_bytes,
            opcode=fp.Opcode.TEXT,
            payload=payload,
            frame_finished=True,
            message_finished=True,
            split=4,
        )

    def test_partial_message_frames(self):
        chunk_size = 1024
        payload = b'x' * (128 * chunk_size)
        payload_len = struct.pack('!Q', len(payload))
        frame_bytes = b'\x81\x7f' + payload_len + payload
        header_len = len(frame_bytes) - len(payload)

        decoder = fp.FrameDecoder(client=True)
        decoder.receive_bytes(frame_bytes[:header_len])
        assert decoder.process_buffer() is None
        frame_bytes = frame_bytes[header_len:]
        payload_sent = 0
        expected_opcode = fp.Opcode.TEXT
        for offset in range(0, len(frame_bytes), chunk_size):
            chunk = frame_bytes[offset:offset + chunk_size]
            decoder.receive_bytes(chunk)
            frame = decoder.process_buffer()
            payload_sent += chunk_size
            all_payload_sent = payload_sent == len(payload)
            assert frame is not None
            assert frame.opcode is expected_opcode
            assert frame.frame_finished is all_payload_sent
            assert frame.message_finished is True
            assert frame.payload == payload[offset:offset + chunk_size]

            expected_opcode = fp.Opcode.CONTINUATION

    def test_partial_control_frame(self):
        chunk_size = 11
        payload = b'x' * 64
        frame_bytes = b'\x89' + bytearray([len(payload)]) + payload

        decoder = fp.FrameDecoder(client=True)

        for offset in range(0, len(frame_bytes) - chunk_size, chunk_size):
            chunk = frame_bytes[offset:offset + chunk_size]
            decoder.receive_bytes(chunk)
            assert decoder.process_buffer() is None

        decoder.receive_bytes(frame_bytes[-chunk_size:])
        frame = decoder.process_buffer()
        assert frame is not None
        assert frame.opcode is fp.Opcode.PING
        assert frame.frame_finished is True
        assert frame.message_finished is True
        assert frame.payload == payload

    def test_long_message_sliced(self):
        payload = b'x' * 65535
        payload_len = struct.pack('!H', len(payload))
        frame_bytes = b'\x81\x7e' + payload_len + payload

        self._split_message_test(
            client=True,
            frame_bytes=frame_bytes,
            opcode=fp.Opcode.TEXT,
            payload=payload,
            split=65535,
        )

    def test_overly_long_control_frame(self):
        payload = b'x' * 128
        payload_len = struct.pack('!H', len(payload))
        frame_bytes = b'\x89\x7e' + payload_len + payload

        self._parse_failure_test(
            client=True,
            frame_bytes=frame_bytes,
            close_reason=fp.CloseReason.PROTOCOL_ERROR,
        )


class TestFrameDecoderExtensions(object):
    class FakeExtension(wpext.Extension):
        name = 'fake'

        def __init__(self):
            self._inbound_header_called = False
            self._inbound_rsv_bit_set = False
            self._inbound_payload_data_called = False
            self._inbound_complete_called = False
            self._fail_inbound_complete = False
            self._outbound_rsv_bit_set = False

        def enabled(self):
            return True

        def frame_inbound_header(self, proto, opcode, rsv, payload_length):
            self._inbound_header_called = True
            if opcode is fp.Opcode.PONG:
                return fp.CloseReason.MANDATORY_EXT
            self._inbound_rsv_bit_set = rsv.rsv3
            return fp.RsvBits(False, False, True)

        def frame_inbound_payload_data(self, proto, data):
            self._inbound_payload_data_called = True
            if data == b'party time':
                return fp.CloseReason.POLICY_VIOLATION
            elif data == b'ragequit':
                self._fail_inbound_complete = True
            if self._inbound_rsv_bit_set:
                data = data.decode('utf-8').upper().encode('utf-8')
            return data

        def frame_inbound_complete(self, proto, fin):
            self._inbound_complete_called = True
            if self._fail_inbound_complete:
                return fp.CloseReason.ABNORMAL_CLOSURE
            if fin and self._inbound_rsv_bit_set:
                return u'™'.encode('utf-8')

        def frame_outbound(self, proto, opcode, rsv, data, fin):
            if opcode is fp.Opcode.TEXT:
                rsv = fp.RsvBits(rsv.rsv1, rsv.rsv2, True)
                self._outbound_rsv_bit_set = True
            if fin and self._outbound_rsv_bit_set:
                data += u'®'.encode('utf-8')
                self._outbound_rsv_bit_set = False
            return rsv, data

    def test_rsv_bit(self):
        ext = self.FakeExtension()
        decoder = fp.FrameDecoder(client=True, extensions=[ext])

        frame_bytes = b'\x91\x00'

        decoder.receive_bytes(frame_bytes)
        frame = decoder.process_buffer()
        assert frame is not None
        assert ext._inbound_header_called
        assert ext._inbound_rsv_bit_set

    def test_wrong_rsv_bit(self):
        ext = self.FakeExtension()
        decoder = fp.FrameDecoder(client=True, extensions=[ext])

        frame_bytes = b'\xa1\x00'

        decoder.receive_bytes(frame_bytes)
        with pytest.raises(fp.ParseFailed) as excinfo:
            decoder.receive_bytes(frame_bytes)
            decoder.process_buffer()
        assert excinfo.value.code is fp.CloseReason.PROTOCOL_ERROR

    def test_header_error_handling(self):
        ext = self.FakeExtension()
        decoder = fp.FrameDecoder(client=True, extensions=[ext])

        frame_bytes = b'\x9a\x00'

        decoder.receive_bytes(frame_bytes)
        with pytest.raises(fp.ParseFailed) as excinfo:
            decoder.receive_bytes(frame_bytes)
            decoder.process_buffer()
        assert excinfo.value.code is fp.CloseReason.MANDATORY_EXT

    def test_payload_processing(self):
        ext = self.FakeExtension()
        decoder = fp.FrameDecoder(client=True, extensions=[ext])

        payload = u'fñör∂'
        expected_payload = payload.upper().encode('utf-8')
        bytes_payload = payload.encode('utf-8')
        frame_bytes = b'\x11' + bytearray([len(bytes_payload)]) + bytes_payload

        decoder.receive_bytes(frame_bytes)
        frame = decoder.process_buffer()
        assert frame is not None
        assert ext._inbound_header_called
        assert ext._inbound_rsv_bit_set
        assert ext._inbound_payload_data_called
        assert frame.payload == expected_payload

    def test_no_payload_processing_when_not_wanted(self):
        ext = self.FakeExtension()
        decoder = fp.FrameDecoder(client=True, extensions=[ext])

        payload = u'fñör∂'
        expected_payload = payload.encode('utf-8')
        bytes_payload = payload.encode('utf-8')
        frame_bytes = b'\x01' + bytearray([len(bytes_payload)]) + bytes_payload

        decoder.receive_bytes(frame_bytes)
        frame = decoder.process_buffer()
        assert frame is not None
        assert ext._inbound_header_called
        assert not ext._inbound_rsv_bit_set
        assert ext._inbound_payload_data_called
        assert frame.payload == expected_payload

    def test_payload_error_handling(self):
        ext = self.FakeExtension()
        decoder = fp.FrameDecoder(client=True, extensions=[ext])

        payload = b'party time'
        frame_bytes = b'\x91' + bytearray([len(payload)]) + payload

        decoder.receive_bytes(frame_bytes)
        with pytest.raises(fp.ParseFailed) as excinfo:
            decoder.receive_bytes(frame_bytes)
            decoder.process_buffer()
        assert excinfo.value.code is fp.CloseReason.POLICY_VIOLATION

    def test_frame_completion(self):
        ext = self.FakeExtension()
        decoder = fp.FrameDecoder(client=True, extensions=[ext])

        payload = u'fñör∂'
        expected_payload = (payload + u'™').upper().encode('utf-8')
        bytes_payload = payload.encode('utf-8')
        frame_bytes = b'\x91' + bytearray([len(bytes_payload)]) + bytes_payload

        decoder.receive_bytes(frame_bytes)
        frame = decoder.process_buffer()
        assert frame is not None
        assert ext._inbound_header_called
        assert ext._inbound_rsv_bit_set
        assert ext._inbound_payload_data_called
        assert ext._inbound_complete_called
        assert frame.payload == expected_payload

    def test_no_frame_completion_when_not_wanted(self):
        ext = self.FakeExtension()
        decoder = fp.FrameDecoder(client=True, extensions=[ext])

        payload = u'fñör∂'
        expected_payload = payload.encode('utf-8')
        bytes_payload = payload.encode('utf-8')
        frame_bytes = b'\x81' + bytearray([len(bytes_payload)]) + bytes_payload

        decoder.receive_bytes(frame_bytes)
        frame = decoder.process_buffer()
        assert frame is not None
        assert ext._inbound_header_called
        assert not ext._inbound_rsv_bit_set
        assert ext._inbound_payload_data_called
        assert ext._inbound_complete_called
        assert frame.payload == expected_payload

    def test_completion_error_handling(self):
        ext = self.FakeExtension()
        decoder = fp.FrameDecoder(client=True, extensions=[ext])

        payload = b'ragequit'
        frame_bytes = b'\x91' + bytearray([len(payload)]) + payload

        decoder.receive_bytes(frame_bytes)
        with pytest.raises(fp.ParseFailed) as excinfo:
            decoder.receive_bytes(frame_bytes)
            decoder.process_buffer()
        assert excinfo.value.code is fp.CloseReason.ABNORMAL_CLOSURE

    def test_outbound_handling_single_frame(self):
        ext = self.FakeExtension()
        proto = fp.FrameProtocol(client=False, extensions=[ext])
        payload = u'😃😄🙃😉'
        data = proto.send_data(payload, fin=True)
        payload = (payload + u'®').encode('utf8')
        assert data == b'\x91' + bytearray([len(payload)]) + payload

    def test_outbound_handling_multiple_frames(self):
        ext = self.FakeExtension()
        proto = fp.FrameProtocol(client=False, extensions=[ext])
        payload = u'😃😄🙃😉'
        data = proto.send_data(payload, fin=False)
        payload = payload.encode('utf8')
        assert data == b'\x11' + bytearray([len(payload)]) + payload

        payload = u'¯\_(ツ)_/¯'
        data = proto.send_data(payload, fin=True)
        payload = (payload + u'®').encode('utf8')
        assert data == b'\x80' + bytearray([len(payload)]) + payload


class TestFrameProtocolReceive(object):
    def test_long_text_message(self):
        payload = 'x' * 65535
        encoded_payload = payload.encode('utf-8')
        payload_len = struct.pack('!H', len(encoded_payload))
        frame_bytes = b'\x81\x7e' + payload_len + encoded_payload

        protocol = fp.FrameProtocol(client=True, extensions=[])
        protocol.receive_bytes(frame_bytes)
        frames = list(protocol.received_frames())
        assert len(frames) == 1
        frame = frames[0]
        assert frame.opcode == fp.Opcode.TEXT
        assert len(frame.payload) == len(payload)
        assert frame.payload == payload

    def _close_test(self, code, reason=None, reason_bytes=None):
        payload = b''
        if code:
            payload += struct.pack('!H', code)
        if reason:
            payload += reason.encode('utf8')
        elif reason_bytes:
            payload += reason_bytes

        frame_bytes = b'\x88' + bytearray([len(payload)]) + payload

        protocol = fp.FrameProtocol(client=True, extensions=[])
        protocol.receive_bytes(frame_bytes)
        frames = list(protocol.received_frames())
        assert len(frames) == 1
        frame = frames[0]
        assert frame.opcode == fp.Opcode.CLOSE
        assert frame.payload[0] == code or fp.CloseReason.NO_STATUS_RCVD
        if reason:
            assert frame.payload[1] == reason
        else:
            assert not frame.payload[1]

    def test_close_no_code(self):
        self._close_test(None)

    def test_close_one_byte_code(self):
        frame_bytes = b'\x88\x01\x0e'
        protocol = fp.FrameProtocol(client=True, extensions=[])

        with pytest.raises(fp.ParseFailed) as exc:
            protocol.receive_bytes(frame_bytes)
            list(protocol.received_frames())
        assert exc.value.code == fp.CloseReason.PROTOCOL_ERROR

    def test_close_bad_code(self):
        with pytest.raises(fp.ParseFailed) as exc:
            self._close_test(123)
        assert exc.value.code == fp.CloseReason.PROTOCOL_ERROR

    def test_close_unknown_code(self):
        with pytest.raises(fp.ParseFailed) as exc:
            self._close_test(2998)
        assert exc.value.code == fp.CloseReason.PROTOCOL_ERROR

    def test_close_local_only_code(self):
        with pytest.raises(fp.ParseFailed) as exc:
            self._close_test(fp.CloseReason.NO_STATUS_RCVD)
        assert exc.value.code == fp.CloseReason.PROTOCOL_ERROR

    def test_close_no_payload(self):
        self._close_test(fp.CloseReason.NORMAL_CLOSURE)

    def test_close_easy_payload(self):
        self._close_test(fp.CloseReason.NORMAL_CLOSURE, u'tarah old chap')

    def test_close_utf8_payload(self):
        self._close_test(fp.CloseReason.NORMAL_CLOSURE, u'fñør∂')

    def test_close_bad_utf8_payload(self):
        payload = unhexlify('cebae1bdb9cf83cebcceb5eda080656469746564')
        with pytest.raises(fp.ParseFailed) as exc:
            self._close_test(fp.CloseReason.NORMAL_CLOSURE,
                             reason_bytes=payload)
        assert exc.value.code == fp.CloseReason.INVALID_FRAME_PAYLOAD_DATA

    def test_close_incomplete_utf8_payload(self):
        payload = u'fñør∂'.encode('utf8')[:-1]
        with pytest.raises(fp.ParseFailed) as exc:
            self._close_test(fp.CloseReason.NORMAL_CLOSURE,
                             reason_bytes=payload)
        assert exc.value.code == fp.CloseReason.INVALID_FRAME_PAYLOAD_DATA

    def test_random_control_frame(self):
        payload = b'give me one ping vasily'
        frame_bytes = b'\x89' + bytearray([len(payload)]) + payload

        protocol = fp.FrameProtocol(client=True, extensions=[])
        protocol.receive_bytes(frame_bytes)
        frames = list(protocol.received_frames())
        assert len(frames) == 1
        frame = frames[0]
        assert frame.opcode == fp.Opcode.PING
        assert len(frame.payload) == len(payload)
        assert frame.payload == payload

    def test_close_reasons_get_utf8_validated(self, monkeypatch):
        validator = FakeValidator()
        reason = u'ƒñø®∂'
        monkeypatch.setattr(fp, 'Utf8Validator', lambda: validator)

        self._close_test(fp.CloseReason.NORMAL_CLOSURE, reason=reason)

        assert validator.validated == reason.encode('utf8')

    def test_close_reason_failing_validation_fails(self, monkeypatch):
        validator = FakeValidator()
        validator.valid = False
        reason = u'ƒñø®∂'
        monkeypatch.setattr(fp, 'Utf8Validator', lambda: validator)

        with pytest.raises(fp.ParseFailed) as exc:
            self._close_test(fp.CloseReason.NORMAL_CLOSURE, reason=reason)
        assert exc.value.code == fp.CloseReason.INVALID_FRAME_PAYLOAD_DATA

    def test_close_reason_with_incomplete_utf8_fails(self, monkeypatch):
        validator = FakeValidator()
        validator.ends_on_complete = False
        reason = u'ƒñø®∂'
        monkeypatch.setattr(fp, 'Utf8Validator', lambda: validator)

        with pytest.raises(fp.ParseFailed) as exc:
            self._close_test(fp.CloseReason.NORMAL_CLOSURE, reason=reason)
        assert exc.value.code == fp.CloseReason.INVALID_FRAME_PAYLOAD_DATA

    def test_close_no_validation(self, monkeypatch):
        monkeypatch.setattr(fp, 'Utf8Validator', lambda: None)
        reason = u'ƒñø®∂'
        self._close_test(fp.CloseReason.NORMAL_CLOSURE, reason=reason)

    def test_close_no_validation_can_still_fail(self, monkeypatch):
        validator = FakeValidator()
        monkeypatch.setattr(fp, 'Utf8Validator', lambda: validator)

        reason = u'fñörd'
        reason = reason.encode('iso-8859-1')

        with pytest.raises(fp.ParseFailed) as exc:
            self._close_test(fp.CloseReason.NORMAL_CLOSURE,
                             reason_bytes=reason)
        assert exc.value.code == fp.CloseReason.INVALID_FRAME_PAYLOAD_DATA


class TestFrameProtocolSend(object):
    def test_simplest_possible_close(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        data = proto.close()
        assert data == b'\x88\x00'

    def test_unreasoning_close(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        data = proto.close(code=fp.CloseReason.NORMAL_CLOSURE)
        assert data == b'\x88\x02\x03\xe8'

    def test_reasoned_close(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        reason = u'¯\_(ツ)_/¯'
        expected_payload = struct.pack('!H', fp.CloseReason.NORMAL_CLOSURE) + \
            reason.encode('utf8')
        data = proto.close(code=fp.CloseReason.NORMAL_CLOSURE, reason=reason)
        assert data == b'\x88' + bytearray([len(expected_payload)]) + \
            expected_payload

    def test_overly_reasoned_close(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        reason = u'¯\_(ツ)_/¯' * 10
        data = proto.close(code=fp.CloseReason.NORMAL_CLOSURE, reason=reason)
        assert bytes(data[0:1]) == b'\x88'
        assert len(data) <= 127
        assert data[4:].decode('utf8')

    def test_reasoned_but_uncoded_close(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        with pytest.raises(TypeError):
            proto.close(reason='termites')

    def test_local_only_close_reason(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        data = proto.close(code=fp.CloseReason.NO_STATUS_RCVD)
        assert data == b'\x88\x02\x03\xe8'

    def test_ping_without_payload(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        data = proto.ping()
        assert data == b'\x89\x00'

    def test_ping_with_payload(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        payload = u'¯\_(ツ)_/¯'.encode('utf8')
        data = proto.ping(payload)
        assert data == b'\x89' + bytearray([len(payload)]) + payload

    def test_pong_without_payload(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        data = proto.pong()
        assert data == b'\x8a\x00'

    def test_pong_with_payload(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        payload = u'¯\_(ツ)_/¯'.encode('utf8')
        data = proto.pong(payload)
        assert data == b'\x8a' + bytearray([len(payload)]) + payload

    def test_single_short_binary_data(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        payload = b"it's all just ascii, right?"
        data = proto.send_data(payload, fin=True)
        assert data == b'\x82' + bytearray([len(payload)]) + payload

    def test_single_short_text_data(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        payload = u'😃😄🙃😉'
        data = proto.send_data(payload, fin=True)
        payload = payload.encode('utf8')
        assert data == b'\x81' + bytearray([len(payload)]) + payload

    def test_multiple_short_binary_data(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        payload = b"it's all just ascii, right?"
        data = proto.send_data(payload, fin=False)
        assert data == b'\x02' + bytearray([len(payload)]) + payload

        payload = b'sure no worries'
        data = proto.send_data(payload, fin=True)
        assert data == b'\x80' + bytearray([len(payload)]) + payload

    def test_multiple_short_text_data(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        payload = u'😃😄🙃😉'
        data = proto.send_data(payload, fin=False)
        payload = payload.encode('utf8')
        assert data == b'\x01' + bytearray([len(payload)]) + payload

        payload = u'🙈🙉🙊'
        data = proto.send_data(payload, fin=True)
        payload = payload.encode('utf8')
        assert data == b'\x80' + bytearray([len(payload)]) + payload

    def test_mismatched_data_messages1(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        payload = u'😃😄🙃😉'
        data = proto.send_data(payload, fin=False)
        payload = payload.encode('utf8')
        assert data == b'\x01' + bytearray([len(payload)]) + payload

        payload = b'seriously, all ascii'
        with pytest.raises(TypeError):
            proto.send_data(payload)

    def test_mismatched_data_messages2(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        payload = b"it's all just ascii, right?"
        data = proto.send_data(payload, fin=False)
        assert data == b'\x02' + bytearray([len(payload)]) + payload

        payload = u'✔️☑️✅✔︎☑'
        with pytest.raises(TypeError):
            proto.send_data(payload)

    def test_message_length_max_short(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        payload = b'x' * 125
        data = proto.send_data(payload, fin=True)
        assert data == b'\x82' + bytearray([len(payload)]) + payload

    def test_message_length_min_two_byte(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        payload = b'x' * 126
        data = proto.send_data(payload, fin=True)
        assert data == b'\x82\x7e' + struct.pack('!H', len(payload)) + payload

    def test_message_length_max_two_byte(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        payload = b'x' * (2 ** 16 - 1)
        data = proto.send_data(payload, fin=True)
        assert data == b'\x82\x7e' + struct.pack('!H', len(payload)) + payload

    def test_message_length_min_eight_byte(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        payload = b'x' * (2 ** 16)
        data = proto.send_data(payload, fin=True)
        assert data == b'\x82\x7f' + struct.pack('!Q', len(payload)) + payload

    def test_client_side_masking_short_frame(self):
        proto = fp.FrameProtocol(client=True, extensions=[])
        payload = b'x' * 125
        data = proto.send_data(payload, fin=True)
        assert data[0] == 0x82
        assert struct.unpack('!B', data[1:2])[0] == len(payload) | 0x80
        masking_key = data[2:6]
        maskbytes = itertools.cycle(masking_key)
        assert data[6:] == \
            bytearray(b ^ next(maskbytes) for b in bytearray(payload))

    def test_client_side_masking_two_byte_frame(self):
        proto = fp.FrameProtocol(client=True, extensions=[])
        payload = b'x' * 126
        data = proto.send_data(payload, fin=True)
        assert data[0] == 0x82
        assert data[1] == 0xfe
        assert struct.unpack('!H', data[2:4])[0] == len(payload)
        masking_key = data[4:8]
        maskbytes = itertools.cycle(masking_key)
        assert data[8:] == \
            bytearray(b ^ next(maskbytes) for b in bytearray(payload))

    def test_client_side_masking_eight_byte_frame(self):
        proto = fp.FrameProtocol(client=True, extensions=[])
        payload = b'x' * 65536
        data = proto.send_data(payload, fin=True)
        assert data[0] == 0x82
        assert data[1] == 0xff
        assert struct.unpack('!Q', data[2:10])[0] == len(payload)
        masking_key = data[10:14]
        maskbytes = itertools.cycle(masking_key)
        assert data[14:] == \
            bytearray(b ^ next(maskbytes) for b in bytearray(payload))

    def test_control_frame_with_overly_long_payload(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        payload = b'x' * 126

        with pytest.raises(ValueError):
            proto.pong(payload)

    def test_data_we_have_no_idea_what_to_do_with(self):
        proto = fp.FrameProtocol(client=False, extensions=[])
        payload = dict()

        with pytest.raises(ValueError):
            proto.send_data(payload)
