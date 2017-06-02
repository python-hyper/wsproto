# -*- coding: utf-8 -*-

import pytest
from binascii import unhexlify
from codecs import getincrementaldecoder
import struct

import wsproto.frame_protocol as fp
import wsproto.extensions as wpext


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
            self._rsv_bit_set = False
            self._inbound_payload_data_called = False
            self._inbound_complete_called = False
            self._fail_inbound_complete = False

        def enabled(self):
            return True

        def frame_inbound_header(self, proto, opcode, rsv, payload_length):
            self._inbound_header_called = True
            if opcode is fp.Opcode.PONG:
                return fp.CloseReason.MANDATORY_EXT
            self._rsv_bit_set = rsv[2]
            return fp.RsvBits(False, False, True)

        def frame_inbound_payload_data(self, proto, data):
            self._inbound_payload_data_called = True
            if data == b'party time':
                return fp.CloseReason.POLICY_VIOLATION
            elif data == b'ragequit':
                self._fail_inbound_complete = True
            if self._rsv_bit_set:
                data = data.decode('utf-8').upper().encode('utf-8')
            return data

        def frame_inbound_complete(self, proto, fin):
            self._inbound_complete_called = True
            if self._fail_inbound_complete:
                return fp.CloseReason.ABNORMAL_CLOSURE
            if fin and self._rsv_bit_set:
                return u'™'.encode('utf-8')

    def test_rsv_bit(self):
        ext = self.FakeExtension()
        decoder = fp.FrameDecoder(client=True, extensions=[ext])

        frame_bytes = b'\x91\x00'

        decoder.receive_bytes(frame_bytes)
        frame = decoder.process_buffer()
        assert frame is not None
        assert ext._inbound_header_called
        assert ext._rsv_bit_set

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
        assert ext._rsv_bit_set
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
        assert not ext._rsv_bit_set
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
        assert ext._rsv_bit_set
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
        assert not ext._rsv_bit_set
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


class TestFrameProtocolSend(object):
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
        expected_payload = struct.pack('!H', fp.CloseReason.NORMAL_CLOSURE) + \
            reason.encode('utf8')
        data = proto.close(code=fp.CloseReason.NORMAL_CLOSURE, reason=reason)
        assert bytes(data[0:1]) == b'\x88'
        assert len(data) <= 127
        assert data[4:].decode('utf8')


def test_payload_length_decode():
    # "the minimal number of bytes MUST be used to encode the length, for
    # example, the length of a 124-byte-long string can't be encoded as the
    # sequence 126, 0, 124" -- RFC 6455

    def make_header(encoding_bytes, payload_len):
        if encoding_bytes == 1:
            assert payload_len <= 125
            return unhexlify("81") + bytes([payload_len])
        elif encoding_bytes == 2:
            assert payload_len < 2**16
            return unhexlify("81" "7e") + struct.pack("!H", payload_len)
        elif encoding_bytes == 8:
            return unhexlify("81" "7f") + struct.pack("!Q", payload_len)
        else:
            assert False

    def make_and_parse(encoding_bytes, payload_len):
        proto = fp.FrameProtocol(client=True, extensions=[])
        proto.receive_bytes(make_header(encoding_bytes, payload_len))
        list(proto.received_frames())

    # Valid lengths for 1 byte
    for payload_len in [0, 1, 2, 123, 124, 125]:
        make_and_parse(1, payload_len)
        for encoding_bytes in [2, 8]:
            with pytest.raises(fp.ParseFailed) as excinfo:
                make_and_parse(encoding_bytes, payload_len)
            assert "used {} bytes".format(encoding_bytes) in str(excinfo.value)

    # Valid lengths for 2 bytes
    for payload_len in [126, 127, 1000, 2**16 - 1]:
        make_and_parse(2, payload_len)
        with pytest.raises(fp.ParseFailed) as excinfo:
            make_and_parse(8, payload_len)
        assert "used 8 bytes" in str(excinfo.value)

    # Valid lengths for 8 bytes
    for payload_len in [2**16, 2**16 + 1, 2**32, 2**63 - 1]:
        make_and_parse(8, payload_len)

    # Invalid lengths for 8 bytes
    for payload_len in [2**63, 2**63 + 1]:
        with pytest.raises(fp.ParseFailed) as excinfo:
            make_and_parse(8, payload_len)
        assert "non-zero MSB" in str(excinfo.value)
