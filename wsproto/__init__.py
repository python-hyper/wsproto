# -*- coding: utf-8 -*-
"""
wsproto
~~~~~~~

A WebSocket implementation.
"""
from typing import Generator, Optional

from .connection import Connection, ConnectionState, ConnectionType
from .events import Event
from .handshake import H11Handshake
from .typing import Headers

__version__ = "0.14.0+dev"


class WSConnection:
    def __init__(self, connection_type: ConnectionType) -> None:
        self.client = connection_type is ConnectionType.CLIENT
        self.handshake = H11Handshake(connection_type)
        self.connection: Optional[Connection] = None

    @property
    def state(self) -> ConnectionState:
        if self.connection is None:  # noqa
            return self.handshake.state
        else:
            return self.connection.state

    def initiate_upgrade_connection(self, headers: Headers, path: str) -> None:
        self.handshake.initiate_upgrade_connection(headers, path)

    def send(self, event: Event) -> bytes:
        data = b""
        if self.connection is None:
            data += self.handshake.send(event)
            self.connection = self.handshake.connection
        else:
            data += self.connection.send(event)
        return data

    def receive_data(self, data: bytes) -> None:
        if self.connection is None:
            self.handshake.receive_data(data)
            self.connection = self.handshake.connection
        else:
            self.connection.receive_data(data)

    def events(self) -> Generator[Event, None, None]:
        for event in self.handshake.events():
            yield event
        if self.connection is not None:
            for event in self.connection.events():
                yield event


__all__ = ("ConnectionType", "WSConnection")
