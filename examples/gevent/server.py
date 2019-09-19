"""
This example implements an abstract base server that you can use to implement
your own websocket server. There is an example at the end which show how to
implement one.
To run the example, you will need the gevent package, a powerful coroutine-based
networking library.
"""
import io
import json
import sys
from abc import ABC, abstractmethod
from typing import Tuple, AnyStr, Any

from gevent import socket
from gevent.server import StreamServer
from wsproto import WSConnection, ConnectionType
from wsproto.connection import ConnectionState
from wsproto.events import (
    Request, AcceptConnection, RejectConnection, RejectData, CloseConnection, Message,
    TextMessage, BytesMessage, Ping, Pong
)
from wsproto.typing import Headers


class BaseServer(ABC):
    bytes_to_receive: int = 65535
    buffer_size: int = io.DEFAULT_BUFFER_SIZE

    def __init__(self, host: str, port: int):
        self._check_init_arguments(host, port)
        self._host = host
        self._port = port
        self._server: StreamServer = None
        self._ws = WSConnection(ConnectionType.SERVER)
        self._client: socket = None  # client socket provided by the StreamServer
        self._running = True

    @staticmethod
    def _check_ws_headers(headers: Headers) -> None:
        if headers is None:
            return

        error_message = 'headers must of a list of tuples of the form [(bytes, bytes), ..]'
        if not isinstance(headers, list):
            raise TypeError(error_message)

        try:
            for key, value in headers:
                if not isinstance(key, bytes) or not isinstance(value, bytes):
                    raise TypeError(error_message)
        except ValueError:  # in case it is not a list of tuples
            raise TypeError(error_message)

    @abstractmethod
    def handle_request(self, request: Request) -> None:
        pass

    def accept_request(self, extra_headers: Headers = None, sub_protocol: str = None) -> None:
        self._check_ws_headers(extra_headers)
        if sub_protocol is not None and not isinstance(sub_protocol, str):
            raise TypeError('sub_protocol must be a string')

        extra_headers = extra_headers if extra_headers else []
        self._client.sendall(self._ws.send(AcceptConnection(extra_headers=extra_headers, subprotocol=sub_protocol)))

    def reject_request(self, status_code: int = 400, reason: str = None) -> None:
        if not isinstance(status_code, int):
            raise TypeError('status_code must be an integer')
        if reason is not None and not isinstance(reason, str):
            raise TypeError('reason must be a string')

        if not reason:
            self._client.sendall(self._ws.send(RejectConnection(status_code=status_code)))
        else:
            data = bytearray(self._ws.send(RejectConnection(has_body=True, headers=[(b'Content-type', b'text/txt')])))
            data.extend(self._ws.send(RejectData(reason.encode())))
            self._client.sendall(bytes(data))

    def close_request(self, code: int = 1000, reason: str = None) -> None:
        if not isinstance(code, int):
            raise TypeError('code must be an integer')
        if not isinstance(reason, str):
            raise TypeError('reason must be a string')

        self._client.sendall(self._ws.send(CloseConnection(code, reason)))

    def _handle_close_event(self, event: CloseConnection) -> None:
        if self._ws.state is ConnectionState.REMOTE_CLOSING:
            self._client.sendall(self._ws.send(event.response()))

    def _handle_ping(self, event: Ping) -> None:
        self._client.sendall(self._ws.send(event.response()))

    @abstractmethod
    def receive_text(self, data: str) -> None:
        pass

    @abstractmethod
    def receive_json(self, data: Any) -> None:
        pass

    @abstractmethod
    def receive_bytes(self, data: bytes) -> None:
        pass

    @abstractmethod
    def handle_pong(self, data: bytes) -> None:
        pass

    def _send_data(self, data: AnyStr) -> None:
        if isinstance(data, str):
            io_object = io.StringIO(data)
        else:
            io_object = io.BytesIO(data)

        with io_object as f:
            chunk = f.read(self.buffer_size)
            while chunk:
                if len(chunk) < self.buffer_size:
                    self._client.sendall(self._ws.send(Message(data, message_finished=True)))
                    break
                else:
                    self._client.sendall(self._ws.send(Message(data, message_finished=False)))
                chunk = f.read(self.buffer_size)

    def ping(self, data: bytes = b'hello') -> None:
        if not isinstance(data, bytes):
            raise TypeError('data must be bytes')

        self._client.sendall(self._ws.send(Ping(data)))

    def send(self, data: AnyStr) -> None:
        if not isinstance(data, (bytes, str)):
            raise TypeError('data must be either a string or binary data')

        self._send_data(data)

    def send_json(self, data: Any) -> None:
        self.send(json.dumps(data))

    @staticmethod
    def _check_init_arguments(host: str, port: int) -> None:
        if not isinstance(host, str):
            raise TypeError('host must be a string')
        error_message = 'custom_port must a positive integer'
        if not isinstance(port, int):
            raise TypeError(error_message)
        if port < 0:
            raise TypeError(error_message)

    def _handler(self, client: socket, address: Tuple[str, int]) -> None:
        self._client = client
        text_message = []
        binary_message = bytearray()

        while self._running:
            data = client.recv(self.bytes_to_receive)
            self._ws.receive_data(data)

            for event in self._ws.events():
                if isinstance(event, Request):
                    self.handle_request(event)

                elif isinstance(event, CloseConnection):
                    self._handle_close_event(event)
                    self._running = False

                elif isinstance(event, Ping):
                    self._handle_ping(event)

                elif isinstance(event, Pong):
                    self.handle_pong(event.payload)

                elif isinstance(event, TextMessage):
                    text_message.append(event.data)
                    if event.message_finished:
                        str_data = ''.join(text_message)
                        try:
                            self.receive_json(json.loads(str_data))
                        except json.JSONDecodeError:
                            self.receive_text(str_data)
                        text_message.clear()

                elif isinstance(event, BytesMessage):
                    binary_message.extend(event.data)
                    if event.message_finished:
                        self.receive_bytes(bytes(binary_message))
                        binary_message.clear()
                else:
                    print('unknown event:', event)

    def run(self, backlog: int = 256, spawn: str = 'default', **kwargs) -> None:
        self._server = StreamServer((self._host, self._port), self._handler, backlog=backlog, spawn=spawn, **kwargs)
        self._server.serve_forever()

    def close(self) -> None:
        if self._server is not None:
            self._server.close()


if __name__ == '__main__':
    class Server(BaseServer):
        def handle_request(self, request: Request) -> None:
            if request.subprotocols:  # this is only to demonstrate the usage of reject_request
                self.reject_request(reason='the server does not handle subprotocols')
                return
            self.accept_request()

        def handle_pong(self, data: bytes) -> None:
            print(data)

        def receive_bytes(self, data: bytes) -> None:
            print('receive bytes:', data)
            if b'ping me' in data:  # this is only to demonstrate the usage of ping
                self.ping(b'I ping you!')
                return
            self.send(data)

        def receive_text(self, data: str) -> None:
            print('receive text:', data)
            self.send(data)
            if 'bye' in data:  # this is only to demonstrate the usage of close_request
                self.close_request(1001, 'bye!')

        def receive_json(self, data: Any) -> None:
            print('receive json:', data)
            self.send_json(data)


    server = None
    try:
        hostname = sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1'
        custom_port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
        print('running host', hostname, 'on port', custom_port)
        server = Server(hostname, custom_port)
        server.run()
    except KeyboardInterrupt:
        server.close()
