# WebTiebaManager 修复计划审核报告（fix-plan-2026-08）

- 审核对象：`.dev_doc/fix-plan-2026-08.md`（15 个 P1/P2 修复点）
- 核验基线：`HEAD 6b9da75`（`uv run pytest -q` = `23 passed, 1 skipped`，与计划一致）
- 日期：2026-08-21
- 方法：逐文件阅读 `src/` 实际代码 + 关键行为实测（APScheduler 重启、路径运算、测试套件）
- 结论先行：
  1. **15 个错误全部真实存在**，计划引用的文件/行号逐一核对无误，无虚报。
  2. **修复方案整体方向正确**，未发现"计划本身直接引入可利用新漏洞"的写法；但有 **1 处结构性缺陷（A1：P2-4 缓存批量的实现设计未落地）**、**1 处修复后新增泄密面且被延后处理（B1：P1-4 URL token）**、以及 **P1-2 相关多处实施陷阱**（A2/A3、C1~C3——已据此将 P1-2 标记为不实施）。
  3. 计划对源审查文档做了**两处必要纠正**（P2-9 分支描述、P1-4 路由路径），相符代码。

---

## 一、错误真实性核验（15 项全部为真）

| 修复点 | 是否真实 | 关键证据（文件:行号 = 实际代码） |
|---|---|---|
| P1-1 assets 路径穿越 | ✅ 真实 | `webui.py:251` `cache_path = WEBUI_CACHE / path` 无归一化；读 `:252-253` FileResponse、写 `:258-260`。路径实测：`cache/webui` + `../../users/x/config.yaml` → `BASE_DIR/users/x/config.yaml`（含明文 bduss/stoken，`write_config` 不脱敏）。路由无鉴权。 |
| P1-2 明文密码 + bcrypt 死代码 | ✅ 真实 | `config.py:270` 默认 `"plain"`；`encryt.py:6-11` plain 直返；`schemas/user.py:29` 明文入库；`auth.py:40` `pwd_context` 仅定义无调用；`pyproject.toml:20` `passlib[bcrypt]`。 |
| P1-3 无速率限制 | ✅ 真实 | `auth.py:168`、`system.py:137`、`initialize.py:60` 均无失败次数限制；`Server._secure_key` 仅 lifespan 关闭置空（`server.py:56`），运行期恒存。 |
| P1-4 资源端点无鉴权 | ✅ 真实 | `resource.py:48-59 / 62-73` 仅 `Controller.running` 检查，走共享匿名 meow 客户端（`utils/anonymous.py:44-50`）。 |
| P1-5 反代全头转发 | ✅ 真实 | `webui.py:146` `if key != "host"` 全量透传（含 Cookie/Referer/Authorization/所有 X-*，含 X-Forwarded-For）。 |
| P1-6 500 回显 `str(exc)` | ✅ 真实 | `server.py:80` `detail: str(exc)`。 |
| P2-1 test_connection 池泄漏 | ✅ 真实 | `interface.py:126-145` 创建 `test_engine` 后无任何 `dispose`。 |
| P2-2 批量确认异常 + 并发 | ✅ 真实 | `user.py:173` 裸 `create_task(confirm_many)`；`confirm_many:155-158` 无 try/except；`operate_confirm`（`user.py:368`）抛 `ValueError`；同一批内同 pid 会取到同一 confirm 执行两次。 |
| P2-3 调度器重启 + 时间无校验 | ✅ 真实 | `cache.py:42-46 / 31-40`；`config.py:341` 无校验。**实测**：`AsyncIOScheduler.shutdown()` 为 `@run_in_event_loop` 延迟生效，shutdown 后瞬间 `running` 仍为 `True`，此时 `start()` → `SchedulerAlreadyRunningError`；重复 shutdown → 事件循环回调中 `SchedulerNotRunningError`。`setup_job` 的 ValueError 被 `event.py:32` exception_logger 吞掉。 |
| P2-4 逐内容小事务 | ✅ 真实 | `crawler.py:321` 循环内每条 `save_items`（独立会话+commit）；`check_and_update_cache`（`interface.py:331-366`）每项 select+update 两次查询。 |
| P2-5 Python 侧聚合 | ✅ 真实 | `process.py:51-56` 拉回全行于 `:65-73` Python 计数。 |
| P2-6 copy 丢 data | ✅ 真实 | `schemas/process.py:43-44` 仅 `content/dto`。 |
| P2-7 while→return 死代码 + TOCTOU | ✅ 真实 | `system.py:112-115` `while...return` 等价 `if`；create（用户+CodeCache 双端）与 register 消费（`:141-158`）存在竞争。 |
| P2-8 时区不一致 | ✅ 真实 | `models.py:23/26-27/107/117/159-160` 与 `process.py:47` `datetime.now()`（naive）、`crawler.py:39` `datetime.now(Asia/Shanghai)` 混用，跨 sqlite/postgres 不一致。 |
| P2-9 reprocess content=None | ✅ 真实 | `process.py:271-278` **有** context 分支 `content=None`。（源审查误写为"无 context 时"，本计划已纠正。） |

---

## 二、修复方案缺陷分析

### A. 高关注度缺陷（可能"未真实修复"或破坏功能）

**A1. P2-4 缓存批量（#3）没有给出可实施设计——计划中最弱一环。**
计划的约束描述（"不能只在 `Crawler.crawl` 收到已由 `Spider` 逐项判定后的 `ProcessObject` 后再声称批量查询"）**正确**，但未给出替代实现。`Spider.crawl` 的控制流（`crawler.py:155/201/218`）要求 thread 的 `updated` 状态在决定是否抓取其 post 之前先拿到，因此"先批量 SELECT 旧缓存 → 计算 status → 再批量 UPDATE"只能写成**两阶段**（批量 SELECT → 逐项判定 → 批量 UPDATE），且 UPDATE 与逐 thread 继续抓取的顺序互相牵扯。若实施者只在 Crawler 层攒 `ContentModel` 批量 `save_items`（这半部分可行），#3 未落地；若强行在不妥粒度批量，可能破坏"规则判断前必须入库"→ 广播回归。
**建议**：把 #3 明确写成 "Spider 层两阶段批量缓存处理" 的设计，并以计划中已列的广播时序测试（任一广播处理器查库可见 chunk 全部内容 / 保存失败不广播）作为红线。

**A2. P1-2 旧配置默认值遮蔽陷阱——升级后可能全量锁死旧用户。**
计划要求"未写出 `encryption_method` 的旧配置按 plain 处理"。但新模型默认值改成 `"bcrypt"` 后，pydantic 对缺失键**静默填入默认值**，解析结果无法区分"旧配置没写"与"新配置故意不写"。实现者必须在 **load 时检查原始 dict 键是否存在**（`"encryption_method" not in raw` → 按 plain 迁移并由迁移逻辑补写），否则升级后全部旧明文用户登录失败——正是计划想避免的回归。计划写了意图未写机制，属高风险实施点。

**A3. P1-2 `authenticate_system` 的坑（计划已正确规避，实现时务必守住）。**
现状 `authenticate_system`（`auth.py:88`）走 `verify_password(key, Controller.config.server.key)`。接入 bcrypt 后，`encrypt()`（`encryt.py:6-11`）只有 plain/md5 两分支，对 `"bcrypt"` 会 `raise ValueError`；若不把系统密钥改为独立常量时间比较，**系统登录会 500**（或回退 legacy 后语义错误）。计划明确要求"系统密钥独立常量时间比较、不得当 bcrypt 用户密码处理"，方向正确；实现时应确保 `encrypt()` 不被任何 bcrypt 路径调用到（建议对 `"bcrypt"` 显式降级或删除），避免潜伏 500。

### B. 中等缺陷 / 覆盖缺口

**B1. P1-4 "token 放 URL"会新增泄密面，却被标注为"待实施时确认"延后。**
`?token=` 进 query string 后会进入：① uvicorn access log（若开）、② 浏览器历史、③ 反向代理明文日志。计划把"为 `/resources/*` 关闭 access log（对齐 P3-7）"列为可选延后项——**这是本次修复自带的副作用，应纳入 P1-4 必做范围而非延后**。另注：授权后"任意登录用户拉任意 portrait/hash"的滥用面仍在（匿名收敛到登录用户），每 IP 读图限流被显式延后——可接受，但应记为残留风险，勿误以为彻底解决。

**B2. P2-5 SQL 聚合的 NULL 语义未点明。**
现逻辑（`process.py:65-73`）中 `is_whitelist is None` 的行计入 `total`，但**不进 hit 也不进 whitelist**。`GROUP BY result_rule, is_whitelist` 在 SQLite/Postgres 会把 `(rule, NULL)` 单独成组；若采用"两个 WHERE（=true / =false）聚合 + `total=count(*)`"则一致；若用单一 GROUP BY 再在 Python 拆，必须显式丢弃 NULL 组（`=true/false` 本就排除 NULL）。现有"与旧逻辑一致"的测试断言必须覆盖 None 行。

**B3. P2-8 TypeDecorator 与"不迁移历史数据"存在张力。**
TypeDecorator 读回时对 SQLite 所有行统一附 `SHANGHAI_TZ`，历史 naive 行也会被**按上海时区重新解释**——若服务器此前运行在非上海时区，历史 `process_time`/`last_update` 的 `.timestamp()` 输出整体漂移。计划说"不迁移既有数据语义"，但类型装饰器本身即在改变旧行语义。需明确：要么接受（默认一直上海部署则无差异），要么一次性转换存量行。

**B4. P1-3 对 `TRUSTED_PROXIES`/X-Forwarded-For 的依赖未被提及。**
`get_ip` 取 `request.client.host`，`TrustedForwardMiddleware`（`middlewares/forwarded_ip.py:27-36`）**仅当直连 peer 在 `TRUSTED_PROXIES`（默认仅 `127.0.0.1`，constants.py:16）内才信任 XFF**。若部署在未配置 `WTM_TRUSTED_PROXIES` 的反代后，所有客户端共享 proxy IP → 一次爆破即全局锁定（自伤 DoS）；若信任链配置松弛，攻击者可伪造 XFF 轮换 IP **绕过限流**。计划应把"限流键采用中间件处理后的 client IP + 明确 WTM_TRUSTED_PROXIES 配置要求"写入实施约束；同时内存滑动窗口应规定裁剪策略（防长运行内存增长）。

**B5. P2-2 后台任务引用泄漏 + 结果无反馈。**
计划"改为包装 try/except 的协程任务"，但 `create_task` 不持有引用、任务销毁时若仍 pending 会报 `Task was destroyed but it is pending!`。建议任务句柄入 `set` 并在回调中清理。批量结果仍不回传前端（现有"请稍后查看结果"契约未改）——非漏洞，但"失败可重试"体验依赖用户主动刷新。

### C. 轻微 / 实施细节

- **C1（P1-2）bcrypt 前缀识别**：只匹配 `$2b$` 不够，应兼容 `$2a$/$2y$`（passlib 4.x 默认 `$2b$`，历史/其他库会产生 `$2a$`），否则旧 bcrypt 值落入 legacy 分支校验失败。建议 `re.compile(r"^\$2[aby]\$")` 一类判定。
- **C2（P1-2）畸形存储哈希应 401 而非 500**：`verify_password` 对非 bcrypt 前缀走 legacy，对坏 bcrypt 哈希会抛异常；应在 `authenticate_user` 把所有哈希校验异常统一收敛为同一 401，避免登录接口被单个坏配置打 500。
- **C3（P1-2）透明升级的幂等**：每次 legacy 登录都重写 config，且需**同步更新内存中** `user.config`（否则同进程后续仍比较 legacy）；建议写入"已升级"标记，避免每次登录都落盘。
- **C4（P2-3）措辞精确性**："已 shutdown 的实例不能复用"在本版 APScheduler 并不严格成立——延迟 shutdown 落地后、`_eventloop` 被清空重取，`super().start()` 实为可成功；真正病根是 shutdown **异步延迟**导致的 `SchedulerAlreadyRunningError` 竞争 + 重复 shutdown 的回调异常（实测复现）。计划"running 则先 stop / shutdown 后丢弃重建"仍是最稳妥根治，另建议 `stop()` 将 `_clear_cache_scheduler` 引用置空。
- **C5（P2-7）锁的作用域**：模块级 `asyncio.Lock` 仅单进程内有效；`CodeCache` 为磁盘持久化（`cache.py:60-85`），若未来多 worker 部署，锁无法跨进程串行"注册消费"，TOCTOU 复现。需注明单进程假设。
- **C6（P2-6）** `data.copy()` 浅拷贝正确（深拷贝大 data 反增加开销），无问题。
- **C7（P1-5）白名单项**：应保留 `Accept-Encoding`（第三方 brotli 收益）、`User-Agent`、`Accept-Language`；白名单顺带天然移除当前也透转的 `X-Forwarded-For`（现属额外信头欺骗面），实现时勿遗漏。

---

## 三、计划对源审查文档的必要修正（加分项）

- **P2-9**：源审查写"无 context 时 content=None"，计划纠正为"**有** context 时 `content=None`"——与 `process.py:271-278` 一致。
- **P1-4**：源审查写 `/api/resources/...`，计划改为实际路由 `/resources/portrait|image`——一致。
- **P1-2 修订补充（2026-08-21）**正确捕捉 `UserInfo.password` 的 32 字符 `validate_password`（`tools.py:176`）会**拒绝 bcrypt 哈希**、导致 config 加载失败——该约束必要且正确（详见附 A.1）。

---

## 四、总体结论与建议

- **错误真实性**：✅ 15/15 真实，无虚报；基线数字真实。
- **"会导致新漏洞"**：未发现计划本身引入直接可利用新漏洞的写法；但 P1-4 URL token 泄密面属修复自带副作用且被标注为可延后——**建议改列为必做（B1）**。
- **"未真实修复"风险**：A1（P2-4 缓存批量设计缺失）最可能"修不干净"；A2（P1-2 默认值遮蔽）是唯一可能引发"升级即全量锁死"的回归点；其余为实施细节/覆盖缺口，按 A/B/C 三档把关即可。
- **实施前建议**：先把 A1（给出两阶段设计）、B1（/resources access log 关闭纳入本次）、B4（限流与 TRUSTED_PROXIES 的关系）补进计划描述，再按"一修复点一 commit"执行。P1-2 本期不实施（见附 A.1）。

---

## 附 A.1 — P1-2 不实施依据摘要（决策记录）

**结论**：P1-2（密码默认明文存储 + bcrypt 死代码）本期**不实施**，移出分步执行清单；是否恢复（或改用其他加固方案）另行确认。

**核验确认的事实（错误真实存在）**：
- `ServerConfig.encryption_method` 默认 `"plain"`（`config.py:270`），`encrypt()` 明文直返（`encryt.py:6-11`）；
- 用户密码明文写入 `WebTMData/users/<name>/config.yaml`（`write_config` 不脱敏）；
- `auth.py:40` `pwd_context` 为从未使用的死代码，`passlib[bcrypt]` 依赖形同虚设。

**不实施理由（为何不宜本期按原方案推进）**：
1. **行为变更面大**：默认加密方式由 plain 切换 + 存量配置读取语义 + 透明迁移，属高风险行为变更，需独立排期与回归；
2. **实施陷阱密集**：
   - A2 旧配置缺失键默认值遮蔽——处理不当即"升级全体锁死"；
   - A3 `authenticate_system` 若不改为独立常量时间比较，系统登录 500；
   - C1~C3 bcrypt 前缀覆盖、畸形哈希 401 收敛、透明升级幂等/内存同步；
   - 依赖 `UserInfo.password` 校验放宽（否则含 bcrypt 的 config 启动即加载失败），需一并确认不影响请求模型校验。
3. **收益与风险不匹配本期目标**：本期其余 14 项均为相对独立的局部修复，P1-2 牵一发动全身，宜单独立项并重新确认设计决策后实施。

**遗留风险提示（即便不实施仍存在）**：用户密码与 `forum.bduss/stoken` 当前均明文落盘——这是 P1-1 路径穿越被评定为高危的直接放大器，故 **P1-1 必须优先修复**；P1-2 恢复实施前，部署应依赖 P1-1 防护与配置文件访问控制兜底。
