# -*- coding: utf-8 -*-
"""
Test the HTTP upgrade phase of connection
"""

import base64
import email
import random
import sys

from wsproto.connection import WSConnection, CLIENT, SERVER
from wsproto.events import (
    ConnectionEstablished, ConnectionFailed, ConnectionRequested
)


IS_PYTHON3 = sys.version_info >= (3, 0)


def parse_headers(headers):
    if IS_PYTHON3:
        headers = email.message_from_bytes(headers)
    else:
        headers = email.message_from_string(headers)

    return dict(headers.items())


class TestClientUpgrade(object):
    def initiate(self, host, path, **kwargs):
        ws = WSConnection(CLIENT, host, path, **kwargs)

        data = ws.bytes_to_send()
        request, headers = data.split(b'\r\n', 1)
        method, path, version = request.strip().split()
        headers = parse_headers(headers)

        print(method, path, version)
        print(repr(headers))

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
