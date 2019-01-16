import json
import socket

from wsproto import WSConnection
from wsproto.compat import PY2
from wsproto.connection import CLIENT
from wsproto.events import AcceptConnection, CloseConnection, Ping, Request, TextMessage, Message
from wsproto.extensions import PerMessageDeflate
from wsproto.frame_protocol import CloseReason

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
    connection = WSConnection(CLIENT)
    sock = socket.socket()
    sock.connect((uri.hostname, uri.port or 80))

    sock.sendall(connection.send(Request(host=uri.netloc, target=uri.path)))

    case_count = None
    while case_count is None:
        data = sock.recv(65535)
        connection.receive_data(data)
        data = ""
        out_data = b""
        for event in connection.events():
            if isinstance(event, TextMessage):
                data += event.data
                if event.message_finished:
                    case_count = json.loads(data)
                    out_data += connection.send(CloseConnection(code=CloseReason.NORMAL_CLOSURE))
            try:
                sock.sendall(out_data)
            except CONNECTION_EXCEPTIONS:
                break

    sock.close()
    return case_count

def run_case(server, case, agent):
    uri = urlparse(server + '/runCase?case=%d&agent=%s' % (case, agent))
    connection = WSConnection(CLIENT)
    sock = socket.socket()
    sock.connect((uri.hostname, uri.port or 80))

    sock.sendall(
        connection.send(Request(
            host=uri.netloc, target='%s?%s' % (uri.path, uri.query),
            extensions=[PerMessageDeflate()],
        ))
    )
    closed = False

    while not closed:
        try:
            data = sock.recv(65535)
        except CONNECTION_EXCEPTIONS:
            data = None
        connection.receive_data(data or None)
        out_data = b""
        for event in connection.events():
            if isinstance(event, Message):
                out_data += connection.send(Message(data=event.data, message_finished=event.message_finished))
            elif isinstance(event, Ping):
                out_data += connection.send(event.response())
            elif isinstance(event, CloseConnection):
                closed = True
                out_data += connection.send(event.response())
            # else:
            #     print("??", event)
        if out_data is None:
            break
        try:
            sock.sendall(out_data)
        except CONNECTION_EXCEPTIONS:
            closed = True
            break

def update_reports(server, agent):
    uri = urlparse(server + '/updateReports?agent=%s' % agent)
    connection = WSConnection(CLIENT)
    sock = socket.socket()
    sock.connect((uri.hostname, uri.port or 80))

    sock.sendall(
        connection.send(Request(host=uri.netloc, target='%s?%s' % (uri.path, uri.query)))
    )
    closed = False

    while not closed:
        data = sock.recv(65535)
        connection.receive_data(data)
        for event in connection.events():
            if isinstance(event, AcceptConnection):
                sock.sendall(connection.send(CloseConnection(code=CloseReason.NORMAL_CLOSURE)))
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
