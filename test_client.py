import asyncio
import json
from urllib.parse import urlparse

from hws.connection import WSClient, ConnectionEstablished, \
                           BinaryMessageReceived, TextMessageReceived, \
                           ConnectionClosed, PerMessageDeflate

SERVER = 'ws://127.0.0.1:8642'
AGENT = 'hws'

@asyncio.coroutine
def get_case_count(server):
    uri = urlparse(server + '/getCaseCount')
    connection = WSClient(uri.netloc, uri.path)
    reader, writer = yield from asyncio.open_connection(uri.hostname, uri.port or 80)

    writer.write(connection.bytes_to_send())

    case_count = None
    while case_count is None:
        data = yield from reader.read(65535)
        connection.receive_bytes(data)
        for event in connection.events():
            if isinstance(event, TextMessageReceived):
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
    connection = WSClient(uri.netloc, '%s?%s' % (uri.path, uri.query),
                          extensions=[PerMessageDeflate()])
    reader, writer = yield from asyncio.open_connection(uri.hostname, uri.port or 80)

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
                connection.send_text(event.message)
            elif isinstance(event, BinaryMessageReceived):
                connection.send_binary(event.message)
            elif isinstance(event, ConnectionClosed):
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
    connection = WSClient(uri.netloc, '%s?%s' % (uri.path, uri.query))
    reader, writer = yield from asyncio.open_connection(uri.hostname, uri.port or 80)

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
# 1.1.1 = 1
# 2.1 = 17
# 3.1 = 28
# 4.1.1 = 34
# 5.1 = 44
# 6.1.1 = 64
# 12.1.1 = 304
# 13.1.1 = 394

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
