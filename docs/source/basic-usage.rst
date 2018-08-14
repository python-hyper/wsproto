Getting Started
===============

This document explains how to get started using wsproto to connect to
WebSocket servers as well as how to write your own.

We assume some level of familiarity with writing Python and networking code. If
you're not familiar with these we highly recommend `you read up on these first
<https://docs.python.org/3/howto/sockets.html>`_.

Connections
-----------

The main class you'll be working with is the
:class:`WSConnection <wsproto.connection.WSConnection>` object. This object
represents a connection to a WebSocket client or server and contains all the
state needed to communicate with the entity at the other end. Whether you're
connecting to a server or receiving a connection from a client, this is the
object you'll use.

`wsproto` provides two layers of abstractions. You need to write code that
interfaces with both of these layers. The following diagram illustrates how your
code is like a sandwich around `wsproto`.

+--------------------+
| Application        |
+--------------------+
| <APPLICATION GLUE> |
+--------------------+
| wsproto            |
+--------------------+
| <NETWORK GLUE>     |
+--------------------+
| Network Layer      |
+--------------------+

``wsproto`` does not do perform any network I/O, so ``<NETWORK GLUE>``
represents the code you need to write to glue ``wsproto`` to the actual network
layer, i.e. code that can send and receive data over the network. The
:class:`WSConnection <wsproto.connection.WSConnection>` class provides two
methods for this purpose. When data has been received on a network socket, you
feed this data into `wsproto` by calling :meth:`receive_bytes
<wsproto.connection.WSConnection.receive_bytes>`. When `wsproto` has data that
needs to be sent over the network, you retrieve that data by calling
:meth:`bytes_to_send <wsproto.connection.WSConnection.bytes_to_send>`, and your
code is responsible for actually sending that data over the network.

Internally, ``wsproto`` process the raw network data you feed into it and turns
it into higher level representations of WebSocket events, such as receiving a
WebSocket message. In ``<APPLICATION GLUE>``, you need to write code to process
these events. The :class:`WSConnection <wsproto.connection.WSConnection>` class
contains a generator method :meth:`events
<wsproto.connection.WSConnection.events>` that yields WebSocket events. To send
a message, you call the :meth:`send_data
<wsproto.connection.WSConnection.send_data>` method.

Connecting to a WebSocket server
--------------------------------

Begin by instantiating a connection object. The ``host`` and ``resource``
arguments are required to instantiate a client. If the WebSocket server is
located at ``http://myhost.com/foo``, then you would instantiate the connection
as follows.

    ws = WSConnection(ConnectionType.CLIENT, host="myhost.com", resource='foo')

Now you need to provide the network glue. For the sake of example, we will use
standard Python sockets here, but ``wsproto`` can be integrated with any network
layer::

    stream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    stream.connect(("myhost", 8000))

To read from the network::

    data = stream.recv(4096)
    ws.receive_bytes(data)

You also need to check if ``wsproto`` has data to send to the network::

    data = ws.bytes_to_send()
    stream.send(data)

A standard Python socket will block on the call to ``stream.recv()``, so you
will probably need to use a non-blocking socket or some form of concurrency like
threading, greenlets, asyncio, etc.

You also need to provide the application glue. To send a WebSocket message::

    ws.send_data("Hello world!")

And to receive WebSocket events::

    for event in ws.events():
        if isinstance(event, ConnectionEstablished):
            print('Connection established')
        elif isinstance(event, ConnectionClosed):
            print('Connection closed: code={} reason={}'.format(
                event.code, event.reason))
        elif isinstance(event, TextReceived):
            print('Received message: {}'.format(event.data))
        else:
            print('Unknown event: {!r}'.format(event))

For a more complete example, see this `toy websocket client
<https://gist.github.com/mehaase/772efaf451eca7a5c3ce7e72ebaefe4e#file-wsproto_client_sync-py>`_.

WebSocket Servers
-----------------

A WebSocket server is similar to a client except that it uses a different
constant::

    ws = WSConnection(ConnectionType.SERVER)

A server also needs to explicitly call the ``accept`` method after it receives a
``ConnectionRequested`` event::

    for event in ws.events():
        if isinstance(event, ConnectionRequested):
            print('Accepting connection request')
            ws.accept(event)
        elif isinstance(event, ConnectionClosed):
            print('Connection closed: code={} reason={}'.format(
                event.code, event.reason))
        elif isinstance(event, TextReceived):
            print('Received message: {}'.format(event.data))
        else:
            print('Unknown event: {!r}'.format(event))

For a more complete example, see this `toy websocket server
<https://gist.github.com/mehaase/772efaf451eca7a5c3ce7e72ebaefe4e#file-wsproto_server_sync-py>`_.
