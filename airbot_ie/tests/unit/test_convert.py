"""Topic-mapping normalization used by the data converter.

Pure software. The normalization turns str values into ``{topic: None}`` (so
every value is a dict) and collects the flat set of referenced topic names.
Was previously a module-level script.
"""

import pytest

pytestmark = pytest.mark.software


def _normalize(topic_mapping: dict) -> set[str]:
    """Normalize str values to ``{topic: None}`` in place; return the flat topic set."""
    topic_names: set[str] = set()
    for key, value in topic_mapping.items():
        if isinstance(value, str):
            topic_mapping[key] = {value: None}
            topic_names.add(value)
        else:
            assert isinstance(value, dict), f"Value for key {key} must be a dict."
            topic_names.update(value.keys())
    return topic_names


def test_topic_mapping_normalization():
    topic_mapping = {
        "jq": {
            "/follow/arm/joint_states/position": slice(0, 6),
            "/follow/eef/joint_states/position": slice(6, 7),
        },
        "eef_pos": "/follow/arm/pose/position",
        "end_force": {
            "/follow/arm/wrench/force": slice(0, 3),
            "/follow/arm/wrench/torque": slice(3, 6),
        },
        "act": "/lead/arm/pose/position",
    }

    topic_names = _normalize(topic_mapping)

    # str values became single-key dicts mapping to None
    assert topic_mapping["eef_pos"] == {"/follow/arm/pose/position": None}
    assert topic_mapping["act"] == {"/lead/arm/pose/position": None}
    # every value is now a dict
    assert all(isinstance(v, dict) for v in topic_mapping.values())
    # the flat topic-name set is complete
    assert topic_names == {
        "/follow/arm/joint_states/position",
        "/follow/eef/joint_states/position",
        "/follow/arm/pose/position",
        "/follow/arm/wrench/force",
        "/follow/arm/wrench/torque",
        "/lead/arm/pose/position",
    }
