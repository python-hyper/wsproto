# -*- coding: utf-8 -*-

import itertools

import pytest

from wsproto.connection import CLIENT, ConnectionState, SERVER, WSConnection
from wsproto.events import (
    AcceptConnection,
    BytesMessage,
    CloseConnection,
    Message,
    Ping,
    Pong,
    Request,
    TextMessage,
)
from wsproto.frame_protocol import CloseReason, FrameProtocol
from wsproto.utilities import LocalProtocolError


class TestConnection(object):
    def create_connection(self):
        server = WSConnection(SERVER)
        client = WSConnection(CLIENT)
        server.receive_bytes(client.send(Request(host="localhost", target="foo")))
        event = next(server.events())
        assert isinstance(event, Request)

        client.receive_bytes(server.send(AcceptConnection()))
        assert isinstance(next(client.events()), AcceptConnection)

        return client, server

    def test_negotiation(self):
        self.create_connection()

    @pytest.mark.parametrize(
        "as_client,final", [(True, True), (True, False), (False, True), (False, False)]
    )
    def test_send_and_receive(self, as_client, final):
        client, server = self.create_connection()
        if as_client:
            me = client
            them = server
        else:
            me = server
            them = client

        data = b"x" * 23

        them.receive_bytes(me.send(Message(data=data, message_finished=final)))

        event = next(them.events())
        assert isinstance(event, BytesMessage)
        assert event.data == data
        assert event.message_finished is final

    @pytest.mark.parametrize(
        "as_client,code,reason",
        [
            (True, CloseReason.NORMAL_CLOSURE, u"bye"),
            (True, CloseReason.GOING_AWAY, u"👋👋"),
            (False, CloseReason.NORMAL_CLOSURE, u"bye"),
            (False, CloseReason.GOING_AWAY, u"👋👋"),
        ],
    )
    def test_close(self, as_client, code, reason):
        client, server = self.create_connection()
        if as_client:
            me = client
            them = server
        else:
            me = server
            them = client

        them.receive_bytes(me.send(CloseConnection(code=code, reason=reason)))

        event = next(them.events())
        assert isinstance(event, CloseConnection)
        assert event.code is code
        assert event.reason == reason

    @pytest.mark.parametrize("swap", [True, False])
    def test_normal_closure(self, swap):
        if swap:
            completor, initiator = self.create_connection()
        else:
            initiator, completor = self.create_connection()

        # initiator sends CLOSE to completor
        completor.receive_bytes(
            initiator.send(CloseConnection(code=CloseReason.NORMAL_CLOSURE))
        )
        assert initiator.state is ConnectionState.LOCAL_CLOSING

        # completor emits Close
        close = next(completor.events())
        assert isinstance(close, CloseConnection)

        # completor enters REMOTE_CLOSING state
        assert completor.state is ConnectionState.REMOTE_CLOSING
        with pytest.raises(StopIteration):
            next(completor.events())

        # completor sends CLOSE back to initiator
        initiator.receive_bytes(completor.send(close.response()))

        # initiator emits Close
        assert isinstance(next(initiator.events()), CloseConnection)

        # initiator enters CLOSED state
        assert initiator.state is ConnectionState.CLOSED
        assert completor.state is ConnectionState.CLOSED
        with pytest.raises(StopIteration):
            next(initiator.events())

        with pytest.raises(LocalProtocolError):
            initiator.receive_bytes(b"Any data")

    def test_abnormal_closure(self):
        client, server = self.create_connection()

        for conn in (client, server):
            conn.receive_bytes(None)
            event = next(conn.events())
            assert isinstance(event, CloseConnection)
            assert event.code is CloseReason.ABNORMAL_CLOSURE
            assert conn.state is ConnectionState.CLOSED

    def test_close_before_handshake(self):
        client = WSConnection(CLIENT)
        with pytest.raises(LocalProtocolError):
            client.send(CloseConnection(code=CloseReason.NORMAL_CLOSURE))

    def test_close_when_closing(self):
        client, _ = self.create_connection()
        client.send(CloseConnection(code=CloseReason.NORMAL_CLOSURE))
        with pytest.raises(LocalProtocolError):
            client.send(CloseConnection(code=CloseReason.NORMAL_CLOSURE))

    @pytest.mark.parametrize("as_client", [True, False])
    def test_ping_pong(self, as_client):
        client, server = self.create_connection()
        if as_client:
            me = client
            them = server
        else:
            me = server
            them = client

        payload = b"x" * 23

        # Send a PING message
        wire_data = me.send(Ping(payload=payload))

        # Verify that the peer emits the Ping event with the correct
        # payload.
        them.receive_bytes(wire_data)
        event = next(them.events())
        assert isinstance(event, Ping)
        assert event.payload == payload
        with pytest.raises(StopIteration):
            repr(next(them.events()))

        # Let the peer send the automatic PONG message
        wire_data = them.send(event.response())
        assert wire_data[0] == 0x8A
        masked = bool(wire_data[1] & 0x80)
        assert wire_data[1] & ~0x80 == len(payload)
        if masked:
            maskbytes = itertools.cycle(bytearray(wire_data[2:6]))
            data = bytearray(b ^ next(maskbytes) for b in bytearray(wire_data[6:]))
        else:
            data = wire_data[2:]
        assert data == payload

        # Verify that connection emits the Pong event with the correct
        # payload.
        me.receive_bytes(wire_data)
        event = next(me.events())
        assert isinstance(event, Pong)
        assert event.payload == payload
        with pytest.raises(StopIteration):
            repr(next(me.events()))

    @pytest.mark.parametrize(
        "payload, expected_payload",
        [(b"", b""), (b"abcdef", b"abcdef")],
        ids=["nopayload", "payload"],
    )
    def test_unsolicited_pong(self, payload, expected_payload):
        client, server = self.create_connection()
        wire_data = client.send(Pong(payload=payload))
        server.receive_bytes(wire_data)
        events = list(server.events())
        assert len(events) == 1
        assert isinstance(events[0], Pong)
        assert events[0].payload == expected_payload

    @pytest.mark.parametrize(
        "text,payload,full_message,full_frame",
        [
            (True, u"ƒñö®∂😎", True, True),
            (True, u"ƒñö®∂😎", False, True),
            (True, u"ƒñö®∂😎", False, False),
            (False, b"x" * 23, True, True),
            (False, b"x" * 23, False, True),
            (False, b"x" * 23, False, False),
        ],
    )
    def test_data_events(self, text, payload, full_message, full_frame):
        if text:
            opcode = 0x01
            encoded_payload = payload.encode("utf8")
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

        connection = WSConnection(CLIENT)
        connection.send(Request(host="localhost", target="foo"))
        connection._proto = FrameProtocol(True, [])
        connection._state = ConnectionState.OPEN

        connection.receive_bytes(frame)
        event = next(connection.events())
        if text:
            assert isinstance(event, TextMessage)
        else:
            assert isinstance(event, BytesMessage)
        assert event.data == payload
        assert event.frame_finished is full_frame
        assert event.message_finished is full_message

    def test_frame_protocol_somehow_loses_its_mind(self):
        class FailFrame(object):
            opcode = object()

        class DoomProtocol(object):
            def receive_bytes(self, data):
                return None

            def received_frames(self):
                return [FailFrame()]

        connection = WSConnection(CLIENT)
        connection.send(Request(host="localhost", target="foo"))
        connection._proto = DoomProtocol()
        connection._state = ConnectionState.OPEN

        connection.receive_bytes(b"")
        with pytest.raises(StopIteration):
            next(connection.events())

    def test_frame_protocol_gets_fed_garbage(self):
        client, server = self.create_connection()

        payload = b"x" * 23
        frame = b"\x09" + bytearray([len(payload)]) + payload

        client.receive_bytes(frame)
        event = next(client.events())
        assert isinstance(event, CloseConnection)
        assert event.code == CloseReason.PROTOCOL_ERROR

        output = client.send(event.response())
        assert output[:1] == b"\x88"
