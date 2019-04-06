# -*- coding: utf-8 -*-
"""
wsproto
~~~~~~~

A WebSocket implementation.
"""
from .connection import ConnectionType
from .handshake import H11Handshake

__version__ = "0.14.0"


class WSConnection(object):
    def __init__(self, connection_type):
        # type: (ConnectionType) -> None
        self.client = connection_type is ConnectionType.CLIENT
        self.handshake = H11Handshake(connection_type)
        self.connection = None

    @property
    def state(self):
        if self.connection is None:  # noqa
            return self.handshake.state
        else:
            return self.connection.state

    def initiate_upgrade_connection(self, headers, path):
        # type: (List[Tuple[bytes, bytes]], str) -> None
        self.handshake.initiate_upgrade_connection(headers, path)

    def send(self, event):
        data = b""
        if self.connection is None:
            data += self.handshake.send(event)
            self.connection = self.handshake.connection
        else:
            data += self.connection.send(event)
        return data

    def receive_data(self, data):
        if self.connection is None:
            self.handshake.receive_data(data)
            self.connection = self.handshake.connection
        else:
            self.connection.receive_data(data)

    def events(self):
        for event in self.handshake.events():
            yield event
        if self.connection is not None:
            for event in self.connection.events():
                yield event


__all__ = ("ConnectionType", "WSConnection")
