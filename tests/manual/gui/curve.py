import numpy as np
import holoviews as hv
from holoviews import opts
from airdc.common.utils.curve import SineGenerator


def visualize_cycle():
    # 参数设置
    length = 6
    initial_phase = 0
    step = np.pi / 10  # 每次移动 18 度
    phase_diff = 0.1  # 序列内部的相位差

    generator = SineGenerator(length, initial_phase, step, phase_diff)

    # 模拟一个周期 (2*pi)，步长为 pi/10，所以大约需要 20 步
    num_steps = 20

    y_list = []
    for i in range(num_steps):
        data = generator.update()
        y_list.append(data)

    # --- Holoviews 可视化 ---
    hv.extension("matplotlib")

    # y_list 是 list of arrays, 转换为 (num_steps, length) 的矩阵
    y_matrix = np.array(y_list)

    # 为每一列（即每一个维度/Joint）创建一条曲线
    curves = {
        i: hv.Curve(y_matrix[:, i], kdims="Step", vdims="Value") for i in range(length)
    }

    # 使用 NdOverlay 叠加曲线
    nd_overlay = hv.NdOverlay(curves, kdims="Dimension").opts(
        opts.Curve(linewidth=1),
        opts.NdOverlay(legend_position="right", title="Sine Generator Output"),
    )

    # 获取渲染器并显示
    renderer = hv.renderer("matplotlib")
    renderer.show(nd_overlay)


if __name__ == "__main__":
    visualize_cycle()
