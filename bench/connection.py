from __future__ import annotations

import random
import time
from typing import List

import wsproto

random_seed = 0
mu = 125 * 1024
sigma = 75 * 1024
iterations = 5000
per_message_deflate = False


rand = random.Random(random_seed)


client_extensions: List[wsproto.extensions.Extension] = []
if per_message_deflate:
    pmd = wsproto.extensions.PerMessageDeflate()
    offer = pmd.offer()
    assert isinstance(offer, str)
    pmd.finalize(offer)
    client_extensions.append(pmd)
client = wsproto.connection.Connection(
    wsproto.ConnectionType.CLIENT,
    extensions=client_extensions,
)


server_extensions: List[wsproto.extensions.Extension] = []
if per_message_deflate:
    pmd = wsproto.extensions.PerMessageDeflate()
    offer = pmd.offer()
    assert isinstance(offer, str)
    pmd.accept(offer)
server = wsproto.connection.Connection(
    wsproto.ConnectionType.SERVER,
    extensions=server_extensions,
)


start = time.perf_counter()
for i in range(iterations):
    client_msg = b"0" * max(0, round(rand.gauss(mu, sigma)))
    client_out = client.send(wsproto.events.BytesMessage(client_msg))
    server.receive_data(client_out)
    for event in server.events():
        pass

    server_msg = "0" * max(0, round(rand.gauss(mu, sigma)))
    server_out = server.send(wsproto.events.TextMessage(server_msg))
    client.receive_data(server_out)
    for event in client.events():
        pass
end = time.perf_counter()

print(f"{end - start:.4f}s")
