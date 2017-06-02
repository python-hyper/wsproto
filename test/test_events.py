import pytest

from h11 import Request

from wsproto.events import (
    ConnectionClosed,
    ConnectionEstablished,
    ConnectionRequested,
)
from wsproto.frame_protocol import CloseReason


def test_connection_requested_repr_no_subprotocol():
    method = b'GET'
    target = b'/foo'
    headers = {
        b'host': b'localhost',
        b'sec-websocket-version': b'13',
    }
    http_version = b'1.1'

    req = Request(method=method, target=target, headers=list(headers.items()),
                  http_version=http_version)

    event = ConnectionRequested([], req)
    r = repr(event)

    assert 'ConnectionRequested' in r
    assert target.decode('ascii') in r


def test_connection_requested_repr_with_subprotocol():
    method = b'GET'
    target = b'/foo'
    headers = {
        b'host': b'localhost',
        b'sec-websocket-version': b'13',
        b'sec-websocket-protocol': b'fnord',
    }
    http_version = b'1.1'

    req = Request(method=method, target=target, headers=list(headers.items()),
                  http_version=http_version)

    event = ConnectionRequested([], req)
    r = repr(event)

    assert 'ConnectionRequested' in r
    assert target.decode('ascii') in r
    assert headers[b'sec-websocket-protocol'].decode('ascii') in r


@pytest.mark.parametrize('subprotocol,extensions', [
    ('sproto', None),
    (None, ['fake']),
    ('sprout', ['pretend']),
])
def test_connection_established_repr(subprotocol, extensions):
    event = ConnectionEstablished(subprotocol, extensions)
    r = repr(event)

    if subprotocol:
        assert subprotocol in r
    if extensions:
        for extension in extensions:
            assert extension in r


@pytest.mark.parametrize('code,reason', [
    (CloseReason.NORMAL_CLOSURE, None),
    (CloseReason.NORMAL_CLOSURE, 'because i felt like it'),
    (CloseReason.INVALID_FRAME_PAYLOAD_DATA, 'GOOD GOD WHAT DID YOU DO'),
])
def test_connection_closed_repr(code, reason):
    event = ConnectionClosed(code, reason)
    r = repr(event)

    assert repr(code) in r
    if reason:
        assert reason in r
