# -*- coding: utf-8 -*-
"""
Test the HTTP upgrade phase of connection
"""

import base64
import email
import random

import pytest

from wsproto.compat import PY3
from wsproto.connection import WSConnection, CLIENT, SERVER
from wsproto.events import (
    ConnectionEstablished, ConnectionFailed, ConnectionRequested
)
from wsproto.extensions import Extension


def parse_headers(headers):
    if PY3:
        headers = email.message_from_bytes(headers)
    else:
        headers = email.message_from_string(headers)

    return dict(headers.items())


class FakeExtension(Extension):
    name = 'fake'

    def __init__(self, offer_response=None, accept_response=None):
        self.offer_response = offer_response
        self.accepted_offer = None
        self.offered = None
        self.accept_response = accept_response

    def offer(self, proto):
        return self.offer_response

    def finalize(self, proto, offer):
        self.accepted_offer = offer

    def accept(self, proto, offer):
        self.offered = offer
        return self.accept_response


class TestClientUpgrade(object):
    def initiate(self, host, path, **kwargs):
        ws = WSConnection(CLIENT, host, path, **kwargs)

        data = ws.bytes_to_send()
        request, headers = data.split(b'\r\n', 1)
        method, path, version = request.strip().split()
        headers = parse_headers(headers)

        return ws, method, path, version, headers

    def test_initiate_connection(self):
        _host = 'frob.nitz'
        _path = '/fnord'

        ws, method, path, version, headers = self.initiate(
            _host, _path, subprotocols=["foo", "bar"])

        assert method == b'GET'
        assert path == _path.encode('ascii')

        assert headers['host'] == _host
        assert headers['connection'].lower() == 'upgrade'
        assert headers['upgrade'].lower() == 'websocket'
        assert 'sec-websocket-key' in headers
        assert 'sec-websocket-version' in headers
        assert headers['sec-websocket-protocol'] == 'foo, bar'

    def test_no_subprotocols(self):
        ws, method, path, version, headers = self.initiate("foo", "/bar")
        assert 'sec-websocket-protocol' not in headers

    def test_correct_accept_token(self):
        _host = 'frob.nitz'
        _path = '/fnord'

        ws, method, path, version, headers = self.initiate(_host, _path)

        key = headers['sec-websocket-key'].encode('ascii')
        accept_token = ws._generate_accept_token(key)

        response = b"HTTP/1.1 101 Switching Protocols\r\n"
        response += b"Connection: Upgrade\r\n"
        response += b"Upgrade: WebSocket\r\n"
        response += b"Sec-WebSocket-Accept: " + accept_token + b"\r\n"
        response += b"\r\n"

        ws.receive_bytes(response)
        assert isinstance(next(ws.events()), ConnectionEstablished)

    def test_incorrect_accept_token(self):
        _host = 'frob.nitz'
        _path = '/fnord'

        ws, method, path, version, headers = self.initiate(_host, _path)

        key = b'This is wrong token'
        accept_token = ws._generate_accept_token(key)

        response = b"HTTP/1.1 101 Switching Protocols\r\n"
        response += b"Connection: Upgrade\r\n"
        response += b"Upgrade: WebSocket\r\n"
        response += b"Sec-WebSocket-Accept: " + accept_token + b"\r\n"
        response += b"\r\n"

        ws.receive_bytes(response)
        assert isinstance(next(ws.events()), ConnectionFailed)

    def test_bad_connection_header(self):
        _host = 'frob.nitz'
        _path = '/fnord'

        ws, method, path, version, headers = self.initiate(_host, _path)

        key = headers['sec-websocket-key'].encode('ascii')
        accept_token = ws._generate_accept_token(key)

        response = b"HTTP/1.1 101 Switching Protocols\r\n"
        response += b"Connection: Updraft\r\n"
        response += b"Upgrade: WebSocket\r\n"
        response += b"Sec-WebSocket-Accept: " + accept_token + b"\r\n"
        response += b"\r\n"

        ws.receive_bytes(response)
        assert isinstance(next(ws.events()), ConnectionFailed)

    def test_bad_upgrade_header(self):
        _host = 'frob.nitz'
        _path = '/fnord'

        ws, method, path, version, headers = self.initiate(_host, _path)

        key = headers['sec-websocket-key'].encode('ascii')
        accept_token = ws._generate_accept_token(key)

        response = b"HTTP/1.1 101 Switching Protocols\r\n"
        response += b"Connection: Upgrade\r\n"
        response += b"Upgrade: SebWocket\r\n"
        response += b"Sec-WebSocket-Accept: " + accept_token + b"\r\n"
        response += b"\r\n"

        ws.receive_bytes(response)
        assert isinstance(next(ws.events()), ConnectionFailed)

    def test_simple_extension_offer(self):
        _host = 'frob.nitz'
        _path = '/fnord'
        _ext = FakeExtension(offer_response=True)

        ws, method, path, version, headers = \
            self.initiate(_host, _path, extensions=[_ext])

        assert _ext.name == headers['sec-websocket-extensions']

    def test_simple_extension_non_offer(self):
        _host = 'frob.nitz'
        _path = '/fnord'
        _ext = FakeExtension(offer_response=False)

        ws, method, path, version, headers = \
            self.initiate(_host, _path, extensions=[_ext])

        assert 'sec-websocket-extensions' not in headers

    def test_extension_offer_with_params(self):
        ext_parameters = 'parameter1=value1; parameter2=value2'
        _ext = FakeExtension(offer_response=ext_parameters)

        _host = 'frob.nitz'
        _path = '/fnord'

        ws, method, path, version, headers = \
            self.initiate(_host, _path, extensions=[_ext])

        assert headers['sec-websocket-extensions'] == \
            '%s; %s' % (_ext.name, ext_parameters)

    def test_simple_extension_accept(self):
        _host = 'frob.nitz'
        _path = '/fnord'
        _ext = FakeExtension(offer_response=True)

        ws, method, path, version, headers = \
            self.initiate(_host, _path, extensions=[_ext])

        key = headers['sec-websocket-key'].encode('ascii')
        accept_token = ws._generate_accept_token(key)

        response = b"HTTP/1.1 101 Switching Protocols\r\n"
        response += b"Connection: Upgrade\r\n"
        response += b"Upgrade: WebSocket\r\n"
        response += b"Sec-WebSocket-Accept: " + accept_token + b"\r\n"
        response += b"Sec-WebSocket-Extensions: " + \
                    _ext.name.encode('ascii') + b"\r\n"
        response += b"\r\n"

        ws.receive_bytes(response)
        assert isinstance(next(ws.events()), ConnectionEstablished)
        assert _ext.name in _ext.accepted_offer

    def test_extension_accept_with_parameters(self):
        _host = 'frob.nitz'
        _path = '/fnord'
        _ext = FakeExtension(offer_response=True)

        ws, method, path, version, headers = \
            self.initiate(_host, _path, extensions=[_ext])

        key = headers['sec-websocket-key'].encode('ascii')
        accept_token = ws._generate_accept_token(key)
        ext_parameters = 'parameter1=value1; parameter2=value2'
        extensions = _ext.name + '; ' + ext_parameters

        response = b"HTTP/1.1 101 Switching Protocols\r\n"
        response += b"Connection: Upgrade\r\n"
        response += b"Upgrade: WebSocket\r\n"
        response += b"Sec-WebSocket-Accept: " + accept_token + b"\r\n"
        response += b"Sec-WebSocket-Extensions: " + \
                    extensions.encode('ascii') + b"\r\n"
        response += b"\r\n"

        ws.receive_bytes(response)
        assert isinstance(next(ws.events()), ConnectionEstablished)
        assert _ext.accepted_offer == extensions

    def test_accept_an_extension_we_do_not_recognise(self):
        _host = 'frob.nitz'
        _path = '/fnord'
        _ext = FakeExtension(offer_response=True)

        ws, method, path, version, headers = \
            self.initiate(_host, _path, extensions=[_ext])

        key = headers['sec-websocket-key'].encode('ascii')
        accept_token = ws._generate_accept_token(key)

        response = b"HTTP/1.1 101 Switching Protocols\r\n"
        response += b"Connection: Upgrade\r\n"
        response += b"Upgrade: WebSocket\r\n"
        response += b"Sec-WebSocket-Accept: " + accept_token + b"\r\n"
        response += b"Sec-WebSocket-Extensions: pretend\r\n"
        response += b"\r\n"

        ws.receive_bytes(response)
        assert isinstance(next(ws.events()), ConnectionFailed)

    def test_wrong_status_code_in_response(self):
        _host = 'frob.nitz'
        _path = '/fnord'

        ws, method, path, version, headers = self.initiate(_host, _path)

        response = b"HTTP/1.1 200 OK\r\n"
        response += b"Server: SimpleHTTP/0.6 Python/3.6.1\r\n"
        response += b"Date: Fri, 02 Jun 2017 20:40:39 GMT\r\n"
        response += b"Content-type: application/octet-stream\r\n"
        response += b"Content-Length: 0\r\n"
        response += b"Last-Modified: Fri, 02 Jun 2017 20:40:00 GMT\r\n"
        response += b"Connection: close\r\n"
        response += b"\r\n"

        ws.receive_bytes(response)
        assert isinstance(next(ws.events()), ConnectionFailed)

    def test_response_takes_a_few_goes(self):
        _host = 'frob.nitz'
        _path = '/fnord'

        ws, method, path, version, headers = self.initiate(_host, _path)

        key = headers['sec-websocket-key'].encode('ascii')
        accept_token = ws._generate_accept_token(key)

        response = b"HTTP/1.1 101 Switching Protocols\r\n"
        response += b"Connection: Upgrade\r\n"
        response += b"Upgrade: WebSocket\r\n"
        response += b"Sec-WebSocket-Accept: " + accept_token + b"\r\n"
        response += b"\r\n"

        split = len(response) // 2

        ws.receive_bytes(response[:split])
        with pytest.raises(StopIteration):
            next(ws.events())

        ws.receive_bytes(response[split:])
        assert isinstance(next(ws.events()), ConnectionEstablished)

    def test_subprotocol_offer(self):
        _host = 'frob.nitz'
        _path = '/fnord'
        subprotocols = ['one', 'two']

        ws, method, path, version, headers = \
            self.initiate(_host, _path, subprotocols=subprotocols)

        for subprotocol in subprotocols:
            assert subprotocol in headers['sec-websocket-protocol']

    def test_subprotocol_accept(self):
        _host = 'frob.nitz'
        _path = '/fnord'
        subprotocols = ['one', 'two']

        ws, method, path, version, headers = \
            self.initiate(_host, _path, subprotocols=subprotocols)

        key = headers['sec-websocket-key'].encode('ascii')
        accept_token = ws._generate_accept_token(key)

        response = b"HTTP/1.1 101 Switching Protocols\r\n"
        response += b"Connection: Upgrade\r\n"
        response += b"Upgrade: WebSocket\r\n"
        response += b"Sec-WebSocket-Accept: " + accept_token + b"\r\n"
        response += b"Sec-WebSocket-Protocol: " + \
                    subprotocols[0].encode('ascii') + b"\r\n"
        response += b"\r\n"

        ws.receive_bytes(response)
        event = next(ws.events())
        assert isinstance(event, ConnectionEstablished)
        assert event.subprotocol == subprotocols[0]

    def test_subprotocol_accept_unoffered(self):
        _host = 'frob.nitz'
        _path = '/fnord'
        subprotocols = ['one', 'two']

        ws, method, path, version, headers = \
            self.initiate(_host, _path, subprotocols=subprotocols)

        key = headers['sec-websocket-key'].encode('ascii')
        accept_token = ws._generate_accept_token(key)

        response = b"HTTP/1.1 101 Switching Protocols\r\n"
        response += b"Connection: Upgrade\r\n"
        response += b"Upgrade: WebSocket\r\n"
        response += b"Sec-WebSocket-Accept: " + accept_token + b"\r\n"
        response += b"Sec-WebSocket-Protocol: three\r\n"
        response += b"\r\n"

        ws.receive_bytes(response)
        assert isinstance(next(ws.events()), ConnectionFailed)


class TestServerUpgrade(object):
    def test_correct_request(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'

        ws = WSConnection(SERVER)

        nonce = bytes(random.getrandbits(8) for x in range(0, 16))
        nonce = base64.b64encode(nonce)

        request = b"GET " + test_path.encode('ascii') + b" HTTP/1.1\r\n"
        request += b'Host: ' + test_host.encode('ascii') + b'\r\n'
        request += b'Connection: Upgrade\r\n'
        request += b'Upgrade: WebSocket\r\n'
        request += b'Sec-WebSocket-Version: 13\r\n'
        request += b'Sec-WebSocket-Key: ' + nonce + b'\r\n'
        request += b'\r\n'

        ws.receive_bytes(request)
        event = next(ws.events())
        assert isinstance(event, ConnectionRequested)
        ws.accept(event)

        data = ws.bytes_to_send()
        response, headers = data.split(b'\r\n', 1)
        version, code, reason = response.split(b' ')
        headers = parse_headers(headers)

        accept_token = ws._generate_accept_token(nonce)

        assert int(code) == 101
        assert headers['connection'].lower() == 'upgrade'
        assert headers['upgrade'].lower() == 'websocket'
        assert headers['sec-websocket-accept'] == accept_token.decode('ascii')

    def test_correct_request_expanded_connection_header(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'

        ws = WSConnection(SERVER)

        nonce = bytes(random.getrandbits(8) for x in range(0, 16))
        nonce = base64.b64encode(nonce)

        request = b"GET " + test_path.encode('ascii') + b" HTTP/1.1\r\n"
        request += b'Host: ' + test_host.encode('ascii') + b'\r\n'
        request += b'Connection: keep-alive, Upgrade\r\n'
        request += b'Upgrade: WebSocket\r\n'
        request += b'Sec-WebSocket-Version: 13\r\n'
        request += b'Sec-WebSocket-Key: ' + nonce + b'\r\n'
        request += b'\r\n'

        ws.receive_bytes(request)
        event = next(ws.events())
        assert isinstance(event, ConnectionRequested)

    def test_wrong_method(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'

        ws = WSConnection(SERVER)

        nonce = bytes(random.getrandbits(8) for x in range(0, 16))
        nonce = base64.b64encode(nonce)

        request = b'POST ' + test_path.encode('ascii') + b' HTTP/1.1\r\n'
        request += b'Host: ' + test_host.encode('ascii') + b'\r\n'
        request += b'Connection: Upgrade\r\n'
        request += b'Upgrade: WebSocket\r\n'
        request += b'Sec-WebSocket-Version: 13\r\n'
        request += b'Sec-WebSocket-Key: ' + nonce + b'\r\n'
        request += b'\r\n'

        ws.receive_bytes(request)
        event = next(ws.events())
        assert isinstance(event, ConnectionFailed)

    def test_bad_connection(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'

        ws = WSConnection(SERVER)

        nonce = bytes(random.getrandbits(8) for x in range(0, 16))
        nonce = base64.b64encode(nonce)

        request = b'GET ' + test_path.encode('ascii') + b' HTTP/1.1\r\n'
        request += b'Host: ' + test_host.encode('ascii') + b'\r\n'
        request += b'Connection: Zoinks\r\n'
        request += b'Upgrade: WebSocket\r\n'
        request += b'Sec-WebSocket-Version: 13\r\n'
        request += b'Sec-WebSocket-Key: ' + nonce + b'\r\n'
        request += b'\r\n'

        ws.receive_bytes(request)
        event = next(ws.events())
        assert isinstance(event, ConnectionFailed)

    def test_bad_upgrade(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'

        ws = WSConnection(SERVER)

        nonce = bytes(random.getrandbits(8) for x in range(0, 16))
        nonce = base64.b64encode(nonce)

        request = b'GET ' + test_path.encode('ascii') + b' HTTP/1.1\r\n'
        request += b'Host: ' + test_host.encode('ascii') + b'\r\n'
        request += b'Connection: Upgrade\r\n'
        request += b'Upgrade: WebPocket\r\n'
        request += b'Sec-WebSocket-Version: 13\r\n'
        request += b'Sec-WebSocket-Key: ' + nonce + b'\r\n'
        request += b'\r\n'

        ws.receive_bytes(request)
        event = next(ws.events())
        assert isinstance(event, ConnectionFailed)

    def test_missing_version(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'

        ws = WSConnection(SERVER)

        nonce = bytes(random.getrandbits(8) for x in range(0, 16))
        nonce = base64.b64encode(nonce)

        request = b'GET ' + test_path.encode('ascii') + b' HTTP/1.1\r\n'
        request += b'Host: ' + test_host.encode('ascii') + b'\r\n'
        request += b'Connection: Upgrade\r\n'
        request += b'Upgrade: WebSocket\r\n'
        request += b'Sec-WebSocket-Key: ' + nonce + b'\r\n'
        request += b'\r\n'

        ws.receive_bytes(request)
        event = next(ws.events())
        assert isinstance(event, ConnectionFailed)

    def test_missing_key(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'

        ws = WSConnection(SERVER)

        request = b'GET ' + test_path.encode('ascii') + b' HTTP/1.1\r\n'
        request += b'Host: ' + test_host.encode('ascii') + b'\r\n'
        request += b'Connection: Upgrade\r\n'
        request += b'Upgrade: WebSocket\r\n'
        request += b'Sec-WebSocket-Version: 13\r\n'
        request += b'\r\n'

        ws.receive_bytes(request)
        event = next(ws.events())
        assert isinstance(event, ConnectionFailed)

    def test_subprotocol_offers(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'

        ws = WSConnection(SERVER)

        nonce = bytes(random.getrandbits(8) for x in range(0, 16))
        nonce = base64.b64encode(nonce)

        request = b'GET ' + test_path.encode('ascii') + b' HTTP/1.1\r\n'
        request += b'Host: ' + test_host.encode('ascii') + b'\r\n'
        request += b'Connection: Upgrade\r\n'
        request += b'Upgrade: WebSocket\r\n'
        request += b'Sec-WebSocket-Version: 13\r\n'
        request += b'Sec-WebSocket-Key: ' + nonce + b'\r\n'
        request += b'Sec-WebSocket-Protocol: one, two\r\n'
        request += b'\r\n'

        ws.receive_bytes(request)
        event = next(ws.events())
        assert isinstance(event, ConnectionRequested)
        assert event.proposed_subprotocols == ['one', 'two']

    def test_accept_subprotocol(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'

        ws = WSConnection(SERVER)

        nonce = bytes(random.getrandbits(8) for x in range(0, 16))
        nonce = base64.b64encode(nonce)

        request = b'GET ' + test_path.encode('ascii') + b' HTTP/1.1\r\n'
        request += b'Host: ' + test_host.encode('ascii') + b'\r\n'
        request += b'Connection: Upgrade\r\n'
        request += b'Upgrade: WebSocket\r\n'
        request += b'Sec-WebSocket-Version: 13\r\n'
        request += b'Sec-WebSocket-Key: ' + nonce + b'\r\n'
        request += b'Sec-WebSocket-Protocol: one, two\r\n'
        request += b'\r\n'

        ws.receive_bytes(request)
        event = next(ws.events())
        assert isinstance(event, ConnectionRequested)
        assert event.proposed_subprotocols == ['one', 'two']

        ws.accept(event, 'two')

        data = ws.bytes_to_send()
        response, headers = data.split(b'\r\n', 1)
        version, code, reason = response.split(b' ')
        headers = parse_headers(headers)

        assert int(code) == 101
        assert headers['sec-websocket-protocol'] == 'two'

    def test_accept_wrong_subprotocol(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'

        ws = WSConnection(SERVER)

        nonce = bytes(random.getrandbits(8) for x in range(0, 16))
        nonce = base64.b64encode(nonce)

        request = b'GET ' + test_path.encode('ascii') + b' HTTP/1.1\r\n'
        request += b'Host: ' + test_host.encode('ascii') + b'\r\n'
        request += b'Connection: Upgrade\r\n'
        request += b'Upgrade: WebSocket\r\n'
        request += b'Sec-WebSocket-Version: 13\r\n'
        request += b'Sec-WebSocket-Key: ' + nonce + b'\r\n'
        request += b'Sec-WebSocket-Protocol: one, two\r\n'
        request += b'\r\n'

        ws.receive_bytes(request)
        event = next(ws.events())
        assert isinstance(event, ConnectionRequested)
        assert event.proposed_subprotocols == ['one', 'two']

        with pytest.raises(ValueError):
            ws.accept(event, 'three')

    def test_simple_extension_negotiation(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'
        ext = FakeExtension(accept_response=True)

        ws = WSConnection(SERVER, extensions=[ext])

        nonce = bytes(random.getrandbits(8) for x in range(0, 16))
        nonce = base64.b64encode(nonce)

        request = b"GET " + test_path.encode('ascii') + b" HTTP/1.1\r\n"
        request += b'Host: ' + test_host.encode('ascii') + b'\r\n'
        request += b'Connection: Upgrade\r\n'
        request += b'Upgrade: WebSocket\r\n'
        request += b'Sec-WebSocket-Version: 13\r\n'
        request += b'Sec-WebSocket-Key: ' + nonce + b'\r\n'
        request += b'Sec-WebSocket-Extensions: ' + \
            ext.name.encode('ascii') + b'\r\n'
        request += b'\r\n'

        ws.receive_bytes(request)
        event = next(ws.events())
        assert isinstance(event, ConnectionRequested)
        ws.accept(event)

        data = ws.bytes_to_send()
        response, headers = data.split(b'\r\n', 1)
        version, code, reason = response.split(b' ')
        headers = parse_headers(headers)

        assert ext.offered == ext.name
        assert headers['sec-websocket-extensions'] == ext.name

    def test_extension_negotiation_with_our_parameters(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'
        offered_params = 'parameter1=value3; parameter2=value4'
        ext_params = 'parameter1=value1; parameter2=value2'
        ext = FakeExtension(accept_response=ext_params)

        ws = WSConnection(SERVER, extensions=[ext])

        nonce = bytes(random.getrandbits(8) for x in range(0, 16))
        nonce = base64.b64encode(nonce)

        request = b"GET " + test_path.encode('ascii') + b" HTTP/1.1\r\n"
        request += b'Host: ' + test_host.encode('ascii') + b'\r\n'
        request += b'Connection: Upgrade\r\n'
        request += b'Upgrade: WebSocket\r\n'
        request += b'Sec-WebSocket-Version: 13\r\n'
        request += b'Sec-WebSocket-Key: ' + nonce + b'\r\n'
        request += b'Sec-WebSocket-Extensions: ' + \
            ext.name.encode('ascii') + b'; ' + \
            offered_params.encode('ascii') + b'\r\n'
        request += b'\r\n'

        ws.receive_bytes(request)
        event = next(ws.events())
        assert isinstance(event, ConnectionRequested)
        ws.accept(event)

        data = ws.bytes_to_send()
        response, headers = data.split(b'\r\n', 1)
        version, code, reason = response.split(b' ')
        headers = parse_headers(headers)

        assert ext.offered == '%s; %s' % (ext.name, offered_params)
        assert headers['sec-websocket-extensions'] == \
            '%s; %s' % (ext.name, ext_params)

    @pytest.mark.parametrize('accept_response', [False, None])
    def test_disinterested_extension_negotiation(self, accept_response):
        test_host = 'frob.nitz'
        test_path = '/fnord'
        ext = FakeExtension(accept_response=accept_response)

        ws = WSConnection(SERVER, extensions=[ext])

        nonce = bytes(random.getrandbits(8) for x in range(0, 16))
        nonce = base64.b64encode(nonce)

        request = b"GET " + test_path.encode('ascii') + b" HTTP/1.1\r\n"
        request += b'Host: ' + test_host.encode('ascii') + b'\r\n'
        request += b'Connection: Upgrade\r\n'
        request += b'Upgrade: WebSocket\r\n'
        request += b'Sec-WebSocket-Version: 13\r\n'
        request += b'Sec-WebSocket-Key: ' + nonce + b'\r\n'
        request += b'Sec-WebSocket-Extensions: ' + \
            ext.name.encode('ascii') + b'\r\n'
        request += b'\r\n'

        ws.receive_bytes(request)
        event = next(ws.events())
        assert isinstance(event, ConnectionRequested)
        ws.accept(event)

        data = ws.bytes_to_send()
        response, headers = data.split(b'\r\n', 1)
        version, code, reason = response.split(b' ')
        headers = parse_headers(headers)

        assert ext.offered == ext.name
        assert 'sec-websocket-extensions' not in headers

    def test_no_params_extension_negotiation(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'
        ext = FakeExtension(accept_response='')

        ws = WSConnection(SERVER, extensions=[ext])

        nonce = bytes(random.getrandbits(8) for x in range(0, 16))
        nonce = base64.b64encode(nonce)

        request = b"GET " + test_path.encode('ascii') + b" HTTP/1.1\r\n"
        request += b'Host: ' + test_host.encode('ascii') + b'\r\n'
        request += b'Connection: Upgrade\r\n'
        request += b'Upgrade: WebSocket\r\n'
        request += b'Sec-WebSocket-Version: 13\r\n'
        request += b'Sec-WebSocket-Key: ' + nonce + b'\r\n'
        request += b'Sec-WebSocket-Extensions: ' + \
            ext.name.encode('ascii') + b'\r\n'
        request += b'\r\n'

        ws.receive_bytes(request)
        event = next(ws.events())
        assert isinstance(event, ConnectionRequested)
        ws.accept(event)

        data = ws.bytes_to_send()
        response, headers = data.split(b'\r\n', 1)
        version, code, reason = response.split(b' ')
        headers = parse_headers(headers)

        assert ext.offered == ext.name
        assert 'sec-websocket-extensions' in headers

    def test_unwanted_extension_negotiation(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'
        ext = FakeExtension(accept_response=False)

        ws = WSConnection(SERVER, extensions=[ext])

        nonce = bytes(random.getrandbits(8) for x in range(0, 16))
        nonce = base64.b64encode(nonce)

        request = b"GET " + test_path.encode('ascii') + b" HTTP/1.1\r\n"
        request += b'Host: ' + test_host.encode('ascii') + b'\r\n'
        request += b'Connection: Upgrade\r\n'
        request += b'Upgrade: WebSocket\r\n'
        request += b'Sec-WebSocket-Version: 13\r\n'
        request += b'Sec-WebSocket-Key: ' + nonce + b'\r\n'
        request += b'Sec-WebSocket-Extensions: pretend\r\n'
        request += b'\r\n'

        ws.receive_bytes(request)
        event = next(ws.events())
        assert isinstance(event, ConnectionRequested)
        ws.accept(event)

        data = ws.bytes_to_send()
        response, headers = data.split(b'\r\n', 1)
        version, code, reason = response.split(b' ')
        headers = parse_headers(headers)

        assert 'sec-websocket-extensions' not in headers

    def test_not_an_http_request_at_all(self):
        ws = WSConnection(SERVER)

        request = b'<xml>Good god, what is this?</xml>\r\n\r\n'

        ws.receive_bytes(request)
        assert isinstance(next(ws.events()), ConnectionFailed)

    def test_h11_somehow_loses_its_mind(self):
        ws = WSConnection(SERVER)
        ws._upgrade_connection.next_event = lambda: object()

        ws.receive_bytes(b'')
        assert isinstance(next(ws.events()), ConnectionFailed)
