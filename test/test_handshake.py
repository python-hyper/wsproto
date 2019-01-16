import pytest

from wsproto.connection import CLIENT, ConnectionState, SERVER
from wsproto.events import AcceptConnection, RejectConnection, Request
from wsproto.handshake import H11Handshake


def test_successful_handshake():
    client = H11Handshake(CLIENT)
    server = H11Handshake(SERVER)

    server.receive_data(client.send(Request(host="localhost", target="/")))
    assert isinstance(next(server.events()), Request)

    client.receive_data(server.send(AcceptConnection()))
    assert isinstance(next(client.events()), AcceptConnection)

    assert client.state is ConnectionState.OPEN
    assert server.state is ConnectionState.OPEN


def test_rejected_handshake():
    client = H11Handshake(CLIENT)
    server = H11Handshake(SERVER)

    server.receive_data(client.send(Request(host="localhost", target="/")))
    assert isinstance(next(server.events()), Request)

    client.receive_data(server.send(RejectConnection()))
    assert isinstance(next(client.events()), RejectConnection)

    assert client.state is ConnectionState.CLOSED
    assert server.state is ConnectionState.CLOSED
