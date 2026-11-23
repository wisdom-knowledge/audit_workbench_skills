# audit-workbench-mcp

审核工作台管理端的 MCP 薄封装。它调用已有的 `/api/v1/admin` 接口，不新增后端接口，权限、版本冲突检查和幂等仍由后端负责。

运行形态是本地 stdio：MCP 客户端（Claude Code、Codex）在会话开始时按配置拉起进程，会话结束时进程退出。

## 工具

| 工具 | 接口 | 类型 |
|-|-|-|
| `login` | 弹出管理端登录页 | 本地 |
| `get_editor` | `GET /admin/projects/{id}/audit-workbench/editor` | 读 |
| `parse_feishu` | `POST /admin/audit-workbench/parse-feishu` | 读（传 project_id 时会更新字段目录） |
| `parse_view_filter` | `POST /admin/audit-workbench/parse-view-filter` | 读 |
| `list_auditors` | `GET /admin/projects/{id}/auditors` | 读 |
| `add_auditors` | `POST /admin/projects/{id}/auditors` | 写 |
| `remove_auditors` | `POST /admin/projects/{id}/auditors/batch-remove` | 写 |
| `save_draft` | `PUT .../audit-workbench/draft` | 写 |
| `discard_draft` | `DELETE .../audit-workbench/draft` | 写 |
| `publish` | `POST .../audit-workbench/publish` | 写 |
| `retry_workflows` | `POST .../audit-workbench/workflows/retry` | 写 |
| `set_runtime_status` | `PATCH .../audit-workbench/runtime-status` | 写 |
| `check_readiness` | 汇总 validate、审核员、状态枚举映射 | 读 |
| `validate_config` | `POST .../audit-workbench/validate` | 读 |
| `get_workflows` / `wait_workflows` | `GET .../audit-workbench/workflows` | 读 |
| `get_reference_configs` | `GET /admin/audit-workbench/recent-published` + 各项目 editor | 读 |
| `get_field_groups` | lark-cli 以用户身份读取底表字段分组 | 读 |
| `suggest_draft` | 按对齐表组装草稿并保存，返回终端报告 | 写（无草稿时直接保存） |
| `set_enqueue_views` | 把用户给出的入队视图链接写入草稿 | 写（直接保存） |
| `ensure_app_collaborator` | lark-cli 以用户身份把「人才招聘」设为底表可管理协作者 | 写（初始化时直接执行） |
| `pre_publish_checklist` | 草稿 + `validate`，列出发布后会创建的工作流 | 读 |
| `created_workflows` | 等待同步，再用 lark-cli 回读启用状态和人工修补状态 | 读 |
| `enable_workflows` | lark-cli `+workflow-enable`，模版二审核操作工作流修补后才启用 | 写 |
| `check_auditor_binding` | `GET .../auditors/feishu-binding` | 读 |
| `onboard_status` | 并发读 editor、workflows、auditors、feishu-binding，已发布时再用 lark-cli 回读工作流状态，判断接入阶段 | 读 |
| `trace` | `GET .../audit-workbench/trace`，再用 lark-cli 回读该轮入队工作流是否启用；提交后结论待定时用 aliyun CLI 按 record_id 查 SLS 运行日志，给出卡点与证据 | 读 |

### 推荐配置

Agent 只做语义对齐：判断本项目底表的每个字段在各参考项目里对应哪个字段，哪个字段承担审核状态、talent_id 等角色，状态选项对应哪个平台状态。计票、置信度、布局和草稿结构都由 `draft_builder.py` 按规则计算：

- 字段在过半数参考项目中有对应才纳入；展示位置、权限取多数，打平取最近发布的项目。
- 对齐表里只能出现本项目底表的字段，否则拒绝保存。
- 布局取覆盖已纳入字段最多的参考项目，没覆盖到的字段按区域追加为单列块，每个区域至少保留一个块。
- 映射的置信度：名称或文案一致为高；凭语义推断为低；没有结果为未推荐出。Agent 没给出的状态选项，取参考项目里同一文案的多数映射。

报告格式由 `report.py` 生成：第一部分列出每轮全部推荐字段，第二部分只列未推荐出和低置信的映射，最后请用户核实字段、映射，并给出各轮视图链接。

写操作默认 `confirm=false`，只返回预览：目标环境、项目、请求摘要、当前状态和影响，不发请求。带 `confirm=true` 才执行，执行后回读 editor，在 `after` 里返回新的版本与更新时间。生产环境还要传 `confirm_project_id`，值与 `project_id` 相同。

写操作不自动重试。超时或连接失败时返回 `result_unknown`，需要先用 `get_editor` 回读确认。读操作在 5xx 或超时时自动重试一次。草稿和发布都不暴露 `force`，冲突时按后端返回的差异重新读取后再提交。

## 返回与错误

成功：

```json
{"ok": true, "env": "boe", "project_id": 7, "fetched_at": "...", "data": {}}
```

失败时工具返回 MCP 错误（`isError: true`），文本是 JSON：

```json
{"ok": false, "code": "conflict", "message": "草稿已被他人更新…", "http_status": 409,
 "detail": {"latest_updated_at": "...", "diff": []}, "hint": "先调用 get_editor 重新读取…"}
```

| code | 来源 |
|-|-|
| `unauthorized` | 401，或本机没有可用登录态 |
| `forbidden` / `not_found` / `bad_request` | 403 / 404 / 400 |
| `conflict` | 409，`detail` 带后端冲突载荷 |
| `validation_failed` | 422；发布校验失败时 `detail.errors` 为逐条校验项，请求结构不符时为字段路径 |
| `rate_limited` | 429 |
| `unavailable` | 5xx、超时、连接失败 |
| `confirm_mismatch` | 生产写操作的 `confirm_project_id` 不一致 |
| `unexpected_response` | 2xx 但不是统一返回结构 |

## 登录态

按以下顺序取管理员 token：

1. `~/.agents/secrets/audit-workbench-admin.env` 中的 `BOE_ADMIN_TOKEN` / `PROD_ADMIN_TOKEN`
2. 环境变量 `AUDIT_WORKBENCH_BOE_ADMIN_TOKEN` / `AUDIT_WORKBENCH_PROD_ADMIN_TOKEN`
3. 专用 Chrome 配置目录 `~/.agents/cache/audit-workbench-admin-chrome`，无窗口静默读取

都不可用时返回 `unauthorized`，由 `login` 工具弹出登录窗口。其他工具不会自动弹窗。token 只保存在进程内存中，以 `Authorization: Bearer` 发送，不出现在返回值和日志里。

## 安装与接入

需要 [uv](https://docs.astral.sh/uv/)，Python 3.10 及以上由 uv 自动准备。

Claude Code：

```bash
claude mcp add audit-workbench -- uv run --directory /path/to/audit_workbench_skills/audit_workbench_mcp audit-workbench-mcp
```

Codex（`~/.codex/config.toml`）：

```toml
[mcp_servers.audit-workbench]
command = "uv"
args = ["run", "--directory", "/path/to/audit_workbench_skills/audit_workbench_mcp", "audit-workbench-mcp"]
```

## 测试

```bash
cd audit_workbench_mcp
uv run pytest
```

测试用 `httpx.MockTransport` 和假 token 来源，不连网，不启动浏览器。
