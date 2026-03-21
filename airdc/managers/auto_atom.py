from airdc.managers.basis import (
    DemonstrateManagerBasis,
    State,
    DemonstrateAction as DAction,
)
from auto_atom.runtime import TaskRunner, TaskFileConfig


class AutoAtomConfig(TaskFileConfig):
    """Configuration for the auto atom manager."""


class AutoAtomManager(DemonstrateManagerBasis):
    """Manager for automatically controlling"""

    config: AutoAtomConfig

    def on_configure(self):
        self._runner = None
        return True

    def update(self) -> bool:
        fsm = self.fsm
        state = fsm.get_state()
        if state not in {State.active, State.sampling}:
            return True
        elif self._runner is None:
            self._runner = TaskRunner().from_config(self.config)
        runner = self._runner
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
                    └─ MujocoEnv.on_switch_mode(SAMPLING)
                        └─ env.reset()   ← !! 随机化被覆盖 !!
                        # 因为 SAMPLING != RESETTING，所以会 reset
            """
            result = fsm.act(DAction.sample)
            runner.reset()
            return result
        elif state is State.sampling:
            result = runner.update()
            if result.done:
                if result.success:
                    return fsm.act(DAction.save)
                return fsm.act(DAction.abandon)
        return True

    def on_shutdown(self):
        if self._runner is not None:
            self._runner.close()
        return True
