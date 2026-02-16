import numpy as np
from typing import Tuple, Optional
from logging import getLogger
from mcap_data_loader.utils.transformations import (
    quaternion_inverse,
    quaternion_multiply,
)
from mcap_data_loader.utils.rela_abs import RelaAbs
from airdc.common.systems.basis import ReferenceMode, ReferenceBase


Position = Tuple[float, float, float]
Orientation = Tuple[float, float, float, float]
Pose = Tuple[Position, Orientation]


class RelativePoseControl:
    def __init__(self, reference_mode: ReferenceMode = ReferenceMode.CURRENT_STATE):
        """A class to handle relative pose control.
        Args:
            reference_mode (ReferenceMode): The reference mode for the control.
        """
        self._rela_abs = RelaAbs()
        self._ref = reference_mode.ref_base()
        self._delta = reference_mode.is_step_mode()
        self.reset()
        self._logger = getLogger(self.__class__.__name__)

    def get_reference(self) -> Pose:
        """Get the reference position and orientation.
        Returns:
            Tuple[Position, Orientation]: The reference position and orientation.
        """
        if self._ref is ReferenceBase.STATE:
            return self.position, self.orientation
        else:
            return self._last_position, self._last_orientation

    def has_reference(self) -> bool:
        return None not in {self.position, self.orientation}

    def reset(self):
        self._updated = False
        self.position = None
        self.orientation = None

    def update_state(
        self, position: Optional[Position], orientation: Optional[Orientation]
    ):
        """Update the current position and orientation.
        Args:
            position (Tuple[float, float, float]): The relative position offset.
            orientation (Tuple[float, float, float, float]): The relative orientation offset as a quaternion.
        """
        if not self._updated:
            self._updated = True
        elif not self._delta:
            self._logger.warning(
                "RelativePoseControl is not in delta mode, update only once. "
            )
            return
        if position:
            self.position = np.asarray(position, dtype=np.float32)
        if orientation:
            self.orientation = np.asarray(orientation, dtype=np.float32)

    def to_relative(
        self, position: Position, orientation: Orientation
    ) -> Tuple[Position, Orientation]:
        """Convert absolute position and orientation to relative.
        Args:
            position (Tuple[float, float, float]): The absolute position.
            orientation (Tuple[float, float, float, float]): The absolute orientation as a quaternion.
        Returns:
            Tuple[Position, Orientation]: The relative position and orientation.
        """
        pos, ori = self.get_reference()
        self._last_position = np.asarray(position, dtype=np.float32)
        self._last_orientation = np.asarray(orientation, dtype=np.float32)
        rel_position = self._last_position - pos
        rel_orientation = quaternion_multiply(
            self._last_orientation, quaternion_inverse(ori)
        )
        return rel_position.tolist(), rel_orientation.tolist()

    def to_absolute(
        self, position: Position, orientation: Orientation
    ) -> Tuple[Position, Orientation]:
        """Convert relative position and orientation to absolute.
        Args:
            position (Tuple[float, float, float]): The relative position.
            orientation (Tuple[float, float, float, float]): The relative orientation as a quaternion.
        Returns:
            Tuple[Position, Orientation]: The absolute position and orientation.
        """
        abs_position = np.asarray(position, dtype=np.float32) + self.position
        abs_orientation = quaternion_multiply(
            np.asarray(orientation, dtype=np.float32), self.orientation
        )
        return abs_position.tolist(), abs_orientation.tolist()


if __name__ == "__main__":
    control = RelativePoseControl()

    control.update_state(
        [0.2853687935873074, 0.0007637551378546763, 0.13076724999347855],
        [
            -0.4913512785641308,
            0.5105520106832696,
            0.5041479806920026,
            0.49370576156739404,
        ],
    )

    rele_pose = control.to_absolute([0, 0.1, 0], [0, 0, 0, 1])
    print("Absolute Pose:", rele_pose)
