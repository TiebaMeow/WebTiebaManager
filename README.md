
<div align="center">

# WebTiebaManager

_基于 [aiotieba](https://github.com/lumina37/aiotieba) 的贴吧吧务管理 / 自动化工具_

</div>

## 目录

- [概述](#概述)
- [特性](#特性)
- [快速开始](#快速开始)
- [Windows EXE 版](#windows-exe-版)
- [部署前准备](#部署前准备)
- [开发与测试](#开发与测试)
- [FAQ](#faq)
- [反馈与参与](#反馈与参与)

## 概述

WebTiebaManager (WTM) 旨在提供一个可视化、可扩展的贴吧多账号管理与自动化执行平台，适用于：

- 多账号集中管理
- 内容/违规检查 自动化
- 后续自定义扩展 (二次开发 / 接口集成)

## 特性

- **Web 界面响应式**：PC / 手机均可管理
- **多账号支持**：并行登录多个百度账号
- **任务自动化**：后续可扩展批量处理逻辑
- **可扩展 API**：暴露内部能力便于二次开发
- **跨平台运行**：推荐 Python 环境，亦提供 Windows EXE

## 快速开始

> 如果你只是想快速跑起来，按下面 3 步即可；若使用 EXE 请见 [Windows EXE 版](#windows-exe-版)。

### 1. 克隆或下载

```bash
git clone https://github.com/TiebaMeow/WebTiebaManager.git
cd WebTiebaManager
```

也可在 Release 中下载 zip 后解压。

### 2. 安装依赖

项目使用 [`uv`](https://docs.astral.sh/uv/) 管理依赖：

```bash
uv sync
```

若未安装 `uv`，请参考官方[安装文档](https://docs.astral.sh/uv/getting-started/installation/)（[中文镜像](https://hellowac.github.io/uv-zh-cn/getting-started/installation/)）。

### 3. 启动

```bash
uv run start.py
```

首次启动日志示例：

```log
2025-09-25 11:53:30 [INFO] system | WebTiebaManager v1.0.0[croissant]
2025-09-25 11:53:30 [WARNING] system | 初始化密钥: KFCvme50
2025-09-25 11:53:30 [WARNING] system | 检测到程序未初始化，请完成初始化
2025-09-25 11:53:30 [INFO] system | 访问 http://localhost:36799 进行管理
2025-09-25 11:53:30 [INFO] system | 正在初始化数据库...
2025-09-25 11:53:30 [INFO] system | 数据库类型: sqlite
2025-09-25 11:53:30 [INFO] system | 加载 0 个用户
2025-09-25 11:53:30 [INFO] system | 数据库初始化完成
2025-09-25 11:53:30 [INFO] system | 系统开始运行
```

按日志提示使用浏览器访问 <http://localhost:36799>，并使用“初始化密钥”完成初始化。完成后建议手动重启一次以确保环境稳定。

## Windows EXE 版

若你不想安装 Python，可使用打包好的 Windows 版本，参见独立文档：[`install_windows.md`](./install_windows.md)。

> 注意：EXE 受运行环境影响较大，如出现问题优先尝试 Python 部署。

## 部署前准备

| 必要条件 | 说明 |
|----------|------|
| 7*24 运行设备 | 家用主机 / NAS / 服务器均可 |
| Python ≥ 3.12 | 官方下载或使用发行版包管理器 |


## 开发与测试

### 本地开发建议流程

```bash
git clone https://github.com/TiebaMeow/WebTiebaManager.git
cd WebTiebaManager
uv sync
uv run start.py --dev
```

### 运行测试

```bash
uv run pytest -q
```

### 代码格式化 / 静态检查

```bash
uv run ruff format .
uv run ruff check .
```

## FAQ

### 其它

如遇异常请附：复现步骤 + 关键日志 截图，在 [Issues](https://github.com/TiebaMeow/WebTiebaManager/issues) 提交。

## 反馈与参与

- 问题 & 建议：提交 Issue
- 贡献代码：Fork 后提 PR（建议先开 Issue 讨论）
- 未来改进方向：插件化条件 / 可视化监控 / API 调用支持

---

如果本项目对你有帮助，欢迎 Star 支持！
