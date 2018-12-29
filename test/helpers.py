from wsproto.extensions import Extension


class FakeExtension(Extension):
    name = "fake"

    def __init__(self, offer_response=None, accept_response=None):
        self.offer_response = offer_response
        self.accepted_offer = None
        self.offered = None
        self.accept_response = accept_response

    def offer(self, proto):
        return self.offer_response

    def finalize(self, proto, offer):
        self.accepted_offer = offer

    def accept(self, proto, offer):
        self.offered = offer
        return self.accept_response
