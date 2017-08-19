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

.. autoclass:: wsproto.connection.WSConnection
   :members:

Events
------

.. autoclass:: wsproto.events.Event
   :members:

.. autoclass:: wsproto.events.ConnectionRequested
   :members:

.. autoclass:: wsproto.events.ConnectionEstablished
   :members:

.. autoclass:: wsproto.events.ConnectionClosed
   :members:

.. autoclass:: wsproto.events.ConnectionFailed
   :members:

.. autoclass:: wsproto.events.DataReceived
   :members:

.. autoclass:: wsproto.events.TextReceived
   :members:

.. autoclass:: wsproto.events.BytesReceived
   :members:

.. autoclass:: wsproto.events.PingReceived
   :members:

.. autoclass:: wsproto.events.PongReceived
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
