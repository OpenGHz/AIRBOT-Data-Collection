"""Unit tests for DiscoverAutoAtomDataReplayManager's per-mcap repeat gate."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from airbot_ie.managers.auto_atom import (
    DiscoverAutoAtomDataReplayManager,
    RedisFilePathMessage,
)


def _make_manager(repeats, output_dir=None):
    """Build a manager instance without running its __init__ / config validators.

    The gate logic we exercise only touches a handful of attributes; we set
    them directly. ``self.config`` is a SimpleNamespace because the real
    DiscoverAutoAtomDataReplayConfig pulls in the full task-file tree.
    """
    mgr = object.__new__(DiscoverAutoAtomDataReplayManager)
    mgr.config = SimpleNamespace(repeats=repeats)
    mgr.fsms = [MagicMock(), MagicMock()]
    mgr._current_message = RedisFilePathMessage(
        file_path="x.mcap", output_dir=output_dir
    )
    mgr._cur_done_count = 0
    mgr._total_saved = 0
    mgr._reorganized_message_id = None
    mgr._repeats_remaining = repeats
    mgr._repeat_index = 0
    return mgr


def _drive_done_tick(mgr):
    """Simulate one tick where the batch just completed."""
    mgr._cur_done_count = len(mgr.fsms)
    # Reset FSMs to non-sampling so the mismatch branch is a no-op
    for fsm in mgr.fsms:
        fsm.get_state.return_value = MagicMock(name="not_sampling")
    return mgr.update()


@patch.object(DiscoverAutoAtomDataReplayManager, "get_logger")
def test_repeats_three_holds_demo_for_three_batches(mock_logger):
    """repeats=3: three done-batches → 3 reorgs, 1 ACK, 1 update_data_path."""
    mgr = _make_manager(repeats=3, output_dir="/out/ep01")
    repeat_indices_seen = []

    def record_repeat_index():
        repeat_indices_seen.append(mgr._repeat_index)

    with (
        patch.object(
            DiscoverAutoAtomDataReplayManager,
            "_reorganize_current_message",
            side_effect=record_repeat_index,
        ) as reorg,
        patch.object(
            DiscoverAutoAtomDataReplayManager, "_ack_current_message", return_value=True
        ) as ack,
        patch.object(DiscoverAutoAtomDataReplayManager, "_update_data_path") as upd,
        patch(
            "airdc.managers.auto_atom.AutoAtomManagerBasis.update", return_value=True
        ),
    ):
        for _ in range(3):
            _drive_done_tick(mgr)

    assert reorg.call_count == 3
    assert ack.call_count == 1
    assert upd.call_count == 1
    assert repeat_indices_seen == [0, 1, 2]
    assert mgr._repeats_remaining == 0


@patch.object(DiscoverAutoAtomDataReplayManager, "get_logger")
def test_repeats_one_matches_legacy_behavior(mock_logger):
    """repeats=1: one done-batch → 1 reorg, 1 ACK, 1 update_data_path (today's path)."""
    mgr = _make_manager(repeats=1, output_dir="/out/ep01")

    with (
        patch.object(
            DiscoverAutoAtomDataReplayManager, "_reorganize_current_message"
        ) as reorg,
        patch.object(
            DiscoverAutoAtomDataReplayManager, "_ack_current_message", return_value=True
        ) as ack,
        patch.object(DiscoverAutoAtomDataReplayManager, "_update_data_path") as upd,
        patch(
            "airdc.managers.auto_atom.AutoAtomManagerBasis.update", return_value=True
        ),
    ):
        _drive_done_tick(mgr)

    assert reorg.call_count == 1
    assert ack.call_count == 1
    assert upd.call_count == 1
    assert mgr._repeat_index == 0


@patch.object(DiscoverAutoAtomDataReplayManager, "get_logger")
def test_episode_id_suffix_only_after_first_repeat(mock_logger, tmp_path):
    """_reorganize_current_message: suffix only when _repeat_index > 0 AND output_dir set."""
    mgr = _make_manager(repeats=3, output_dir=str(tmp_path / "ep_xyz"))
    mgr.config = SimpleNamespace(
        repeats=3, max_episodes=1, reorganized_dir=tmp_path / "reorg"
    )
    mgr._data_root = tmp_path

    captured_episode_ids = []

    def fake_reorganize_data_by_episode(cfg):
        captured_episode_ids.append(cfg.episode[1] if len(cfg.episode) >= 2 else "")

    fsm = MagicMock()
    fsm.sample_info.episode = 1
    fsm.dataset_config.absolute_directory = tmp_path / "task"
    mgr.fsms = [fsm]
    mgr._total_saved = 1

    with (
        patch(
            "airbot_ie.managers.auto_atom.reorganize_data_by_episode",
            side_effect=fake_reorganize_data_by_episode,
        ),
        patch.object(
            DiscoverAutoAtomDataReplayManager, "_episode_mp4s_ok", return_value=True
        ),
    ):
        # mimic the gate's mutation order: reorg runs, then _repeat_index increments
        for expected_index in (0, 1, 2):
            mgr._reorganize_current_message()
            mgr._repeat_index += 1

    assert captured_episode_ids == ["ep_xyz", "ep_xyz-r1", "ep_xyz-r2"]


@patch.object(DiscoverAutoAtomDataReplayManager, "get_logger")
def test_folder_mode_no_suffix(mock_logger, tmp_path):
    """When output_dir is None, no -r{i} suffix is applied (folder mode)."""
    mgr = _make_manager(repeats=2, output_dir=None)

    captured = []

    def fake_reorganize_data_by_episode(cfg):
        # In folder mode, no second element is appended to --episode
        captured.append(cfg.episode)

    mgr.config = SimpleNamespace(
        repeats=2, max_episodes=1, reorganized_dir=tmp_path / "reorg"
    )
    fsm = MagicMock()
    fsm.sample_info.episode = 1
    fsm.dataset_config.absolute_directory = tmp_path / "task"
    mgr.fsms = [fsm]
    mgr._total_saved = 1
    mgr._data_root = tmp_path

    with (
        patch(
            "airbot_ie.managers.auto_atom.reorganize_data_by_episode",
            side_effect=fake_reorganize_data_by_episode,
        ),
        patch.object(
            DiscoverAutoAtomDataReplayManager, "_episode_mp4s_ok", return_value=True
        ),
    ):
        for _ in range(2):
            mgr._reorganize_current_message()
            mgr._repeat_index += 1

    # Single-element episode arg (source only, no destination remap)
    assert all(len(ep) == 1 for ep in captured), captured


def test_positive_int_rejects_zero():
    """repeats=0 must be rejected at config-validation time by PositiveInt."""
    from pydantic import BaseModel, PositiveInt, ValidationError

    class _Probe(BaseModel):
        repeats: PositiveInt = 1

    with pytest.raises(ValidationError):
        _Probe(repeats=0)
