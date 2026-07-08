from airdc.common.utils.shareable_numpy import ShareableNumpy
from multiprocessing.managers import SharedMemoryManager
import numpy as np
import cv2
from typing import Dict, Union
import time


def worker(arr: Union[ShareableNumpy, Dict[str, ShareableNumpy]]) -> None:
    if not isinstance(arr, dict):
        arr = {"array": arr}
    for k, v in arr.items():
        print(f"Child process sees array {k} with shape {v.shape} and dtype {v.dtype}")
        v[:] += 10
        if len(v.shape) == 3:
            cv2.imshow(f"Worker Process Image {k}", v.array)
            cv2.waitKey(0)
            cv2.destroyAllWindows()
        else:
            print(f"Child process array {k} after modification:", v.array)
    time.sleep(5)
    print("Child process sees modified result:", v.array)


if __name__ == "__main__":
    from multiprocessing.context import SpawnProcess

    with SharedMemoryManager() as smm:
        # arr_shape = (1, 7)
        arr_shape = (480, 640, 3)
        # arr_shape = (4320, 7680, 3)
        dtype = np.uint8
        arr_dict = {}
        np_arr = np.ones(arr_shape, dtype=dtype) * 100
        for i in range(4):
            arr = ShareableNumpy.from_array(np_arr, smm=smm)
            arr_dict[i] = arr

        print("Main process initial array:", arr.array)

        p = SpawnProcess(target=worker, args=(arr_dict,))
        p.start()
        time.sleep(2)
        print("Main process sees modified result:", arr.array)
        # np_arr[:] -= 10
        arr[:] -= 10
        p.join()
