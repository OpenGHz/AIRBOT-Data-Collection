from airdc.common.utils.shareable_value import ShareableValue
from multiprocessing.managers import SharedMemoryManager
import numpy as np
from typing import Dict, Union
import time


def worker(arr: Union[ShareableValue, Dict[str, ShareableValue]]) -> None:
    if not isinstance(arr, dict):
        arr = {"array": arr}
    for k, v in arr.items():
        print(f"Child process sees key {k} with value {v.value} and dtype {v.dtype}")
        v.value = 10
        print(f"Child process key {k} after modification:", v.value)
    time.sleep(5)
    print("Child process sees modified result:", v.value)


if __name__ == "__main__":
    from multiprocessing.context import SpawnProcess

    with SharedMemoryManager() as smm:
        value_dict = {}
        time_stamp = 0
        for i in range(4):
            shm_value = ShareableValue.from_value(time_stamp, np.uint64, smm=smm)
            value_dict[i] = shm_value
        print("Main process initial array:", shm_value.value)
        p = SpawnProcess(target=worker, args=(value_dict,))
        p.start()
        time.sleep(2)
        print("Main process sees modified result:", shm_value.value)
        shm_value.value -= 10
        p.join()
