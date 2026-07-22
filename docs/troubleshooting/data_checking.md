# 数据检查

## MCAP

参考数据可视化部分提到的[MCAP CLI安装说明](../visualize/foxglove.md#mcap_cli)安装mcap命令行工具。更多安装和使用方法请参考[MCAP官方文档](https://mcap.dev/guides/cli)。

### 查看基本信息

```bash
mcap info <file_name>.mcap
```

这将列出MCAP文件的基本信息，包括版本、大小、时间范围和话题列表等。各 topic 名称后缀（如 `joint_state/effort`、`pose/rot6d`、`follow`/`lead`）的物理含义见[数据 Topic 命名与物理含义](../reference/data_topics.md)。

### 列出附件

```bash
mcap list attachments <file_name>.mcap
```

这将列出MCAP文件中的所有附件及其相关信息，默认包括：。

一般默认包括：`json`类型的`component_info`和`log_stamps`，以及`mp4`类型的视频附件。


### 列出元信息

```bash
mcap list metadata <file_name>.mcap
```

这将列出MCAP文件中的所有元信息条目，主要是采样器的配置、电脑系统的基本参数信息等。

### 文件诊断

```bash
mcap doctor <file_name>.mcap
```

这将检查MCAP文件的完整性并报告任何发现的问题（若无问题，则无输出）。
