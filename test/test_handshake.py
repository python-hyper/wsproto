import pytest

from wsproto.connection import CLIENT, ConnectionState, SERVER
from wsproto.events import AcceptConnection, Ping, RejectConnection, Request
from wsproto.handshake import H11Handshake
from wsproto.utilities import LocalProtocolError


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


def test_initiate_upgrade_as_client():
    client = H11Handshake(CLIENT)
    with pytest.raises(LocalProtocolError):
        client.initiate_upgrade_connection([], "/")


def test_send_invalid_event():
    client = H11Handshake(CLIENT)
    with pytest.raises(LocalProtocolError):
        client.send(Ping())
