Prototype sans-io WebSocket implementation
==========================================

This needs a pile of cleaning up.

It passes the autobahn test suite except for the permessage-deflate extension
testing which is currently unimplemented.

To test, in one shell run the Autobahn test server:

    > wstest -m fuzzingserver --debug -s ws-fuzzingserver.json

And in another shell run the test client:

    > python test_client.py

This is all currently Python 3 only.
