"""
Simple websocket client. The example at the end of the file is self-explaining.
To run the example, you will need the gevent package, a powerful coroutine-based
networking library.
"""
import io
import json
import re
from enum import Enum
from typing import Callable, Tuple, List, Dict, Any, Union, AnyStr

from gevent import socket, spawn
from gevent.event import AsyncResult
from wsproto import WSConnection, ConnectionType
from wsproto.connection import ConnectionState
from wsproto.events import (
    Event, Request, AcceptConnection, CloseConnection, Pong, Ping, RejectConnection, RejectData, TextMessage,
    BytesMessage, Message
)
from wsproto.typing import Headers
from wsproto.utilities import ProtocolError

EventCallback = Callable[['Client', Event], Any]
StrCallback = Callable[[str], Any]
BytesCallback = Callable[[bytes], Any]
JsonCallback = Callable[[Any], Any]
Callback = Union[EventCallback, StrCallback, BytesCallback, JsonCallback]


class EventType(Enum):
    CONNECT = 'connect'
    DISCONNECT = 'disconnect'
    PING = 'ping'
    PONG = 'pong'
    JSON_MESSAGE = 'json'
    TEXT_MESSAGE = 'text'
    BINARY_MESSAGE = 'binary'


class ConnectionRejectedError(ProtocolError):
    """Exception raised when the client receives the event RejectConnection"""

    def __init__(self, status_code: int, headers: Headers, reason: bytes):
        self.status_code = status_code
        self.headers = headers
        self.reason = reason

    def __str__(self):
        return f'status = {self.status_code}, headers = {self.headers}, reason = {self.reason}'


class Client:
    _callbacks: Dict[EventType, Callable] = {}
    receive_bytes: int = 65535
    buffer_size: int = io.DEFAULT_BUFFER_SIZE

    def __init__(self, connect_uri: str, headers: Headers = None, extensions: List[str] = None,
                 sub_protocols: List[str] = None):
        self._check_ws_headers(headers)
        self._check_list_argument('extensions', extensions)
        self._check_list_argument('sub_protocols', sub_protocols)

        self._sock: socket = None
        self._ws: WSConnection = None
        # wsproto does not seem to like empty path, so we provide an arbitrary one
        self._default_path = '/path'
        self._running = True
        self._handshake_finished = AsyncResult()

        host, port, path = self._get_connect_information(connect_uri)
        self._establish_tcp_connection(host, port)
        self._establish_websocket_handshake(host, path, headers, extensions, sub_protocols)

        self._green = spawn(self._run)

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

    @staticmethod
    def _check_list_argument(name: str, ws_argument: List[str]) -> None:
        if ws_argument is None:
            return

        error_message = f'{name} must be a list of strings'
        if not isinstance(ws_argument, list):
            raise TypeError(error_message)
        for item in ws_argument:
            if not isinstance(item, str):
                raise TypeError(error_message)

    def _get_connect_information(self, connect_uri: str) -> Tuple[str, int, str]:
        if not isinstance(connect_uri, str):
            raise TypeError('Your uri must be a string')

        regex = re.match(r'ws://(\w+)(:\d+)?(/\w+)?', connect_uri)
        if not regex:
            raise ValueError('Your uri must follow the syntax ws://<host>[:port][/path]')

        host = regex.group(1)
        port = int(regex.group(2)[1:]) if regex.group(2) is not None else 80
        path = regex.group(3)[1:] if regex.group(3) is not None else self._default_path
        return host, port, path

    @staticmethod
    def _check_callable(method: str, callback: Callable) -> None:
        if not isinstance(callback, callable):
            raise TypeError(f'{method} callback must be a callable')

    @classmethod
    def _on_callback(cls, event_type: EventType, func: Callback) -> Callback:
        cls._callbacks[event_type] = func
        return func

    @classmethod
    def on_connect(cls, func: EventCallback) -> EventCallback:
        return cls._on_callback(EventType.CONNECT, func)

    @classmethod
    def on_disconnect(cls, func: EventCallback) -> EventCallback:
        return cls._on_callback(EventType.DISCONNECT, func)

    @classmethod
    def on_ping(cls, func: BytesCallback) -> BytesCallback:
        return cls._on_callback(EventType.PING, func)

    @classmethod
    def on_pong(cls, func: BytesCallback) -> BytesCallback:
        return cls._on_callback(EventType.PONG, func)

    @classmethod
    def on_text_message(cls, func: StrCallback) -> StrCallback:
        return cls._on_callback(EventType.TEXT_MESSAGE, func)

    @classmethod
    def on_json_message(cls, func: JsonCallback) -> JsonCallback:
        return cls._on_callback(EventType.JSON_MESSAGE, func)

    @classmethod
    def on_binary_message(cls, func: BytesCallback) -> BytesCallback:
        return cls._on_callback(EventType.BINARY_MESSAGE, func)

    def _establish_tcp_connection(self, host: str, port: int) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.connect((host, port))

    def _establish_websocket_handshake(self, host: str, path: str, headers: Headers, extensions: List[str],
                                       sub_protocols: List[str]) -> None:
        self._ws = WSConnection(ConnectionType.CLIENT)
        headers = headers if headers is not None else []
        extensions = extensions if extensions is not None else []
        sub_protocols = sub_protocols if sub_protocols is not None else []
        request = Request(host=host, target=path, extra_headers=headers, extensions=extensions,
                          subprotocols=sub_protocols)
        self._sock.sendall(self._ws.send(request))

    def _run(self) -> None:
        reject_data = bytearray()
        reject_status_code = 400
        reject_headers = []
        text_message = []
        byte_message = bytearray()

        while self._running:
            data = self._sock.recv(self.receive_bytes)
            if not data:
                data = None
            self._ws.receive_data(data)

            for event in self._ws.events():
                if isinstance(event, AcceptConnection):
                    self._handshake_finished.set()
                    if EventType.CONNECT in self._callbacks:
                        self._callbacks[EventType.CONNECT](self, event)

                if isinstance(event, RejectConnection):
                    if not event.has_body:
                        self._handshake_finished.set_exception(
                            ConnectionRejectedError(event.status_code, event.headers, reject_data)
                        )
                        self._running = False
                        break
                    else:
                        reject_status_code = event.status_code
                        reject_headers = event.headers

                if isinstance(event, RejectData):
                    reject_data.extend(event.data)
                    if event.body_finished:
                        self._handshake_finished.set_exception(
                            ConnectionRejectedError(reject_status_code, reject_headers, reject_data)
                        )
                        self._running = False
                        break

                if isinstance(event, CloseConnection):
                    self._running = False
                    if EventType.DISCONNECT in self._callbacks:
                        self._callbacks[EventType.DISCONNECT](event)
                    # if the server sends first a close connection we need to reply with another one
                    if self._ws.state is ConnectionState.REMOTE_CLOSING:
                        self._sock.sendall(self._ws.send(event.response()))

                if isinstance(event, Ping):
                    if EventType.PING in self._callbacks:
                        self._callbacks[EventType.PING](event.payload)
                    self._sock.sendall(self._ws.send(event.response()))

                if isinstance(event, Pong):
                    if EventType.PONG in self._callbacks:
                        self._callbacks[EventType.PONG](event.payload)

                if isinstance(event, TextMessage):
                    text_message.append(event.data)
                    if event.message_finished:
                        if EventType.JSON_MESSAGE in self._callbacks:
                            str_message = ''.join(text_message)
                            try:
                                self._callbacks[EventType.JSON_MESSAGE](self, json.loads(str_message))
                                text_message.clear()
                                continue  # no need to process text handler if json handler already does the job
                            except json.JSONDecodeError:
                                pass
                        if EventType.TEXT_MESSAGE in self._callbacks:
                            self._callbacks[EventType.TEXT_MESSAGE](self, ''.join(text_message))
                        text_message.clear()

                if isinstance(event, BytesMessage):
                    byte_message.extend(event.data)
                    if event.message_finished:
                        if EventType.BINARY_MESSAGE in self._callbacks:
                            self._callbacks[EventType.BINARY_MESSAGE](self, byte_message)
                        byte_message.clear()

        self._sock.close()

    def ping(self, data: bytes = b'hello') -> None:
        self._handshake_finished.get()
        if not isinstance(data, bytes):
            raise TypeError('data must be bytes')

        self._sock.sendall(self._ws.send(Ping(data)))

    def _send_data(self, data: AnyStr) -> None:
        if isinstance(data, str):
            io_object = io.StringIO(data)
        else:
            io_object = io.BytesIO(data)

        with io_object as f:
            chunk = f.read(self.buffer_size)
            while chunk:
                if len(chunk) < self.buffer_size:
                    self._sock.sendall(self._ws.send(Message(data, message_finished=True)))
                    break
                else:
                    self._sock.sendall(self._ws.send(Message(data, message_finished=False)))
                chunk = f.read(self.buffer_size)

    def send(self, data: AnyStr) -> None:
        self._handshake_finished.get()
        if not isinstance(data, (bytes, str)):
            raise TypeError('data must be bytes or string')

        self._send_data(data)

    def send_json(self, data: Any) -> None:
        self.send(json.dumps(data))

    def _close_ws_connection(self):
        close_data = self._ws.send(CloseConnection(code=1000, reason='nothing more to do'))
        self._sock.sendall(close_data)

    def close(self) -> None:
        self._handshake_finished.get()
        if self._ws.state is ConnectionState.OPEN:
            self._close_ws_connection()
        # don't forget to join the run greenlet, if not, you will have some surprises with your event handlers!
        self._green.join()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


if __name__ == '__main__':
    @Client.on_connect
    def connect(_, event: AcceptConnection) -> None:
        print('connection accepted')
        print(event)


    @Client.on_disconnect
    def disconnect(event: CloseConnection) -> None:
        print('connection closed')
        print(event)


    @Client.on_ping
    def ping(payload: bytes) -> None:
        print('ping message:', payload)


    @Client.on_pong
    def pong(payload: bytes) -> None:
        print('pong message:', payload)


    @Client.on_json_message
    def handle_json_message(_, payload: Any) -> None:
        print('json message:', payload)


    @Client.on_text_message
    def handle_text_message(_, payload: str) -> None:
        print('text message:', payload)


    @Client.on_binary_message
    def handle_binary_message(_, payload: bytearray) -> None:
        print('binary message:', payload)


    with Client('ws://localhost:8080/foo') as client:
        client.ping()
        client.send_json({'hello': 'world'})
        client.send('my name is Kevin')
        client.send(b'just some bytes for testing purpose')
