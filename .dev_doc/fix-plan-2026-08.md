# WebTiebaManager P1&P2 修复计划

- 来源：`.dev_doc/code-review-2026-08.md`（v1.5.4，分支 `dev`）
- 计划日期：2026-08-21
- 审核：`.dev_doc/fix-plan-review-2026-08.md`（2026-08-21，对本计划的独立核验；**P1-2 据此标记为不实施**）
- 对应版本基线：`6b9da75`（当前 `HEAD`；在 `11a6ecf release v1.5.4` 后已包含 `check_and_update_cache` 类型兼容修复）
- 范围：P1（P1-1、P1-3 ~ P1-6；**P1-2 本期不实施**）+ P2 全部（P2-1 ~ P2-9）。P3 不在本期范围。
- **★ P1-2 不实施声明（2026-08-21 审核后归档）**：经对本计划的独立审核，P1-2 涉及较大行为变更（默认加密方式由 plain 切换、存量配置读取语义、透明迁移）与多处实施陷阱，本期决定**不实施**并移出分步执行清单（Todo #2 状态 = `✖ 不实施`）。其现状、原方案、风险与实施陷阱详见 `.dev_doc/fix-plan-review-2026-08.md`（§A2/A3、§C1~C3、附 A.1）；恢复实施（或改用其他加固方案）前须重新确认设计决策。
- 约束：本计划仅为文档产出（本会话不修改任何代码）。实际修复在后续会话**严格按本计划分步执行**。
- 目标：每个修复点 = 一个独立执行步骤；**每完成一个修复点：① 回归验证 ② 更新下方 Todo 清单 ③ 单独提交一次 Git commit**。

---

## 一、执行约定（分步修复 / 更新 Todo / 提交）

1. **分步修复**：严格按照「Todo 清单」中列出的修复点顺序逐个实施，一次只做一个修复点，杜绝跨修复点混改。
2. **每完成一个更新 Todo 清单**：完成某修复点并验证通过后，立即回到本文件，将该修复点对应条目状态改为 `☑`、填入实际 Git 提交号，再进入下一修复点。
3. **每次完成进行一次提交**：每个修复点产出一个独立 commit（可回滚）；提交信息使用仓库既有中文风格（参照历史如 `fix: 修正评论缓存...`、`chore: ...`），建议模板如下：
   - 安全/修复：`fix: <P编号> <一句话描述>`
   - 性能：`perf: <P编号> <一句话描述>`
   - 提交信息中不强求带 `P编号`，但需能对应到修复点。
4. **回归基线**：每次提交前运行 `uv run pytest -q` 保持全绿；涉及路由/存储的修复点另做手工 API 冒烟。
5. **不自行推断设计**：第二节和第六节中的设计决策已与用户确认（**其中标注「搁置，P1-2 不实施」的条目除外**——P1-2 相关决策已失效，见 Todo #2）；第七节列出的后续项目不属于本期已确认范围。实施中若遇到本计划未约定的其他设计取舍，**暂停并询问**，不得自行选择。
6. **前端请求方式变更项**：P1-4 因涉及 WebUI（外部前端，`web-tieba-manager-front`，不在本仓库）请求方式变更，原按约定只描述现状；2026-08 已结合前端仓库代码核对并**确认鉴权方案**（见 Todo #4「修复方案（已确认）」）。后续如有新的涉及外部 WebUI 请求方式变更的修复点，仍按「先描述现状、方案单独确认」处理。

---

## 二、设计决策记录（已与用户确认，2026-08）

| 决策点 | 结论 |
|---|---|
| P1-2 密码存储方案 | **接入 bcrypt**（passlib/bcrypt + `run_in_executor` + 旧值迁移），不采用 md5 默认方案；持久化哈希不能继续通过明文密码的 32 字符校验 |
| P1-3 限流参数 | 默认：**同 IP 15 分钟窗口内失败 10 次 → 临时锁定 15 分钟**；覆盖 `/api/login`、`/api/register`、`/api/initialize/initialize` |
| P2-8 时区约定 | **统一存上海时间**（对齐现有 `now_with_tz` 语义），不采用 UTC 方案 |
| P2-2 批量确认并发策略 | **每用户 `asyncio.Lock` 串行执行**（保留 confirm 数据，失败可重试），不采用「先删 confirm 再执行」 |

> **2026-08-21 审核后更新：P1-2 本期不实施**（见 `.dev_doc/fix-plan-review-2026-08.md`）。上表及下方修订表中所有 P1-2 相关决策条目（`P1-2 密码存储方案`、`P1-2 bcrypt 持久化校验`，以及第六节 `系统密钥校验` / `用户配置密码字段`）**一并搁置**，仅作历史记录；恢复实施前需重新确认，不得直接按下列旧结论执行。

> 2026-08-21 审查修订：以下补充约束已与用户确认并纳入实施。

| 修订点 | 结论 |
|---|---|
| ~P1-2 bcrypt 持久化校验~（**已搁置，P1-2 不实施**） | 保留现有配置结构；`UserInfo` 允许读取受支持的 bcrypt 存储哈希，明文长度/字符集校验仅放在注册/初始化请求模型；系统密钥继续使用独立的常量时间比较，不因默认 bcrypt 改变登录语义。 |
| P2-4 批处理时序 | 先批量提交整个 chunk，再按原顺序广播；不得在每次广播前 flush。缓存状态批处理需在 `Spider` 仍持有原始对象的层面设计。 |
| P2-8 SQLite 时区读取 | 统一采用 datetime `TypeDecorator` 在 bind/result 两侧处理，SQLite 读回的 naive datetime 按上海时区解释。 |

---

## 三、Todo 清单（修复推进状态）

> 执行时逐行更新；`状态` 取值：`☐ 未开始` / `◐ 进行中` / `☑ 已完成` / `✖ 不实施`（不实施项需附原因，如 P1-2）；`提交号` 填实际 commit 短哈希；不实施项填 `-`。

| # | 修复点 | 状态 | 提交号 |
|---|---|---|---|
| 1 | P1-1 WebUI `assets` 路由路径穿越（读+写双重校验 + 测试） | ☑ 已完成 | `待填` |
| 2 | P1-2 密码默认明文 + bcrypt 死代码 | ✖ 不实施（原因见 `.dev_doc/fix-plan-review-2026-08.md`） | - |
| 3 | P1-3 登录/注册/初始化限流 + 初始化后丢弃 `_secure_key` | ☐ 未开始 | - |
| 4 | P1-4 资源代理端点无鉴权（**方案已确认：短时专用资源 token，前后端分别实施**） | ☐ 未开始 | - |
| 5 | P1-5 反代原样转发浏览器头（白名单转发） | ☐ 未开始 | - |
| 6 | P1-6 500 响应回显异常详情（仅 DEV 回显） | ☐ 未开始 | - |
| 7 | P2-1 `test_connection` 连接池泄漏（try/finally dispose） | ☐ 未开始 | - |
| 8 | P2-2 `confirm_many` 后台任务异常无人处理 + 并发（try/except + 每用户 Lock） | ☐ 未开始 | - |
| 9 | P2-3 `CacheCleaner` 重启边界 + `cleanup_time` 无校验 | ☐ 未开始 | - |
| 10 | P2-4 爬虫逐内容小事务（per-forum 缓冲批量写入 + 缓存批量更新） | ☐ 未开始 | - |
| 11 | P2-5 概览统计改 SQL 聚合 | ☐ 未开始 | - |
| 12 | P2-6 `ProcessObject.copy()` 携带 `data` | ☐ 未开始 | - |
| 13 | P2-7 邀请码创建死循环/竞争（while→if + 检查后写入） | ☐ 未开始 | - |
| 14 | P2-8 时区语义统一为上海时间 | ☐ 未开始 | - |
| 15 | P2-9 `reprocess` 响应 `content=None`（优先真实内容，缺失时 unknown 兜底） | ☐ 未开始 | - |

---

## 四、修复点详情

---

### Todo #1 — P1-1 未授权任意文件读取/写入（WebUI `assets` 路由路径穿越）

**优先级**：P1（最紧急，先修）。

**现状（代码现状，已核对）**：
- `src/api/routes/webui.py` `assets` 路由（约 240-262 行）：
  ```python
  cache_path = WEBUI_CACHE / path
  if cache_path.exists():
      return FileResponse(cache_path, headers=cache_headers)   # 读任意文件
  ...
  if status_code == 200:
      cache_path.parent.mkdir(parents=True, exist_ok=True)      # 写任意路径
      async with aiofiles.open(cache_path, "wb") as f:
          await f.write(content)
  ```
- `path` 直接参与 `WEBUI_CACHE / path`，**无任何归一化/校验**。该路由无鉴权。
- 后果（已由审查方隔离验证）：`/assets/../../users/<name>/config.yaml` 会解析到真实用户配置并**读出**明文 `bduss/stoken`；`/assets/../../config.toml` 等路径在反代返回 200 时还会被**写入**任意位置。
- 同文件已有可复用的防护范式：`_normalize_relative_path`（69-78 行，拒绝 `..`、`\`→`/`、`lstrip("/")`）；`resources` 路由（292-298 行，`..`/`/`开头/绝对路径 400 + `resolve(strict=True)` + `is_relative_to`）；`_read_from_local_dir`（88-92 行，`resolve(strict=True)` + `is_relative_to`）。

**修复方案**：
1. `assets` 路由入口先取 `normalized = _normalize_relative_path(path)`；`None`、空串、或形如 `assets/../../...`（含 `..`）直接 400。
2. **读路径**：仅在目标存在时使用 `(WEBUI_CACHE / normalized).resolve(strict=True)`，并校验 `is_relative_to(WEBUI_CACHE.resolve())`，不满足则 400，满足后才 `FileResponse`。
3. **写路径**：目标首次缓存时不存在，不能在 `mkdir` 前使用 `strict=True`。先以 `strict=False` 解析并校验目标及父目录位于 `WEBUI_CACHE` 内，创建父目录后重新解析父目录和目标，再执行写入；任一步发现符号链接或越界均返回 400。
4. 返回码与 `resources` 路由保持一致：非法路径统一 400 `Bad Request`。

**涉及文件**：`src/api/routes/webui.py`；新增/追加测试于 `test/`。

**测试/验证**：
- 新增路由测试（TestClient/httpx）：`/assets/../../users/x/config.yaml`、`/assets/../../config.toml`、`/assets/..%2F..` 变体返回 400；合法 `assets/...` 子路径返回正常 200/缓存。
- 手工 curl 验证无法再读出 `config.yaml`。
- 首次缓存合法但不存在的资源仍能写入并返回 200；缓存目录中的符号链接不能越界读写。
- `uv run pytest -q` 全绿。

**提交**：`fix: 修复 WebUI assets 路由路径穿越（读/写双重校验 + 测试）`

---

### Todo #2 — P1-2 密码默认明文存储 + 未使用的 bcrypt 死代码（✖ 本期不实施）

> **✖ 不实施声明（2026-08-21 审核后）**：本期**不实施** P1-2，且**不进入「一、执行约定」的分步执行与提交流程**。原因：该修复涉及较大行为变更（默认加密方式由 plain 切换、存量配置读取语义、向后兼容陷阱、透明迁移）与多处实施风险；独立审核（`.dev_doc/fix-plan-review-2026-08.md` §A2/A3、§C1~C3、附 A.1）评估为不宜在本期按原方案推进。**是否恢复实施、或改用其他加固方案，须单独确认后再纳入新计划**。
>
> 下文「现状」与「原修复方案」**仅作历史记录与再评估参考，不属于本期执行范围**。

**优先级**：P1。

**现状（代码现状，已核对）**：
- `src/api/encryt.py`：`encrypt()` 对 `encryption_method == "plain"` 直接返回原密码；`src/core/config.py` `ServerConfig.encryption_method` 默认 `"plain"`（270 行），故 `UserInfo.password` 以明文写入 `WebTMData/users/<name>/config.yaml`（`UserManager.new_user`→`write_config`，`src/utils/config.py` `write_config` 不脱敏）。
- `src/api/auth.py` 第 40 行 `pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")` 从未使用；`verify_password`（68-69 行）直接用 `encrypt(plain) == encrypted`。
- 依赖 `passlib[bcrypt]`（`pyproject.toml` 第 20 行）。
- 已确认方案：**接入 bcrypt**。

**修复方案（已确认：bcrypt + run_in_executor + 旧值迁移）**：
1. 扩展 `ServerConfig.encryption_method` 为 `Literal["plain", "md5", "bcrypt"]`，**新系统默认 `"bcrypt"`**；旧配置文件中的 `plain`/`md5` 值保留可解析，并打一次显式告警（向后兼容）。对于未写出 `encryption_method` 的旧配置，读取迁移逻辑必须按原有 plain 语义处理，不能因新模型默认值变为 bcrypt 而使旧用户全部无法登录。用户配置模型必须允许读取 `$2b$...` 等存储哈希，不能复用明文密码的最大 32 字符校验。
2. `src/api/encryt.py` 重构：
   - `hash_password(plain) -> str`：bcrypt 生成哈希（密文内置盐，旧 `encryption_salt` 字段对 bcrypt 不再参与）。
   - `verify_password(plain, stored) -> bool`：**自动识别存储格式**——`$2b$`（bcrypt）走 bcrypt 校验；否则按原 `encryption_method` 的 md5/plain 兼容校验（legacy）。
   - bcrypt 为同步 CPU 密集操作，所有用户密码校验/生成经 `await asyncio.to_thread(...)`（或共享 executor）执行，**避免阻塞事件循环**；调用方（`authenticate_user`）相应改为 async。
   - `authenticate_system` 使用独立的常量时间比较校验 `ServerConfig.key`，不得把系统密钥当作 bcrypt 用户密码处理；增加系统权限登录回归测试。
   - 删除或受控 `pwd_context` 死代码（本轮接入后即成为真正接口，不再死代码）。
3. **写入口**：新建用户唯一入口 `UserManager.new_user`（供 `initialize_post`、`register_user` 调用）在 `write_config` 前统一 `config.user.password = await hash_password(...)`；`update_config` 不触碰密码，不会重复哈希。
4. **旧值迁移**：`authenticate_user` 登录成功且存储为 legacy（plain/md5）时，**透明升级**为 bcrypt 并保存配置；**不修改 `password_last_update`**（密码语义未变，避免误杀在线的旧 token；token 失效机制留作真正的密码变更）。

**涉及文件**：`src/api/encryt.py`、`src/api/auth.py`、`src/core/config.py`、`src/user/manager.py`（写入口）、相关测试。

**测试/验证**：
- 新注册用户 config.yaml 中密码为 `$2b$...`。
- 构造旧 plain/md5 用户：可正常登录，登录后配置升级为 bcrypt，且尚未过期的 token 仍有效（`password_last_update` 未变）。
- 构造缺少 `encryption_method` 字段的旧系统配置，确认旧 plain 用户仍可登录并在迁移后补写明确的加密方式。
- 重启后可重新加载含 bcrypt 哈希的用户配置；系统密钥登录在新默认配置下仍可用。
- bcrypt 校验不阻塞：压测/观察登录接口无事件循环阻塞。
- `uv run pytest -q` 全绿。

**提交**：`fix: 接入 bcrypt 密码哈希并迁移旧值（P1-2）`

---

### Todo #3 — P1-3 登录/注册/初始化无速率限制

**优先级**：P1。

**现状（代码现状，已核对）**：
- `/api/login`（`src/api/auth.py` `login_for_access_token`，168 行起）无失败次数限制/冷却。
- `/api/register`（`src/api/routes/system.py` `register_user`，137 行起）无限制。
- `/api/initialize/initialize`（`src/api/routes/initialize.py`，60 行起）校验仅靠固定 8 字符 `secure_key`（`Server.secure_key()`，`src/api/server.py` 95-99 行），无失败次数限制；且初始化完成后 `Server._secure_key` 保留到进程结束（lifespan 关闭时才置空，`src/api/server.py` 56 行）。
- `ip_depends`（`src/api/auth.py` 165 行）已存在于各端点签名中，可直接复用取 IP。

**修复方案（已确认参数）**：
1. 新增内存滑动窗口限流器（建议 `src/utils/rate_limit.py` 或 `src/api/middlewares/`）：键为 `(ip, scope)` 或 `ip`，记录失败时间戳列表。
   - 参数：窗口 15 分钟、窗口内失败上限 10 次、命中后锁定 15 分钟。
2. 挂载点：
   - `/api/login`：认证失败时记录；达上限后返回可识别的锁定响应（429/延迟）。不存在用户时也执行一次与 bcrypt 相当的 dummy hash 校验，再叠加统一失败延迟，避免仅靠随机 `sleep` 造成仍可观测的账号存在性差异。
   - `/api/register`：注册失败（如邀请码无效）计入。
   - `/api/initialize/initialize`：`secure_key` 校验失败计入。
3. **初始化完成后立即丢弃 `Server._secure_key`**（`initialize_post` 成功返回前 `Server._secure_key = None`）。
4. 前端无需变更请求方式；仅需在登录页对 429/锁定文案做展示（可选同步项，不阻塞后端落地）。

**涉及文件**：新增限流模块；`src/api/auth.py`、`src/api/routes/system.py`、`src/api/routes/initialize.py`、`src/api/server.py`。

**测试/验证**：
- 同一 IP 连续 10+ 次错误登录/注册/初始化后返回锁定响应；正常用户不受影响。
- 初始化成功后 `Server._secure_key is None`。
- 校验不泄露账号是否存在（失败延迟一致）。
- 不存在用户与错误密码用户均执行等价的密码校验路径，避免仅依赖随机延迟。
- `uv run pytest -q` 全绿。

**提交**：`fix: 登录/注册/初始化增加 IP 滑动窗口限流，初始化后丢弃安全密钥（P1-3）`

---

### Todo #4 — P1-4 公开资源代理端点可被滥用（✅ 方案已确认：短时专用资源 token；代码待实施）

> **状态更新（2026-08 方案确认轮）**：此前本节因涉及 WebUI（外部前端）请求方式变更，仅按约定记录现状；现前端仓库 `web-tieba-manager-front` 已就位并完成代码核对，鉴权方案已与用户确认（见下「修复方案（已确认）」）。**本轮仅确认方案并更新文档，不修改任何代码**；前后端代码分别在各自仓库后续会话实施（前端对应方案见其 `.dev_doc`）。

**优先级**：P1。

**现状（代码现状，已核对）**：
- `src/api/routes/resource.py`：
  - `get_portrait`（48-59 行）：`GET /resources/portrait/{portrait}`
  - `get_image`（62-73 行）：`GET /resources/image/{hash}`
- 两端点**均无鉴权**，仅检查 `Controller.running`（否则 503）。匿名请求可驱动本机「贴吧 meow」客户端高频拉取任意 `portrait`/`hash` 图像，消耗本机到贴吧的带宽/配额，并可能使服务器 IP 被贴吧限流（429）波及正常爬虫。
- 前端现状（`web-tieba-manager-front`，已核对）：`ProcessCard.vue`（54/79-82 行）、`ConfirmList.vue`（135/351/375 行）、`DashboardHome.vue`（57 行）均以裸 `<img :src="TokenRequest.host + '/resources/...'">` 请求，**不携带 token**；`<img>` 原生请求无法携带 Authorization 头。通用 API 经 `src/lib/request.ts` 的 axios 携带 `Authorization: Bearer <access_token>`（localStorage），token 默认 7 天、全 API 权限。

**修复方案（已确认：方案 B — 短时专用资源 token 放 URL）**：
- **原则**：不给读图端点使用全权限长时效 JWT（会进入访问日志/Referer，等同泄露整个 API 凭证）；改为签发**短时效、仅授权 `/resources/*` 读图**的专用 token，前端拼进 `<img src>` 的 `?token=`。对 `<img>`/Notification `icon`/懒加载/多主机兼容性最佳，前端改动最小。
- **后端改动（`WebTiebaManager`，后续会话实施）**：
  1. 新增 `POST /resources/token`（挂 `current_user_depends`，Authorization 头认证）：签发 HS256 JWT，claims 含 `scope="resources"`、`exp`（默认 TTL 15 分钟，常量 `RESOURCE_TOKEN_TTL`，是否做成 `ServerConfig` 可配置项留待实施时确认）、`sub=<username>`、`iat`；复用现有 `secret_key` 签名，无需新增密钥管理；响应走 `BaseResponse`（data 含 `token` 与 `expires_in` 秒）。
  2. `get_portrait` / `get_image` 增加统一鉴权依赖：从 query `?token=` **或** `Authorization: Bearer` 读取资源 token；校验签名 + `scope == "resources"` + `exp` 未过 + `sub` 对应用户仍存在；失败 401。保留 `Controller.running` 503 检查；`size` 仍走 query，与 `token` 并存。普通全权限 access token 必须被拒绝。
  3. 本期**不加**每 IP 限流与后端图像缓存（已确认另行评估；P1-3 限流器落地后可复用。注：审查建议的「每 IP 限流」由此后移）。
  4. 默认**不保留匿名开关**（前后端同发版；若需灰度，是否加 `resources_require_auth` 配置项留待实施时确认）。
- **前端改动（`web-tieba-manager-front`，后续会话实施，详见其 `.dev_doc` 对应方案）**：
  1. 新增资源 token 管理模块：登录/换 token/换 host 后经 `POST /resources/token` 获取（axios 带 Bearer），内存缓存 + 过期前自动刷新，监听 `SwitchTokenEvent` 失效缓存。
  2. 新增 `portraitUrl`/`imageUrl` 帮助函数拼 `?token=`（处理好与 `?size=` 并存）。
  3. 更新 `ProcessCard.vue`、`ConfirmList.vue`（含 Notification `icon` 135 行）、`DashboardHome.vue` 的图片 `src`。

**涉及文件**：后端 `src/api/routes/resource.py`（新增 token 签发端点 + 读图鉴权依赖，鉴权逻辑可放该文件或 `src/api/auth.py`）；前端见 `web-tieba-manager-front` `.dev_doc` 方案。

**测试/验证**：
- 未携带 token、过期 token、签名错误 token、scope 不符 token、已删除用户 token、普通全权限 access token 均返回 401。
- query token 与 `Authorization` 两种合法请求均可读图；`size` 参数和 token 同时存在时仍正确传递。
- `POST /resources/token` 仅接受有效登录用户，并验证 `exp`、scope 与响应 `expires_in`。
- 前端所有列出的图片入口在登录、换 token、换 host、token 过期后均能刷新；前后端联调后再提交。

**待实施时确认项**：
- TTL 值（默认 15 分钟）与是否做成配置项；
- 是否加灰度开关；
- 后端为 `/resources/*` 关闭 uvicorn access log（对齐 P3-7 思路）以降低 URL 泄 token 面，是否纳入本次。

**本期动作**：仅确认方案并更新文档（本文件 Todo #4 节 + 前端仓库 `.dev_doc` 新建对应方案），**不修改任何代码**。

---

### Todo #5 — P1-5 反向代理原样转发浏览器请求头

**优先级**：P1。

**现状（代码现状，已核对）**：
- `src/api/routes/webui.py` `reverse_proxy`（142-165 行）第 146 行：
  ```python
  headers = {key: value for key, value in request.headers.items() if key != "host"}
  ```
  将浏览器请求的全部头（含 `Cookie`、`Referer`、自定义 `X-*`）原样透传给 `WEBUI_BASE` 指向的第三方（`MAIN_SERVER` / `WTM_WEBUI_SERVER`），存在登录态/Cookie 泄露风险。

**修复方案**：
1. 改为**白名单转发**：仅转发必要头，如 `Accept`、`Accept-Encoding`、`Accept-Language`、`User-Agent` 等。
2. 显式剥离 `Cookie`、`Authorization`、`Referer`、`Origin` 及所有 `X-*` 自定义头。

**涉及文件**：`src/api/routes/webui.py`；测试见下。

**测试/验证**：
- 构造带 `Cookie`/`Authorization`/`X-Custom` 的请求，断言第三方（mock 反代目标）收到的头中不含敏感/自定义头、含白名单头。
- `uv run pytest -q` 全绿。

**提交**：`fix: 反向代理改为白名单转发，剥离敏感浏览器头（P1-5）`

---

### Todo #6 — P1-6 500 响应回显异常详情

**优先级**：P1。

**现状（代码现状，已核对）**：
- `src/api/server.py` `global_exception_handler`（70-81 行）：
  ```python
  return JSONResponse(status_code=500, content={"message": "服务器内部错误", "detail": str(exc)})
  ```
  将 `str(exc)` 直接返回客户端，可能泄露内部路径/配置/堆栈。

**修复方案**：
1. 非 `DEV`/`DEBUG` 环境：仅返回 `{"message": "服务器内部错误"}`，去除 `detail`。
2. 完整异常信息（`exc`）保留在日志（现有 `system_logger.exception` 已记录）。
3. `DEV` 环境维持回显 `detail` 便于开发。

**涉及文件**：`src/api/server.py`。

**测试/验证**：
- 构造异步未处理异常，断言生产响应体不含异常字符串/内部路径；DEV 下保留。
- `uv run pytest -q` 全绿。

**提交**：`fix: 500 响应不再向客户端回显异常详情（P1-6）`

---

### Todo #7 — P2-1 数据库连接测试泄漏连接池

**现状（代码现状，已核对）**：
- `src/db/interface.py` `test_connection`（117-145 行）：`test_engine = create_async_engine(...)` 后仅执行 `_test()`，返回/异常/超时路径均**未 `dispose`**，PostgreSQL 场景遗留连接与连接池。

**修复方案**：
1. 在 `await asyncio.wait_for(_test(), timeout=30)` 外层加 `try/finally`，结束后 `await test_engine.dispose()`。

**涉及文件**：`src/db/interface.py`。

**测试/验证**：
- 单测：`test_connection` 返回后引擎已 dispose（可注入/断言无泄漏）；跑既有 `test_database.py` 与手动 `test_db_connection` 冒烟。
- `uv run pytest -q` 全绿。

**提交**：`fix: 数据库连接测试结束后释放连接池（P2-1）`

---

### Todo #8 — P2-2 批量确认后台任务异常无人处理 + 重复点击并发

**现状（代码现状，已核对）**：
- `src/api/routes/user.py` `confirm_operation`（161-174 行）：`pid` 为列表时（173 行）裸 `asyncio.create_task(confirm_many(...))`。
- `confirm_many`（155-158 行）内部调用 `user.operate_confirm(confirm, action)`，可能抛 `ValueError`（如账号未登录，`src/user/user.py` 368 行），但后台任务**无人捕获/记录**；重复点击会产生并发重复执行。

**修复方案（已确认：每用户 asyncio.Lock 串行执行）**：
1. 为每个 `User`（或按用户名）维护 `asyncio.Lock`，抽出统一的确认执行 helper；**单个 pid 和批量 pid 两条入口都必须经过该锁**，重复点击排队而非并发。
2. 在锁内重新读取确认项并对 pid 去重，避免请求到达前后确认状态变化以及重复 pid 导致重复执行。
3. 任务体按单个确认项加 `try/except`：捕获异常（`ValueError` 等），用 `user.logger` 记录失败并继续处理后续项目；保留失败确认以便重试。由 `.create_task` 改为创建包装了 try/except 的协程任务，杜绝未处理异常。

**涉及文件**：`src/api/routes/user.py`、`src/user/user.py`（Lock 归属）。

**测试/验证**：
- 并发触发同一用户的批量确认，断言串行执行（计数/日志）；账号未登录的批量确认不崩、有日志。
- 单个确认请求与批量确认请求并发时，断言同一确认项只执行一次。
- `uv run pytest -q` 全绿。

**提交**：`fix: 批量确认后台任务捕获异常并按用户串行化（P2-2）`

---

### Todo #9 — P2-3 缓存清理调度器重启边界 + 清理时间无校验

**现状（代码现状，已核对）**：
- `src/utils/cache.py` `CacheCleaner`：`start`（42-46 行）每次直接 `initialize()` + `setup_job()` + `start()`；服务重启（`serve()` 循环）时对同一 scheduler **重复 `start()`** 可能报错。
- `setup_job`（31-40 行）`hour, minute = map(int, cls._clear_cache_time.split(":"))` 对 `cleanup_time` 无格式校验，非法值仅被 `AsyncEvent` 异常日志吞掉，任务不按预期执行。
- `update_clear_cache_time`（54-57 行）已统一使用 `CronTrigger`（`replace_existing=True`）。

**修复方案**：
1. `start` 前检查 scheduler 状态：`running` 则先 `stop()`；已 `shutdown` 的实例不能复用，必须丢弃并重建（不能仅依赖“是否 running”区分 stopped/uninitialized）。
2. 在 `SystemConfig.cleanup_time` 的模型校验或 `apply_new` 阶段拒绝非法 `HH:MM`，避免无效配置先写盘；`update_clear_cache_time` / `setup_job` 仍需做防御性校验，非法值记录 `system_logger.error` 并保持旧调度任务。
3. 统一继续使用 `CronTrigger`。

**涉及文件**：`src/utils/cache.py`。

**测试/验证**：
- 连续两次 `start()` 不炸；非法 `cleanup_time`（如 `"25:99"`、`"foo"`）不注册任务且有告警日志；`test_cache.py` 保持通过。
- 非法配置不会写入系统配置文件；停止后再次启动会重建 scheduler，且只存在一个 `clear_cache_job`。

**提交**：`fix: 缓存清理调度器重启边界修复与清理时间校验（P2-3）`

---

### Todo #10 — P2-4 爬虫逐内容小事务写入（性能）

**现状（代码现状，已核对）**：
- `src/tieba/crawler.py` `crawl`（297-349 行）第 319-321 行：
  ```python
  # TODO 优化插入逻辑，使得content能在爬取结束后批量插入
  # note 规则判断依赖已插入数据库的内容，需要再判断前插入
  await Database.save_items([ContentModel.from_content(content)])
  ```
  循环内对每条内容独立 `save_items`（每次独立会话+commit），大帖/多吧开销显著。
- 同一循环内 `Controller.DispatchContent.broadcast(process_object)`（323 行）依赖已入库内容。
- `src/db/interface.py` `check_and_update_cache`（331-366 行）每项两次查询。

**修复方案**：
1. **per-forum 缓冲批量写入**：对当前贴吧设置内容缓冲，攒满 `chunk_size`（默认 200）后合并一次 `save_items`；每吧处理结束做一次收尾 flush。
2. **保持「规则判断前必须入库」依赖**：每个 chunk 必须先一次性提交内容，再按原抓取顺序执行 `DispatchContent.broadcast`；不得在每次 broadcast 前单独 flush，否则无法获得批量事务收益。数据库保存失败时不得广播该 chunk。
3. `check_and_update_cache` 的批量化必须在仍掌握一批原始爬虫对象的层面完成：先批量读取旧缓存、计算每项 `UpdateStatus`，再一次性更新缓存；不能只在 `Crawler.crawl` 收到已由 `Spider` 逐项判定后的 `ProcessObject` 后再声称批量查询。

**涉及文件**：`src/tieba/crawler.py`、`src/db/interface.py`。

**测试/验证**：
- 跑 `test_database_integration.py`、`test_database.py` 确认批量写入兼容（SQLite/Postgres 方言）。
- 手工冒烟：启动爬虫，观察单吧/多吧数据完整落库、规则判断正常。
- 测试广播顺序：任一广播处理器查询数据库时，对应 chunk 的全部内容已经提交；保存异常时对应内容不被广播。
- `uv run pytest -q` 全绿。

**提交**：`perf: 爬虫改为按吧缓冲批量写入并合并缓存更新（P2-4）`

---

### Todo #11 — P2-5 概览统计改 SQL 聚合

**现状（代码现状，已核对）**：
- `src/api/routes/process.py` `get_overview`（45-82 行）：将 24h 内全部 `(result_rule, is_whitelist)` 行拉回内存再计数（65-73 行），数据量大时浪费内存/带宽。

**修复方案**：
1. 改为 SQL 聚合：`count(*)` + `GROUP BY result_rule, is_whitelist`（`sqlalchemy.func`）。
2. `hint_rules` 保留现有 `distinct` 查询。
3. 响应结构（`ProcessCountData`）不变，前端无感知。

**涉及文件**：`src/api/routes/process.py`。

**测试/验证**：
- 构造样例日志数据，断言 `total`/`hit_rules`/`whitelist_rules`/`hint_rules` 与旧逻辑结果一致。
- `uv run pytest -q` 全绿。

**提交**：`perf: 概览统计改为 SQL 聚合（P2-5）`

---

### Todo #12 — P2-6 `ProcessObject.copy()` 丢弃 `data`

**现状（代码现状，已核对）**：
- `src/schemas/process.py` `ProcessObject.copy()`（43-44 行）：仅保留 `content`/`dto`，丢弃已缓存到 `data` 的中间结果（如 `user_info`、`is_thread_author`，见 `user.user.py` `handle_dispatch`→`self.process(obj.copy())`）。

**修复方案**：
1. `copy()` 携带 `data` 浅拷贝：`return ProcessObject(content=self.content, data=self.data.copy(), dto=self.dto)`，避免未来分流处理时重复 API 查询。

**涉及文件**：`src/schemas/process.py`。

**测试/验证**：
- 单测断言 `copy()` 后 `data` 保留（引用同一份浅拷贝内容）。
- `uv run pytest -q` 全绿。

**提交**：`fix: ProcessObject.copy 保留 data 浅拷贝（P2-6）`

---

### Todo #13 — P2-7 邀请码创建死代码 / 竞争

**现状（代码现状，已核对）**：
- `src/api/routes/system.py` `create_invite_code`（99-120 行）第 112 行：
  ```python
  while any(u.config.user.code == req.code for u in UserManager.users.values()):
      return BaseResponse(code=400, data="", message="邀请码已存在，请更换后重试")
  ```
  `while` 内部直接 `return`，循环无意义；且「用户配置 code」与 `CodeCache`（39 行）两端检查存在 TOCTOU 竞争。

**修复方案**：
1. `while` → `if`，保持语义并更新/澄清文案。
2. **检查后写入原子化**：用模块级 `asyncio.Lock` 包裹「双端检查 + `CodeCache.set`」，消除同一时间内创建重码的 TOCTOU 竞争。注册消费也必须在同一锁内完成“读取邀请码、创建用户、删除邀请码”，否则两个并发注册请求仍可能复用同一邀请码。

**涉及文件**：`src/api/routes/system.py`。

**测试/验证**：
- 创建已存在 code 返回 400；并发创建同一 code 时只有一个成功。
- 并发注册消费同一 code 时只有一个成功，失败请求不会留下重复用户或重新可用的邀请码。
- `uv run pytest -q` 全绿。

**提交**：`fix: 邀请码创建去除无效循环并消除 TOCTOU 竞争（P2-7）`

---

### Todo #14 — P2-8 时区语义统一为上海时间

**现状（代码现状，已核对）**：
- `src/models/models.py`：`SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")`（23 行）、`now_with_tz()`（26-27 行）返回带时区上海时间；`ContentModel`/`ProcessLogModel` 的 `DateTime(timezone=True)` 字段（107、117、159-160 行）。
- SQLite 不保留时区（读回 naive），与 `datetime.now()`（naive 本地时间）混用（如 `src/api/routes/process.py` 47 行 `since = datetime.now() - timedelta(hours=24)`），跨库（sqlite/postgres）行为不一致。
- 已确认方案：**统一存上海时间**。

**修复方案**：
1. 约定：入库与比较统一使用上海时区（`SHANGHAI_TZ`），读取侧按上海时区解释。
2. 统一阈值来源：`process.py` 的 `since` 改为 `now_with_tz()`（或等价同源上海时间）；`src/db/interface.py` `clear_contents_before`（369-376 行）的清理边界用同源上海时间（与 `last_update` 清理边界一致）。
3. 「存上海时间」语义说明：入库前保证 `tzinfo=SHANGHAI_TZ`；通过 datetime `TypeDecorator` 在 SQLite 读回时重新附加 `SHANGHAI_TZ`，不再让 `.timestamp()` 按服务器本地时区解释。
4. 文档注明与 `last_update` 清理边界的时区一致性；**不迁移既有历史数据语义**（仅统一新写入与比较逻辑）。

**涉及文件**：`src/models/models.py`、`src/api/routes/process.py`、`src/db/interface.py`、文档。

**测试/验证**：
- 同一时刻跨 sqlite/postgres 写入+查询的时间比较一致；overview/search/清理边界阈值同源。
- SQLite 读回的 `create_time`、`last_update`、`process_time` 均带上海时区语义，序列化出的 Unix 时间戳与 PostgreSQL 一致。
- `uv run pytest -q` 全绿。

**提交**：`fix: 统一时区语义为上海时间，查询阈值同源（P2-8）`

---

### Todo #15 — P2-9 `reprocess` 响应 `content=None`

**现状（代码现状，已核对）**：
- `src/api/routes/process.py` `reprocess_content`（238-282 行）：存在 `context` 时（271-278 行）返回 `ProcessContextData(content=None, ...)`，前端按 `ProcessContextData` 渲染可能崩溃（对比 `get_process_detail` 使用 `content or make_unknown_content(...)`，215-224 行）。
- 前端为外部 WebUI，**本修复不改请求方式、不破坏响应结构**。

**修复方案**：
1. `reprocess_content` 的 `context` 分支优先返回函数前面已成功读取的真实 `content`；只有未来改为延迟读取且内容确实不存在时，才使用 `make_unknown_content(request.pid, context[0].tid)` 作为防御性兜底。不得用 unknown 内容覆盖可用的标题、正文、图片和作者信息。

**涉及文件**：`src/api/routes/process.py`。

**测试/验证**：
- `reprocess` 有 `context` 时响应包含真实内容；内容不可用的独立场景才返回 unknown 兜底；手工冒烟前端详情弹窗不崩。
- `uv run pytest -q` 全绿。

**提交**：`fix: reprocess 响应优先返回真实内容并保留 unknown 兜底（P2-9）`

---

## 五、回归基线

- 基线：当前 HEAD `6b9da75`，`uv run pytest -q` 全绿（`23 passed, 1 skipped`；覆盖 `test_cache` / `test_database` / `test_event` / `test_database_integration`）。
- 每个修复点完成后：先回归测试，再更新 Todo 清单，再单独提交。
- 全部完成后的最终验收：整份 Todo 清单 `☑`、全部修复点有独立 commit、`uv run pytest -q` 全绿、手工 API 冒烟通过。

## 六、补充设计决策（已与用户确认，2026-08-21）

| 决策点 | 结论 |
|---|---|
| ~系统密钥校验~（搁置，P1-2 不实施） | 保持独立的常量时间比较；bcrypt 仅用于用户密码。 |
| ~用户配置密码字段~（搁置，P1-2 不实施） | 保留现有配置结构；允许读取 bcrypt 哈希，明文校验仅由注册/初始化请求模型负责。 |
| 爬虫批处理时序 | 整个 chunk 提交成功后，再按原顺序广播。 |
| SQLite datetime 适配 | 使用 datetime `TypeDecorator` 在 bind/result 两侧统一按上海时区处理。 |

## 七、待定 / 后续补全项

| 项 | 状态 | 说明 |
|---|---|---|
| P1-4 资源代理鉴权 | 方案已确认（短时专用资源 token，方案 B） | 前后端分别在各自仓库实施；每 IP 读图限流与后端图像缓存另行评估 |
| P1-3 登录锁定前端文案 | 可选同步 | 前端仅展示 429/锁定文案，不改变请求方式，不阻塞后端落地 |
| P1-2 密码哈希方案 | 本期不实施（✖ 搁置） | 原因与实施陷阱见 `.dev_doc/fix-plan-review-2026-08.md`（§A2/A3、附 A.1）；是否恢复实施或改用其他方案另行确认；若恢复，再评估 bcrypt 轮数 / 是否加 pepper 等加固项 |
| P3 各项 | 本期不做 | 排入后续迭代，改动时补对应单测 |

---

> 本计划为文档产出，本次会话未修改任何源码。后续会话按「一、执行约定」逐修复点实施。
>
> **2026-08-21 审核后更新**：P1-2 已标记为 `✖ 不实施`（含其设计决策条目一并搁置），不进入执行流程；本计划其余各项的分析（核实结论 + 修复缺陷/建议）见 `.dev_doc/fix-plan-review-2026-08.md`。
