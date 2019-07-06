"""
This server reads a message from a WebSocket, and sends the reverse string in a
response message. It can only handle one client at a time. This is a very bad
implementation of a server! It is only intended to demonstrate how to use
wsproto.
"""

import socket
import sys

from wsproto import ConnectionType, WSConnection
from wsproto.events import (
    AcceptConnection,
    CloseConnection,
    Message,
    Ping,
    Request,
    TextMessage,
)

MAX_CONNECTS = 5
RECEIVE_BYTES = 4096


def main() -> None:
    """Run the server."""
    try:
        ip = sys.argv[1]
        port = int(sys.argv[2])
    except (IndexError, ValueError):
        print("Usage: {} <BIND_IP> <PORT>".format(sys.argv[0]))
        sys.exit(1)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((ip, port))
    server.listen(0)

    try:
        while True:
            print("Waiting for connection...")
            (stream, addr) = server.accept()
            print("Client connected: {}:{}".format(addr[0], addr[1]))
            handle_connection(stream)
            stream.shutdown(socket.SHUT_WR)
            stream.close()
    except KeyboardInterrupt:
        print("Received SIGINT: shutting down…")


def handle_connection(stream: socket.socket) -> None:
    """
    Handle a connection.

    The server operates a request/response cycle, so it performs a synchronous
    loop:

    1) Read data from network into wsproto
    2) Get new events and handle them
    3) Send data from wsproto to network

    :param stream: a socket stream
    """
    ws = WSConnection(ConnectionType.SERVER)
    running = True

    while running:
        # 1) Read data from network
        in_data = stream.recv(RECEIVE_BYTES)
        print("Received {} bytes".format(len(in_data)))
        ws.receive_data(in_data)

        # 2) Get new events and handle them
        out_data = b""
        for event in ws.events():
            if isinstance(event, Request):
                # Negotiate new WebSocket connection
                print("Accepting WebSocket upgrade")
                out_data += ws.send(AcceptConnection())
            elif isinstance(event, CloseConnection):
                # Print log message and break out
                print(
                    "Connection closed: code={} reason={}".format(
                        event.code, event.reason
                    )
                )
                out_data += ws.send(event.response())
                running = False
            elif isinstance(event, TextMessage):
                # Reverse text and send it back to wsproto
                print("Received request and sending response")
                out_data += ws.send(Message(data=event.data[::-1]))
            elif isinstance(event, Ping):
                # wsproto handles ping events for you by placing a pong frame in
                # the outgoing buffer. You should not call pong() unless you want to
                # send an unsolicited pong frame.
                print("Received ping and sending pong")
                out_data += ws.send(event.response())
            else:
                print("Unknown event: {!r}".format(event))

        # 4) Send data from wsproto to network
        print("Sending {} bytes".format(len(out_data)))
        stream.send(out_data)


if __name__ == "__main__":
    main()
