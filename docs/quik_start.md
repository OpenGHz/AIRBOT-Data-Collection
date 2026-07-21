# 快速开始

## 推荐路径：使用 Pixi

```bash
# 安装 Pixi
bash install/install_pixi.sh

# 安装依赖（自动创建 Python 3.12 环境）
pixi install

# 进入数据采集环境
pixi shell -e collect

# 或直接运行
pixi run -e collect airdc
```

详细说明见 [Pixi 环境与工作流指南](./setup/pixi.md)。

## 传统路径：pip 安装

```bash
# 创建环境（推荐 Python 3.12）
python3.12 -m venv .venv && source .venv/bin/activate

# 安装系统依赖与 Python 包
bash install/install.sh

# 运行
airdc
```

## 开发者预提交检查

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```
