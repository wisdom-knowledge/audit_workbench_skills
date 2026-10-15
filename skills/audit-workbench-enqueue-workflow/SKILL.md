---
name: audit-workbench-enqueue-workflow
description: >
  为某个项目的审核工作台在飞书多维表格上创建入队工作流。用户给底表 URL、确认轮次后，按轮生成
  SetRecordTrigger → enqueue HTTP；非末轮带晋级兜底。不要用于建表、发布 schema、submit/晋级代码，或非入队自动化。
metadata:
  requires:
    bins: ["lark-cli"]
    skills: ["lark-base"]
---

# 审核工作台入队工作流

对用户只走三轮对话：确认底表并问轮次/环境 → 确认配置清单 → 交付链接。内部仍按下面步骤执行。工作流 JSON 用本 skill 的脚本生成，不要手写 `raw_body`。

对用户说话要短：只问缺的、只列待确认的。不要解释猜测、排除、脚本、CLI 或创建过程。失败只说缺什么。

金模板：`https://meetchances.feishu.cn/base/NFyGb7cQPaW5VjsKI51cINXknbS?table=wkfAaswR0PMw3b54` 下的「入队·第1轮（review_stage=1） 副本」（含晋级兜底）和「入队·第2轮（review_stage=2）」（末轮不串台）。

身份：`--as user`。写操作走 `lark-cli base +workflow-create` / `+workflow-update`。新建默认停用，不要擅自 `+workflow-enable`。

## 安装

规范目录是 `~/.agents/skills/audit-workbench-enqueue-workflow`。安装时跑 [scripts/install.py](scripts/install.py)，它会装到该目录，并 symlink 到本机其它 agent 的 skill 目录（Claude / Codex / Grok / Trae 等）。细节见 [references/install.md](references/install.md)。

```bash
python3 scripts/install.py
```

## 对用户的三轮对话

缺 URL 时先多问一句：「底表 URL？」Wiki / `/base/` 都可以。

### 第一轮：确认底表，问轮次和环境

```bash
lark-cli base +url-resolve --url '<url>' --as user --format json
```

- 解析到 `table` 且 `block_type=table`：记下 `base_token`、`table_id`、表名。
- `table=` 实际是 workflow / 其它 block：`+table-list`，优先名含「数据底表」的表；多张候选只列名称让用户选。
- 解析失败或无权限：停下，只说缺权限或解析失败。

对用户只发：

```text
底表：{表名}（{table_id}）
Base：{base_token}

审核工作台要几轮？环境用 BOE 还是生产？
```

未确认轮次和环境不要拉字段、不要创建。`BOE` → `https://service-boe.meetchances.com/api/v1/internal/audit-workbench/tasks/enqueue` + `BOE_API_KEY`；`生产` → `https://service.meetchances.com/api/v1/internal/audit-workbench/tasks/enqueue` + `PROD_API_KEY`。

### 第二轮：配置清单，等确认

```bash
lark-cli base +table-get --base-token <base_token> --table-id <table_id> --as user --format json
lark-cli base +field-list --base-token <base_token> --table-id <table_id> --as user --format json
```

把 `+field-list` JSON 交给猜测脚本（[references/field-guess.md](references/field-guess.md)）。脚本只猜每轮「审核状态 / 审核员talent_id」。Key 读法见 [references/secrets.md](references/secrets.md)，展示只留末 4 位。本机没有对应环境 Key 时不要出配置清单，只发：

```text
首次使用，找 rd 同学要一份 audit-workbench-enqueue.env，添加到 ~/.agents/secrets/ 目录下。
```

用户说放好后再读文件。不要让用户把 Key 贴到对话里。

对用户只发下面这份清单。缺项留空并只给可指定的列名。用户确认前不要生成。

```text
第 1 轮（含晋级兜底）
- 监听：`审核状态`（fld…）+ `审核员talent_id`（fld…）
- 晋级通过选项：审核通过、审核员修改后通过

第 N 轮（末轮）
- 监听：`N轮审核状态`（fld…）+ `N轮审核员talent_id`（fld…）

公共
- 环境：BOE 或 生产
- 请求地址：对应 enqueue URL
- X-API-Key 末 4 位：xxxx
- app_token / table_id / 表名

飞书会保存 API Key 明文。确认后创建，默认停用。
```

必须齐：每轮监听列、环境、请求地址、Key、`app_token`、`table_id`、表名；非末轮还要通过选项 `审核通过`、`审核员修改后通过`。

### 第三轮：创建后交链接

用 [scripts/render_enqueue_workflow.py](scripts/render_enqueue_workflow.py) 逐轮渲染，步骤图见 [references/round-template.md](references/round-template.md)。

- 标题：`审核工作台题目入队·第N轮`
- 每一轮：`SetRecordTrigger`（本轮状态 + 本轮审核员talent_id）→ HTTP enqueue 本轮
- **非末轮**再接 IfElse：本轮状态包含「审核通过」或「审核员修改后通过」→ HTTP enqueue **下一轮**
- **末轮不串台**，只有 trigger + 本轮 HTTP
- `record_id` 必须是 `ref: $.trig.recordId`
- body 用 `app_token` + `table_id` + `review_stage`，不写 `project_id`
- `trigger_control_list` 含 `pasteUpdate`、`automationBatchUpdate`、`openAPIBatchUpdate`
- 先 `+workflow-list`：同名已存在则只问「更新还是跳过」，禁止再造「副本」
- 创建前 `--dry-run`；配置清单已确认则可带确认 flag 写入
- 串行创建；`client_token` 每条唯一
- CLI 输出可能含 Key：回复不要回显，`--jq` 只取 `ok` / `title` / `workflow_id` / `status`；本地 JSON 用完删除
- **不要启用**
- 创建过程不要向用户播报进度

对用户只发：

```text
已创建（停用）。请在飞书核对监听列、URL、Key、body 后手动启用。

第 1 轮（含晋级兜底）
https://meetchances.feishu.cn/base/{app_token}?table={workflow_id}

第 N 轮（末轮）
https://meetchances.feishu.cn/base/{app_token}?table={workflow_id}
```

## 安全

- API Key **禁止**写进 `SKILL.md`、references、scripts 默认值、git。
- 本机 secrets：`~/.agents/secrets/audit-workbench-enqueue.env`（目录 `700`，文件 `600`）。见 [references/secrets.md](references/secrets.md)。
- 飞书工作流会保存 Key 明文，生成前在确认清单里告知用户。CLI 输出和本地 JSON 里的完整 Key 禁止回显到对话。
- 本 skill 不改底表字段、不发布审核工作台、不启停其它自动化。

## 失败就停

权限不足、表找不到、轮次不是正整数、环境不是 `BOE` 或 `生产`、本机没有对应环境 Key、某轮两列猜不出且用户没指定、用户未确认每轮监听字段、非末轮找不到通过选项、enqueue URL 不是上述两个地址之一：停止并说明缺什么。
