import numpy as np
import time

# 测试不同规模
sizes = [10_000, 100_000, 1_000_000, 10_000_000]

for N in sizes:
    py_list = list(range(N))

    start = time.time()
    np_arr = np.fromiter(py_list, dtype=np.int64, count=N)
    dt = time.time() - start

    print(f"长度 {N:>8,}: 转换耗时 {dt * 1000:.2f} ms")
