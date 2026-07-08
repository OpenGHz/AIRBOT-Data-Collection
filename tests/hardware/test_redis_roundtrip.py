"""Redis pub/sub round-trip smoke test.

``@hardware`` + ``@redis`` means the conftest probe auto-skips this when no Redis
is reachable (``localhost:6379``, overridable via ``AIRDC_REDIS_HOST`` /
``AIRDC_REDIS_PORT``). It mirrors the file-path pub/sub used by the Redis
manager: publish a payload and assert a subscriber receives it verbatim.
"""

import os
import time

import pytest

pytestmark = [pytest.mark.hardware, pytest.mark.redis]


def test_pubsub_round_trip():
    import redis

    host = os.environ.get("AIRDC_REDIS_HOST", "localhost")
    port = int(os.environ.get("AIRDC_REDIS_PORT", "6379"))
    channel = "airdc_test_channel"
    payload = "/tmp/airdc/roundtrip.mcap"

    client = redis.Redis(host=host, port=port, decode_responses=True)
    client.ping()

    pubsub = client.pubsub()
    pubsub.subscribe(channel)
    # Drain the subscription confirmation message.
    confirm = pubsub.get_message(timeout=1.0)
    assert confirm is not None and confirm["type"] == "subscribe"

    time.sleep(0.05)  # let the subscription settle before publishing
    client.publish(channel, payload)

    received = None
    deadline = time.time() + 2.0
    while time.time() < deadline:
        msg = pubsub.get_message(timeout=0.5)
        if msg and msg["type"] == "message":
            received = msg["data"]
            break

    pubsub.close()
    client.close()

    assert received == payload
