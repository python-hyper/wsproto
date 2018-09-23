0.13.0 Unreleased
-----------------

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
