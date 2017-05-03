import asyncio

from wsproto.connection import WSConnection, SERVER, ConnectionRequested, \
                               ConnectionClosed
from wsproto.events import DataReceived
from wsproto.extensions import PerMessageDeflate

count = 0

def new_conn(reader, writer):
    global count
    print("test_server.py received connection {}".format(count))
    count += 1
    ws = WSConnection(SERVER, extensions=[PerMessageDeflate()])
    closed = False
    while not closed:
        try:
            data = yield from reader.read(65535)
        except ConnectionError:
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
            writer.write(data)
            yield from writer.drain()
        except (ConnectionError, OSError):
            closed = True

    writer.close()

# It's important to get a clean shutdown so that coverage will work
def shutdown_conn(reader, writer):
    asyncio.get_event_loop().stop()

start_server = asyncio.start_server(new_conn, '127.0.0.1', 8642)
start_shutdown_watcher = asyncio.start_server(shutdown_conn, '127.0.0.1', 8643)

if __name__ == '__main__':
    try:
        asyncio.get_event_loop().run_until_complete(start_server)
        asyncio.get_event_loop().run_until_complete(start_shutdown_watcher)
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        pass
