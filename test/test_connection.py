# -*- coding: utf-8 -*-

import itertools

import pytest

from wsproto.connection import WSConnection, CLIENT, SERVER, ConnectionState
from wsproto.events import (
    ConnectionClosed,
    ConnectionEstablished,
    ConnectionRequested,
    TextReceived,
    BytesReceived,
    PingReceived,
    PongReceived)
from wsproto.frame_protocol import CloseReason, FrameProtocol


class TestConnection(object):
    def create_connection(self):
        server = WSConnection(SERVER)
        client = WSConnection(CLIENT, host='localhost', resource='foo')

        server.receive_bytes(client.bytes_to_send())
        event = next(server.events())
        assert isinstance(event, ConnectionRequested)

        server.accept(event)
        client.receive_bytes(server.bytes_to_send())
        assert isinstance(next(client.events()), ConnectionEstablished)

        return client, server

    def test_negotiation(self):
        self.create_connection()

    def test_default_args(self):
        with pytest.raises(ValueError, match="Host must not be None"):
            WSConnection(CLIENT, resource='/ws')
        with pytest.raises(ValueError, match="Resource must not be None"):
            WSConnection(CLIENT, host='localhost')

    @pytest.mark.parametrize('as_client,final', [
        (True, True),
        (True, False),
        (False, True),
        (False, False)
    ])
    def test_send_and_receive(self, as_client, final):
        client, server = self.create_connection()
        if as_client:
            me = client
            them = server
        else:
            me = server
            them = client

        data = b'x' * 23

        me.send_data(data, final)
        them.receive_bytes(me.bytes_to_send())

        event = next(them.events())
        assert isinstance(event, BytesReceived)
        assert event.data == data
        assert event.message_finished is final

    @pytest.mark.parametrize('as_client,code,reason', [
        (True, CloseReason.NORMAL_CLOSURE, u'bye'),
        (True, CloseReason.GOING_AWAY, u'👋👋'),
        (False, CloseReason.NORMAL_CLOSURE, u'bye'),
        (False, CloseReason.GOING_AWAY, u'👋👋'),
    ])
    def test_close(self, as_client, code, reason):
        client, server = self.create_connection()
        if as_client:
            me = client
            them = server
        else:
            me = server
            them = client

        me.close(code, reason)
        them.receive_bytes(me.bytes_to_send())

        event = next(them.events())
        assert isinstance(event, ConnectionClosed)
        assert event.code is code
        assert event.reason == reason

    @pytest.mark.parametrize('swap', [
        True,
        False
    ])
    def test_normal_closure(self, swap):
        if swap:
            completor, initiator = self.create_connection()
        else:
            initiator, completor = self.create_connection()

        # initiator sends CLOSE to completor
        initiator.close()
        completor.receive_bytes(initiator.bytes_to_send())

        # completor emits ConnectionClosed
        assert isinstance(next(completor.events()), ConnectionClosed)

        # completor enters CLOSED state
        assert completor.closed
        with pytest.raises(StopIteration):
            next(completor.events())

        # completor sends CLOSE back to initiator
        initiator.receive_bytes(completor.bytes_to_send())

        # initiator emits ConnectionClosed
        assert isinstance(next(initiator.events()), ConnectionClosed)

        # initiator enters CLOSED state
        assert initiator.closed
        with pytest.raises(StopIteration):
            next(initiator.events())

        completor.ping()
        with pytest.raises(ValueError):
            initiator.receive_bytes(completor.bytes_to_send())

    def test_abnormal_closure(self):
        client, server = self.create_connection()

        for conn in (client, server):
            conn.receive_bytes(None)
            event = next(conn.events())
            assert isinstance(event, ConnectionClosed)
            assert event.code is CloseReason.ABNORMAL_CLOSURE
            assert conn.closed

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

    @pytest.mark.parametrize('as_client', [True, False])
    def test_ping_pong(self, as_client):
        client, server = self.create_connection()
        if as_client:
            me = client
            them = server
        else:
            me = server
            them = client

        payload = b'x' * 23

        # Send a PING message
        me.ping(payload)
        wire_data = me.bytes_to_send()

        # Verify that the peer emits the PingReceive event with the correct
        # payload.
        them.receive_bytes(wire_data)
        event = next(them.events())
        assert isinstance(event, PingReceived)
        assert event.payload == payload
        with pytest.raises(StopIteration):
            repr(next(them.events()))

        # Let the peer send the automatic PONG message
        wire_data = them.bytes_to_send()
        assert wire_data[0] == 0x8a
        masked = bool(wire_data[1] & 0x80)
        assert wire_data[1] & ~0x80 == len(payload)
        if masked:
            maskbytes = itertools.cycle(bytearray(wire_data[2:6]))
            data = bytearray(b ^ next(maskbytes)
                             for b in bytearray(wire_data[6:]))
        else:
            data = wire_data[2:]
        assert data == payload

        # Verify that connection emits the PongReceive event with the correct
        # payload.
        me.receive_bytes(wire_data)
        event = next(me.events())
        assert isinstance(event, PongReceived)
        assert event.payload == payload
        with pytest.raises(StopIteration):
            repr(next(me.events()))

    @pytest.mark.parametrize('args, expected_payload', [
        ((), b''),
        ((b'abcdef',), b'abcdef')
    ], ids=['nopayload', 'payload'])
    def test_unsolicited_pong(self, args, expected_payload):
        client, server = self.create_connection()
        client.pong(*args)
        wire_data = client.bytes_to_send()
        server.receive_bytes(wire_data)
        events = list(server.events())
        assert len(events) == 1
        assert isinstance(events[0], PongReceived)
        assert events[0].payload == expected_payload

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
        client, server = self.create_connection()

        payload = b'x' * 23
        frame = b'\x09' + bytearray([len(payload)]) + payload

        client.receive_bytes(frame)
        event = next(client.events())
        assert isinstance(event, ConnectionClosed)
        assert event.code == CloseReason.PROTOCOL_ERROR

        output = client.bytes_to_send()
        assert output[:1] == b'\x88'
