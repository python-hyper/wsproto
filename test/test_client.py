# These tests test the behaviours expected of wsproto in when the
# connection is a client.
from typing import List, Optional, Tuple

import h11
import pytest

from wsproto import WSConnection
from wsproto.connection import CLIENT
from wsproto.events import (
    AcceptConnection,
    Event,
    RejectConnection,
    RejectData,
    Request,
)
from wsproto.extensions import Extension
from wsproto.frame_protocol import CloseReason
from wsproto.typing import Headers
from wsproto.utilities import (
    generate_accept_token,
    normed_header_dict,
    RemoteProtocolError,
)
from .helpers import FakeExtension


def _make_connection_request(request: Request) -> h11.Request:
    client = WSConnection(CLIENT)
    server = h11.Connection(h11.SERVER)
    server.receive_data(client.send(request))
    return server.next_event()


def test_connection_request() -> None:
    request = _make_connection_request(Request(host="localhost", target="/"))

    assert request.http_version == b"1.1"
    assert request.method == b"GET"
    assert request.target == b"/"
    headers = normed_header_dict(request.headers)
    assert headers[b"connection"] == b"Upgrade"
    assert headers[b"host"] == b"localhost"
    assert headers[b"sec-websocket-version"] == b"13"
    assert headers[b"upgrade"] == b"WebSocket"
    assert b"sec-websocket-key" in headers


def test_connection_request_additional_headers() -> None:
    request = _make_connection_request(
        Request(
            host="localhost",
            target="/",
            extra_headers=[(b"X-Foo", b"Bar"), (b"X-Bar", b"Foo")],
        )
    )

    headers = normed_header_dict(request.headers)
    assert headers[b"x-foo"] == b"Bar"
    assert headers[b"x-bar"] == b"Foo"


def test_connection_request_simple_extension() -> None:
    extension = FakeExtension(offer_response=True)
    request = _make_connection_request(
        Request(host="localhost", target="/", extensions=[extension])
    )

    headers = normed_header_dict(request.headers)
    assert headers[b"sec-websocket-extensions"] == extension.name.encode("ascii")


def test_connection_request_simple_extension_no_offer() -> None:
    extension = FakeExtension(offer_response=False)
    request = _make_connection_request(
        Request(host="localhost", target="/", extensions=[extension])
    )

    headers = normed_header_dict(request.headers)
    assert b"sec-websocket-extensions" not in headers


def test_connection_request_parametrised_extension() -> None:
    offer_response = "parameter1=value1; parameter2=value2"
    extension = FakeExtension(offer_response=offer_response)
    request = _make_connection_request(
        Request(host="localhost", target="/", extensions=[extension])
    )

    headers = normed_header_dict(request.headers)
    assert headers[b"sec-websocket-extensions"] == b"%s; %s" % (
        extension.name.encode("ascii"),
        offer_response.encode("ascii"),
    )


def test_connection_request_subprotocols() -> None:
    request = _make_connection_request(
        Request(host="localhost", target="/", subprotocols=["one", "two"])
    )

    headers = normed_header_dict(request.headers)
    assert headers[b"sec-websocket-protocol"] == b"one, two"


def _make_handshake(
    response_status: int,
    response_headers: Headers,
    subprotocols: Optional[List[str]] = None,
    extensions: Optional[List[Extension]] = None,
    auto_accept_key: bool = True,
) -> List[Event]:
    client = WSConnection(CLIENT)
    server = h11.Connection(h11.SERVER)
    server.receive_data(
        client.send(
            Request(
                host="localhost",
                target="/",
                subprotocols=subprotocols or [],
                extensions=extensions or [],
            )
        )
    )
    request = server.next_event()
    if auto_accept_key:
        full_request_headers = normed_header_dict(request.headers)
        response_headers.append(
            (
                b"Sec-WebSocket-Accept",
                generate_accept_token(full_request_headers[b"sec-websocket-key"]),
            )
        )
    response = h11.InformationalResponse(
        status_code=response_status, headers=response_headers
    )
    client.receive_data(server.send(response))

    return list(client.events())


def test_handshake() -> None:
    events = _make_handshake(
        101, [(b"connection", b"Upgrade"), (b"upgrade", b"WebSocket")]
    )
    assert events == [AcceptConnection()]


def test_broken_handshake() -> None:
    events = _make_handshake(
        102, [(b"connection", b"Upgrade"), (b"upgrade", b"WebSocket")]
    )
    assert isinstance(events[0], RejectConnection)
    assert events[0].status_code == 102


def test_handshake_extra_accept_headers() -> None:
    events = _make_handshake(
        101,
        [(b"connection", b"Upgrade"), (b"upgrade", b"WebSocket"), (b"X-Foo", b"bar")],
    )
    assert events == [AcceptConnection(extra_headers=[(b"x-foo", b"bar")])]


@pytest.mark.parametrize("extra_headers", [[], [(b"connection", b"Keep-Alive")]])
def test_handshake_response_broken_connection_header(extra_headers: Headers) -> None:
    with pytest.raises(RemoteProtocolError) as excinfo:
        events = _make_handshake(101, [(b"upgrade", b"WebSocket")] + extra_headers)
    assert str(excinfo.value) == "Missing header, 'Connection: Upgrade'"


@pytest.mark.parametrize("extra_headers", [[], [(b"upgrade", b"h2")]])
def test_handshake_response_broken_upgrade_header(extra_headers: Headers) -> None:
    with pytest.raises(RemoteProtocolError) as excinfo:
        events = _make_handshake(101, [(b"connection", b"Upgrade")] + extra_headers)
    assert str(excinfo.value) == "Missing header, 'Upgrade: WebSocket'"


def test_handshake_response_missing_websocket_key_header() -> None:
    with pytest.raises(RemoteProtocolError) as excinfo:
        events = _make_handshake(
            101,
            [(b"connection", b"Upgrade"), (b"upgrade", b"WebSocket")],
            auto_accept_key=False,
        )
    assert str(excinfo.value) == "Bad accept token"


def test_handshake_with_subprotocol() -> None:
    events = _make_handshake(
        101,
        [
            (b"connection", b"Upgrade"),
            (b"upgrade", b"WebSocket"),
            (b"sec-websocket-protocol", b"one"),
        ],
        subprotocols=["one", "two"],
    )
    assert events == [AcceptConnection(subprotocol="one")]


def test_handshake_bad_subprotocol() -> None:
    with pytest.raises(RemoteProtocolError) as excinfo:
        events = _make_handshake(
            101,
            [
                (b"connection", b"Upgrade"),
                (b"upgrade", b"WebSocket"),
                (b"sec-websocket-protocol", b"new"),
            ],
        )
    assert str(excinfo.value) == "unrecognized subprotocol new"


def test_handshake_with_extension() -> None:
    extension = FakeExtension(offer_response=True)
    events = _make_handshake(
        101,
        [
            (b"connection", b"Upgrade"),
            (b"upgrade", b"WebSocket"),
            (b"sec-websocket-extensions", b"fake"),
        ],
        extensions=[extension],
    )
    assert events == [AcceptConnection(extensions=[extension])]


def test_handshake_bad_extension() -> None:
    with pytest.raises(RemoteProtocolError) as excinfo:
        events = _make_handshake(
            101,
            [
                (b"connection", b"Upgrade"),
                (b"upgrade", b"WebSocket"),
                (b"sec-websocket-extensions", b"bad, foo"),
            ],
        )
    assert str(excinfo.value) == "unrecognized extension bad"


def test_protocol_error() -> None:
    client = WSConnection(CLIENT)
    client.send(Request(host="localhost", target="/"))
    with pytest.raises(RemoteProtocolError) as excinfo:
        client.receive_data(b"broken nonsense\r\n\r\n")
    assert str(excinfo.value) == "Bad HTTP message"


def _make_handshake_rejection(
    status_code: int, body: Optional[bytes] = None
) -> List[Event]:
    client = WSConnection(CLIENT)
    server = h11.Connection(h11.SERVER)
    server.receive_data(client.send(Request(host="localhost", target="/")))
    headers = []
    if body is not None:
        headers.append(("Content-Length", str(len(body))))
    client.receive_data(
        server.send(h11.Response(status_code=status_code, headers=headers))
    )
    if body is not None:
        client.receive_data(server.send(h11.Data(data=body)))
    client.receive_data(server.send(h11.EndOfMessage()))

    return list(client.events())


def test_handshake_rejection() -> None:
    events = _make_handshake_rejection(400)
    assert events == [
        RejectConnection(
            headers=[(b"connection", b"close")], has_body=True, status_code=400
        ),
        RejectData(body_finished=True, data=b""),
    ]


def test_handshake_rejection_with_body() -> None:
    events = _make_handshake_rejection(400, b"Hello")
    assert events == [
        RejectConnection(
            headers=[(b"content-length", b"5")], has_body=True, status_code=400
        ),
        RejectData(body_finished=False, data=b"Hello"),
        RejectData(body_finished=True, data=b""),
    ]
