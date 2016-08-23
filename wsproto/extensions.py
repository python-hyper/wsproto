# -*- coding: utf-8 -*-
"""
wsproto/extensions
~~~~~~~~~~~~~~

WebSocket extensions.
"""

import zlib

from .frame_protocol import CloseReason, Opcode


class Extension(object):
    name = None

    def enabled(self):
        return False

    def offer(self, connection):
        return None

    def accept(self, connection, offer):
        return None

    def frame_inbound_header(self, proto, opcode, rsv, payload_length):
        pass

    def frame_inbound_payload_data(self, proto, data):
        return data

    def frame_inbound_complete(self, proto, fin):
        pass

    def frame_outbound(self, proto, opcode, rsv, data):
        return (rsv, data)


class PerMessageDeflate(Extension):
    name = 'permessage-deflate'

    def __init__(self, client_no_context_takeover=False,
                 client_max_window_bits=15, server_no_context_takeover=False,
                 server_max_window_bits=15):
        self.client_no_context_takeover = client_no_context_takeover
        self.client_max_window_bits = client_max_window_bits
        self.server_no_context_takeover = server_no_context_takeover
        self.server_max_window_bits = server_max_window_bits

        self._compressor = None
        self._decompressor = None
        self._inbound_compressed = None

        self._enabled = False

    def enabled(self):
        return self._enabled

    def offer(self, connection):
        parameters = [
            'client_max_window_bits=%d' % self.client_max_window_bits,
            'server_max_window_bits=%d' % self.server_max_window_bits,
            ]

        if self.client_no_context_takeover:
            parameters.append('client_no_context_takeover')
        if self.server_no_context_takeover:
            parameters.append('server_no_context_takeover')

        return '; '.join(parameters)

    def finalize(self, connection, offer):
        bits = [b.strip() for b in offer.split(';')]
        for bit in bits[1:]:
            if bit.startswith('client_no_context_takeover'):
                self.client_no_context_takeover = True
            elif bit.startswith('server_no_context_takeover'):
                self.server_no_context_takeover = True
            elif bit.startswith('client_max_window_bits'):
                self.client_max_window_bits = int(bit.split('=', 1)[1].strip())
            elif bit.startswith('server_max_window_bits'):
                self.server_max_window_bits = int(bit.split('=', 1)[1].strip())

        self._enabled = True

    def _parse_params(self, params):
        client_max_window_bits = None
        server_max_window_bits = None

        bits = [b.strip() for b in params.split(';')]
        for bit in bits[1:]:
            if bit.startswith('client_no_context_takeover'):
                self.client_no_context_takeover = True
            elif bit.startswith('server_no_context_takeover'):
                self.server_no_context_takeover = True
            elif bit.startswith('client_max_window_bits'):
                if '=' in bit:
                    client_max_window_bits = int(bit.split('=', 1)[1].strip())
                else:
                    client_max_window_bits = self.client_max_window_bits
            elif bit.startswith('server_max_window_bits'):
                if '=' in bit:
                    server_max_window_bits = int(bit.split('=', 1)[1].strip())
                else:
                    server_max_window_bits = self.server_max_window_bits

        return client_max_window_bits, server_max_window_bits

    def accept(self, connection, offer):
        client_max_window_bits, server_max_window_bits = \
            self._parse_params(offer)

        self._enabled = True

        parameters = []

        if self.client_no_context_takeover:
            parameters.append('client_no_context_takeover')
        if client_max_window_bits is not None:
            parameters.append('client_max_window_bits=%d' %
                              client_max_window_bits)
            self.client_max_window_bits = client_max_window_bits
        if self.server_no_context_takeover:
            parameters.append('server_no_context_takeover')
        if server_max_window_bits is not None:
            parameters.append('server_max_window_bits=%d' %
                              server_max_window_bits)
            self.server_max_window_bits = server_max_window_bits

        return '; '.join(parameters)

    def frame_inbound_header(self, proto, opcode, rsv, payload_length):
        if True in rsv[1:]:
            return CloseReason.PROTOCOL_ERROR
        elif rsv[0] and opcode.iscontrol():
            return CloseReason.PROTOCOL_ERROR
        elif rsv[0] and opcode is Opcode.CONTINUATION:
            return CloseReason.PROTOCOL_ERROR

        if self._inbound_compressed is None:
            self._inbound_compressed = rsv[0]
            if self._inbound_compressed:
                if proto.client:
                    bits = self.server_max_window_bits
                else:
                    bits = self.client_max_window_bits
                if self._decompressor is None:
                    self._decompressor = zlib.decompressobj(-bits)

    def frame_inbound_payload_data(self, proto, data):
        if not self._inbound_compressed:
            return data

        try:
            return self._decompressor.decompress(data)
        except zlib.error:
            return CloseReason.INVALID_FRAME_PAYLOAD_DATA

    def frame_inbound_complete(self, proto, fin):
        if not fin or not self._inbound_compressed:
            return

        try:
            data = self._decompressor.decompress(b'\x00\x00\xff\xff')
            data += self._decompressor.flush()
        except zlib.error:
            return CloseReason.INVALID_FRAME_PAYLOAD_DATA

        if fin:
            if proto.client:
                no_context_takeover = self.server_no_context_takeover
            else:
                no_context_takeover = self.client_no_context_takeover

            if no_context_takeover:
                self._decompressor = None

            self._inbound_compressed = None

        return data

    def frame_outbound(self, proto, opcode, rsv, data):
        if opcode not in (Opcode.TEXT, Opcode.BINARY):
            return (rsv, data)

        if self._compressor is None:
            if proto.client:
                bits = self.client_max_window_bits
            else:
                bits = self.server_max_window_bits
            self._compressor = zlib.compressobj(wbits=-bits)

        data = self._compressor.compress(data)
        data += self._compressor.flush(zlib.Z_SYNC_FLUSH)
        data = data[:-4]

        rsv = list(rsv)
        rsv[0] = True

        if proto.client:
            no_context_takeover = self.client_no_context_takeover
        else:
            no_context_takeover = self.server_no_context_takeover

        if no_context_takeover:
            self._compressor = None

        return (rsv, data)

    def __repr__(self):
        descr = ['client_max_window_bits=%d' % self.client_max_window_bits]
        if self.client_no_context_takeover:
            descr.append('client_no_context_takeover')
        descr.append('server_max_window_bits=%d' % self.server_max_window_bits)
        if self.server_no_context_takeover:
            descr.append('server_no_context_takeover')

        descr = '; '.join(descr)

        return '<%s %s>' % (self.__class__.__name__, descr)
