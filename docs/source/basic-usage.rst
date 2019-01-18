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
:class:`WSConnection <wsproto.WSConnection>` object. This object
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

`wsproto` does not do perform any network I/O, so ``<NETWORK GLUE>``
represents the code you need to write to glue `wsproto` to the actual
network layer, i.e.  code that can send and receive data over the
network. The :class:`WSConnection <wsproto.WSConnection>`
class provides two methods for this purpose. When data has been
received on a network socket, you feed this data into `wsproto` by
calling :meth:`receive_data
<wsproto.WSConnection.receive_data>`. When `wsproto` sends
events the :meth:`send <wsproto.WSConnection.send>` will
return the bytes that need to be sent over the network. Your code is
responsible for actually sending that data over the network.

.. note::

    If the connection drops, a standard Python ``socket.recv()`` will return
    zero. You should call ``receive_data(None)`` to update the internal
    `wsproto` state to indicate that the connection has been closed.

Internally, `wsproto` process the raw network data you feed into it and turns it
into higher level representations of WebSocket events. In ``<APPLICATION
GLUE>``, you need to write code to process these events. The
:class:`WSConnection <wsproto.WSConnection>` class contains a
generator method :meth:`events <wsproto.WSConnection.events>` that
yields WebSocket events. To send a message, you call the :meth:`send
<wsproto.WSConnection.send>` method.

Connecting to a WebSocket server
--------------------------------

Begin by instantiating a connection object in the client mode and then
create a :class:`Request <wsproto.events.Request>` instance to
send. The Request must specify ``host`` and ``target`` arguments. If
the WebSocket server is located at ``http://example.com/foo``, then you
would instantiate the connection as follows::

    ws = WSConnection(ConnectionType.CLIENT)
    ws.send(Request(host="example.com", target='foo'))

Now you need to provide the network glue. For the sake of example, we will use
standard Python sockets here, but `wsproto` can be integrated with any network
layer::

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("example.com", 80))

To read from the network::

    data = sock.recv(4096)
    ws.receive_data(data)

You also need to send data returned by the send method::

    data = ws.send(Message(data=b"Hello"))
    sock.send(data)

A standard Python socket will block on the call to ``sock.recv()``, so you
will probably need to use a non-blocking socket or some form of concurrency like
threading, greenlets, asyncio, etc.

You also need to provide the application glue. To send a WebSocket message::

    ws.send(Message(data="Hello world!"))

And to receive WebSocket events::

    for event in ws.events():
        if isinstance(event, AcceptConnection):
            print('Connection established')
        elif isinstance(event, RejectConnection):
            print('Connection rejected')
        elif isinstance(event, CloseConnection):
            print('Connection closed: code={} reason={}'.format(
                event.code, event.reason
            ))
            sock.send(ws.send(event.response()))
        elif isinstance(event, Ping):
            print('Received Ping frame with payload {}'.format(event.payload))
            sock.send(ws.send(event.response()))
        elif isinstance(event, TextMessage):
            print('Received TEXT data: {}'.format(event.data))
            if event.message_finished:
                print('Message finished.')
        elif isinstance(event, BytesMessage):
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

A server also needs to explicitly send an :class:`AcceptConnection
<wsproto.events.AcceptConnection>` after it receives a
``Request`` event::

    for event in ws.events():
        if isinstance(event, Request):
            print('Accepting connection request')
            sock.send(ws.send(AcceptConnection()))
        elif isinstance(event, CloseConnection):
            print('Connection closed: code={} reason={}'.format(
                event.code, event.reason
            ))
            sock.send(ws.send(event.response()))
        elif isinstance(event, Ping):
            print('Received Ping frame with payload {}'.format(event.payload))
            sock.send(ws.send(event.response()))
        elif isinstance(event, TextMessage):
            print('Received TEXT data: {}'.format(event.data))
            if event.message_finished:
                print('TEXT Message finished.')
        elif isinstance(event, BinaryMessage):
            print('Received BINARY data: {}'.format(event.data))
            if event.message_finished:
                print('BINARY Message finished.')
        else:
            print('Unknown event: {!r}'.format(event))

Alternatively a server can explicitly reject the connection by sending
:class:`RejectConnection <wsproto.events.RejectConnection>` after
receiving a ``Request`` event.

For a more complete example, see `synchronous_server.py
<https://github.com/python-hyper/wsproto/blob/master/example/synchronous_server.py>`_.

Protocol Errors
---------------

Protocol errors relating to either incorrect data or incorrect state
changes are raised when the connection receives data or when events
are sent. A :class:`LocalProtocolError
<wsproto.utilities.LocalProtocolError>` is raised if the local actions
are in error whereas a :class:`RemoteProtocolError
<wsproto.utilities.RemoteProtocolError>` is raised if the remote
actions are in error.

Closing
-------

WebSockets are closed with a handshake that requires each endpoint to
send one frame and receive one frame. Sending a
:class:`CloseConnection <wsproto.events.CloseConnection>` instance
sets the state to ``LOCAL_CLOSING``. When a close frame is received,
it yields a ``CloseConnection`` event, sets the state to
``REMOTE_CLOSING`` **and requires a reply to be sent**, this reply
should be a ``CloseConnection`` event. To aid with this the
``CloseConnection`` class has a :func:`response()
<wsproto.events.CloseConnection.response>` method to create the
appropriate reply. For example,

.. code-block:: python

    if isinstance(event, CloseConnection):
        sock.send(ws.send(event.response()))

When the reply has been received by the initiator, it will also yield
a ``CloseConnection`` event.

Regardless of which endpoint initiates the closing handshake, the
server is responsible for tearing down the underlying connection. When
the server receives a ``CloseConnection`` event, it should send
pending `wsproto` data (if any) and then it can start tearing down the
underlying connection.

.. note::

    Both client and server connections must remember to reply to
    ``CloseConnection`` events initiated by the remote party.

Ping Pong
---------

The :class:`WSConnection <wsproto.WSConnection>` class supports
sending WebSocket ping and pong frames via sending :class:`Ping
<wsproto.events.Ping>` and :class:`Pong <wsproto.events.Pong>`. When a
``Ping`` frame is received it **requires a reply**, this reply should be
a ``Pong`` event. To aid with this the ``Ping`` class has a
:func:`response() <wsproto.events.Ping.response>` method to create the
appropriate reply. For example,

.. code-block:: python

    if isinstance(event, Ping):
        sock.send(ws.send(event.response()))

.. note::

    Both client and server connections must remember to reply to
    ``Ping`` events initiated by the remote party.
