"""
The client reads a line from stdin, sends it to the server, then prints the
response. This is a poor implementation of a client. It is only intended to
demonstrate how to use wsproto.
"""
from __future__ import annotations

import socket
import sys

from wsproto import WSConnection
from wsproto.connection import ConnectionType
from wsproto.events import (
    AcceptConnection,
    CloseConnection,
    Message,
    Ping,
    Pong,
    Request,
    TextMessage,
)

RECEIVE_BYTES = 4096


def main() -> None:
    """Run the client."""
    try:
        host = sys.argv[1]
        port = int(sys.argv[2])
    except (IndexError, ValueError):
        print(f"Usage: {sys.argv[0]} <HOST> <PORT>")
        sys.exit(1)

    try:
        wsproto_demo(host, port)
    except KeyboardInterrupt:
        print("\nReceived SIGINT: shutting down…")


def wsproto_demo(host: str, port: int) -> None:
    """
    Demonstrate wsproto:

    0) Open TCP connection
    1) Negotiate WebSocket opening handshake
    2) Send a message and display response
    3) Send ping and display pong
    4) Negotiate WebSocket closing handshake
    """
    # 0) Open TCP connection
    print(f"Connecting to {host}:{port}")
    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    conn.connect((host, port))

    # 1) Negotiate WebSocket opening handshake
    print("Opening WebSocket")
    ws = WSConnection(ConnectionType.CLIENT)
    # Because this is a client WebSocket, we need to initiate the connection
    # handshake by sending a Request event.
    net_send(ws.send(Request(host=host, target="server")), conn)
    net_recv(ws, conn)
    handle_events(ws)

    # 2) Send a message and display response
    message = "wsproto is great"
    print(f"Sending message: {message}")
    net_send(ws.send(Message(data=message)), conn)
    net_recv(ws, conn)
    handle_events(ws)

    # 3) Send ping and display pong
    payload = b"table tennis"
    print(f"Sending ping: {payload!r}")
    net_send(ws.send(Ping(payload=payload)), conn)
    net_recv(ws, conn)
    handle_events(ws)

    # 4) Negotiate WebSocket closing handshake
    print("Closing WebSocket")
    net_send(ws.send(CloseConnection(code=1000, reason="sample reason")), conn)
    # After sending the closing frame, we won't get any more events. The server
    # should send a reply and then close the connection, so we need to receive
    # twice:
    net_recv(ws, conn)
    conn.shutdown(socket.SHUT_WR)
    net_recv(ws, conn)


def net_send(out_data: bytes, conn: socket.socket) -> None:
    """Write pending data from websocket to network."""
    print(f"Sending {len(out_data)} bytes")
    conn.send(out_data)


def net_recv(ws: WSConnection, conn: socket.socket) -> None:
    """Read pending data from network into websocket."""
    in_data = conn.recv(RECEIVE_BYTES)
    if not in_data:
        # A receive of zero bytes indicates the TCP socket has been closed. We
        # need to pass None to wsproto to update its internal state.
        print("Received 0 bytes (connection closed)")
        ws.receive_data(None)
    else:
        print(f"Received {len(in_data)} bytes")
        ws.receive_data(in_data)


def handle_events(ws: WSConnection) -> None:
    for event in ws.events():
        if isinstance(event, AcceptConnection):
            print("WebSocket negotiation complete")
        elif isinstance(event, TextMessage):
            print(f"Received message: {event.data}")
        elif isinstance(event, Pong):
            print(f"Received pong: {event.payload!r}")
        else:
            raise Exception("Do not know how to handle event: " + str(event))


if __name__ == "__main__":
    main()
