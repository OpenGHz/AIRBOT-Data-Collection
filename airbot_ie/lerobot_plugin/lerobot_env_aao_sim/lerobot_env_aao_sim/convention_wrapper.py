"""convention_wrapper.py — gym wrappers for rot6d convention conversion.

Two thin wrappers that apply ``swap_rot6d_convention`` to either the
observation or the action side.  Because the conversion is self-inverse,
there is no ``direction`` parameter: wrapping converts sim→real OR real→sim
(they are the same operation).

Usage — policy trained on real data, evaluated in sim:

    env = AAOSimEnv(observation_rotation="rot6d", ...)
    env = Rot6dObsWrapper(env)     # sim obs → real convention for policy input
    env = Rot6dActionWrapper(env)  # real action → sim convention before step()
"""

from __future__ import annotations

import gymnasium as gym
import numpy as np

from .rot6d_convention import swap_rot6d_convention

# rot6d occupies indices [3:9] inside agent_pos / action: [pos3, rot6d6, grip1]
_S, _E = 3, 9


class Rot6dObsWrapper(gym.ObservationWrapper):
    """Convert rot6d slice of ``obs["agent_pos"]`` between sim and real conventions."""

    def observation(self, obs: dict) -> dict:
        p = obs["agent_pos"].copy()
        p[_S:_E] = swap_rot6d_convention(p[_S:_E])
        return {**obs, "agent_pos": p}


class Rot6dActionWrapper(gym.ActionWrapper):
    """Convert rot6d slice of ``action`` between sim and real conventions."""

    def action(self, action: np.ndarray) -> np.ndarray:
        a = action.copy()
        a[_S:_E] = swap_rot6d_convention(a[_S:_E])
        return a


# Legacy names kept for backward compatibility
Rot6dConventionWrapper = Rot6dObsWrapper
Rot6dActionConventionWrapper = Rot6dActionWrapper
