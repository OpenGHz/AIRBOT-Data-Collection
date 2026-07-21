from enum import Enum
from pynput import keyboard
from airdc.managers.basis import (
    DemonstrateManagerBasis,
    ManagerConfigBasis,
    DemonstrateAction as DAction,
    ManagerAction as MAction,
    KeyToAction,
)


class KeyboardCallbackConfig(ManagerConfigBasis):
    key_to_action: KeyToAction = {
        keyboard.Key.space.name: DAction.sample,
        "s": DAction.save,
        "q": DAction.abandon,
        "r": DAction.remove,
        "p": DAction.capture,
        "z": DAction.finish,
        "i": MAction.INSTRUCTION,
        "g": MAction.MODE,
        "f": MAction.FOLLOW,
        "f2": MAction.LOCK,
        "c": DAction.configure,  # Allow reconfiguration from unconfigured state
        # additional keys
        keyboard.Key.esc.name: DAction.finish,
        keyboard.Key.enter.name: DAction.save,
        keyboard.Key.shift.name: DAction.abandon,
    }


class KeyboardCallbackManager(DemonstrateManagerBasis):
    """Handles key press events for controlling data collection.

    This class listens for specific key presses and triggers actions of the demontrate fsm.
    These actions include starting or stopping data collection, printing
    current component states, removing the last saved episode, etc.
    """

    config: KeyboardCallbackConfig

    def on_configure(self):
        self.listener = keyboard.Listener(on_press=self._keypress_callback)
        self.listener.start()
        self.show_instruction()
        return True

    def update(self) -> bool:
        return True

    def _keypress_callback(self, key: keyboard.Key) -> None:
        """Handles key press events and triggers the appropriate actions.

        This function listens for key presses and initiates the corresponding actions in the
        demonstrate fsm. The actions can include starting or stopping data collection,
        printing states, removing episodes, or changing robot states.

        Args:
            key: The key event triggered by the user.

        Returns:
            None: This function does not return any value.
        """
        self._act_key(self._key_to_str(key).lower())

    def on_shutdown(self) -> bool:
        self.listener.stop()
        # TODO: why can not be stopped?
        # self.listener.join(2)
        # return not self.listener.is_alive()
        return True

    def _key_to_str(self, key):
        if isinstance(key, str):
            return key
        elif isinstance(key, Enum):
            return key.name
        else:
            try:
                key_char = key.char
                if key_char is None:
                    self.get_logger().warning(
                        "Unknown key pressed. There may be a situation where the number keys on the numeric keypad cannot be recognized properly."
                    )
                    key_char = str(key)
            except AttributeError:
                key_char = str(key)
            return key_char
