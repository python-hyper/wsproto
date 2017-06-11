import json
import socket

from wsproto.compat import PY2
from wsproto.connection import WSConnection, CLIENT, ConnectionEstablished, \
                               ConnectionClosed
from wsproto.events import TextReceived, DataReceived
from wsproto.extensions import PerMessageDeflate

if PY2:
    from urlparse import urlparse
else:
    from urllib.parse import urlparse

SERVER = 'ws://127.0.0.1:8642'
AGENT = 'wsproto'

if PY2:
    CONNECTION_EXCEPTIONS = (OSError,)
else:
    CONNECTION_EXCEPTIONS = (ConnectionError, OSError)

def get_case_count(server):
    uri = urlparse(server + '/getCaseCount')
    connection = WSConnection(CLIENT, uri.netloc, uri.path)
    sock = socket.socket()
    sock.connect((uri.hostname, uri.port or 80))

    sock.sendall(connection.bytes_to_send())

    case_count = None
    while case_count is None:
        data = sock.recv(65535)
        connection.receive_bytes(data)
        data = ""
        for event in connection.events():
            if isinstance(event, TextReceived):
                data += event.data
                if event.message_finished:
                    case_count = json.loads(data)
                    connection.close()
            try:
                sock.sendall(connection.bytes_to_send())
            except CONNECTION_EXCEPTIONS:
                break

    sock.close()
    return case_count

def run_case(server, case, agent):
    uri = urlparse(server + '/runCase?case=%d&agent=%s' % (case, agent))
    connection = WSConnection(CLIENT,
                              uri.netloc, '%s?%s' % (uri.path, uri.query),
                              extensions=[PerMessageDeflate()])
    sock = socket.socket()
    sock.connect((uri.hostname, uri.port or 80))

    sock.sendall(connection.bytes_to_send())
    closed = False

    while not closed:
        try:
            data = sock.recv(65535)
        except CONNECTION_EXCEPTIONS:
            data = None
        connection.receive_bytes(data or None)
        for event in connection.events():
            if isinstance(event, DataReceived):
                connection.send_data(event.data, event.message_finished)
            elif isinstance(event, ConnectionClosed):
                closed = True
            # else:
            #     print("??", event)
        if data is None:
            break
        try:
            data = connection.bytes_to_send()
            sock.sendall(data)
        except CONNECTION_EXCEPTIONS:
            closed = True
            break

def update_reports(server, agent):
    uri = urlparse(server + '/updateReports?agent=%s' % agent)
    connection = WSConnection(CLIENT,
                              uri.netloc, '%s?%s' % (uri.path, uri.query))
    sock = socket.socket()
    sock.connect((uri.hostname, uri.port or 80))

    sock.sendall(connection.bytes_to_send())
    closed = False

    while not closed:
        data = sock.recv(65535)
        connection.receive_bytes(data)
        for event in connection.events():
            if isinstance(event, ConnectionEstablished):
                connection.close()
                sock.sendall(connection.bytes_to_send())
                try:
                    sock.close()
                except CONNECTION_EXCEPTIONS:
                    pass
                finally:
                    closed = True

CASE = None
# 1.1.1 = 1
# 2.1 = 17
# 3.1 = 28
# 4.1.1 = 34
# 5.1 = 44
# 6.1.1 = 64
# 12.1.1 = 304
# 13.1.1 = 394

def run_tests(server, agent):
    case_count = get_case_count(server)
    if CASE is not None:
        print(">>>>> Running test case %d" % CASE)
        run_case(server, CASE, agent)
    else:
        for case in range(1, case_count + 1):
            print(">>>>> Running test case %d of %d" % (case, case_count))
            run_case(server, case, agent)
        print("\nRan %d cases." % case_count)
    update_reports(server, agent)

if __name__ == '__main__':
    run_tests(SERVER, AGENT)
