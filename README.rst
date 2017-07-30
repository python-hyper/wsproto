Pure Python, pure state-machine WebSocket implementation
========================================================

.. image:: https://travis-ci.org/python-hyper/wsproto.svg?branch=master
    :target: https://travis-ci.org/python-hyper/wsproto
    :alt: Build status
.. image:: https://readthedocs.org/projects/wsproto/badge/?version=latest
    :target: http://wsproto.readthedocs.io/en/latest/?badge=latest
    :alt: Documentation Status
.. image:: https://codecov.io/gh/python-hyper/wsproto/branch/master/graph/badge.svg
    :target: https://codecov.io/gh/python-hyper/wsproto
    :alt: Code coverage

This repository contains a pure-Python implementation of a WebSocket protocol
stack. It's written from the ground up to be embeddable in whatever program you
choose to use, ensuring that you can communicate via WebSockets, as defined in
`RFC6455 <https://tools.ietf.org/html/rfc6455>`_, regardless of your programming
paradigm.

This repository does not provide a parsing layer, a network layer, or any rules
about concurrency. Instead, it's a purely in-memory solution, defined in terms
of data actions and WebSocket frames. RFC6455 and

Compression Extensions for WebSocket via
`RFC7692 <https://tools.ietf.org/html/rfc7692>`_ are fully supported.

wsproto supports Python 2.7, 3.5 or higher.

To install it, just run:

.. code-block:: console

    $ pip install wsproto


Usage
=====

It passes the autobahn test suite completely and strictly in both client and
server modes and using permessage-deflate.

If `wsaccel <https://pypi.python.org/pypi/wsaccel>`_ is installed
(optional), then it will be used to speed things up.

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


Documentation
=============

Documentation is available at https://wsproto.readthedocs.io/en/latest/.

Contributing
============

``wsproto`` welcomes contributions from anyone! Unlike many other projects we
are happy to accept cosmetic contributions and small contributions, in addition
to large feature requests and changes.

Before you contribute (either by opening an issue or filing a pull request),
please `read the contribution guidelines`_.

.. _read the contribution guidelines: http://python-hyper.org/en/latest/contributing.html

License
=======

``wsproto`` is made available under the MIT License. For more details, see the
``LICENSE`` file in the repository.

Authors
=======

``wsproto`` was created by @jeamland, and is maintained by the python-hyper
community.
