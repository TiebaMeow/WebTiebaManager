# WebTiebaManager 代码审查报告

- 版本：v1.5.4（当前分支 `dev`）
- 日期：2026-08
- 范围：`src/` 全部源码（约 7000 行）+ `test/` + 配置/依赖
- 方法：逐文件阅读 + 隔离路径运算/静态验证（未改动任何源码）

---

## 摘要

发现 1 个高危安全问题（未授权任意文件读取）、5 个中高安全/健壮性问题、8 个正确性/性能问题、9 个优化/整洁项。按 P[x]（P1 最紧急）排列。

---

## P1 安全 / 高风险（建议尽快修复）

### P1-1 未授权任意文件读取（WebUI 静态资源路由路径穿越）

- **风险**：`assets` 路由对 URL 传入的 `path` 未做归一化/校验，直接 `WEBUI_CACHE / path` 后 `exists()` + `FileResponse` 返回。已用隔离计算验证：`/assets/../../users/<name>/config.yaml`、`/assets/../../config.toml` 会解析到 `BASE_DIR/users/.../config.yaml` 等真实文件。用户 `config.yaml` 中 `forum.bduss/stoken` 为**明文**（`User.save_config` → `write_config` 不脱敏），等于可被未经认证的请求直接窃取账号 Cookie/STOKEN。该路由无鉴权。
- **相关文件**：`src/api/routes/webui.py`（`assets` 路由 `cache_path = WEBUI_CACHE / path` 第 251 行）
- **修复方向**：复用现有 `_normalize_relative_path`（拒绝 `..`/绝对路径），并在读取/回写前加 `resolve(strict=True)` + `is_relative_to(WEBUI_CACHE)` 双重校验（与 `_read_from_local_dir`、`resources` 路由一致）；对 `..`、`\`、以 `/` 开头的路径直接 400。补充对应路由测试。

### P1-2 密码默认明文存储 + 未使用的 bcrypt 死代码

- **风险**：`ServerConfig.encryption_method` 默认 `"plain"`，`encrypt()` 直接返回原密码；用户密码以明文写入 `WebTMData/users/<name>/config.yaml`。`auth.py` 中 `pwd_context = CryptContext(schemes=["bcrypt"])` 定义了但从未使用（依赖 `passlib`/`bcrypt` 亦因此几乎无效）。
- **相关文件**：`src/core/config.py`（ServerConfig）、`src/api/encryt.py`、`src/schemas/user.py`（UserInfo.password）、`src/api/auth.py`（第 40 行死代码）
- **修复方向**：默认改为 `md5`（保留明文仅为向后兼容并显式告警），或启用现有 bcrypt：`encrypt`/`verify_password` 统一走哈希；密码变更时用 `password_last_update` 失效旧 token（机制已存在）。若启用 bcrypt，口令校验为同步操作需 `run_in_executor` 避免阻塞事件循环。删除 `pwd_context` 死代码或真正接入，并保留旧值迁移逻辑（`apply_new` 已处理盐值）。

### P1-3 登录/注册/初始化无速率限制（可暴力破解）

- **风险**：`/api/login`、`/api/register`、`/api/initialize/initialize`（初始化密钥固定 8 字符）均无失败次数限制/冷却。
- **相关文件**：`src/api/auth.py`（`login_for_access_token`）、`src/api/routes/system.py`（`register_user`）、`src/api/routes/initialize.py`
- **修复方向**：基于 `ip_depends` 做内存滑动窗口限流（同 IP 每窗口 N 次失败后临时锁定并混合登录延迟，不泄露账号是否存在）；初始化完成后立即丢弃 `Server._secure_key`（当前保留到进程结束）。

### P1-4 公开资源代理端点可被滥用

- **风险**：`/api/resources/portrait`、`/api/resources/image` 无鉴权（仅 `Controller.running` 检查），可驱动匿名贴吧客户端高频请求任意 portrait/image hash，消耗本机到贴吧的带宽/配额，可能使服务器 IP 被贴吧限流（429）波及正常爬虫。
- **相关文件**：`src/api/routes/resource.py`（`get_portrait`/`get_image`）
- **修复方向**：至少要求有效 token（`current_user_depends`），并叠加每 IP 速率限制；写成由已登录前端按需请求即可（前端已有登录态）。

### P1-5 反向代理原样转发浏览器请求头给第三方服务器

- **风险**：`reverse_proxy` 将 `request.headers`（除 `host`）整体透传给 `WEBUI_BASE` 指向的第三方（`MAIN_SERVER`/`WTM_WEBUI_SERVER`），会泄露浏览器携带的 `Cookie`、`Referer` 乃至自定义头；若未来使用 Cookie 会话将直接泄露登录态。
- **相关文件**：`src/api/routes/webui.py`（`reverse_proxy` 第 146 行）
- **修复方向**：改白名单转发（`Accept`、`Accept-Encoding`、`User-Agent` 等必要头），显式剥离 `Cookie`/`Authorization`/`X-*` 自定义头。

### P1-6 500 响应回显异常详情

- **风险**：全局异常处理器把 `str(exc)` 直接放进给客户端的响应（`detail`），内部路径/配置/堆栈信息可能泄露。
- **相关文件**：`src/api/server.py`（`global_exception_handler` 第 80 行）
- **修复方向**：生产环境只返回通用消息并记日志（日志中保留 `exc`）；仅 `DEV/DEBUG` 下回显详情。

---

## P2 正确性 / 健壮性 / 性能

### P2-1 数据库连接测试泄漏连接池

- **问题**：`Database.test_connection` 创建的 `test_engine` 从未 `dispose`，PostgreSQL 场景会遗留连接/池。
- **相关文件**：`src/db/interface.py`（`test_connection` 第 126 行）
- **修复方向**：在 `_test` 结束（含异常/超时）后 `await test_engine.dispose()`（用 `try/finally`）。

### P2-2 批量确认操作后台任务异常无人处理

- **问题**：`confirm_many` 以 `asyncio.create_task` 裸跑，内部 `operate_confirm` 可能抛 `ValueError`（账号未登录）但无人捕获/记录；且重复点击会产生并发重复执行。
- **相关文件**：`src/api/routes/user.py`（`confirm_many` 第 155 行、`confirm_operation`）
- **修复方向**：任务内 `try/except` 记录失败（`user.logger`），对同一 pid 加内存级互斥（简单 `asyncio.Lock` per user，或先删 confirm 再执行以幂等）；结束时把结果通过日志/确认列表反馈。

### P2-3 缓存清理调度器重启边界 + 清理时间无校验

- **问题**：`CacheCleaner.start` 在服务重启（走 `serve()` 循环）时对同一 scheduler 再次 `start()`，且 `setup_job` 依赖 `replace_existing`；`cleanup_time` 解析 `int(x)` 无格式校验，非法值仅靠 `AsyncEvent` 的异常日志吞掉，任务不会按期望执行。
- **相关文件**：`src/utils/cache.py`（`CacheCleaner`）
- **修复方向**：`start` 前判断 `running`/`shutdown` 状态，必要时重建 scheduler；`update_clear_cache_time`/`setup_job` 对 `HH:MM` 做校验（非法则告警并跳过），统一用 `CronTrigger` 替换。

### P2-4 爬虫逐内容小事务写入（性能）

- **问题**：`Crawler.crawl` 在循环内对每条内容单独 `Database.save_items(...)`（每次独立会话+commit），大帖/多吧时开销显著；代码内已有 TODO 注明。
- **相关文件**：`src/tieba/crawler.py`（第 319-321 行）
- **修复方向**：批量攒满 `chunk_size`（如 200）或每吧结束后合并 `save_items`；同时 `check_and_update_cache` 每项两次查询也可合并为批量 `select ... where pid in (...)` + 一次 `update`。保持“规则判断前必须入库”的依赖（可用 per-forum 缓冲 + 判断前 flush），并跑既有 `test_database_integration` 保证兼容。

### P2-5 概览统计在 Python 侧聚合

- **问题**：`/api/process/overview` 把 24h 内全部行拉回再数；数据量大时浪费内存/带宽。
- **相关文件**：`src/api/routes/process.py`（`get_overview`）
- **修复方向**：改 SQL 聚合（`count` + `GROUP BY result_rule, is_whitelist`），`hint_rules` 保留 `distinct` 查询。

### P2-6 `ProcessObject.copy()` 丢弃 `data`

- **问题**：`copy()` 只保留 `content`/`dto`，会丢弃已缓存到 `data` 的中间结果（如 `user_info`、`is_thread_author`）。
- **相关文件**：`src/schemas/process.py`（`ProcessObject.copy` 第 43 行）
- **修复方向**：`copy(deep=False)` 时带上 `data` 的浅拷贝（`self.data.copy()`），避免未来分流处理时重复 API 查询。

### P2-7 邀请码创建逻辑死代码 / 竞争

- **问题**：`create_invite_code` 的 `while any(...)` 内部直接 `return`，循环无意义；两端（用户配置 code 与 CodeCache）存在 TOCTOU 竞争。
- **相关文件**：`src/api/routes/system.py`（第 112 行）
- **修复方向**：改为先检查再写入（必要时加锁或唯一性约束）；`while` 改为 `if`，更新文案。

### P2-8 时区语义 sqlite / postgres 不一致

- **问题**：`DateTime(timezone=True)` 配 SQLite 不保留时区（读回 naive），与 `datetime.now()`/`SHANGHAI_TZ` 混用，跨库行为不一致（目前 `attached_content`、`search` 的 `process_time` 比较基本自洽，但换库会变）。
- **相关文件**：`src/models/models.py`（`now_with_tz`/`SHANGHAI_TZ`）、`src/api/routes/process.py`、`src/db/interface.py`
- **修复方向**：统一约定存 UTC（或统一上海时间），入库前转 `timezone.utc`，查询阈值同源；文档注明与 `last_update` 清理边界。

### P2-9 `reprocess` 响应 `content=None`

- **问题**：`/api/process/reprocess` 在无 `context` 时 `content=None`，前端按 `ProcessContextData` 渲染可能崩溃。
- **相关文件**：`src/api/routes/process.py`（第 271-278 行）
- **修复方向**：`content` 缺省时用 `make_unknown_content(pid)`，或返回明确的 404/空结构并同步前端契约。

---

## P3 优化 / 整洁

### P3-1 规则评估

- **问题**：`Processer.resolve` 用 `condition_identifier.index(identifier)` 拼装，O(n²)；`RuleLogic.priority_groups` 计算了但不参与剪枝（`Rule.check` 仍逐个评估后 `evaluate_expression`）。
- **相关文件**：`src/process/process.py`（第 144 行）、`src/core/config.py`（`RuleLogic`）、`src/rule/rule.py`
- **修复方向**：`resolve` 用 `dict` 记录 id→index；`Rule.check` 对 `And` 的 necessary 条件先查，失败即短路（注意保持 `step_status` 语义）。

### P3-2 数据库索引

- **问题**：`process_log` 查询以 `(user, process_time)` 排序、`(user, result_rule)` 过滤，现仅有单列索引。
- **相关文件**：`src/models/models.py`（`ProcessLogModel`）
- **修复方向**：增加 `Index("ix_process_log_user_time", "user", "process_time")` 与 `(user, result_rule)` 复合索引（SQLite/Postgres 均支持，需在 `Base.metadata.create_all` 前保证索引定义；为已有库用 `create`/迁移脚本补充）。

### P3-3 WebUI zip 每次请求重新打开解压

- **问题**：`_read_from_zip` 每个资源请求都 `ZipFile` 打开 + 读取；可静态缓存 zip 内的 `name→offset` 索引。
- **相关文件**：`src/api/routes/webui.py`
- **修复方向**：进程内维护 `{zip_path: {entry_name: (offset, length)}}` 索引（zip 元数据换取 `read` 定位），`zip_path` mtime 变化时重建。

### P3-4 插件 zip 解压路径穿越防护

- **问题**：`zipfile.extractall` 对含 `../` 条目的 zip 存在 zip-slip 风险（当前插件为可信来源，但属加固点）。
- **相关文件**：`src/core/plugin.py`（第 82、157 行）
- **修复方向**：解压前遍历 `namelist()` 校验每条相对路径归一化后仍在目标目录内，非法条目拒绝；同样适用于 `load_lib_from_zip`。

### P3-5 死代码 / 未用依赖

- **问题**：`pwd_context`、以及暂未使用的 `passlib` 依赖（若不接入 bcrypt 应从 `pyproject.toml` 移除）；`tools.py` 的 `Mosaic.has_mosaic` 等未见调用。
- **相关文件**：`src/api/auth.py`、`pyproject.toml`
- **修复方向**：按 P1-2 决定接入或删除；用 `uv remove` 清理未用依赖（`numpy`/`opencv-python-headless` 在 `resource.py` 在用，保留）。

### P3-6 可测性（`src.control` 替身）

- **问题**：`test/test_cache.py`、`test/test_database.py` 通过注入假 `src.control` 模块绕过对 `src.core.controller.Controller` 的强依赖；说明 `utils/cache.py`、`db/interface.py` 对全局单例耦合较重。
- **相关文件**：`src/utils/cache.py`、`src/db/interface.py`、`test/`
- **修复方向**：可选 —— 把 `Controller.config` 等通过可注入依赖访问，逐步消除测试替身 hack；不阻塞，列为技术债。

### P3-7 SSE 日志 token 走 URL query

- **问题**：`/api/log/realtime`、`/api/system/log/realtime` 把 JWT 放在 query，易进代理/访问日志。
- **相关文件**：`src/api/routes/log.py`
- **修复方向**：改 `Authorization` 头（SSE 可用 fetch EventSource 类库/自实现）；若前端受限，至少对该日志路径关闭 uvicorn access log。

### P3-8 阻塞调用

- **问题**：`shutil.rmtree`（删用户/重建）在事件循环线程执行，大用户目录会阻塞；`EtaSleep.sleep_sync` 有 `time.sleep`（当前仅同步场景）。
- **相关文件**：`src/user/manager.py`、`src/user/user.py`、`src/core/plugin.py`
- **修复方向**：`delete_user`/`new_user(force)` 用 `asyncio.to_thread(shutil.rmtree, ...)`。

### P3-9 其他小项

- `startup` 弹窗：`src/api/server.py` 内重复 `import asyncio`；`RUN`/`dev_run` 分支可简化。
- 清理老化缓存时 `ExpireCache.expire` 只删无 TTL 键，逻辑与命名注释出入，补文档。
- 反代 `index`/`favicon` 无超时参数的 `session.get`（依赖 aiohttp 全局默认 5min）可显式给 `ClientTimeout`。
- 测试仅覆盖 cache/db/event，核心规则引擎（`RuleLogic`、`Processer.resolve`、crawler 分页）无单测 → 后续按 P2-4/P3-1 改动时优先补。

---

## 修复顺序建议 / 验收标准

1. 先修 P1-1（安全）→ 追加 `test` 或手工 curl 验证 `..` 请求返回 400 且无法读到 `config.yaml`。
2. 再修 P1-2~P1-4、P1-6（鉴权/加密/限流/异常回显）→ 验证旧配置可迁移、无密钥的用户不可提权、限流生效。
3. P2 各项按“性能-写入正确性-资源回收”排序 → 以现有 `uv run pytest -q` 全绿 + 手工 API 冒烟为回归基线。
4. P3 作为技术债排入后续迭代，改动时补对应单测（规则引擎、`resolve`、爬虫批量写入）。

---

## 假设与说明

- 本仓库为自托管管理工具、插件为可信来源，因此 P3-4/P1-5 属加固而非紧急；不改变既有 API 对外契约（P2-9 需同步前端，其余保持响应结构不变）。
- 本报告仅为审查结论，未改动任何源码。
