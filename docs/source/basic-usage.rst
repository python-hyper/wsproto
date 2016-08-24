Getting Started
===============

This document explains how to get started using wsproto to connect to
WebSocket servers as well as how to write your own.

We assume some level of familiarity with writing Python and networking code. If
you're not familiar with these we highly recommend you read up on these first.

Connections
-----------

The main class you'll be working with is the
:class:`WSConnection <wsproto.connection.WSConnection>` object. This object
represents a connection to a WebSocket client or server and contains all the
state needed to communicate with the entity at the other end. Whether you're
connecting to a server or receiving a connection from a client this is the
object you'll use.

The interface to this object is pretty simple. There are some parameters you
may need to provide at initialisation time and these may vary based on whether
you're acting as a client or a server. Once created you feed data from the
network into the connection using the
:meth:`receive_bytes <wsproto.connection.WSConnection.receive_bytes>` method
and retrieve data to be sent to the network using the
:meth:`bytes_to_send <wsproto.connection.WSConnection.bytes_to_send>` method.
On the other end, protocol events that you can react to arrive via the
:meth:`events <wsproto.connection.WSConnection.events>` generator method and
you can send messages back to the other end using the
:meth:`send_data <wsproto.connection.WSConnection.send_data>` method.

Connecting to a WebSocket server
--------------------------------

Some guff about writing clients

WebSocket Servers
-----------------

Some guff about writing servers.
