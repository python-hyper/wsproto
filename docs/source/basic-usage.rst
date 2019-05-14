Getting Started
===============

.. currentmodule:: wsproto

This document explains how to get started using wsproto to connect to
WebSocket servers as well as how to write your own.

We assume some level of familiarity with writing Python and networking code. If
you're not familiar with these we highly recommend `you read up on these first
<https://docs.python.org/3/howto/sockets.html>`_. It may also be helpful `to
study Sans-I/O <https://sans-io.readthedocs.io/>`_, which describes the ideas
behind writing a network protocol library that doesn't do any network I/O.

Connections
-----------

The main class you'll be working with is the :class:`WSConnection` object. This
object represents a connection to a WebSocket peer. This class can handle both
WebSocket clients and WebSocket servers.

``wsproto`` provides two layers of abstractions. You need to write code that
interfaces with both of these layers. The following diagram illustrates how your
code is like a sandwich around ``wsproto``.

+----------------------+
| Application          |
+----------------------+
| **APPLICATION GLUE** |
+----------------------+
| wsproto              |
+----------------------+
| **NETWORK GLUE**     |
+----------------------+
| Network Layer        |
+----------------------+

``wsproto`` does not do perform any network I/O, so **NETWORK GLUE** represents
the code you need to write to glue ``wsproto`` to an actual network, for example
using Python's `socket <https://docs.python.org/3/library/socket.html>`_ module.
The :class:`WSConnection` class provides two methods for this purpose. When data
has been received on a network socket, you should feed this data into a
connection instance by calling :meth:`WSConnection.receive_data`. When you want
to communicate with the remote peer, e.g. send a message, ping, or close the
connection, you should create an instance of one of the
:class:`wsproto.events.Event` subclasses and pass it to
:meth:`WSConnection.send` to get the corresponding bytes that need to be sent.
Your code is responsible for actually sending that data over the network.

.. note::

    If the connection drops, a standard Python ``socket.recv()`` will return
    zero bytes. You should call ``receive_data(None)`` to update the internal
    ``wsproto`` state to indicate that the connection has been closed.

Internally, ``wsproto`` processes the raw network data you feed into it and
turns it into higher level representations of WebSocket events. In **APPLICATION
GLUE**, you need to write code to process these events. Incoming data is exposed
though the generator method :meth:`WSConnection.events`, which yields WebSocket
events. Each event is an instance of an :class:`.events.Event` subclass.

WebSocket Clients
-----------------

Begin by instantiating a connection object in client mode and then create a
:class:`wsproto.events.Request` instance. The Request must specify ``host`` and
``target`` arguments. If the WebSocket server is located at
``http://example.com/foo``, then you would instantiate the connection as
follows::

    from wsproto import ConnectionType, WSConnection
    from wsproto.events import Request
    ws = WSConnection(ConnectionType.CLIENT)
    request = Request(host="example.com", target='foo')
    data = ws.send(request)

Keep in mind that ``wsproto`` does not do any network I/O. Instead,
:meth:`WSConnection.send` returns data that you must send to the remote peer.
Here is an example using a standard Python socket::

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("example.com", 80))
    sock.send(data)

To receive communications from the peer, you must pass the data received from
the peer into the connection instance::

    data = sock.recv(4096)
    ws.receive_data(data)

The connection instance parses the received data and determines if any high-level
events have occurred, such as receiving a ping or a message. To retrieve these
events, use the generator function :meth:`WSConnection.events`::

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
the data currently in the ``wsproto`` internal buffer and then exit. Therefore,
you should iterate over this generator after receiving new network data.

For a more complete example, see `synchronous_client.py
<https://github.com/python-hyper/wsproto/blob/master/example/synchronous_client.py>`_.

WebSocket Servers
-----------------

A WebSocket server is similar to a client, but it uses a different
:class:`wsproto.ConnectionType` constant.

::

    from wsproto import ConnectionType, WSConnection
    from wsproto.events import Request
    ws = WSConnection(ConnectionType.SERVER)

A server also needs to explicitly send an :class:`AcceptConnection
<wsproto.events.AcceptConnection>` after it receives a
``Request`` event::

    for event in ws.events():
        if isinstance(event, Request):
            print('Accepting connection request')
            sock.send(ws.send(AcceptConnection()))
        elif...

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
``REMOTE_CLOSING`` **and requires a reply to be sent**. This reply
should be a ``CloseConnection`` event. To aid with this the
``CloseConnection`` class has a :meth:`response()
<wsproto.events.CloseConnection.response>` method to create the
appropriate reply. For example,

.. code-block:: python

    if isinstance(event, CloseConnection):
        sock.send(ws.send(event.response()))

When the reply has been received by the initiator, it will also yield
a ``CloseConnection`` event.

Regardless of which endpoint initiates the closing handshake, the server is
responsible for tearing down the underlying connection. When a
``CloseConnection`` event is generated, it should send pending any ``wsproto``
data and then tear down the underlying connection.

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
:meth:`response() <wsproto.events.Ping.response>` method to create the
appropriate reply. For example,

.. code-block:: python

    if isinstance(event, Ping):
        sock.send(ws.send(event.response()))

.. note::

    Both client and server connections must remember to reply to
    ``Ping`` events initiated by the remote party.
