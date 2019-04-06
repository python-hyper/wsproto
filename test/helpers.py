from typing import Optional, Union

from wsproto.extensions import Extension


class FakeExtension(Extension):
    name = "fake"

    def __init__(
        self,
        offer_response: Optional[Union[bool, str]] = None,
        accept_response: Optional[Union[bool, str]] = None,
    ) -> None:
        self.offer_response = offer_response
        self.accepted_offer: Optional[str] = None
        self.offered: Optional[str] = None
        self.accept_response = accept_response

    def offer(self) -> Union[bool, str]:
        return self.offer_response

    def finalize(self, offer: str) -> None:
        self.accepted_offer = offer

    def accept(self, offer: str) -> Union[bool, str]:
        self.offered = offer
        return self.accept_response
