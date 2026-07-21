from airdc.state_machine.basis import ToDestConfig
from airdc.state_machine.fsm import (
    DemonstrateAction as Action,
    DemonstrateState as State,
    StateMachineConfig,
)


STATE_MACHINE_CONFIG = StateMachineConfig(
    states=State,
    initial=State.unconfigured,
    action_transitions={
        Action.configure: {
            State.unconfigured: [
                ToDestConfig(dest=State.inactive),
            ],
        },
        Action.activate: {
            State.inactive: [
                ToDestConfig(dest=State.active),
            ]
        },
        Action.sample: {
            # a prepare callback with the same name as the action
            # will be automatically added to the
            # first transition of each source and the result of
            # the callback will be used as the conditions
            # for the first None conditions & unless transition and
            # and as the unless for the last None conditions & unless
            # transition
            State.active: [
                # success
                # the after callback will use the corresponding trigger
                ToDestConfig(dest=State.sampling),
                # # failure
                # # the before callback will use the original method
                # ToDestConfig(dest=None),
            ],
        },
        Action.update: {
            State.sampling: [
                # success
                ToDestConfig(dest=None),
                # failure
                ToDestConfig(dest=State.active),
            ],
        },
        Action.abandon: {
            State.sampling: [
                ToDestConfig(dest=State.active),
            ]
        },
        Action.save: {
            State.sampling: [
                ToDestConfig(dest=State.active),
            ]
        },
        Action.remove: {State.active: [ToDestConfig(dest=None)]},
        Action.finish: {
            State.active: [ToDestConfig(dest=State.finalized)],
            State.unconfigured: [
                ToDestConfig(dest=State.finalized)
            ],  # Allow finish from unconfigured
        },
        Action.capture: {
            State.active: [ToDestConfig(dest=None)],
            State.sampling: [ToDestConfig(dest=None)],
        },
    },
)


def get_fsm_config(**kwargs) -> StateMachineConfig:
    if kwargs:
        return StateMachineConfig.model_validate(
            STATE_MACHINE_CONFIG.model_copy(update=kwargs)
        )
    return STATE_MACHINE_CONFIG
