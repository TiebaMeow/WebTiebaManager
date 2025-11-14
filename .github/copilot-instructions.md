# WebTiebaManager AI 编程指南

欢迎来到 WebTiebaManager！本指南旨在帮助 AI 编程助手快速理解项目结构、关键模式和开发工作流，从而高效地进行协作。

## 1. 架构概述

本项目是一个基于 **FastAPI** 的异步 Web 应用，用于管理百度贴吧账号和执行自动化任务。核心组件分离在 `src` 目录下：

- **`src/api`**: FastAPI 应用层。
  - `server.py`: 主 `FastAPI` 实例。
  - `routes/`: 按功能划分的 API 路由模块。所有 API 都应遵循这种模块化结构。
  - `middlewares/`: 自定义中间件。
- **`src/core`**: 核心业务逻辑与应用生命周期管理。
  - `controller.py`: 应用的“大脑”，负责启动、关闭和协调其他服务。
  - `config.py`: 使用 `tomlkit` 管理 `WebTMData/config.toml` 配置文件。
- **`src/db` & `src/models`**: 数据库层，使用 **SQLAlchemy 2.0** (异步)。
  - `db/interface.py`: 数据库操作的统一接口。
  - `models/models.py`: SQLAlchemy 数据表模型定义。
- **`src/schemas`**: **Pydantic** 模型，用于 API 的数据校验和序列化。
- **`src/tieba`**: 封装了与 `aiotieba` 库的交互，是所有贴吧操作的出口。
- **`src/process` & `src/rule`**: 自动化任务引擎。
  - `rule/`: 定义了自动化操作的条件 (`condition.py`) 和动作 (`operation.py`)。这是一个可扩展的规则系统。
  - `process/process.py`: 实际执行规则的处理器。
- **`src/utils`**: 通用工具模块，如日志 (`logging.py`) 和缓存 (`cache.py`)。

**数据流**:
`API (api)` -> `数据校验 (schemas)` -> `核心逻辑 (core)` -> `数据库 (db)` / `贴吧操作 (tieba)` / `自动化 (process)`

## 2. 关键开发工作流

项目使用 `uv` 进行依赖管理和脚本运行。

- **安装/同步依赖**:
  ```bash
  uv sync
  ```
- **启动开发服务器**:
  ```bash
  uv run start.py --dev
  ```
- **运行测试**: 测试使用 `pytest` 和 `pytest-asyncio`。
  ```bash
  uv run pytest -q
  ```
- **代码格式化与检查**: 使用 `ruff`。
  ```bash
  # 格式化
  uv run ruff format .
  # 检查
  uv run ruff check .
  ```

## 3. 项目约定与模式

- **全异步**: 整个代码库遵循 `async/await` 模式。所有 I/O 操作（数据库、HTTP 请求）都必须是异步的。
- **依赖注入**: FastAPI 的 `Depends` 被广泛用于注入服务和依赖项，例如在 `src/api/routes/user.py` 中注入用户管理器。
- **配置管理**: 配置通过 `src/core/config.py` 中的 `Config` 类进行全局访问。不要直接读取 TOML 文件。
- **日志**: 使用 `loguru` 进行日志记录。通过 `from src.utils.logging import logger` 导入全局 logger 实例。
- **缓存**: 使用 `cashews` 库进行缓存。缓存装饰器 (`@cache.cache`) 应用于需要缓存结果的函数上。
- **模块化路由**: 在 `src/api/server.py` 中，通过 `app.include_router()` 引入各个子路由，保持主文件的整洁。

## 4. 外部依赖与集成

- **`aiotieba`**: 与百度贴吧交互的核心库。所有相关逻辑都应封装在 `src/tieba` 模块内。
- **`FastAPI`**: Web 框架。熟悉其依赖注入、Pydantic 模型和异步支持至关重要。
- **`SQLAlchemy`**: ORM 框架。本项目使用其异步特性，与 `aiosqlite` (默认) 或 `asyncpg` 配合使用。

在开始编码前，请确保你已熟悉以上约定。这将帮助你编写出符合项目风格且易于维护的代码。
