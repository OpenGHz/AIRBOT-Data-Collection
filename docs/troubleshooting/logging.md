# 日志与运行记录

本项目使用 [Hydra](https://hydra.cc) 来组合（compose）配置并记录每次运行的信息。
入口为 `airdc`（`airdc.main:main`），其内部通过
`mcap_data_loader.configurers.hydra_cfger.Configurer` 驱动 Hydra，因此在 Hydra 的运行
记录里作业名（`hydra.job.name`）显示为 `hydra_cfger`。

理解「日志记录到哪里」需要区分两类信息：

1. **控制台日志**（运行时打印的文本）——只输出到终端，默认不落盘。
2. **配置快照**（本次运行实际使用了哪些配置）——由 Hydra 自动写入 `outputs/` 目录。

## 每次运行的输出目录

每启动一次数据采集，Hydra 会按启动时间创建一个独立的运行目录：

```
outputs/${now:%Y-%m-%d}/${now:%H-%M-%S}/
```

例如 `outputs/2026-07-07/20-28-26/`。使用多任务（multirun / sweep）模式时，
目录改为 `multirun/${now:%Y-%m-%d}/${now:%H-%M-%S}/${job_num}/`。

> 该目录规则来自 Hydra 的 `hydra.run.dir` / `hydra.sweep.dir`，可在运行记录
> `hydra.yaml` 中查到。`outputs/` 与 `multirun/` 已在 `.gitignore` 中忽略，不会进入版本库。

## 配置快照：`.hydra/` 目录

在每个运行目录下，Hydra 会创建一个 `.hydra/` 子目录（由 `hydra.output_subdir=.hydra`
指定），写入 **3 个文件**，完整记录本次运行「用的是什么配置」：

| 文件 | 内容 |
|------|------|
| `.hydra/config.yaml` | **本次运行最终生效的应用配置**（由 `airbot_ie/configs/config.yaml` 的 `defaults` 组合、并叠加命令行覆盖后解析出来的完整结果）。想复现或排查一次采集，先看这个文件。 |
| `.hydra/overrides.yaml` | 本次运行在命令行上传入的覆盖项列表（如 `samplers=lerobot foo.bar=1`）。没有覆盖时为空列表 `[]`。 |
| `.hydra/hydra.yaml` | Hydra 自身的配置，包含运行目录规则、日志配置、`job`/`runtime` 信息、`config_sources`（配置来源路径）以及 `choices`（本次选中的各配置组，如 `samplers: mcap`、`managers: keyboard`）。 |

排查某次采集「为什么用了这些参数」时，`.hydra/config.yaml` 是最权威的依据——它是解析后的
真实取值，而不是模板。

## 控制台日志

控制台日志的行为由 `airbot_ie/configs/hydra/job_logging/custom.yaml` 决定
（在 `config.yaml` 中通过 `override hydra/job_logging: custom` 启用）：

```yaml
handlers:
  console:
    class: logging.StreamHandler        # 只有 StreamHandler，没有 FileHandler
    formatter: colorful                 # mcap_data_loader.utils.log.ColorfulFormatter
root:
  level: INFO
loggers:
  airdc:
    level: INFO
  transitions:
    level: WARNING                      # 状态机库较吵，降为 WARNING
```

要点：

- 该配置**只挂了一个 `StreamHandler`（输出到 stdout），没有文件处理器**，所以
  运行时的日志文本**默认不会写入 `outputs/` 里的 `.log` 文件**——`outputs/` 中只保存
  上面的配置快照。若需要留存终端日志，可在启动命令后自行重定向，例如
  `airdc ... 2>&1 | tee run.log`。
- `chdir` 为 `null`，即 Hydra **不会**把工作目录切换到运行目录，程序仍在项目根目录下运行。

### 调整日志级别

- **临时调整**：命令行覆盖，例如把根日志或 `airdc` 打到 DEBUG：

  ```bash
  airdc hydra.job_logging.root.level=DEBUG
  airdc hydra.job_logging.loggers.airdc.level=DEBUG
  ```

- **持久调整**：直接编辑 `airbot_ie/configs/hydra/job_logging/custom.yaml` 中对应的
  `level`。

### 需要把日志写入文件

在 `custom.yaml` 中增加一个 `FileHandler` 并挂到 `root.handlers` 即可，例如：

```yaml
handlers:
  console:
    class: logging.StreamHandler
    formatter: colorful
    stream: ext://sys.stdout
  file:
    class: logging.FileHandler
    formatter: colorful
    filename: ${hydra.runtime.output_dir}/run.log   # 落到本次运行目录
root:
  level: INFO
  handlers: [ console, file ]
```

这样日志会随配置快照一起保存到当次的 `outputs/.../run.log`。

## 磁盘清理

`outputs/`（以及 multirun 的 `multirun/`）每运行一次就新增一个按时间命名的目录，长期使用会
累积较多小目录。它们已被 `.gitignore` 忽略，可放心按需清理，例如删除某天的全部记录：

```bash
rm -rf outputs/2026-07-07
```

## 其他

- [常见问题](faq.md)
- [数据检查](data_checking.md)
