# These tests test the behaviours expected of wsproto in when the
# connection is a server.
from typing import cast, List, Optional, Tuple

import h11
import pytest

from wsproto import WSConnection
from wsproto.connection import SERVER
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
    generate_nonce,
    normed_header_dict,
    RemoteProtocolError,
)
from .helpers import FakeExtension


def _make_connection_request(request_headers: Headers, method: str = "GET") -> Request:
    client = h11.Connection(h11.CLIENT)
    server = WSConnection(SERVER)
    server.receive_data(
        client.send(h11.Request(method=method, target="/", headers=request_headers))
    )
    event = next(server.events())
    assert isinstance(event, Request)
    return event


def test_connection_request() -> None:
    event = _make_connection_request(
        [
            (b"Host", b"localhost"),
            (b"Connection", b"Keep-Alive, Upgrade"),
            (b"Upgrade", b"WebSocket"),
            (b"Sec-WebSocket-Version", b"13"),
            (b"Sec-WebSocket-Key", generate_nonce()),
            (b"X-Foo", b"bar"),
        ]
    )

    assert event.extensions == []
    assert event.host == "localhost"
    assert event.subprotocols == []
    assert event.target == "/"
    headers = normed_header_dict(event.extra_headers)
    assert b"host" not in headers
    assert b"sec-websocket-extensions" not in headers
    assert b"sec-websocket-protocol" not in headers
    assert headers[b"connection"] == b"Keep-Alive, Upgrade"
    assert headers[b"sec-websocket-version"] == b"13"
    assert headers[b"upgrade"] == b"WebSocket"
    assert headers[b"x-foo"] == b"bar"


def test_connection_request_bad_method() -> None:
    with pytest.raises(RemoteProtocolError) as excinfo:
        event = _make_connection_request(
            [
                (b"Host", b"localhost"),
                (b"Connection", b"Keep-Alive, Upgrade"),
                (b"Upgrade", b"WebSocket"),
                (b"Sec-WebSocket-Version", b"13"),
                (b"Sec-WebSocket-Key", generate_nonce()),
            ],
            method="POST",
        )
    assert str(excinfo.value) == "Request method must be GET"


def test_connection_request_bad_connection_header() -> None:
    with pytest.raises(RemoteProtocolError) as excinfo:
        event = _make_connection_request(
            [
                (b"Host", b"localhost"),
                (b"Connection", b"Keep-Alive, No-Upgrade"),
                (b"Upgrade", b"WebSocket"),
                (b"Sec-WebSocket-Version", b"13"),
                (b"Sec-WebSocket-Key", generate_nonce()),
            ]
        )
    assert str(excinfo.value) == "Missing header, 'Connection: Upgrade'"


def test_connection_request_bad_upgrade_header() -> None:
    with pytest.raises(RemoteProtocolError) as excinfo:
        event = _make_connection_request(
            [
                (b"Host", b"localhost"),
                (b"Connection", b"Keep-Alive, Upgrade"),
                (b"Upgrade", b"h2c"),
                (b"Sec-WebSocket-Version", b"13"),
                (b"Sec-WebSocket-Key", generate_nonce()),
            ]
        )
    assert str(excinfo.value) == "Missing header, 'Upgrade: WebSocket'"


@pytest.mark.parametrize("version", [b"12", b"not-a-digit"])
def test_connection_request_bad_version_header(version: bytes) -> None:
    with pytest.raises(RemoteProtocolError) as excinfo:
        event = _make_connection_request(
            [
                (b"Host", b"localhost"),
                (b"Connection", b"Keep-Alive, Upgrade"),
                (b"Upgrade", b"WebSocket"),
                (b"Sec-WebSocket-Version", version),
                (b"Sec-WebSocket-Key", generate_nonce()),
            ]
        )
    assert str(excinfo.value) == "Missing header, 'Sec-WebSocket-Version'"
    assert excinfo.value.event_hint == RejectConnection(
        headers=[(b"Sec-WebSocket-Version", b"13")], status_code=426
    )


def test_connection_request_key_header() -> None:
    with pytest.raises(RemoteProtocolError) as excinfo:
        event = _make_connection_request(
            [
                (b"Host", b"localhost"),
                (b"Connection", b"Keep-Alive, Upgrade"),
                (b"Upgrade", b"WebSocket"),
                (b"Sec-WebSocket-Version", b"13"),
            ]
        )
    assert str(excinfo.value) == "Missing header, 'Sec-WebSocket-Key'"


def test_upgrade_request() -> None:
    server = WSConnection(SERVER)
    server.initiate_upgrade_connection(
        [
            (b"Host", b"localhost"),
            (b"Connection", b"Keep-Alive, Upgrade"),
            (b"Upgrade", b"WebSocket"),
            (b"Sec-WebSocket-Version", b"13"),
            (b"Sec-WebSocket-Key", generate_nonce()),
            (b"X-Foo", b"bar"),
        ],
        "/",
    )
    event = next(server.events())
    event = cast(Request, event)

    assert event.extensions == []
    assert event.host == "localhost"
    assert event.subprotocols == []
    assert event.target == "/"
    headers = normed_header_dict(event.extra_headers)
    assert b"host" not in headers
    assert b"sec-websocket-extensions" not in headers
    assert b"sec-websocket-protocol" not in headers
    assert headers[b"connection"] == b"Keep-Alive, Upgrade"
    assert headers[b"sec-websocket-version"] == b"13"
    assert headers[b"upgrade"] == b"WebSocket"
    assert headers[b"x-foo"] == b"bar"


def _make_handshake(
    request_headers: Headers,
    accept_headers: Optional[Headers] = None,
    subprotocol: Optional[str] = None,
    extensions: Optional[List[Extension]] = None,
) -> Tuple[h11.InformationalResponse, bytes]:
    client = h11.Connection(h11.CLIENT)
    server = WSConnection(SERVER)
    nonce = generate_nonce()
    server.receive_data(
        client.send(
            h11.Request(
                method="GET",
                target="/",
                headers=[
                    (b"Host", b"localhost"),
                    (b"Connection", b"Keep-Alive, Upgrade"),
                    (b"Upgrade", b"WebSocket"),
                    (b"Sec-WebSocket-Version", b"13"),
                    (b"Sec-WebSocket-Key", nonce),
                ]
                + request_headers,
            )
        )
    )
    client.receive_data(
        server.send(
            AcceptConnection(
                extra_headers=accept_headers or [],
                subprotocol=subprotocol,
                extensions=extensions or [],
            )
        )
    )
    event = client.next_event()
    return event, nonce


def test_handshake() -> None:
    response, nonce = _make_handshake([])

    response.headers = sorted(response.headers)  # For test determinism
    assert response == h11.InformationalResponse(
        status_code=101,
        headers=[
            (b"connection", b"Upgrade"),
            (b"sec-websocket-accept", generate_accept_token(nonce)),
            (b"upgrade", b"WebSocket"),
        ],
    )


def test_handshake_extra_headers() -> None:
    response, nonce = _make_handshake([], accept_headers=[(b"X-Foo", b"bar")])

    response.headers = sorted(response.headers)  # For test determinism
    assert response == h11.InformationalResponse(
        status_code=101,
        headers=[
            (b"connection", b"Upgrade"),
            (b"sec-websocket-accept", generate_accept_token(nonce)),
            (b"upgrade", b"WebSocket"),
            (b"x-foo", b"bar"),
        ],
    )


@pytest.mark.parametrize("accept_subprotocol", ["one", "two"])
def test_handshake_with_subprotocol(accept_subprotocol: str) -> None:
    response, _ = _make_handshake(
        [(b"Sec-Websocket-Protocol", b"one, two")], subprotocol=accept_subprotocol
    )

    headers = normed_header_dict(response.headers)
    assert headers[b"sec-websocket-protocol"] == accept_subprotocol.encode("ascii")


def test_handshake_with_extension() -> None:
    extension = FakeExtension(accept_response=True)
    response, _ = _make_handshake(
        [(b"Sec-Websocket-Extensions", extension.name.encode("ascii"))],
        extensions=[extension],
    )

    headers = normed_header_dict(response.headers)
    assert headers[b"sec-websocket-extensions"] == extension.name.encode("ascii")


def test_handshake_with_extension_params() -> None:
    offered_params = "parameter1=value3; parameter2=value4"
    accepted_params = "parameter1=value1; parameter2=value2"
    extension = FakeExtension(accept_response=accepted_params)
    response, _ = _make_handshake(
        [
            (
                b"Sec-Websocket-Extensions",
                ("%s; %s" % (extension.name, offered_params)).encode("ascii"),
            )
        ],
        extensions=[extension],
    )

    headers = normed_header_dict(response.headers)
    assert extension.offered == "%s; %s" % (extension.name, offered_params)
    assert headers[b"sec-websocket-extensions"] == (
        "%s; %s" % (extension.name, accepted_params)
    ).encode("ascii")


def test_handshake_with_extra_unaccepted_extension() -> None:
    extension = FakeExtension(accept_response=True)
    response, _ = _make_handshake(
        [
            (
                b"Sec-Websocket-Extensions",
                b"pretend, %s" % extension.name.encode("ascii"),
            )
        ],
        extensions=[extension],
    )

    headers = normed_header_dict(response.headers)
    assert headers[b"sec-websocket-extensions"] == extension.name.encode("ascii")


def test_protocol_error() -> None:
    server = WSConnection(SERVER)
    with pytest.raises(RemoteProtocolError) as excinfo:
        server.receive_data(b"broken nonsense\r\n\r\n")
    assert str(excinfo.value) == "Bad HTTP message"


def _make_handshake_rejection(
    status_code: int, body: Optional[bytes] = None
) -> List[Event]:
    client = h11.Connection(h11.CLIENT)
    server = WSConnection(SERVER)
    nonce = generate_nonce()
    server.receive_data(
        client.send(
            h11.Request(
                method="GET",
                target="/",
                headers=[
                    (b"Host", b"localhost"),
                    (b"Connection", b"Keep-Alive, Upgrade"),
                    (b"Upgrade", b"WebSocket"),
                    (b"Sec-WebSocket-Version", b"13"),
                    (b"Sec-WebSocket-Key", nonce),
                ],
            )
        )
    )
    if body is not None:
        client.receive_data(
            server.send(
                RejectConnection(
                    headers=[(b"content-length", b"%d" % len(body))],
                    status_code=status_code,
                    has_body=True,
                )
            )
        )
        client.receive_data(server.send(RejectData(data=body)))
    else:
        client.receive_data(server.send(RejectConnection(status_code=status_code)))
    events = []
    while True:
        event = client.next_event()
        events.append(event)
        if isinstance(event, h11.EndOfMessage):
            return events


def test_handshake_rejection() -> None:
    events = _make_handshake_rejection(400)
    assert events == [
        h11.Response(headers=[(b"content-length", b"0")], status_code=400),
        h11.EndOfMessage(),
    ]


def test_handshake_rejection_with_body() -> None:
    events = _make_handshake_rejection(400, body=b"Hello")
    assert events == [
        h11.Response(headers=[(b"content-length", b"5")], status_code=400),
        h11.Data(data=b"Hello"),
        h11.EndOfMessage(),
    ]
