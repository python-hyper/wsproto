from __future__ import annotations

from typing import Union

from wsproto import extensions as wpext
from wsproto import frame_protocol as fp


class ConcreteExtension(wpext.Extension):
    def offer(self) -> Union[bool, str]:
        return "myext"


class TestExtension:
    def test_enabled(self) -> None:
        ext = ConcreteExtension()
        assert not ext.enabled()

    def test_offer(self) -> None:
        ext = ConcreteExtension()
        assert ext.offer() == "myext"

    def test_accept(self) -> None:
        ext = ConcreteExtension()
        offer = "myext"
        assert ext.accept(offer) is None

    def test_finalize(self) -> None:
        ext = ConcreteExtension()
        offer = "myext"
        ext.finalize(offer)

    def test_frame_inbound_header(self) -> None:
        ext = ConcreteExtension()
        result = ext.frame_inbound_header(None, None, None, None)  # type: ignore[arg-type]
        assert result == fp.RsvBits(False, False, False)

    def test_frame_inbound_payload_data(self) -> None:
        ext = ConcreteExtension()
        data = b""
        assert ext.frame_inbound_payload_data(None, data) == data  # type: ignore[arg-type]

    def test_frame_inbound_complete(self) -> None:
        ext = ConcreteExtension()
        assert ext.frame_inbound_complete(None, None) is None  # type: ignore[arg-type]

    def test_frame_outbound(self) -> None:
        ext = ConcreteExtension()
        rsv = fp.RsvBits(True, True, True)
        data = b""
        assert ext.frame_outbound(None, None, rsv, data, None) == (  # type: ignore[arg-type]
            rsv,
            data,
        )
