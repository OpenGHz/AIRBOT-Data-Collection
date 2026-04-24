import math
import os
import subprocess
from pydantic import BaseModel, AliasChoices
from threading import Lock
from typing import List, Dict
from mcap_data_loader.utils.basic import get_items_by_ext, zip
from mcap_data_loader.utils.log import init_logging
from mcap_data_loader.basis import StrEnum


zip_equal = zip


class BaseModelWithFieldAliases(BaseModel):
    """By default, `validation_alias` will override the original field name.
    This class also adds the original field name to the alias."""

    def __init_subclass__(cls, **kwargs):
        for name, field in cls.model_fields.items():
            kebab = name.replace("_", "-")
            alias = field.validation_alias
            if isinstance(alias, AliasChoices):
                choices = list(alias.choices)
            elif alias:
                choices = [alias]
            else:
                choices = []
            if kebab not in choices:
                field.validation_alias = AliasChoices(*choices, kebab)
        super().__init_subclass__(**kwargs)


def optimal_grid(
    N: int, screen_width: int, screen_height: int, image_aspect_ratio: float = 1.0
):
    """Determine the best grid layout for a given screen resolution

    Args:
    - N: number of images
    - screen_width: screen width in pixels
    - screen_height: screen height in pixels
    - image_aspect_ratio: image aspect ratio (default 1.0 for square)

    Returns:
    - rows: number of rows
    - cols: number of columns
    """
    ratio_adjustment = (screen_height / screen_width) * image_aspect_ratio
    ideal_rows = math.sqrt(N * ratio_adjustment)
    best_error = float("inf")
    optimal_rows, optimal_cols = 1, N
    for r in range(max(1, int(ideal_rows * 0.7)), int(ideal_rows * 1.3) + 1):
        c = math.ceil(N / r)

        cell_width = screen_width / c
        cell_height = screen_height / r
        cell_aspect_ratio = cell_width / cell_height

        aspect_error = abs(cell_aspect_ratio - image_aspect_ratio) / image_aspect_ratio
        wasted_space = (r * c - N) / N
        total_error = aspect_error + wasted_space

        if total_error < best_error:
            best_error = total_error
            optimal_rows, optimal_cols = r, c

    return optimal_rows, optimal_cols


def execute_shell_script(
    script_path: str,
    args=None,
    env=None,
    timeout=None,
    check=True,
    with_sudo: bool = False,
):
    """
    执行shell脚本并返回执行结果

    参数:
        script_path (str): 脚本文件路径
        args (list): 传递给脚本的参数列表
        env (dict): 自定义环境变量
        timeout (int): 脚本执行超时时间(秒)
        check (bool): 是否在返回非零退出状态时抛出异常

    返回:
        subprocess.CompletedProcess: 包含执行结果的对象
    """
    # 确保脚本存在且可执行
    if not os.path.isfile(script_path):
        raise FileNotFoundError(f"脚本文件不存在: {script_path}")

    if not os.access(script_path, os.X_OK):
        # 尝试添加可执行权限
        try:
            os.chmod(script_path, os.stat(script_path).st_mode | 0o111)
            print(f"已为脚本添加可执行权限: {script_path}")
        except OSError as e:
            raise PermissionError(f"脚本不可执行且无法添加权限: {e}")

    # 构建命令
    cmd = [os.path.abspath(script_path)]
    if with_sudo:
        cmd.insert(0, "sudo")
    if args:
        cmd.extend(args)

    # 合并环境变量
    new_env = os.environ.copy()
    if env:
        new_env.update(env)

    print(f"执行命令: {' '.join(cmd)}")

    try:
        # 执行脚本
        result = subprocess.run(
            cmd,
            env=new_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )
        return result
    except subprocess.TimeoutExpired as e:
        print(f"脚本执行超时: {e}")
        # 返回部分结果
        return subprocess.CompletedProcess(
            args=e.cmd, returncode=-1, stdout=e.stdout, stderr=e.stderr
        )
    except subprocess.CalledProcessError as e:
        print(f"脚本执行失败，返回代码: {e.returncode}")
        print(f"标准输出:\n{e.stdout}")
        print(f"错误输出:\n{e.stderr}")
        raise


def get_can_interfaces():
    try:
        # 执行 ip l 命令
        ip_result = subprocess.run(
            ["ip", "l"], capture_output=True, text=True, check=True
        )

        # 获取输出并按行分割
        output = ip_result.stdout
        lines = output.split("\n")

        # 筛选包含 'can' 的行并提取设备名称
        can_interfaces = []
        for line in lines:
            if "can" in line:
                # 提取设备名称（格式通常为数字: 设备名: <...>）
                parts = line.strip().split(": ")
                if len(parts) > 1:
                    can_interfaces.append(parts[1])

        return can_interfaces

    except subprocess.CalledProcessError as e:
        print(f"命令执行失败: {e.stderr}")
        return []
    except Exception as e:
        print(f"发生错误: {e}")
        return []


def linear_map(
    x, raw_range: tuple[float, float], target_range: tuple[float, float]
) -> float:
    a, b = raw_range
    c, d = target_range
    return (x - a) * (d - c) / (b - a) + c


def sort_index(order: list, name_list: list, value_list: list) -> tuple:
    order_dict = {val: idx for idx, val in enumerate(order)}
    sorted_pairs = sorted(zip(value_list, name_list), key=lambda x: order_dict[x[1]])
    sorted_value_list, _ = zip(*sorted_pairs)
    return sorted_value_list


def list_remove(lis: list, items: set) -> list:
    return [item for item in lis if item not in items]


def ensure_equal_length(ref: list, value: list, one_copy: bool = True):
    if len(value) == 1 and one_copy:
        value *= len(ref)
    if len(ref) != len(value):
        raise ValueError(f"Length mismatch: {len(ref)} vs {len(value)}")
    return value


class EnvVarManager:
    """Class to manage environment variables: store original values, clear, and restore them."""

    def __init__(self, var_names: List[str]):
        self._var_names = list(var_names)
        self._original_values: Dict[str, str] = {}
        self._lock = Lock()

        with self._lock:
            for name in self._var_names:
                if name in os.environ:
                    self._original_values[name] = os.environ[name]
                else:
                    self._original_values[name] = None

    def clear(self) -> None:
        with self._lock:
            for name in self._var_names:
                os.environ.pop(name, None)
        return self

    def restore(self) -> None:
        with self._lock:
            for name in self._var_names:
                original_value = self._original_values.get(name)
                if original_value is not None:
                    os.environ[name] = original_value
                else:
                    os.environ.pop(name, None)
        return self

    def __enter__(self) -> "EnvVarManager":
        return self.clear()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.restore()


proxy_context = EnvVarManager(
    ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
)

if __name__ == "__main__":
    init = "original_value"
    os.environ["TEST_ENV_VAR"] = init
    print("Initial:", os.environ.get("TEST_ENV_VAR"))
    manager = EnvVarManager(["TEST_ENV_VAR"])
    os.environ["TEST_ENV_VAR"] = "modified_value"
    print("Before clear:", os.environ.get("TEST_ENV_VAR"))

    manager.clear()
    print("After clear:", os.environ.get("TEST_ENV_VAR"))

    manager.restore()
    print("After restore:", os.environ.get("TEST_ENV_VAR"))
