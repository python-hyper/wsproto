import asyncio

from wsproto.connection import WSConnection, SERVER, ConnectionRequested, \
                               ConnectionClosed
from wsproto.events import DataReceived
from wsproto.extensions import PerMessageDeflate

def new_conn(reader, writer):
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
                ws.send_data(event.data, event.final)
            elif isinstance(event, ConnectionClosed):
                closed = True
            if data is None:
                break

            try:
                data = ws.bytes_to_send()
                writer.write(data)
                yield from writer.drain()
            except (ConnectionError, OSError):
                closed = True

            if closed:
                break

    writer.close()

start_server = asyncio.start_server(new_conn, '127.0.0.1', 8642)

if __name__ == '__main__':
    try:
        asyncio.get_event_loop().run_until_complete(start_server)
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        pass
