import wsproto.extensions as wpext
import wsproto.frame_protocol as fp


class TestExtension:
    def test_enabled(self) -> None:
        ext = wpext.Extension()
        assert not ext.enabled()

    def test_offer(self) -> None:
        ext = wpext.Extension()
        assert ext.offer() is None

    def test_accept(self) -> None:
        ext = wpext.Extension()
        offer = "myext"
        assert ext.accept(offer) is None

    def test_finalize(self) -> None:
        ext = wpext.Extension()
        offer = "myext"
        ext.finalize(offer)

    def test_frame_inbound_header(self) -> None:
        ext = wpext.Extension()
        result = ext.frame_inbound_header(None, None, None, None)  # type: ignore
        assert result == fp.RsvBits(False, False, False)

    def test_frame_inbound_payload_data(self) -> None:
        ext = wpext.Extension()
        data = b""
        assert ext.frame_inbound_payload_data(None, data) == data  # type: ignore

    def test_frame_inbound_complete(self) -> None:
        ext = wpext.Extension()
        assert ext.frame_inbound_complete(None, None) is None  # type: ignore

    def test_frame_outbound(self) -> None:
        ext = wpext.Extension()
        rsv = fp.RsvBits(True, True, True)
        data = b""
        assert ext.frame_outbound(None, None, rsv, data, None) == (  # type: ignore
            rsv,
            data,
        )
