import pytest
from binascii import unhexlify
import wsproto.frame_protocol as fp

def test_close_with_long_reason():
    # Long close reasons get silently truncated
    proto = fp.FrameProtocol(client=False, extensions=[])
    data = proto.close(code=fp.CloseReason.NORMAL_CLOSURE,
                       reason="x" * 200)
    assert data == unhexlify("887d03e8") + b"x" * 123

    # While preserving valid utf-8
    proto = fp.FrameProtocol(client=False, extensions=[])
    # pound sign is 2 bytes in utf-8, so naive truncation to 123 bytes will
    # cut it in half. Instead we truncate to 122 bytes.
    data = proto.close(code=fp.CloseReason.NORMAL_CLOSURE,
                       reason="£" * 100)
    assert data == unhexlify("887c03e8") + "£".encode("utf-8") * 61
