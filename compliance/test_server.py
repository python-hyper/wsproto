import select
import socket

from wsproto.connection import WSConnection, SERVER, ConnectionRequested, \
                               ConnectionClosed
from wsproto.events import DataReceived
from wsproto.extensions import PerMessageDeflate

count = 0

def new_conn(sock):
    global count
    print("test_server.py received connection {}".format(count))
    count += 1
    ws = WSConnection(SERVER, extensions=[PerMessageDeflate()])
    closed = False
    while not closed:
        try:
            data = sock.recv(65535)
        except socket.error:
            data = None

        ws.receive_bytes(data or None)

        for event in ws.events():
            if isinstance(event, ConnectionRequested):
                ws.accept(event)
            elif isinstance(event, DataReceived):
                ws.send_data(event.data, event.message_finished)
            elif isinstance(event, ConnectionClosed):
                closed = True

        if not data:
            closed = True

        try:
            data = ws.bytes_to_send()
            sock.sendall(data)
        except socket.error:
            closed = True

    sock.close()

def start_listener(host='127.0.0.1', port=8642, shutdown_port=8643):
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
        r, _, _ = select.select(filenos.keys(), [], [], 0)

        for sock in [filenos[fd] for fd in r]:
            if sock is server:
                new_conn(server.accept()[0])
            else:
                done = True

if __name__ == '__main__':
    try:
        start_listener()
    except KeyboardInterrupt:
        pass
