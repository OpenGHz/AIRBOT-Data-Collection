from collections import defaultdict
from enum import Enum, auto
from functools import partial
from logging import getLogger
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, ConfigDict
from transitions import EventData
from transitions.extensions import LockedMachine
from airdc.utils import StrEnum
import sys


State = Optional[Union[str, Enum, dict]]
StateKey = Union[str, Enum]
Action = Union[str, Enum]
SMCallable = Optional[Union[Callable, str, List[Union[Callable, str]]]]
Nameable = Union[str, Enum, partial, Callable]


class CallbackEventType(StrEnum):
    """Types of callback events."""

    PREPARE_EVENT_BEFORE = auto()
    """The callback before prepare event."""
    PREPARE_EVENT = auto()
    """The prepare event callback for an action."""
    PREPARE_EVENT_AFTER = auto()
    """The callback after prepare event."""
    BEFORE_STATE_CHANGE = auto()
    """The callback before state change."""
    AFTER_STATE_CHANGE = auto()
    """The callback after state change."""


class ToDestConfig(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    dest: State
    """Destination state."""
    conditions: SMCallable = None
    """Conditions to trigger this transition."""
    unless: SMCallable = None
    """Unless conditions to trigger this transition."""
    before: SMCallable = None
    """Callable before the transition."""
    after: SMCallable = None
    """Callable after the transition."""
    prepare: SMCallable = None
    """Callable to prepare the transition."""


ActionTransitions = Dict[Union[State, Tuple[State, ...]], List[ToDestConfig]]
SourceTransitions = Dict[Action, List[ToDestConfig]]


class StateMachineConfig(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    states: List[State] = []
    """All possible states used in the fsm."""
    initial: State = None
    """Initial state of the fsm."""
    action_transitions: Dict[Action, ActionTransitions] = {}
    """The action transitions will be added first, then the source transitions."""
    source_transitions: Dict[StateKey, SourceTransitions] = {}
    """The source transitions will be added after the action transitions.
    Usually, this is used for the error source state."""
    ignore_invalid_triggers: bool = True
    """
    when True, any calls to trigger methods
    that are not valid for the present state (e.g., calling an
    a_to_b() trigger when the current state is c) will be silently
    ignored rather than raising an invalid transition exception.
    """
    name: Optional[str] = None
    """If a name is set, it will be used as a prefix for logger outputs."""
    # # When True, processes transitions sequentially. A trigger
    # # executed in a state callback function will be queued and executed later.
    # # Due to the nature of the queued processing, all transitions will
    # # _always_ return True since conditional checks cannot be conducted at queueing time.
    # queued: bool = False
    finalize_event: SMCallable = None
    """
    A callable called on for each triggered event after transitions have been processed.
    This is also called when a transition raises an exception.
    """
    # # A callable called on for before possible transitions will be processed.
    # # It receives the very same args as normal callbacks.
    # prepare_event: Callable = None
    # # A callable called when an event raises an exception. If not set,
    # # the exception will be raised instead.
    # on_exception: Callable = None
    # # When True, any arguments passed to trigger
    # # methods will be wrapped in an EventData object, allowing
    # # indirect and encapsulated access to data. When False, all
    # # positional and keyword arguments will be passed directly to all
    # # callback methods.
    # send_event: bool = True


class StateMachineBasis:
    def __init__(self, config: StateMachineConfig):
        self.machine = LockedMachine(
            self,
            before_state_change=self.before_state_change,
            after_state_change=self.after_state_change,
            prepare_event=self.prepare_event,
            on_exception=self.on_exception,
            queued=False,
            send_event=True,
            # finalize_event=
            **config.model_dump(
                exclude={"action_transitions", "source_transitions", "log_level"}
            ),
        )
        self._action_result: Dict[str, bool] = {}
        self._last_state = self.get_state()
        self._last_action = None
        self._calls = defaultdict(dict)
        self._calls_raw = {}
        self.add_action_transitions(config.action_transitions)
        self.add_source_transitions(config.source_transitions or {})

    def get_logger(self):
        return getLogger("transitions").getChild(self.__class__.__name__)

    def add_action_transitions(
        self, action_transitions: Dict[Action, ActionTransitions]
    ):
        """Add all transitions of an action.
        The order of the ToDestConfig is important.
        """
        for action, transitions in action_transitions.items():
            action_name = self.get_name(action)
            for source, to_dests in transitions.items():
                for index, to_dest in enumerate(to_dests):
                    if to_dest.conditions is None:
                        break
                if index == len(to_dests) - 1:
                    # if the last transition is success, do not add failure
                    failure = None
                else:
                    failure = to_dests[-1]
                self.add_action_source_transitions(
                    action_name,
                    source,
                    success=to_dests[index],
                    failure=failure,
                    not_only_success=to_dests[:index],
                    not_only_failure=to_dests[index + 1 : -1],
                )

    def add_source_transitions(
        self, source_transitions: Dict[State, SourceTransitions]
    ):
        action_transitions = defaultdict(dict)
        for source, transitions in source_transitions.items():
            for action, todests in transitions.items():
                action_transitions[action][source] = todests
        return self.add_action_transitions(action_transitions)

    def add_action_source_transitions(
        self,
        action: Action,
        source: State,
        success: ToDestConfig,
        failure: ToDestConfig,
        not_only_success: Optional[List[ToDestConfig]] = None,
        not_only_failure: Optional[List[ToDestConfig]] = None,
    ):
        action_name = self.get_name(action)
        assert not self.is_action_source_added(action_name, source)
        self._add_action_source_transitions(
            action_name, source, success, not_only_success, "success"
        )
        self._add_action_source_transitions(
            action_name, source, failure, not_only_failure, "failure"
        )

    def _add_action_source_transitions(
        self,
        action_name: str,
        source: State,
        only: ToDestConfig,
        not_only: Optional[List[ToDestConfig]] = None,
        kind: str = "success",
    ):
        not_only = not_only or []
        if only:
            exclude_fields = ["conditions", "unless"]
            for field in exclude_fields:
                assert getattr(only, field) is None, f"{field} should be None"
        args = (f"t_{action_name}", source)
        self._add_not_only_transitions(action_name, source, not_only, kind)
        cond_mapping = {
            "success": "conditions",
            "failure": "unless",
        }
        if only:
            self.machine.add_transition(
                *args,
                **only.model_dump(exclude=exclude_fields),
                **{cond_mapping[kind]: self.is_action_success},
            )

    def _add_not_only_transitions(
        self, action: str, source: State, to_dests: List[ToDestConfig], kind: str
    ):
        if kind == "success":
            cond = "conditions"
        elif kind == "failure":
            cond = "unless"
        for to_dest in to_dests:
            to_dest_dict = to_dest.model_dump()
            if to_dest_dict.get(cond) is None:
                to_dest[cond] = []
            to_dest[cond].insert(0, self.is_action_success)
            self.machine.add_transition(
                f"t_{action}",
                source,
                **to_dest.model_dump(),
            )

    def is_action_source_added(
        self, action: str, source: Union[State, Tuple[State]]
    ) -> bool:
        """Check if the action source is added."""
        if not isinstance(source, tuple):
            source = (source,)
        for src in source:
            if self.machine.get_transitions(f"t_{self.get_name(action)}", src):
                # self.get_logger().error(
                #     f"Action {action} source {source} is already added."
                # )
                return True
        return False

    @staticmethod
    def get_name(value: Nameable) -> str:
        if isinstance(value, Enum):
            return value.name
        elif isinstance(value, str):
            return value
        elif isinstance(value, partial):
            return value.func.__name__
        else:
            return value.__name__

    def get_state(self) -> str:
        return self.state

    def act(self, action: Action) -> bool:
        """Act the action and return the result."""
        if not self.trigger(f"t_{self.get_name(action)}"):
            self.get_logger().warning(f"Action failed: {action}")
            return False
        return True

    def prepare_event(self, event_data: EventData):
        """Prepare the action."""
        action = self._get_action_from_event(event_data)
        self.get_logger().info(
            f"Executing action: {action} in state: {self.get_state()}"
        )
        result = False
        if self._execute_callbacks(CallbackEventType.PREPARE_EVENT_BEFORE, action):
            if self._execute_callbacks(CallbackEventType.PREPARE_EVENT, action):
                if self._execute_callbacks(
                    CallbackEventType.PREPARE_EVENT_AFTER, action
                ):
                    result = True
                else:
                    self.get_logger().error(
                        f"Prepare event after callback failed for action: {action}"
                    )
            else:
                self.get_logger().error(
                    f"Prepare event callback failed for action: {action}"
                )
        else:
            self.get_logger().error(
                f"Prepare event before callback failed for action: {action}"
            )
        self._action_result[action] = result
        self._last_action = action

    def before_state_change(self, event_data: EventData):
        """Prepare the state."""
        self._last_state = self.get_state()
        # self.get_logger().info(f"State is about to change from {self._last_state}")
        # self._calls[CallbackType.BEFORE_STATE_CHANGE].get(
        #     self.get_state(), lambda: None
        # )()

    def after_state_change(self, event_data: EventData):
        """After the state is changed."""
        # TODO: now call only if state actually changed
        # should we make this behavior configurable?
        if self._last_state != self.get_state():
            self.get_logger().info(
                f"State changed from {self._last_state} to {self.get_state()}"
            )
            if not self._execute_callbacks(
                CallbackEventType.AFTER_STATE_CHANGE, self.get_state()
            ):
                self.get_logger().error(
                    f"After state change callback failed for state: {self.get_state()}"
                )

    def _get_action_from_event(self, event_data: EventData) -> str:
        return event_data.event.name.removeprefix("t_")

    def _execute_callbacks(self, cb_type: CallbackEventType, name: str) -> Any:
        """Call the action."""
        call = self._calls[cb_type].get(name, None)
        if call is not None:
            return call()
        return True

    def is_action_success(self, event_data: EventData) -> bool:
        """Check if the action is success."""
        return bool(self._action_result[self._get_action_from_event(event_data)])

    def get_last_action(self) -> str:
        """Get the last action."""
        return self._last_action

    def get_last_action_result(self) -> Any:
        """Get the last action result."""
        return self._action_result[self._last_action]

    def on_exception(self, event_data: EventData) -> None:
        exc_type = sys.exc_info()[0]
        if exc_type is not None and not issubclass(exc_type, Exception):
            raise
        self.get_logger().exception(f"{event_data}")

    # def finalize_event(self, event_data: EventData) -> None:
    #     """Finalize the event."""
    #     self.get_logger().debug(f"{event_data}")

    def register_callbacks(
        self, cb_type: CallbackEventType, callbacks: Dict[Nameable, Callable]
    ):
        self._calls_raw[cb_type] = callbacks
        for name, callback in callbacks.items():
            self._calls[cb_type][name] = callback

    def get_callbacks(self) -> Dict[CallbackEventType, Dict[Nameable, Callable]]:
        return self._calls_raw

    def shutdown(self):
        """Shutdown the state machine, release all resources."""
        pass
