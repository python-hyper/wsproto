# -*- coding: utf-8 -*-

import pytest

from wsproto.connection import WSConnection, CLIENT, SERVER, ConnectionState
from wsproto.events import (ConnectionClosed, TextReceived, BytesReceived)
from wsproto.frame_protocol import CloseReason, FrameProtocol


class FakeProtocol(object):
    def __init__(self):
        self.send_data_response = None
        self.close_response = None
        self.received_frames_response = []

        self.send_data_payload = None
        self.send_data_final = None
        self.close_code = None
        self.close_reason = None
        self.receive_bytes_bytes = None

    def send_data(self, payload, final):
        self.send_data_payload = payload
        self.send_data_final = final
        return self.send_data_response

    def close(self, code, reason):
        self.close_code = code
        self.close_reason = reason
        return self.close_response

    def receive_bytes(self, data):
        self.receive_bytes_bytes = data

    def received_frames(self):
        return self.received_frames_response


class TestConnection(object):
    @pytest.mark.parametrize('final', [True, False])
    def test_send_data(self, final):
        data = b'x' * 23
        payload = b'y' * 23

        proto = FakeProtocol()
        proto.send_data_response = payload

        connection = WSConnection(SERVER)
        connection._proto = proto
        connection.send_data(data, final)

        assert proto.send_data_payload == data
        assert proto.send_data_final is final
        assert connection.bytes_to_send() == payload

    @pytest.mark.parametrize('code,reason', [
        (CloseReason.NORMAL_CLOSURE, u'bye'),
        (CloseReason.GOING_AWAY, u'👋👋'),
    ])
    def test_close(self, code, reason):
        payload = b'y' * 23

        proto = FakeProtocol()
        proto.close_response = payload

        connection = WSConnection(SERVER)
        connection._proto = proto
        connection.close(code, reason)

        assert proto.close_code is code
        assert proto.close_reason == reason
        assert connection.bytes_to_send() == payload

    def test_normal_closure(self):
        payload = b'y' * 23

        proto = FakeProtocol()
        proto.close_response = payload

        connection = WSConnection(SERVER)
        connection._proto = proto
        connection.close()

        connection.bytes_to_send()
        connection.receive_bytes(None)
        with pytest.raises(StopIteration):
            next(connection.events())
        assert connection.closed

    def test_abnormal_closure(self):
        payload = b'y' * 23

        proto = FakeProtocol()
        proto.close_response = payload

        connection = WSConnection(SERVER)
        connection._proto = proto
        connection._state = ConnectionState.OPEN

        connection.receive_bytes(None)
        assert isinstance(next(connection.events()), ConnectionClosed)
        assert connection.closed

    def test_bytes_send_all(self):
        connection = WSConnection(SERVER)
        connection._outgoing = b'fnord fnord'
        assert connection.bytes_to_send() == b'fnord fnord'
        assert connection.bytes_to_send() == b''

    def test_bytes_send_some(self):
        connection = WSConnection(SERVER)
        connection._outgoing = b'fnord fnord'
        assert connection.bytes_to_send(5) == b'fnord'
        assert connection.bytes_to_send() == b' fnord'

    def test_receive_bytes(self):
        payload = b'y' * 23

        proto = FakeProtocol()

        connection = WSConnection(SERVER)
        connection._proto = proto
        connection._state = ConnectionState.OPEN

        connection.receive_bytes(payload)
        assert proto.receive_bytes_bytes == payload

    def test_events_ping(self):
        payload = b'x' * 23
        frame = b'\x89' + bytearray([len(payload)]) + payload

        connection = WSConnection(CLIENT, host='localhost', resource='foo')
        connection._proto = FrameProtocol(True, [])
        connection._state = ConnectionState.OPEN
        connection.bytes_to_send()

        connection.receive_bytes(frame)
        with pytest.raises(StopIteration):
            next(connection.events())
        output = connection.bytes_to_send()
        assert output[:2] == b'\x8a' + bytearray([len(payload) | 0x80])

    def test_events_close(self):
        payload = b'\x03\xe8' + b'x' * 23
        frame = b'\x88' + bytearray([len(payload)]) + payload

        connection = WSConnection(CLIENT, host='localhost', resource='foo')
        connection._proto = FrameProtocol(True, [])
        connection._state = ConnectionState.OPEN
        connection.bytes_to_send()

        connection.receive_bytes(frame)
        event = next(connection.events())
        assert isinstance(event, ConnectionClosed)
        assert event.code == CloseReason.NORMAL_CLOSURE
        assert event.reason == payload[2:].decode('utf8')

        output = connection.bytes_to_send()
        assert output[:2] == b'\x88' + bytearray([len(payload) | 0x80])

    @pytest.mark.parametrize('text,payload,full_message,full_frame', [
        (True, u'ƒñö®∂😎', True, True),
        (True, u'ƒñö®∂😎', False, True),
        (True, u'ƒñö®∂😎', False, False),
        (False, b'x' * 23, True, True),
        (False, b'x' * 23, False, True),
        (False, b'x' * 23, False, False),
    ])
    def test_data_events(self, text, payload, full_message, full_frame):
        if text:
            opcode = 0x01
            encoded_payload = payload.encode('utf8')
        else:
            opcode = 0x02
            encoded_payload = payload

        if full_message:
            opcode = bytearray([opcode | 0x80])
        else:
            opcode = bytearray([opcode])

        if full_frame:
            length = bytearray([len(encoded_payload)])
        else:
            length = bytearray([len(encoded_payload) + 100])

        frame = opcode + length + encoded_payload

        connection = WSConnection(CLIENT, host='localhost', resource='foo')
        connection._proto = FrameProtocol(True, [])
        connection._state = ConnectionState.OPEN
        connection.bytes_to_send()

        connection.receive_bytes(frame)
        event = next(connection.events())
        if text:
            assert isinstance(event, TextReceived)
        else:
            assert isinstance(event, BytesReceived)
        assert event.data == payload
        assert event.frame_finished is full_frame
        assert event.message_finished is full_message

        assert not connection.bytes_to_send()

    def test_frame_protocol_somehow_loses_its_mind(self):
        class FailFrame(object):
            opcode = object()

        class DoomProtocol(object):
            def receive_bytes(self, data):
                return None

            def received_frames(self):
                return [FailFrame()]

        connection = WSConnection(CLIENT, host='localhost', resource='foo')
        connection._proto = DoomProtocol()
        connection._state = ConnectionState.OPEN
        connection.bytes_to_send()

        connection.receive_bytes(b'')
        with pytest.raises(StopIteration):
            next(connection.events())
        assert not connection.bytes_to_send()

    def test_frame_protocol_gets_fed_garbage(self):
        payload = b'x' * 23
        frame = b'\x09' + bytearray([len(payload)]) + payload

        connection = WSConnection(CLIENT, host='localhost', resource='foo')
        connection._proto = FrameProtocol(True, [])
        connection._state = ConnectionState.OPEN
        connection.bytes_to_send()

        connection.receive_bytes(frame)
        event = next(connection.events())
        assert isinstance(event, ConnectionClosed)
        assert event.code == CloseReason.PROTOCOL_ERROR

        output = connection.bytes_to_send()
        assert output[:1] == b'\x88'
