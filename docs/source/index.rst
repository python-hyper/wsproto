.. wsproto documentation master file, created by
   sphinx-quickstart on Wed Aug 24 10:37:29 2016.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

wsproto: A pure Python WebSocket protocol stack
===============================================

wsproto is a WebSocket protocol stack written to be as flexible as possible. To
that end it is written in pure Python and performs no I/O of its own. Instead
it relies on the user to provide a bridge between it and whichever I/O mechanism
is in use, allowing it to be used in single-threaded, multi-threaded or
event-driven code.

The goal for wsproto is 100% compliance with `RFC 6455`_. Additionally a
mechanism is provided to add extensions allowing the implementation of extra
functionally such as per-message compression as specified in `RFC 7692`_.

For usage examples, see :doc:`basic-usage` or see the examples provided.

Contents:

.. toctree::
   :maxdepth: 2

   installation
   basic-usage
   advanced-usage
   api

.. _RFC 6455: https://tools.ietf.org/html/rfc6455
.. _RFC 7692: https://tools.ietf.org/html/rfc7692
