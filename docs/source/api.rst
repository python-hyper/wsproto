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

.. autoclass:: wsproto.events.Request
   :members:

.. autoclass:: wsproto.events.AcceptConnection
   :members:

.. autoclass:: wsproto.events.CloseConnection
   :members:

.. autoclass:: wsproto.events.Fail
   :members:

.. autoclass:: wsproto.events.Data
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
