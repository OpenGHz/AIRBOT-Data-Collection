import numpy as np


class SineGenerator:
    def __init__(self, length, initial_phase, step, phase_diff):
        """
        :param length: 数组长度
        :param initial_phase: 初始相位 (弧度)
        :param step: 每次更新时相位增加的步长
        :param phase_diff: 数组中相邻元素的相位差
        """
        self.length = length
        self.current_phase = initial_phase
        self.step = step
        self.phase_diff = phase_diff

        # 预先生成相位偏移数组，提高计算效率
        self.offsets = np.arange(self.length) * self.phase_diff

    def update(self) -> np.ndarray:
        """更新相位并返回当前的正弦值数组"""
        # 计算当前所有点的相位
        phases = self.current_phase + self.offsets
        values = np.sin(phases)

        # 为下一次调用更新起始相位
        self.current_phase += self.step
        return values
