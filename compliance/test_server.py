import select
import socket
from typing import Optional

from wsproto import WSConnection
from wsproto.connection import ConnectionState, SERVER
from wsproto.events import AcceptConnection, CloseConnection, Message, Ping, Request
from wsproto.extensions import PerMessageDeflate

count = 0


def new_conn(sock: socket.socket) -> None:
    global count
    print("test_server.py received connection {}".format(count))
    count += 1
    ws = WSConnection(SERVER)
    closed = False
    while not closed:
        try:
            data: Optional[bytes] = sock.recv(65535)
        except socket.error:
            data = None

        ws.receive_data(data or None)

        outgoing_data = b""
        for event in ws.events():
            if isinstance(event, Request):
                outgoing_data += ws.send(
                    AcceptConnection(extensions=[PerMessageDeflate()])
                )
            elif isinstance(event, Message):
                outgoing_data += ws.send(
                    Message(data=event.data, message_finished=event.message_finished)
                )
            elif isinstance(event, Ping):
                outgoing_data += ws.send(event.response())
            elif isinstance(event, CloseConnection):
                closed = True
                if ws.state is not ConnectionState.CLOSED:
                    outgoing_data += ws.send(event.response())

        if not data:
            closed = True

        try:
            sock.sendall(outgoing_data)
        except socket.error:
            closed = True

    sock.close()


def start_listener(
    host: str = "127.0.0.1", port: int = 8642, shutdown_port: int = 8643
) -> None:
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(1)
    shutdown_server = socket.socket()
    shutdown_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    shutdown_server.bind((host, shutdown_port))
    shutdown_server.listen(1)

    done = False
    filenos = {s.fileno(): s for s in (server, shutdown_server)}

    while not done:
        r, _, _ = select.select(list(filenos.keys()), [], [], 0)

        for sock in [filenos[fd] for fd in r]:
            if sock is server:
                new_conn(server.accept()[0])
            else:
                done = True


if __name__ == "__main__":
    try:
        start_listener()
    except KeyboardInterrupt:
        pass
