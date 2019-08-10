0.15.0 2019-08-10
-----------------

*This contains all the Bugfixes in the 0.14 branch.*

* Drop support for Python 2. Please pin to ~= 0.14.0 if you support
  Python 2.
* Drop support for Python 3.5, meaning the minimum supported version
  is Python 3.6.1.
* Switch events to be dataclass based, otherwise the API is
  consistent.
* Add type hints throughout and support PEP 561 via a py.typed
  file. This should allow projects that use wsproto to type check their
  usage of wsproto.
* Bugfix prevent the test folder being installed as a package called
  test.
* Explicitly require Host header in handshake.
* Drop wsaccel support and utilise the aiohttp/@willmcgugan masking
  method. wsaccel is unmaintained and this new maksing method is
  almost as quick.

0.14.1 2019-05-30
-----------------

* Loosen the h11 requirement to >= 0.8.1 as wsproto is compatible with
  0.9 onwards.
* Stop installing a "test" package on installation.

0.14.0 2019-04-06
-----------------

* Bugfix clarify subprotocol type as str not bytes.
* Support HTTP/2 WebSockets. This requires a HTTP/2 parser (not
  included), with hyper-h2 recommended. It renames
  ``handshake_extensions`` and hence is a breaking change.
* Bugfix badly formatted type hints.
* Bugfix minor issues identified by type checking.

0.13.0 2019-01-24
-----------------

* Introduce a send method on the connection which accepts the new
  events. This requires the following usage changes, ::

    connection.accept(subprotocol=subprotocol) -> connection.send(AcceptConnection(subprotocol=subprotocol))
    connection.send_data(data) -> connection.send(Message(payload=payload))
    connection.close(code) -> connection.send(CloseConnection(code=code))
    connection.ping() -> connection.send(Ping())
    connection.pong() -> connection.send(Pong())

* The Event structure is altered to allow for events to be sent and
  received, this requires the following name changes in existing code, ::

    ConnectionRequested -> Request
    ConnectionEstablished -> AcceptConnection
    ConnectionClosed -> CloseConnection
    DataReceived -> Message
    TextReceived -> TextMessage
    BytesReceived -> BytesMessage
    PingReceived -> Ping
    PongReceived -> Pong

* Introduce RejectConnection and RejectData events to be used by a
  server connection to reject rather than accept a connection or by a
  client connection to emit the rejection response. The RejectData
  event represents the rejection response body, if present.
* Add an extra_headers field to the AcceptConnection event in order to
  customise the acceptance response in server mode or to emit this
  information in client mode.
* Switch from Fail events being returned to RemoteProtocolError`s being
  raised.
* Switch from ValueError`s to LocalProtocolError`s being raised when
  an action is taken that is incompatible with the connection state or
  websocket standard.
* Enforce version checking in SERVER mode, only 13 is supported.
* Add an event_hint to RemoteProtocolErrors to hint at how to respond
  to issues.
* Switch from a ``bytes_to_send`` method to the ``send`` method
  returning the bytes to send directly. Responses to Ping and Close
  messages must now be sent (via ``send``), with the ``Ping`` and
  ``CloseConnection`` events gaining a ``response`` method. This
  allows ::

    if isinstance(event, Ping):
        bytes_to_send = connection.send(event.response())
* Separate the handshake from the active connection handling. This
  allows the handshake and connection to be seperately used. By
  default though WSConnection does both.
* ``receive_bytes`` is renamed to ``receive_data`` and
  ``WSConnection`` should be imported from ``wsproto`` rather than
  ``wsproto.connection``.

0.12.0 2018-09-23
-----------------

* Support h11 ~0.8.1.
* Support Python 3.7.
* Make the close-handshake more explicit, by sending a close frame on
  reciept of a close frame.
* Bugfix fix deflate after a non-compressable message.
* Bugfix connection header acceptance, by accepting Connection header
  values that are comma separated lists.

0.11.0 2017-12-31
-----------------

* Separate extension handling into its own method.
* Add events for PING and PONG frames.
* Stop supporting Python 3.4.
* Large increase in tests and test coverage.
* Bugfix extension accept for empty strings.
* Bugfix raise if default arguments are invalid.

0.10.0 2017-05-03
-----------------

0.9.1 2016-10-27
----------------

(Unreleased on PyPI)

0.9.0 2016-08-24
----------------

(First release on PyPI)
