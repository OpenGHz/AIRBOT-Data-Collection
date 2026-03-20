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
            runner.reset()
            return fsm.act(DAction.sample)
        elif state is State.sampling:
            result = runner.update()
            if result.done:
                if result.success:
                    return fsm.act(DAction.save)
                return fsm.act(DAction.abandon)
        return True

    def on_shutdown(self):
        self._runner.close()
        return True
