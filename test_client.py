import asyncio
import json
from urllib.parse import urlparse

from hws.connection import WSConnection, ConnectionEstablished, BinaryMessageReceived, TextMessageReceived, ConnectionClosed

SERVER = 'ws://127.0.0.1:8642'
AGENT = 'hws'

@asyncio.coroutine
def get_case_count(server):
    uri = urlparse(server + '/getCaseCount')
    connection = WSConnection(uri.netloc, uri.path)
    reader, writer = yield from asyncio.open_connection(uri.hostname, uri.port or 80)

    connection.initiate_connection()
    writer.write(connection.bytes_to_send())

    case_count = None
    while case_count is None:
        data = yield from reader.read(65535)
        connection.receive_bytes(data)
        for event in connection.events():
            print(repr(event))
            if isinstance(event, TextMessageReceived):
                print(repr(event.message))
                case_count = json.loads(event.message)
                connection.close()
            try:
                writer.write(connection.bytes_to_send())
                yield from writer.drain()
            except (ConnectionError, OSError):
                break

    return case_count

@asyncio.coroutine
def run_case(server, case, agent):
    uri = urlparse(server + '/runCase?case=%d&agent=%s' % (case, agent))
    connection = WSConnection(uri.netloc, '%s?%s' % (uri.path, uri.query))
    reader, writer = yield from asyncio.open_connection(uri.hostname, uri.port or 80)

    connection.initiate_connection()
    writer.write(connection.bytes_to_send())
    closed = False

    while not closed:
        try:
            data = yield from reader.read(65535)
        except ConnectionError:
            data = None
        connection.receive_bytes(data or None)
        for event in connection.events():
            if isinstance(event, TextMessageReceived):
                print("Echoing text message.")
                connection.send_text(event.message)
            elif isinstance(event, BinaryMessageReceived):
                connection.send_binary(event.message)
                print("Echoing binary message.")
            elif isinstance(event, ConnectionClosed):
                print("Connection closed: %r" % event.code)
                closed = True
            if data is None:
                break
            try:
                data = connection.bytes_to_send()
                writer.write(data)
                yield from writer.drain()
            except (ConnectionError, OSError):
                closed = True
                break

@asyncio.coroutine
def update_reports(server, agent):
    uri = urlparse(server + '/updateReports?agent=%s' % agent)
    connection = WSConnection(uri.netloc, '%s?%s' % (uri.path, uri.query))
    reader, writer = yield from asyncio.open_connection(uri.hostname, uri.port or 80)

    connection.initiate_connection()
    writer.write(connection.bytes_to_send())
    closed = False

    while not closed:
        data = yield from reader.read(65535)
        connection.receive_bytes(data)
        for event in connection.events():
            if isinstance(event, ConnectionEstablished):
                connection.close()
                writer.write(connection.bytes_to_send())
                try:
                    yield from writer.drain()
                    writer.close()
                except (ConnectionError, OSError):
                    pass
                finally:
                    closed = True

CASE = None

@asyncio.coroutine
def run_tests(server, agent):
    case_count = yield from get_case_count(server)
    if CASE is not None:
        print(">>>>> Running test case %d" % CASE)
        yield from run_case(server, CASE, agent)
    else:
        for case in range(1, case_count + 1):
            print(">>>>> Running test case %d of %d" % (case, case_count))
            yield from run_case(server, case, agent)
        print("\nRan %d cases." % case_count)
    yield from update_reports(server, agent)

if __name__ == '__main__':
    main = run_tests(SERVER, AGENT)
    asyncio.get_event_loop().run_until_complete(main)
