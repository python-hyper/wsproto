wsproto API
============

This document details the API of wsproto.

Semantic Versioning
-------------------

wsproto follows semantic versioning for its public API. Please note that the
guarantees of semantic versioning apply only to the API that is *documented
here*. Simply because a method or data field is not prefaced by an underscore
does not make it part of wsproto's public API. Anything not documented here is
subject to change at any time.

Connection
----------

.. autoclass:: wsproto.WSConnection
   :special-members: __init__
   :members:

.. autoclass:: wsproto.ConnectionType
   :members:

.. autoclass:: wsproto.connection.ConnectionState
   :members:

Handshake
---------

.. autoclass:: wsproto.handshake.H11Handshake
   :members:

.. autofunction:: wsproto.handshake.client_extensions_handshake

.. autofunction:: wsproto.handshake.server_extensions_handshake

Events
------

Event constructors accept any field as a keyword argument. Some fields are
required, while others have default values.

.. autoclass:: wsproto.events.Event
   :members:

.. autoclass:: wsproto.events.Request
   :members:

.. autoclass:: wsproto.events.AcceptConnection
   :members:

.. autoclass:: wsproto.events.RejectConnection
   :members:

.. autoclass:: wsproto.events.RejectData
   :members:

.. autoclass:: wsproto.events.CloseConnection
   :members:

.. autoclass:: wsproto.events.Message
   :members:

.. autoclass:: wsproto.events.TextMessage
   :members:

.. autoclass:: wsproto.events.BytesMessage
   :members:

.. autoclass:: wsproto.events.Ping
   :members:

.. autoclass:: wsproto.events.Pong
   :members:

Frame Protocol
--------------

.. autoclass:: wsproto.frame_protocol.Opcode
   :members:

.. autoclass:: wsproto.frame_protocol.CloseReason
   :members:

Extensions
----------

.. autoclass:: wsproto.extensions.Extension
   :members:

.. autodata:: wsproto.extensions.SUPPORTED_EXTENSIONS

Exceptions
----------

.. autoclass:: wsproto.utilities.LocalProtocolError
   :members:

.. autoclass:: wsproto.utilities.RemoteProtocolError
   :members:
