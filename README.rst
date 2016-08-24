Prototype sans-io WebSocket implementation
==========================================

.. image:: https://travis-ci.org/jeamland/wsproto.svg?branch=master
    :target: https://travis-ci.org/jeamland/wsproto

This needs a pile of cleaning up.

It passes the autobahn test suite completely and strictly in both client and
server modes and using permessage-deflate.

If you want to run the compliance tests, go into the compliance directory and
then to test client mode, in one shell run the Autobahn test server:

.. code-block:: console
    $ wstest -m fuzzingserver -s ws-fuzzingserver.json

And in another shell run the test client:

.. code-block:: console
    $ python test_client.py

And to test server mode, run the test server:

.. code-block:: console
    $ python test_server.py

And in another shell run the Autobahn test client:

.. code-block:: console
    $ wstest -m fuzzingclient -s ws-fuzzingclient.json

This was written using Python 3.5. Python 2.7 has not been well tested yet.
