Prototype sans-io WebSocket implementation
==========================================

[![Build Status](https://travis-ci.org/jeamland/wsproto.svg?branch=master)](https://travis-ci.org/jeamland/wsproto)

This needs a pile of cleaning up.

It passes the autobahn test suite completely and strictly in both client and
server modes and using permessage-deflate.

To test client mode, in one shell run the Autobahn test server:

    > wstest -m fuzzingserver -s ws-fuzzingserver.json

And in another shell run the test client:

    > python test_client.py

And to test server mode, run the test server:

    > python test_server.py

And in another shell run the Autobahn test client:

    > wstest -m fuzzingclient -s ws-fuzzingclient.json

This is all currently Python 3 only.
