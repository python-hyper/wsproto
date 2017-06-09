import wsproto.extensions as wpext
import wsproto.frame_protocol as fp


class TestExtension(object):
    def test_enabled(self):
        ext = wpext.Extension()
        assert not ext.enabled()

    def test_offer(self):
        ext = wpext.Extension()
        assert ext.offer(None) is None

    def test_accept(self):
        ext = wpext.Extension()
        assert ext.accept(None, None) is None

    def test_finalize(self):
        ext = wpext.Extension()
        assert ext.finalize(None, None) is None

    def test_frame_inbound_header(self):
        ext = wpext.Extension()
        result = ext.frame_inbound_header(None, None, None, None)
        assert result == fp.RsvBits(False, False, False)

    def test_frame_inbound_payload_data(self):
        ext = wpext.Extension()
        data = object()
        assert ext.frame_inbound_payload_data(None, data) == data

    def test_frame_inbound_complete(self):
        ext = wpext.Extension()
        assert ext.frame_inbound_complete(None, None) is None

    def test_frame_outbound(self):
        ext = wpext.Extension()
        rsv = fp.RsvBits(True, True, True)
        data = object()
        assert ext.frame_outbound(None, None, rsv, data, None) == (rsv, data)
