# AIRDC 文档

**AIRDC (AI Robot Data Collection)** 是一个专为具身智能研发设计的高性能、模块化、可扩展的机器人多模态数据采集框架。它屏蔽底层硬件复杂性、优化数据吞吐，帮助研究人员和工程师构建大规模、高保真的多模态数据集。

> [!TIP]
> 左侧边栏包含完整导航。若为首次使用，建议从 [项目简介](/intro.md) 与 [快速开始](/quik_start.md) 开始。

## 从这里开始

- [项目简介](/intro.md) —— AIRDC 是什么、核心特性
- [快速开始](/quik_start.md) —— 最短安装与运行路径
- [Pixi 环境与工作流](/setup/pixi.md) —— 推荐的环境管理方式
- [架构总览](/architecture/overview.md) —— 运行时结构与模块职责

## 文档分区

- **入门与使用** —— 安装、配置、遥操、采集
- **训练与推理** —— [LeRobot 训练/推理](/workflows/lerobot.md)、[AAO 仿真采集](/workflows/aao.md)
- **架构与开发** —— 架构、数据流、模块扩展、测试规范
- **运维与数据检查** —— 运行手册、数据检查、可视化、故障排查
- **参考** —— [Scripts 工具集](/reference/scripts.md)
- **产品与规划** —— 产品视角与 Persona（表达产品视角和未来工作，不直接替代代码或运行结果）

安装与采集的完整流程也可参考仓库根 [README](https://github.com/OpenGHz/AIRBOT-Data-Collection#readme)。

## 维护约定

- `docs/architecture/`、`docs/runbooks/` 记录当前代码库已经存在的结构、流程和操作方式。
- `docs/product/` 用于表达产品视角和未来工作，不直接替代代码或运行结果。
- 如果当前实现与文档冲突，应优先修正文档或代码，使两者重新对齐。
- 文档站点基于 [Docsify](https://docsify.js.org) 构建（零构建，纯 Markdown 直出）；本地预览见下文。

## 本地预览文档站点

```bash
# 方式一：docsify-cli
npm i -g docsify-cli
docsify serve docs

# 方式二：任意静态服务器
python3 -m http.server -d docs 3000
```

然后浏览器打开 http://localhost:3000 。侧边栏（`_sidebar.md`）使用绝对路径，新增页面时请同步更新。
