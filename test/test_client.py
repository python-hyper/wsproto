# These tests test the behaviours expected of wsproto in when the
# connection is a client.

import h11
import pytest

from wsproto.connection import CLIENT, WSConnection
from wsproto.events import AcceptConnection, Fail, RejectConnection, RejectData, Request
from wsproto.frame_protocol import CloseReason
from wsproto.utilities import generate_accept_token, normed_header_dict
from .helpers import FakeExtension


def _make_connection_request(request):
    # type: (Request) -> h11.Request
    client = WSConnection(CLIENT)
    server = h11.Connection(h11.SERVER)
    client.send(request)
    server.receive_data(client.bytes_to_send())
    return server.next_event()


def test_connection_request():
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


def test_connection_request_additional_headers():
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


def test_connection_request_simple_extension():
    extension = FakeExtension(offer_response=True)
    request = _make_connection_request(
        Request(host="localhost", target="/", extensions=[extension])
    )

    headers = normed_header_dict(request.headers)
    assert headers[b"sec-websocket-extensions"] == extension.name.encode("ascii")


def test_connection_request_simple_extension_no_offer():
    extension = FakeExtension(offer_response=False)
    request = _make_connection_request(
        Request(host="localhost", target="/", extensions=[extension])
    )

    headers = normed_header_dict(request.headers)
    assert b"sec-websocket-extensions" not in headers


def test_connection_request_parametrised_extension():
    extension = FakeExtension(offer_response="parameter1=value1; parameter2=value2")
    request = _make_connection_request(
        Request(host="localhost", target="/", extensions=[extension])
    )

    headers = normed_header_dict(request.headers)
    assert headers[b"sec-websocket-extensions"] == b"%s; %s" % (
        extension.name.encode("ascii"),
        extension.offer_response.encode("ascii"),
    )


def test_connection_request_subprotocols():
    request = _make_connection_request(
        Request(host="localhost", target="/", subprotocols=["one", "two"])
    )

    headers = normed_header_dict(request.headers)
    assert headers[b"sec-websocket-protocol"] == b"one, two"


def _make_handshake(
    response_status,
    response_headers,
    subprotocols=None,
    extensions=None,
    auto_accept_key=True,
):
    client = WSConnection(CLIENT)
    server = h11.Connection(h11.SERVER)
    client.send(
        Request(
            host="localhost",
            target="/",
            subprotocols=subprotocols or [],
            extensions=extensions or [],
        )
    )
    server.receive_data(client.bytes_to_send())
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
    client.receive_bytes(server.send(response))

    return list(client.events())


def test_handshake():
    events = _make_handshake(
        101, [(b"connection", b"Upgrade"), (b"upgrade", b"WebSocket")]
    )
    assert [AcceptConnection()]


@pytest.mark.parametrize("extra_headers", [[], [(b"connection", b"Keep-Alive")]])
def test_handshake_response_broken_connection_header(extra_headers):
    events = _make_handshake(101, [(b"upgrade", b"WebSocket")] + extra_headers)
    assert events == [
        Fail(
            code=CloseReason.PROTOCOL_ERROR, reason="Missing Connection: Upgrade header"
        )
    ]


@pytest.mark.parametrize("extra_headers", [[], [(b"upgrade", b"h2")]])
def test_handshake_response_broken_upgrade_header(extra_headers):
    events = _make_handshake(101, [(b"connection", b"Upgrade")] + extra_headers)
    assert events == [
        Fail(
            code=CloseReason.PROTOCOL_ERROR, reason="Missing Upgrade: WebSocket header"
        )
    ]


def test_handshake_response_missing_websocket_key_header():
    events = _make_handshake(
        101,
        [(b"connection", b"Upgrade"), (b"upgrade", b"WebSocket")],
        auto_accept_key=False,
    )
    assert events == [Fail(code=CloseReason.PROTOCOL_ERROR, reason="Bad accept token")]


def test_handshake_with_subprotocol():
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


def test_handshake_bad_subprotocol():
    events = _make_handshake(
        101,
        [
            (b"connection", b"Upgrade"),
            (b"upgrade", b"WebSocket"),
            (b"sec-websocket-protocol", b"new"),
        ],
    )
    assert events == [
        Fail(code=CloseReason.PROTOCOL_ERROR, reason="unrecognized subprotocol new")
    ]


def test_handshake_with_extension():
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


def test_handshake_bad_extension():
    events = _make_handshake(
        101,
        [
            (b"connection", b"Upgrade"),
            (b"upgrade", b"WebSocket"),
            (b"sec-websocket-extensions", b"bad, foo"),
        ],
    )
    assert events == [
        Fail(code=CloseReason.PROTOCOL_ERROR, reason="unrecognized extension bad")
    ]


def test_protocol_error():
    client = WSConnection(CLIENT)
    client.send(Request(host="localhost", target="/"))
    client.receive_bytes(b"broken nonsense\r\n\r\n")
    assert list(client.events()) == [
        Fail(code=CloseReason.PROTOCOL_ERROR, reason="Bad HTTP message")
    ]


def _make_handshake_rejection(status_code, body=None):
    client = WSConnection(CLIENT)
    server = h11.Connection(h11.SERVER)
    client.send(Request(host="localhost", target="/"))
    server.receive_data(client.bytes_to_send())
    headers = []
    if body is not None:
        headers.append(("Content-Length", str(len(body))))
    client.receive_bytes(
        server.send(h11.Response(status_code=status_code, headers=headers))
    )
    if body is not None:
        client.receive_bytes(server.send(h11.Data(data=body)))
    client.receive_bytes(server.send(h11.EndOfMessage()))

    return list(client.events())


def test_handshake_rejection():
    events = _make_handshake_rejection(400)
    assert events == [
        RejectConnection(headers=[(b"connection", b"close")], status_code=400),
        RejectData(body_finished=True, data=b""),
    ]


def test_handshake_rejection_with_body():
    events = _make_handshake_rejection(400, b"Hello")
    assert events == [
        RejectConnection(headers=[(b"content-length", b"5")], status_code=400),
        RejectData(body_finished=False, data=b"Hello"),
        RejectData(body_finished=True, data=b""),
    ]
