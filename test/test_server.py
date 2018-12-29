# These tests test the behaviours expected of wsproto in when the
# connection is a server.

import h11
import pytest

from wsproto.connection import SERVER, WSConnection
from wsproto.events import AcceptConnection, Fail, RejectConnection, RejectData, Request
from wsproto.frame_protocol import CloseReason
from wsproto.utilities import generate_accept_token, generate_nonce, normed_header_dict
from .helpers import FakeExtension


def _make_connection_request(request_headers, method="GET"):
    # type: (List[Tuple[str, str]]) -> Union[Request, Fail]
    client = h11.Connection(h11.CLIENT)
    server = WSConnection(SERVER)
    server.receive_bytes(
        client.send(h11.Request(method=method, target="/", headers=request_headers))
    )
    return next(server.events())


def test_connection_request():
    event = _make_connection_request(
        [
            ("Host", "localhost"),
            ("Connection", "Keep-Alive, Upgrade"),
            ("Upgrade", "WebSocket"),
            ("Sec-WebSocket-Version", "13"),
            ("Sec-WebSocket-Key", generate_nonce()),
            ("X-Foo", "bar"),
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


def test_connection_request_bad_method():
    event = _make_connection_request(
        [
            ("Host", "localhost"),
            ("Connection", "Keep-Alive, Upgrade"),
            ("Upgrade", "WebSocket"),
            ("Sec-WebSocket-Version", "13"),
            ("Sec-WebSocket-Key", generate_nonce()),
        ],
        method="POST",
    )
    assert event == Fail(
        code=CloseReason.PROTOCOL_ERROR, reason="Request method must be GET"
    )


def test_connection_request_bad_connection_header():
    event = _make_connection_request(
        [
            ("Host", "localhost"),
            ("Connection", "Keep-Alive, No-Upgrade"),
            ("Upgrade", "WebSocket"),
            ("Sec-WebSocket-Version", "13"),
            ("Sec-WebSocket-Key", generate_nonce()),
        ]
    )
    assert event == Fail(
        code=CloseReason.PROTOCOL_ERROR, reason="Missing Connection: Upgrade header"
    )


def test_connection_request_bad_upgrade_header():
    event = _make_connection_request(
        [
            ("Host", "localhost"),
            ("Connection", "Keep-Alive, Upgrade"),
            ("Upgrade", "h2c"),
            ("Sec-WebSocket-Version", "13"),
            ("Sec-WebSocket-Key", generate_nonce()),
        ]
    )
    assert event == Fail(
        code=CloseReason.PROTOCOL_ERROR, reason="Missing Upgrade: WebSocket header"
    )


@pytest.mark.parametrize("version", ["12", "not-a-digit"])
@pytest.mark.skip  # Will fix in a subsequent commit
def test_connection_request_bad_version_header(version):
    event = _make_connection_request(
        [
            ("Host", "localhost"),
            ("Connection", "Keep-Alive, Upgrade"),
            ("Upgrade", "WebSocket"),
            ("Sec-WebSocket-Version", version),
            ("Sec-WebSocket-Key", generate_nonce()),
        ]
    )
    assert event == Fail(
        code=CloseReason.PROTOCOL_ERROR, reason="Missing Upgrade: WebSocket header"
    )


def test_connection_request_key_header():
    event = _make_connection_request(
        [
            ("Host", "localhost"),
            ("Connection", "Keep-Alive, Upgrade"),
            ("Upgrade", "WebSocket"),
            ("Sec-WebSocket-Version", "13"),
        ]
    )
    assert event == Fail(
        code=CloseReason.PROTOCOL_ERROR, reason="Missing Sec-WebSocket-Key header"
    )


def _make_handshake(request_headers, subprotocol=None, extensions=None):
    client = h11.Connection(h11.CLIENT)
    server = WSConnection(SERVER)
    nonce = generate_nonce()
    server.receive_bytes(
        client.send(
            h11.Request(
                method="GET",
                target="/",
                headers=[
                    ("Host", "localhost"),
                    ("Connection", "Keep-Alive, Upgrade"),
                    ("Upgrade", "WebSocket"),
                    ("Sec-WebSocket-Version", "13"),
                    ("Sec-WebSocket-Key", nonce),
                ]
                + request_headers,
            )
        )
    )
    server.send(AcceptConnection(subprotocol=subprotocol, extensions=extensions or []))
    client.receive_data(server.bytes_to_send())
    event = client.next_event()
    return event, nonce


def test_handshake():
    response, nonce = _make_handshake([])

    response.headers = sorted(response.headers)  # For test determinism
    assert response == h11.InformationalResponse(
        status_code=101,
        headers=[
            ("connection", "Upgrade"),
            ("sec-websocket-accept", generate_accept_token(nonce)),
            ("upgrade", "WebSocket"),
        ],
    )


@pytest.mark.parametrize("accept_subprotocol", ["one", "two"])
def test_handshake_with_subprotocol(accept_subprotocol):
    response, _ = _make_handshake(
        [("Sec-Websocket-Protocol", "one, two")], accept_subprotocol
    )

    headers = normed_header_dict(response.headers)
    assert headers[b"sec-websocket-protocol"] == accept_subprotocol.encode("ascii")


def test_handshake_with_extension():
    extension = FakeExtension(accept_response=True)
    response, _ = _make_handshake(
        [("Sec-Websocket-Extensions", extension.name)], extensions=[extension]
    )

    headers = normed_header_dict(response.headers)
    assert headers[b"sec-websocket-extensions"] == extension.name.encode("ascii")


def test_handshake_with_extension_params():
    offered_params = "parameter1=value3; parameter2=value4"
    accepted_params = "parameter1=value1; parameter2=value2"
    extension = FakeExtension(accept_response=accepted_params)
    response, _ = _make_handshake(
        [("Sec-Websocket-Extensions", "%s; %s" % (extension.name, offered_params))],
        extensions=[extension],
    )

    headers = normed_header_dict(response.headers)
    assert extension.offered == "%s; %s" % (extension.name, offered_params)
    assert headers[b"sec-websocket-extensions"] == (
        "%s; %s" % (extension.name, accepted_params)
    ).encode("ascii")


def test_handshake_with_extra_unaccepted_extension():
    extension = FakeExtension(accept_response=True)
    response, _ = _make_handshake(
        [("Sec-Websocket-Extensions", "pretend, %s" % extension.name)],
        extensions=[extension],
    )

    headers = normed_header_dict(response.headers)
    assert headers[b"sec-websocket-extensions"] == extension.name.encode("ascii")


def test_protocol_error():
    server = WSConnection(SERVER)
    server.receive_bytes(b"broken nonsense\r\n\r\n")
    assert list(server.events()) == [
        Fail(code=CloseReason.PROTOCOL_ERROR, reason="Bad HTTP message")
    ]


def _make_handshake_rejection(status_code, body=None):
    client = h11.Connection(h11.CLIENT)
    server = WSConnection(SERVER)
    nonce = generate_nonce()
    server.receive_bytes(
        client.send(
            h11.Request(
                method="GET",
                target="/",
                headers=[
                    ("Host", "localhost"),
                    ("Connection", "Keep-Alive, Upgrade"),
                    ("Upgrade", "WebSocket"),
                    ("Sec-WebSocket-Version", "13"),
                    ("Sec-WebSocket-Key", nonce),
                ],
            )
        )
    )
    if body is not None:
        server.send(
            RejectConnection(
                headers=[(b"content-length", b"%d" % len(body))],
                status_code=status_code,
                has_body=True,
            )
        )
        server.send(RejectData(data=body))
    else:
        server.send(RejectConnection(status_code=status_code))
    client.receive_data(server.bytes_to_send())
    events = []
    while True:
        event = client.next_event()
        events.append(event)
        if isinstance(event, h11.EndOfMessage):
            return events


def test_handshake_rejection():
    events = _make_handshake_rejection(400)
    assert events == [
        h11.Response(headers=[("content-length", "0")], status_code=400),
        h11.EndOfMessage(),
    ]


def test_handshake_rejection_with_body():
    events = _make_handshake_rejection(400, body=b"Hello")
    assert events == [
        h11.Response(headers=[("content-length", "5")], status_code=400),
        h11.Data(data=b"Hello"),
        h11.EndOfMessage(),
    ]
