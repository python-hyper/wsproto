Advanced Usage
==============

This document explains some of the more advanced usage concepts with
`wsproto`. This is assume you are familiar with `wsproto` and I/O in
Python.

Back-pressure
-------------

Back-pressure is an important concept to understand when implementing a
client/server protocol. This section briefly explains the issue and then
explains how to handle back-pressure when using `wsproto`.

Imagine that you have a WebSocket server that reads messages from the
client, does some processing, and then sends a response. What happens
if the client sends messages faster than the server can process them?
If the incoming messages are buffered in memory, then the server will
slowly use more and more memory, until the OS eventually kills
it. This scenario is directly applicable to `wsproto`, because every
time you call ``receive_data(some_byte_string_of_data)``, it appends
that data to an internal buffer.

The slow endpoint needs a way to signal the fast endpoint to stop sending
messages until the slow endpoint can catch up. This signaling is called
"back-pressure". As a Sans-IO library, `wsproto` is not responsible for
network concerns like back-pressure, so that responsibility belongs to your
network glue code.

Fortunately, TCP has the ability to signal backpressure, and the
operating system will do that for you automatically—if you follow a
few rules! The OS buffers all incoming and outgoing network
data. Standard Python socket methods, such as ``send(...)`` and
``recv()``, copy data to and from those OS buffers. For example, if
the peer is sending data too quickly, then the OS receive buffer will
start to get full, and the OS will signal the peer to stop
transmitting.  When ``recv()`` is called, the OS will copy data from
its internal buffer into your process, free up space in its own
buffer, and then signal to the peer to start transmitting again.

Therefore, you need to follow these two rules to implement back-pressure over
TCP:

#. Do not receive from the socket faster than your code can process the
   messages. Your processing code may need to signal the receiving code when its
   ready to receive more data.
#. Do not store out-going messages in an unbounded collection. Ideally,
   out-going messages should be sent to the OS as soon as possible. If you need
   to buffer messages in memory, the buffer should be bounded so that it can not
   grow indefinitely.

Post handshake connection
-------------------------

A WebSocket connection starts with a handshake, which is an agreement
to use the WebSocket protocol, and on which sub-protocol and
extensions to use. It can be advantageous to perform this handshake
outside of `wsproto`, for example in a dual stack setup whereby the
HTTP handling is completed seperately. In this case the
:class:`Connection <wsproto.connection.Connection>` class can be used
directly.

.. code-block:: python

    connection = Connection(extensions)  # Agreed extensions
    sock.send(connection.send(Message(data=b"Hi")))

    connection.receive_data(sock.recv(4096))

    for event in connection.events():
        # As with WSConnection, only without any handshake events

HTTP/2
------

WebSockets over HTTP/2 have a distinct difference to HTTP/1 in that
only a single HTTP/2 stream is dedicated to the WebSocket rather than
the entire connection (as in HTTP/1). This requires the HTTP/2
connection to be managed before the WebSocket connection with
`Hyper-h2 <https://python-hyper.org/h2>`_ being recommended for
HTTP/2.

Although `wsproto` doesn't manage the HTTP/2 connection it can still
be used for the WebSocket stream. The HTTP/2 connection will need to
handshake the WebSocket stream, with the key being agreement on the
extensions used. Once the extensions have been agreed the
:class:`Connection <wsproto.connection.Connection>` class can be used
to manage the WebSocket connection, noting that data to be sent or
received will need to be parsed by the HTTP/2 connection first. In
practice for a server this looks like,

.. code-block:: python

     from wsproto.connection import Connection, ConnectionType
     from wsproto.extensions import PerMessageDeflate
     from wsproto.handshake import server_extensions_handshake

     # WebSocket request has been received
     request_extensions: List[str]
     supported_extensions = [PerMessageDeflate()]
     accepts = server_extensions_handshake(request_extensions, supported_extensions)
     if accepts:
         response_headers.append({"sec-websocket-extensions": accepts})
     # Send the response headers
     connection = Connection(ConnectionType.SERVER, supported_extensions)

and for a client

.. code-block:: python

    from wsproto.connection import Connection, ConnectionType
    from wsproto.extensions import PerMessageDeflate
    from wsproto.handshake import client_extensions_handshake

    # WebSocket response has been received
    accepted_extensions: List[str]
    proposed_extensions = [PerMessageDeflate()]
    extensions = client_extensions_handshake(accepted_extensions, proposed_extensions)
    connection = Connection(ConnectionType.CLIENT, supported_extensions)

any data received on the stream should be passed to the ``connection``
via the ``receive_bytes`` method and bytes returned from the
``connection.send`` method should be wrapped in a HTTP/2 data frame
and sent.
