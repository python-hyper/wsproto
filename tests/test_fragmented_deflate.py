from __future__ import annotations

import zlib

import pytest

from wsproto.connection import CLIENT, SERVER, Connection
from wsproto.events import BytesMessage, Ping, Pong
from wsproto.extensions import PerMessageDeflate


def make_frame(payload: bytes, opcode: int, fin: bool, compressed: bool, masked: bool) -> bytes:
    # These fixtures use short frames and a fixed client masking key.
    assert len(payload) < 126
    header = bytes([
        (int(fin) << 7) | (int(compressed) << 6) | opcode,
        (int(masked) << 7) | len(payload),
    ])
    if not masked:
        return header + payload
    key = b"mask"
    return header + key + bytes(value ^ key[index % 4] for index, value in enumerate(payload))


@pytest.mark.parametrize("client", [False, True])
@pytest.mark.parametrize("control", [None, 9, 10])
@pytest.mark.parametrize("chunk_size", [1, 7, 65536])
@pytest.mark.parametrize("no_context_takeover", [False, True])
@pytest.mark.parametrize("compressed", [False, True])
def test_fragmented_message_with_control_frames(
    client: bool,
    control: int | None,
    chunk_size: int,
    no_context_takeover: bool,
    compressed: bool,
) -> None:
    extension = PerMessageDeflate(
        client_no_context_takeover=no_context_takeover,
        server_no_context_takeover=no_context_takeover,
    )
    extension.finalize("permessage-deflate")
    connection = Connection(CLIENT if client else SERVER, extensions=[extension])
    compressor = zlib.compressobj(wbits=-15)
    payload = b"fragmented binary message " * 3
    wire = bytearray()
    expected_controls = []

    for _ in range(2):
        if no_context_takeover:
            compressor = zlib.compressobj(wbits=-15)
        encoded = payload
        if compressed:
            encoded = compressor.compress(payload) + compressor.flush(zlib.Z_SYNC_FLUSH)
            assert encoded.endswith(b"\x00\x00\xff\xff")
            encoded = encoded[:-4]
        split = len(encoded) // 2
        if control is not None:
            wire += make_frame(b"before", control, True, False, not client)
            expected_controls.append(b"before")
        wire += make_frame(encoded[:split], 2, False, compressed, not client)
        if control is not None:
            wire += make_frame(b"between", control, True, False, not client)
            expected_controls.append(b"between")
        wire += make_frame(encoded[split:], 0, True, False, not client)
        if control is not None:
            wire += make_frame(b"after", control, True, False, not client)
            expected_controls.append(b"after")

    messages = []
    controls = []
    current = b""
    for offset in range(0, len(wire), chunk_size):
        connection.receive_data(wire[offset : offset + chunk_size])
        for event in connection.events():
            if isinstance(event, (Ping, Pong)):
                controls.append(event.payload)
            else:
                assert isinstance(event, BytesMessage)
                current += event.data
                if event.message_finished:
                    messages.append(current)
                    current = b""
    assert messages == [payload, payload]
    assert controls == expected_controls
