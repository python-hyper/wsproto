from __future__ import annotations

import pytest

from wsproto.connection import CLIENT, SERVER, ConnectionState
from wsproto.events import AcceptConnection, Ping, RejectConnection, Request
from wsproto.handshake import H11Handshake
from wsproto.utilities import LocalProtocolError, RemoteProtocolError, generate_accept_token


def test_successful_handshake() -> None:
    client = H11Handshake(CLIENT)
    server = H11Handshake(SERVER)

    server.receive_data(client.send(Request(host="localhost", target="/")))
    assert isinstance(next(server.events()), Request)

    client.receive_data(server.send(AcceptConnection()))
    assert isinstance(next(client.events()), AcceptConnection)

    assert client.state is ConnectionState.OPEN
    assert server.state is ConnectionState.OPEN

    assert repr(client) == "H11Handshake(client=True, state=ConnectionState.OPEN)"
    assert repr(server) == "H11Handshake(client=False, state=ConnectionState.OPEN)"


def test_host_encoding() -> None:
    client = H11Handshake(CLIENT)
    server = H11Handshake(SERVER)
    data = client.send(Request(host="芝士汉堡", target="/"))
    assert b"Host: xn--7ks3rz39bh7u" in data
    server.receive_data(data)
    request = next(server.events())
    assert isinstance(request, Request)
    assert request.host == "芝士汉堡"


@pytest.mark.parametrize("http", [b"HTTP/1.0", b"HTTP/1.1"])
def test_rejected_handshake(http: bytes) -> None:
    server = H11Handshake(SERVER)
    with pytest.raises(RemoteProtocolError):
        server.receive_data(
            b"GET / " + http + b"\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Key: VQr8cvwwZ1fEk62PDq8J3A==\r\n"
            b"Sec-WebSocket-Version: 13\r\n"
            b"\r\n",
        )


def test_initiate_upgrade_as_client() -> None:
    client = H11Handshake(CLIENT)
    with pytest.raises(LocalProtocolError):
        client.initiate_upgrade_connection([], "/")


def test_send_invalid_event() -> None:
    client = H11Handshake(CLIENT)
    with pytest.raises(LocalProtocolError):
        client.send(Ping())


def test_h11_multiple_headers_handshake() -> None:
    server = H11Handshake(SERVER)
    data = (
        b"GET wss://api.website.xyz/ws HTTP/1.1\r\n"
        b"Host: api.website.xyz\r\n"
        b"Connection: Upgrade\r\n"
        b"Pragma: no-cache\r\n"
        b"Cache-Control: no-cache\r\n"
        b"User-Agent: Mozilla/5.0 (X11; Linux x86_64) "
        b"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.5060.114 Safari/537.36\r\n"
        b"Upgrade: websocket\r\n"
        b"Origin: https://website.xyz\r\n"
        b"Sec-WebSocket-Version: 13\r\n"
        b"Accept-Encoding: gzip, deflate, br\r\n"
        b"Accept-Language: ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7\r\n"
        b"Sec-WebSocket-Key: tOzeAzi9xK7ADxxEdTzmaA==\r\n"
        b"Sec-WebSocket-Extensions: this-extension; isnt-seen, even-tho, it-should-be\r\n"
        b"Sec-WebSocket-Protocol: there-protocols\r\n"
        b"Sec-WebSocket-Protocol: arent-seen\r\n"
        b"Sec-WebSocket-Extensions: this-extension; were-gonna-see, and-another-extension; were-also; gonna-see=100; percent\r\n"
        b"Sec-WebSocket-Protocol: only-these-protocols, are-seen, from-the-request-object\r\n"
        b"\r\n"
    )
    server.receive_data(data)
    request = next(server.events())
    assert isinstance(request, Request)
    assert request.subprotocols == [
        "there-protocols",
        "arent-seen",
        "only-these-protocols",
        "are-seen",
        "from-the-request-object",
    ]
    assert request.extensions == [
        "this-extension; isnt-seen",
        "even-tho",
        "it-should-be",
        "this-extension; were-gonna-see",
        "and-another-extension; were-also; gonna-see=100; percent",
    ]


def _assert_rejection(excinfo: pytest.ExceptionInfo[RemoteProtocolError]) -> None:
    hint = excinfo.value.event_hint
    assert isinstance(hint, RejectConnection)
    assert hint.status_code == 400


@pytest.mark.parametrize(
    "header",
    [
        b"Host: \xff\xfe",
        b"Host: localhost\r\nConnection: Upgrade, \xff",
        b"Host: localhost\r\nSec-WebSocket-Extensions: \xff",
        b"Host: localhost\r\nSec-WebSocket-Protocol: \xff",
    ],
)
def test_obs_text_header_rejected(header: bytes) -> None:
    # obs-text (non-ASCII) bytes in these header values must be rejected
    # with a RemoteProtocolError, not an uncaught UnicodeDecodeError.
    server = H11Handshake(SERVER)
    with pytest.raises(RemoteProtocolError) as excinfo:
        server.receive_data(
            b"GET / HTTP/1.1\r\n" + header + b"\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Key: VQr8cvwwZ1fEk62PDq8J3A==\r\n"
            b"Sec-WebSocket-Version: 13\r\n"
            b"\r\n",
        )
    _assert_rejection(excinfo)


def test_obs_text_response_header_rejected() -> None:
    # obs-text in a handshake response header value must be rejected with a
    # RemoteProtocolError, not an uncaught UnicodeDecodeError.
    client = H11Handshake(CLIENT)
    data = client.send(Request(host="localhost", target="/"))
    key = b""
    for line in data.split(b"\r\n"):
        if line.lower().startswith(b"sec-websocket-key: "):
            key = line.split(b": ", 1)[1]
    accept = generate_accept_token(key)
    with pytest.raises(RemoteProtocolError) as excinfo:
        client.receive_data(
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + accept + b"\r\n"
            b"Sec-WebSocket-Protocol: \xff\r\n"
            b"\r\n",
        )
    _assert_rejection(excinfo)
