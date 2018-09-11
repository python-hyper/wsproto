Getting Started
===============

This document explains how to get started using wsproto to connect to
WebSocket servers as well as how to write your own.

We assume some level of familiarity with writing Python and networking code. If
you're not familiar with these we highly recommend `you read up on these first
<https://docs.python.org/3/howto/sockets.html>`_. It may also be helpful `to
study Sans-I/O <https://sans-io.readthedocs.io/>`_, which describes the ideas
behind writing a network protocol library that doesn't do any network I/O.

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

`wsproto` does not do perform any network I/O, so ``<NETWORK GLUE>`` represents
the code you need to write to glue `wsproto` to the actual network layer, i.e.
code that can send and receive data over the network. The
:class:`WSConnection <wsproto.connection.WSConnection>` class provides two
methods for this purpose. When data has been received on a network socket, you
feed this data into `wsproto` by calling :meth:`receive_bytes
<wsproto.connection.WSConnection.receive_bytes>`. When `wsproto` has data that
needs to be sent over the network, you retrieve that data by calling
:meth:`bytes_to_send <wsproto.connection.WSConnection.bytes_to_send>`, and your
code is responsible for actually sending that data over the network.

.. note::

    If the connection drops, a standard Python ``socket.recv()`` will return
    zero. You should call ``receive_bytes(None)`` to update the internal
    `wsproto` state to indicate that the connection has been closed.

Internally, `wsproto` process the raw network data you feed into it and turns it
into higher level representations of WebSocket events. In ``<APPLICATION
GLUE>``, you need to write code to process these events. The
:class:`WSConnection <wsproto.connection.WSConnection>` class contains a
generator method :meth:`events <wsproto.connection.WSConnection.events>` that
yields WebSocket events. To send a message, you call the :meth:`send_data
<wsproto.connection.WSConnection.send_data>` method.

Connecting to a WebSocket server
--------------------------------

Begin by instantiating a connection object. The ``host`` and ``resource``
arguments are required to instantiate a client. If the WebSocket server is
located at ``http://myhost.com/foo``, then you would instantiate the connection
as follows::

    ws = WSConnection(ConnectionType.CLIENT, host="myhost.com", resource='foo')

Now you need to provide the network glue. For the sake of example, we will use
standard Python sockets here, but `wsproto` can be integrated with any network
layer::

    stream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    stream.connect(("myhost", 8000))

To read from the network::

    data = stream.recv(4096)
    ws.receive_bytes(data)

You also need to check if `wsproto` has data to send to the network::

    data = ws.bytes_to_send()
    stream.send(data)

Note that ``bytes_to_send()`` will return zero bytes if the protocol has no
pending data. You can either poll this method or call it only when you expect
to have pending data.

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
            print('Received TEXT data: {}'.format(event.data))
            if event.message_finished:
                print('Message finished.')
        elif isinstance(event, BinaryReceived):
            print('Received BINARY data: {}'.format(event.data))
            if event.message_finished:
                print('BINARY Message finished.')
        else:
            print('Unknown event: {!r}'.format(event))

The method ``events()`` returns a generator which will yield events for all of
the data currently in the `wsproto` internal buffer and then exit. Therefore,
you should iterate over this generator after receiving new network data.

For a more complete example, see `synchronous_client.py
<https://github.com/python-hyper/wsproto/blob/master/example/synchronous_client.py>`_.

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
            print('Received TEXT data: {}'.format(event.data))
            if event.message_finished:
                print('TEXT Message finished.')
        elif isinstance(event, BinaryReceived):
            print('Received BINARY data: {}'.format(event.data))
            if event.message_finished:
                print('BINARY Message finished.')
        else:
            print('Unknown event: {!r}'.format(event))

For a more complete example, see `synchronous_server.py
<https://github.com/python-hyper/wsproto/blob/master/example/synchronous_server.py>`_.

Closing
-------

WebSockets are closed with a handshake that requires each endpoint to send one
frame and receive one frame. The ``close()`` method places a close frame in the
send buffer. When a close frame is received, it yields a ``ConnectionClosed``
event, *and it also places a reply frame in the send buffer.* When that reply
has been received by the initiator, it will also receive a ``ConnectionClosed``
event.

Regardless of which endpoint initiates the closing handshake, the server is
responsible for tearing down the underlying connection. When the server receives
a ``ConnectionClosed`` event, it should send pending `wsproto` data (if any)
and then it can start tearing down the underlying connection.

Ping Pong
---------

The :class:`WSConnection <wsproto.connection.WSConnection>` class supports
sending WebSocket ping and pong frames via the methods :meth:`ping
<wsproto.connection.WSConnection.ping>` and :meth:`pong
<wsproto.connection.WSConnection.pong>`.

.. note::

    When a ping is received, `wsproto` automatically places a pong frame in
    its outgoing buffer. You should only call ``pong()`` if you want to send an
    unsolicited pong frame.

Back-pressure
-------------

Back-pressure is an important concept to understand when implementing a
client/server protocol. This section briefly explains the issue and then
explains how to handle back-pressure when using `wsproto`.

Imagine that you have a WebSocket server that reads messages from the client,
does some processing, and then sends a response. What happens if the client
sends messages faster than the the server can process them? If the incoming
messages are buffered in memory, then the server will slowly use more and more
memory, until the OS eventually kills it. This scenario is directly applicable
to `wsproto`, because every time you call ``receive_bytes()``, it appends that
data to an internal buffer.

The slow endpoint needs a way to signal the fast endpoint to stop sending
messages until the slow endpoint can catch up. This signaling is called
"back-pressure". As a Sans-IO library, `wsproto` is not responsible for
network concerns like back-pressure, so that responsibility belongs to your
network glue code.

Fortunately, TCP has the ability to signal backpressure, and the operating
system will do that for you automatically—if you follow a few rules! The OS
buffers all incoming and outgoing network data. Standard Python socket methods
like ``send()`` and ``recv()`` copy data to and from those OS buffers. For
example, if the peer is sending data too quickly, then the OS receive buffere
will start to get full, and the OS will signal the peer to stop transmitting.
When ``recv()`` is called, the OS will copy data from its internal buffer into
your process, free up space in its own buffer, and then signal to the peer to
start transmitting again.

Therefore, you need to follow these two rules to implement back-pressure over
TCP:

#. Do not receive from the socket faster than your code can process the
   messages. Your processing code may need to signal the receiving code when its
   ready to receive more data.
#. Do not store out-going messages in an unbounded collection. Ideally,
   out-going messages should be sent to the OS as soon as possible. If you need
   to buffer messages in memory, the buffer should be bounded so that it can not
   grow indefinitely.
