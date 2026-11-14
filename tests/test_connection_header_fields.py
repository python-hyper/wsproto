"""Combine Connection tokens from every field line during the handshake."""

from __future__ import annotations

import pytest

from wsproto import ConnectionType, WSConnection
from wsproto.connection import ConnectionState
from wsproto.events import AcceptConnection, BytesMessage, Request
from wsproto.utilities import RemoteProtocolError


@pytest.mark.parametrize("server_side", [False, True])
@pytest.mark.parametrize("chunk_size", [1, 65536])
@pytest.mark.parametrize(
    ("values", "accepted"),
    [
        ([b"Upgrade", b"keep-alive"], True),
        ([b"keep-alive", b"Upgrade"], True),
        ([b"keep-alive", b"uPgRaDe", b"custom-hop"], True),
        ([b"keep-alive, uPgRaDe"], True),
        ([b"keep-alive", b"close"], False),
        ([], False),
    ],
)
def test_connection_field_lines(
    server_side: bool,
    chunk_size: int,
    values: list[bytes],
    accepted: bool,
) -> None:
    client = WSConnection(ConnectionType.CLIENT)
    server = WSConnection(ConnectionType.SERVER)
    wire = client.send(Request(host="localhost", target="/"))
    receiver = server
    if not server_side:
        server.receive_data(wire)
        assert isinstance(next(server.events()), Request)
        wire = server.send(AcceptConnection())
        receiver = client

    replacement = b"".join((b"Connection" if index % 2 == 0 else b"cOnNeCtIoN") + b": " + value + b"\r\n" for index, value in enumerate(values))
    assert b"Connection: Upgrade\r\n" in wire
    wire = wire.replace(b"Connection: Upgrade\r\n", replacement)

    def receive() -> None:
        for offset in range(0, len(wire), chunk_size):
            receiver.receive_data(wire[offset : offset + chunk_size])

    if not accepted:
        with pytest.raises(RemoteProtocolError, match="Missing header, 'Connection: Upgrade'"):
            receive()
        return

    receive()
    event = next(receiver.events())
    assert isinstance(event, Request if server_side else AcceptConnection)
    if server_side:
        client.receive_data(server.send(AcceptConnection()))
        assert isinstance(next(client.events()), AcceptConnection)
    assert client.state is ConnectionState.OPEN
    assert server.state is ConnectionState.OPEN

    payload = b"\x00\x01\x00\xff" * 40
    server.receive_data(client.send(BytesMessage(data=payload)))
    assert b"".join(event.data for event in server.events() if isinstance(event, BytesMessage)) == payload
