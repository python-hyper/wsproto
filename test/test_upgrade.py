# -*- coding: utf-8 -*-
"""
Test the HTTP upgrade phase of connection
"""

import base64
import email
import random

from wsproto.connection import WSClient, WSServer
from wsproto.events import (
    ConnectionEstablished, ConnectionFailed, ConnectionRequested
)

class TestClientUpgrade(object):
    def initiate(self, host, path):
        ws = WSClient(host, path)

        data = ws.bytes_to_send()
        request, headers = data.split(b'\r\n', 1)
        method, path, version = request.strip().split()
        headers = dict(email.message_from_bytes(headers).items())

        print(method, path, version)
        print(repr(headers))

        return ws, method, path, version, headers

    def test_initiate_connection(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'

        ws, method, path, version, headers = self.initiate(test_host, test_path)

        assert method == b'GET'
        assert path == test_path.encode('ascii')

        assert headers['host'] == test_host
        assert headers['connection'].lower() == 'upgrade'
        assert headers['upgrade'].lower() == 'websocket'
        assert 'sec-websocket-key' in headers
        assert 'sec-websocket-version' in headers

    def test_correct_accept_token(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'

        ws, method, path, version, headers = self.initiate(test_host, test_path)

        key = headers['sec-websocket-key'].encode('ascii')
        accept_token = ws._generate_accept_token(key)

        response = b"HTTP/1.1 101 Switching Protocols\r\n"
        response += b"Connection: Upgrade\r\n"
        response += b"Upgrade: WebSocket\r\n"
        response += b"Sec-WebSocket-Accept: %s\r\n" % accept_token
        response += b"\r\n"

        ws.receive_bytes(response)
        assert isinstance(next(ws.events()), ConnectionEstablished)

    def test_incorrect_accept_token(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'

        ws, method, path, version, headers = self.initiate(test_host, test_path)

        key = b'This is wrong token'
        accept_token = ws._generate_accept_token(key)

        response = b"HTTP/1.1 101 Switching Protocols\r\n"
        response += b"Connection: Upgrade\r\n"
        response += b"Upgrade: WebSocket\r\n"
        response += b"Sec-WebSocket-Accept: %s\r\n" % accept_token
        response += b"\r\n"

        ws.receive_bytes(response)
        assert isinstance(next(ws.events()), ConnectionFailed)

    def test_bad_connection_header(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'

        ws, method, path, version, headers = self.initiate(test_host, test_path)

        key = headers['sec-websocket-key'].encode('ascii')
        accept_token = ws._generate_accept_token(key)

        response = b"HTTP/1.1 101 Switching Protocols\r\n"
        response += b"Connection: Updraft\r\n"
        response += b"Upgrade: WebSocket\r\n"
        response += b"Sec-WebSocket-Accept: %s\r\n" % accept_token
        response += b"\r\n"

        ws.receive_bytes(response)
        assert isinstance(next(ws.events()), ConnectionFailed)

    def test_bad_upgrade_header(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'

        ws, method, path, version, headers = self.initiate(test_host, test_path)

        key = headers['sec-websocket-key'].encode('ascii')
        accept_token = ws._generate_accept_token(key)

        response = b"HTTP/1.1 101 Switching Protocols\r\n"
        response += b"Connection: Upgrade\r\n"
        response += b"Upgrade: SebWocket\r\n"
        response += b"Sec-WebSocket-Accept: %s\r\n" % accept_token
        response += b"\r\n"

        ws.receive_bytes(response)
        assert isinstance(next(ws.events()), ConnectionFailed)


class TestServerUpgrade(object):
    def test_correct_request(self):
        test_host = 'frob.nitz'
        test_path = '/fnord'

        ws = WSServer()

        nonce = bytes(random.getrandbits(8) for x in range(0, 16))
        nonce = base64.b64encode(nonce)

        request = b"GET %s HTTP/1.1\r\n" % test_path.encode('ascii')
        request += b'Host: %s\r\n' % test_host.encode('ascii')
        request += b'Connection: Upgrade\r\n'
        request += b'Upgrade: WebSocket\r\n'
        request += b'Sec-WebSocket-Version: 13\r\n'
        request += b'Sec-WebSocket-Key: %s\r\n' % nonce
        request += b'\r\n'

        ws.receive_bytes(request)
        event = next(ws.events())
        assert isinstance(event, ConnectionRequested)
        ws.accept(event)

        data = ws.bytes_to_send()
        response, headers = data.split(b'\r\n', 1)
        version, code, reason = response.split(b' ')
        headers = dict(email.message_from_bytes(headers).items())

        accept_token = ws._generate_accept_token(nonce)

        assert int(code) == 101
        assert headers['connection'].lower() == 'upgrade'
        assert headers['upgrade'].lower() == 'websocket'
        assert headers['sec-websocket-accept'] == accept_token.decode('ascii')
