# -*- coding: utf-8 -*-
"""
wsproto/extensions
~~~~~~~~~~~~~~~~~~

WebSocket extensions.
"""

import zlib
from typing import Optional, Tuple, Union

from .frame_protocol import CloseReason, FrameDecoder, FrameProtocol, Opcode, RsvBits


class Extension:
    name: Optional[str] = None

    def enabled(self) -> bool:
        return False

    def offer(self) -> Union[bool, str]:
        pass

    def accept(self, offer: str) -> Union[bool, str]:
        pass

    def finalize(self, offer: str) -> None:
        pass

    def frame_inbound_header(
        self,
        proto: Union[FrameDecoder, FrameProtocol],
        opcode: Opcode,
        rsv: RsvBits,
        payload_length: int,
    ) -> Union[CloseReason, RsvBits]:
        return RsvBits(False, False, False)

    def frame_inbound_payload_data(
        self, proto: Union[FrameDecoder, FrameProtocol], data: bytes
    ) -> Union[bytes, CloseReason]:
        return data

    def frame_inbound_complete(
        self, proto: Union[FrameDecoder, FrameProtocol], fin: bool
    ) -> Union[bytes, CloseReason, None]:
        pass

    def frame_outbound(
        self,
        proto: Union[FrameDecoder, FrameProtocol],
        opcode: Opcode,
        rsv: RsvBits,
        data: bytes,
        fin: bool,
    ) -> Tuple[RsvBits, bytes]:
        return (rsv, data)


class PerMessageDeflate(Extension):
    name = "permessage-deflate"

    DEFAULT_CLIENT_MAX_WINDOW_BITS = 15
    DEFAULT_SERVER_MAX_WINDOW_BITS = 15

    def __init__(
        self,
        client_no_context_takeover: bool = False,
        client_max_window_bits: Optional[int] = None,
        server_no_context_takeover: bool = False,
        server_max_window_bits: Optional[int] = None,
    ) -> None:
        self.client_no_context_takeover = client_no_context_takeover
        if client_max_window_bits is None:
            client_max_window_bits = self.DEFAULT_CLIENT_MAX_WINDOW_BITS
        self.client_max_window_bits = client_max_window_bits
        self.server_no_context_takeover = server_no_context_takeover
        if server_max_window_bits is None:
            server_max_window_bits = self.DEFAULT_SERVER_MAX_WINDOW_BITS
        self.server_max_window_bits = server_max_window_bits

        self._compressor: Optional[zlib._Compress] = None  # noqa
        self._decompressor: Optional[zlib._Decompress] = None  # noqa
        # This refers to the current frame
        self._inbound_is_compressible: Optional[bool] = None
        # This refers to the ongoing message (which might span multiple
        # frames). Only the first frame in a fragmented message is flagged for
        # compression, so this carries that bit forward.
        self._inbound_compressed: Optional[bool] = None

        self._enabled = False

    def _compressible_opcode(self, opcode: Opcode) -> bool:
        return opcode in (Opcode.TEXT, Opcode.BINARY, Opcode.CONTINUATION)

    def enabled(self) -> bool:
        return self._enabled

    def offer(self) -> Union[bool, str]:
        parameters = [
            "client_max_window_bits=%d" % self.client_max_window_bits,
            "server_max_window_bits=%d" % self.server_max_window_bits,
        ]

        if self.client_no_context_takeover:
            parameters.append("client_no_context_takeover")
        if self.server_no_context_takeover:
            parameters.append("server_no_context_takeover")

        return "; ".join(parameters)

    def finalize(self, offer: str) -> None:
        bits = [b.strip() for b in offer.split(";")]
        for bit in bits[1:]:
            if bit.startswith("client_no_context_takeover"):
                self.client_no_context_takeover = True
            elif bit.startswith("server_no_context_takeover"):
                self.server_no_context_takeover = True
            elif bit.startswith("client_max_window_bits"):
                self.client_max_window_bits = int(bit.split("=", 1)[1].strip())
            elif bit.startswith("server_max_window_bits"):
                self.server_max_window_bits = int(bit.split("=", 1)[1].strip())

        self._enabled = True

    def _parse_params(self, params: str) -> Tuple[int, int]:
        client_max_window_bits = None
        server_max_window_bits = None

        bits = [b.strip() for b in params.split(";")]
        for bit in bits[1:]:
            if bit.startswith("client_no_context_takeover"):
                self.client_no_context_takeover = True
            elif bit.startswith("server_no_context_takeover"):
                self.server_no_context_takeover = True
            elif bit.startswith("client_max_window_bits"):
                if "=" in bit:
                    client_max_window_bits = int(bit.split("=", 1)[1].strip())
                else:
                    client_max_window_bits = self.client_max_window_bits
            elif bit.startswith("server_max_window_bits"):
                if "=" in bit:
                    server_max_window_bits = int(bit.split("=", 1)[1].strip())
                else:
                    server_max_window_bits = self.server_max_window_bits

        return client_max_window_bits, server_max_window_bits

    def accept(self, offer: str) -> Union[bool, str]:
        client_max_window_bits, server_max_window_bits = self._parse_params(offer)

        self._enabled = True

        parameters = []

        if self.client_no_context_takeover:
            parameters.append("client_no_context_takeover")
        if client_max_window_bits is not None:
            parameters.append("client_max_window_bits=%d" % client_max_window_bits)
            self.client_max_window_bits = client_max_window_bits
        if self.server_no_context_takeover:
            parameters.append("server_no_context_takeover")
        if server_max_window_bits is not None:
            parameters.append("server_max_window_bits=%d" % server_max_window_bits)
            self.server_max_window_bits = server_max_window_bits

        return "; ".join(parameters)

    def frame_inbound_header(
        self,
        proto: Union[FrameDecoder, FrameProtocol],
        opcode: Opcode,
        rsv: RsvBits,
        payload_length: int,
    ) -> Union[CloseReason, RsvBits]:
        if rsv.rsv1 and opcode.iscontrol():
            return CloseReason.PROTOCOL_ERROR
        if rsv.rsv1 and opcode is Opcode.CONTINUATION:
            return CloseReason.PROTOCOL_ERROR

        self._inbound_is_compressible = self._compressible_opcode(opcode)

        if self._inbound_compressed is None:
            self._inbound_compressed = rsv.rsv1
            if self._inbound_compressed:
                assert self._inbound_is_compressible
                if proto.client:
                    bits = self.server_max_window_bits
                else:
                    bits = self.client_max_window_bits
                if self._decompressor is None:
                    self._decompressor = zlib.decompressobj(-int(bits))

        return RsvBits(True, False, False)

    def frame_inbound_payload_data(
        self, proto: Union[FrameDecoder, FrameProtocol], data: bytes
    ) -> Union[bytes, CloseReason]:
        if not self._inbound_compressed or not self._inbound_is_compressible:
            return data

        try:
            return self._decompressor.decompress(bytes(data))
        except zlib.error:
            return CloseReason.INVALID_FRAME_PAYLOAD_DATA

    def frame_inbound_complete(
        self, proto: Union[FrameDecoder, FrameProtocol], fin: bool
    ) -> Union[bytes, CloseReason, None]:
        if not fin:
            return None
        if not self._inbound_is_compressible:
            self._inbound_compressed = None
            return None
        if not self._inbound_compressed:
            self._inbound_compressed = None
            return None

        try:
            data = self._decompressor.decompress(b"\x00\x00\xff\xff")
            data += self._decompressor.flush()
        except zlib.error:
            return CloseReason.INVALID_FRAME_PAYLOAD_DATA

        if proto.client:
            no_context_takeover = self.server_no_context_takeover
        else:
            no_context_takeover = self.client_no_context_takeover

        if no_context_takeover:
            self._decompressor = None

        self._inbound_compressed = None

        return data

    def frame_outbound(
        self,
        proto: Union[FrameDecoder, FrameProtocol],
        opcode: Opcode,
        rsv: RsvBits,
        data: bytes,
        fin: bool,
    ) -> Tuple[RsvBits, bytes]:
        if not self._compressible_opcode(opcode):
            return (rsv, data)

        if opcode is not Opcode.CONTINUATION:
            rsv = RsvBits(True, *rsv[1:])

        if self._compressor is None:
            assert opcode is not Opcode.CONTINUATION
            if proto.client:
                bits = self.client_max_window_bits
            else:
                bits = self.server_max_window_bits
            self._compressor = zlib.compressobj(
                zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -int(bits)
            )

        data = self._compressor.compress(bytes(data))

        if fin:
            data += self._compressor.flush(zlib.Z_SYNC_FLUSH)
            data = data[:-4]

            if proto.client:
                no_context_takeover = self.client_no_context_takeover
            else:
                no_context_takeover = self.server_no_context_takeover

            if no_context_takeover:
                self._compressor = None

        return (rsv, data)

    def __repr__(self) -> str:
        descr = ["client_max_window_bits=%d" % self.client_max_window_bits]
        if self.client_no_context_takeover:
            descr.append("client_no_context_takeover")
        descr.append("server_max_window_bits=%d" % self.server_max_window_bits)
        if self.server_no_context_takeover:
            descr.append("server_no_context_takeover")

        return "<%s %s>" % (self.__class__.__name__, "; ".join(descr))


#: SUPPORTED_EXTENSIONS maps all supported extension names to their class.
#: This can be used to iterate all supported extensions of wsproto, instantiate
#: new extensions based on their name, or check if a given extension is
#: supported or not.
SUPPORTED_EXTENSIONS = {PerMessageDeflate.name: PerMessageDeflate}
