from airdc.managers.basis import (
    DemonstrateManagerBasis,
    State,
    DemonstrateAction as DAction,
)
from auto_atom.runtime import TaskRunner, TaskFileConfig
import numpy as np


class AutoAtomConfig(TaskFileConfig):
    """Configuration for the auto atom manager."""


class AutoAtomManager(DemonstrateManagerBasis):
    """Manager for automatically controlling"""

    config: AutoAtomConfig

    def on_configure(self):
        self._runner = None
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
            elif state is State.sampling:
                update_mask[i] = True
        if not (reset_mask.any() or update_mask.any()):
            return True
        if self._runner is None:
            self._runner = TaskRunner().from_config(self.config)
        runner = self._runner
        runner.reset(reset_mask)
        update_result = runner.update(update_mask)
        done_ids = np.where(update_result.done)[0]
        success_ids = np.where(update_result.success)[0]
        fail_ids = np.setdiff1d(done_ids, success_ids)
        for i in success_ids:
            fsms[int(i)].act(DAction.save)
        for i in fail_ids:
            fsms[int(i)].act(DAction.abandon)
        return True

    def on_shutdown(self):
        if self._runner is not None:
            self._runner.close()
        return True
