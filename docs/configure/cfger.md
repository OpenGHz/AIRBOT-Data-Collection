# 配置框架说明

AIRDC 的配置系统基于可插拔的 configurer 后端，默认使用 Hydra，也支持用户通过 `--configurer` 参数切换到其他实现。

## 默认 Hydra 配置器

默认配置器是 `mcap_data_loader.configurers.hydra_cfger.Configurer`，由 `mcap-data-loader` 包提供（editable 安装在 `third_party/MCAP-DataLoader`）。它将 Hydra 的组合式配置与 Pydantic 数据模型结合，支持通过 YAML 文件和命令行覆盖参数。

### CLI 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--config-name` / `--name` | 配置文件名（不含 `.yaml`），Hydra 会在 `--config-path` 中搜索同名文件 | `config` |
| `--config-path` / `--path` | 配置目录或完整 `.yaml` 路径 | 当前工作目录 |
| `--base-dir` | 配置搜索基准目录；`__main__` = 包目录，否则 CWD | CWD |
| `--add-cwd-mode` | 是否添加 CWD 到 Hydra 搜索路径：`prepend` / `append` / `none` | `append` |
| `--show-resolved` / `-sr` | 打印解析后的完整配置并退出（不运行主程序） | — |
| `--cfger-help` | 打印配置器帮助信息 | — |

### 常见用法

```bash
# 使用默认配置（airbot_ie/configs/config.yaml）
airdc

# 指定配置名（搜索 config_path 中的 aao_config_real.yaml）
airdc --name aao_config_real

# 指定完整路径
airdc --path airbot_ie/configs/config.yaml

# 覆盖参数
airdc --path airbot_ie/configs/config.yaml dataset.directory=my_data batch_size=2

# 查看解析后的配置
airdc --name aao_config_real -sr

# Hydra multirun（在多个参数组合上并行运行）
airdc -m batch_size=1,2,4 samplers=mock,mcap
```

### 配置组合规则

Hydra 通过 `defaults:` 列表和 `# @package _global_` 注解实现配置组合。例如：

```yaml
# airbot_ie/configs/config.yaml
defaults:
  - basis
  - managers: keyboard
  - demonstrators: setup
  - samplers: mcap
```

每个组对应一个子目录（如 `managers/`），Hydra 会加载 `managers/keyboard.yaml` 并合并到最终配置。详细规则见 [Hydra 文档](https://hydra.cc/)。

## 切换配置器

通过环境变量 `AIRDC_CONFIGURER` 或 `--configurer` 参数指定其他配置器类：

```bash
export AIRDC_CONFIGURER=my_package.my_cfger.MyConfigurer
airdc
```

或

```bash
airdc --configurer my_package.my_cfger.MyConfigurer
```

自定义配置器需实现 `mcap_data_loader.configurers.basis.ConfigurerBasis` 接口。

## 配置顶层结构

解析后的配置对象是 `airdc.config.DataCollectionArgs`，包含：

- `update_rate` (float) — 主循环频率（Hz），0 = 全速
- `batch_size` (int) — 并行 FSM 数量
- `fsm` — 状态机配置（transitions / callbacks）
- `managers: Dict[str, DemonstrateManagerBasis]` — 控制器字典
- `demonstrator` — 数据源（真机/仿真/环境）
- `sampler` — 数据写入器
- `visualizer` — 实时显示器（可为 null）
- `dataset` — 输出目录/文件后缀配置
- `sample_limit` — 采集限制（轮数/时长/样本数）
- `log_metrics` / `log_jitter` — 日志配置

完整字段定义见 `airdc/config.py` 和 `airdc/demonstrate/configs.py`。

## 相关文档

- [常见配置调整](./common.md) — 如何修改具体配置项
- [架构总览](../architecture/overview.md) — 配置如何映射到运行时组件
