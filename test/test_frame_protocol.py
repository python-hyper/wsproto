import pytest
from binascii import unhexlify
import struct
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


def test_payload_length_decode():
    # "the minimal number of bytes MUST be used to encode the length, for
    # example, the length of a 124-byte-long string can't be encoded as the
    # sequence 126, 0, 124" -- RFC 6455

    def make_header(encoding_bytes, payload_len):
        if encoding_bytes == 1:
            assert payload_len <= 125
            return unhexlify("81") + bytes([payload_len])
        elif encoding_bytes == 2:
            assert payload_len < 2**16
            return unhexlify("81" "7e") + struct.pack("!H", payload_len)
        elif encoding_bytes == 8:
            return unhexlify("81" "7f") + struct.pack("!Q", payload_len)
        else:
            assert False

    def make_and_parse(encoding_bytes, payload_len):
        proto = fp.FrameProtocol(client=True, extensions=[])
        proto.receive_bytes(make_header(encoding_bytes, payload_len))
        list(proto.received_frames())

    # Valid lengths for 1 byte
    for payload_len in [0, 1, 2, 123, 124, 125]:
        make_and_parse(1, payload_len)
        for encoding_bytes in [2, 8]:
            with pytest.raises(fp.ParseFailed) as excinfo:
                make_and_parse(encoding_bytes, payload_len)
            assert "used {} bytes".format(encoding_bytes) in str(excinfo.value)

    # Valid lengths for 2 bytes
    for payload_len in [126, 127, 1000, 2**16 - 1]:
        make_and_parse(2, payload_len)
        with pytest.raises(fp.ParseFailed) as excinfo:
            make_and_parse(8, payload_len)
        assert "used 8 bytes" in str(excinfo.value)

    # Valid lengths for 8 bytes
    for payload_len in [2**16, 2**16 + 1, 2**32, 2**63 - 1]:
        make_and_parse(8, payload_len)

    # Invalid lengths for 8 bytes
    for payload_len in [2**63, 2**63 + 1]:
        with pytest.raises(fp.ParseFailed) as excinfo:
            make_and_parse(8, payload_len)
        assert "non-zero MSB" in str(excinfo.value)
