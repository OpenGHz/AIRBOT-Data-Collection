from typing import ClassVar, Optional, Type
from airdc.managers.basis import (
    DemonstrateManagerBasis,
    State,
    DemonstrateAction as DAction,
)
from auto_atom.runner.base import RunnerBase
from auto_atom.runner.data_replay import DataReplayRunner, DataReplayTaskFileConfig
from auto_atom.runtime import TaskRunner, TaskFileConfig
import numpy as np


class AutoAtomConfig(TaskFileConfig):
    """Configuration for the auto atom manager."""


class AutoAtomDataReplayConfig(DataReplayTaskFileConfig):
    """Configuration for the data-replay manager."""


class AutoAtomManagerBasis(DemonstrateManagerBasis):
    """Manager basis for automatically controlling"""

    runner_cls: ClassVar[Optional[Type[RunnerBase]]] = None

    def on_configure(self):
        self._runner = self.runner_cls().from_config(self.config)
        self._cur_done_count = 0
        self._runner_done_handled = np.zeros(len(self.fsms), dtype=bool)
        self._total_saved = 0
        return True

    def update(self) -> bool:
        fsms = self.fsms
        batch_size = len(fsms)
        reset_mask = np.zeros(batch_size, dtype=bool)
        update_mask = np.zeros(batch_size, dtype=bool)
        for i, fsm in enumerate(fsms):
            state = fsm.get_state()
            # print(f"FSM {i} state: {state}")
            if state is State.active:
                """
                1. runner.reset()
                └─ MujocoTaskBackend.reset()
                    ├─ env.reset()       ← 重置到 XML 默认值
                    ├─ operator.home()
                    └─ _apply_randomization()  ✓ 随机化已应用

                2. fsm.act(DAction.sample)
                └─ PREPARE_EVENT_BEFORE 回调: demonstrator.react(sample)
                    └─ SingleComponentDemonstrator.switch_mode(SAMPLING)
                        └─ BatchedMujocoEnv.on_switch_mode(SAMPLING)
                            └─ env.reset()   ← !! 随机化被覆盖 !!
                            # 因为 SAMPLING != RESETTING，所以会 reset
                """
                reset_mask[i] = fsm.act(DAction.sample)
                if reset_mask[i]:
                    self._runner_done_handled[i] = False
            elif state is State.sampling:
                update_mask[i] = True
        if not (reset_mask.any() or update_mask.any()):
            return True
        runner = self._runner
        if reset_mask.any():
            runner.reset(reset_mask)
        if not update_mask.any():
            return True
        # 对需要更新的runner执行一步更新，返回各runner的完成和成功状态
        update_result = runner.update(update_mask)
        # 将完成状态转为布尔掩码，标记哪些runner已结束
        done_mask = np.asarray(update_result.done, dtype=bool)
        # 筛选出本轮新完成的runner：需要同时满足被更新、已完成、且尚未处理过
        new_done_mask = update_mask & done_mask & ~self._runner_done_handled
        # 在新完成的runner中，进一步筛选出成功的runner
        success_mask = new_done_mask & np.asarray(update_result.success, dtype=bool)
        # 获取本轮新完成的runner索引
        done_ids = np.where(new_done_mask)[0]
        # 获取成功的runner索引（这里判定成功的前提是要先done）
        success_ids = np.where(success_mask)[0]
        # 从新完成的runner中去掉成功的，剩下的即为失败的runner索引
        fail_ids = np.setdiff1d(done_ids, success_ids)
        for i in success_ids:
            fsms[int(i)].act(DAction.save)
        # FIXME: what if failed to save?
        self._total_saved += len(success_ids)
        for i in fail_ids:
            fsms[int(i)].act(DAction.abandon)
        self._cur_done_count = len(done_ids)
        self._runner_done_handled[new_done_mask] = True
        return True

    def on_shutdown(self):
        if self._runner is not None:
            self._runner.close()
        return True


class AutoAtomManager(AutoAtomManagerBasis):
    """Manager for automatically controlling the demonstrate interface based on a rule-based configuration"""

    config: AutoAtomConfig
    runner_cls = TaskRunner


class AutoAtomDataReplayManager(AutoAtomManagerBasis):
    """Manager for replaying the demonstration data"""

    runner_cls = DataReplayRunner

    def __init__(self, config: AutoAtomDataReplayConfig):
        self._runner: DataReplayRunner
        self.config = config
