"""Keep agreed compression settings stable across alternative offers."""

from __future__ import annotations

import pytest

from wsproto import ConnectionType, WSConnection
from wsproto.events import AcceptConnection, BytesMessage, CloseConnection, Request, TextMessage
from wsproto.extensions import PerMessageDeflate
from wsproto.handshake import server_extensions_handshake

from .helpers import FakeExtension


@pytest.mark.parametrize("accept_response", [True, "", "parameter=value"])
def test_first_accepted_offer_is_preserved(accept_response: bool | str) -> None:
    extension = FakeExtension(accept_response=accept_response)
    assert (
        server_extensions_handshake(
            ["fake; preferred", "fake; fallback"],
            [extension],
        )
        is not None
    )
    assert extension.offered == "fake; preferred"


def test_declined_offer_does_not_prevent_fallback() -> None:
    extension = PerMessageDeflate()
    assert (
        server_extensions_handshake(
            ["permessage-deflate; server_max_window_bits=8", "permessage-deflate"],
            [extension],
        )
        == b"permessage-deflate"
    )
    assert extension.enabled()


@pytest.mark.parametrize("text", [False, True])
@pytest.mark.parametrize("split_headers", [False, True])
@pytest.mark.parametrize("chunk_size", [7, 65536])
@pytest.mark.parametrize("extra_offer", [False, True])
def test_rejected_alternative_does_not_reset_negotiated_context(
    text: bool,
    split_headers: bool,
    chunk_size: int,
    extra_offer: bool,
) -> None:
    client = WSConnection(ConnectionType.CLIENT)
    server = WSConnection(ConnectionType.SERVER)
    client_extension = PerMessageDeflate()
    server_extension = PerMessageDeflate()
    alternative = b"permessage-deflate; client_no_context_takeover; server_max_window_bits=8"
    extra_headers = [(b"Sec-WebSocket-Extensions", alternative)] if extra_offer else []
    request_event = Request(
        host="localhost",
        target="/",
        extensions=[client_extension],
        extra_headers=extra_headers,
    )
    request = client.send(request_event)
    if not split_headers:
        request = request.replace(b"\r\nSec-WebSocket-Extensions: " + alternative, b", " + alternative)
    server.receive_data(request)
    assert isinstance(next(server.events()), Request)
    response = server.send(AcceptConnection(extensions=[server_extension]))
    assert b"client_no_context_takeover" not in response
    client.receive_data(response)
    assert isinstance(next(client.events()), AcceptConnection)

    # The second message reuses the first message's compression dictionary.
    # A context reset that was not negotiated turns it into a protocol error.
    payload = "실시간 음성 대화 " * 100 if text else bytes(range(256)) * 16
    for _ in range(2):
        wire = client.send(TextMessage(data=payload) if isinstance(payload, str) else BytesMessage(data=payload))
        events = []
        for offset in range(0, len(wire), chunk_size):
            server.receive_data(wire[offset : offset + chunk_size])
            events.extend(server.events())
        assert not any(isinstance(event, CloseConnection) for event in events)
        if isinstance(payload, str):
            messages = [event for event in events if isinstance(event, TextMessage)]
            assert "".join(event.data for event in messages) == payload
        else:
            messages = [event for event in events if isinstance(event, BytesMessage)]
            assert b"".join(event.data for event in messages) == payload
        assert messages[-1].message_finished
