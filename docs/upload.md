# 数据上传（DataLoop）

AIRDC 支持在保存 MCAP 文件后自动上传到 DataLoop 云端平台。该功能由 `airbot_ie/samplers/mcap_sampler.py` 中的 `AIRBOTMcapDataSampler` 提供。

## 功能说明

当启用上传功能时，每次成功保存 MCAP episode 后，sampler 会自动调用 DataLoop 客户端将文件上传到指定的 project。上传操作在 `save()` 完成后同步执行。

## 配置方式

在 Hydra 配置文件中（通常是 `airbot_ie/configs/` 下的采集配置），为 sampler 添加 `upload` 配置块：

```yaml
samplers:
  _target_: airbot_ie.samplers.mcap_sampler.AIRBOTMcapDataSampler
  upload:
    enable: true
    endpoint: "https://your-dataloop-endpoint.com"
    username: "your-username"
    password: "your-password"
  task_info:
    task_id: 12345  # DataLoop project ID
```

### 配置字段

- `upload.enable` (bool, 默认 `false`) — 是否启用上传。设为 `true` 时在每次 `save()` 后触发上传。
- `upload.endpoint` (str) — DataLoop 服务端点 URL。
- `upload.username` (str) — DataLoop 用户名。
- `upload.password` (str) — DataLoop 密码。
- `task_info.task_id` (int/str) — DataLoop project ID，上传目标项目的标识符。

## 运行时行为

1. **配置阶段** (`on_configure()`)：如果 `upload.enable=true`，sampler 会实例化 `DataLoopClient` 并验证连接。如果 `dataloop` 包不可用，启动时会报错。
2. **保存阶段** (`save()`)：MCAP 文件写入本地后，立即调用 `dataloop_client.samples.upload_sample()` 上传。
3. **日志输出**：上传前会打印 `Will upload to task id: <id>`；上传成功后打印 `Uploaded to cloud: <message>`。

## 依赖安装

上传功能依赖 `dataloop` Python 包（私有包，需联系 AIRBOT 售后获取安装包或访问凭证）。如果环境中缺少该包，启动时会打印警告：

```
It is detected that the `UPLOAD` package is not installed, and the cloud upload function will not be available.
```

此时 `upload.enable=true` 会导致 `AssertionError`。

## 注意事项

- 上传是**同步阻塞**操作，在上传完成前 `save()` 不会返回。对于大文件或慢网络，可能影响采集流程的响应性。
- 上传失败不会阻止本地保存成功（本地 MCAP 已落盘），但会在日志中体现。
- `task_id` 可以是字符串或整数；代码会自动转换为 `int` 后传给 DataLoop API。
- 用户名和密码以明文存储在配置文件中，注意保护配置文件权限或使用环境变量替代（需要手动扩展 `UploadConfig`）。

## 相关代码

- sampler 实现：[airbot_ie/samplers/mcap_sampler.py](../airbot_ie/samplers/mcap_sampler.py)
- 配置模型：`UploadConfig` (`airbot_ie/samplers/mcap_sampler.py:23`)
- 上传逻辑：`_upload_to_cloud()` (`:66`)
