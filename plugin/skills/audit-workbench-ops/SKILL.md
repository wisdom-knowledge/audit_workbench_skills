---
name: audit-workbench-ops
description: >
  审核工作台排障：按 record_id 查一条记录为什么没进专家端、某位审核员为什么看不到、审核员提交后
  飞书为什么没变、为什么没进下一轮。只读，给出卡在哪一环、证据和下一步。不要用于改配置、处理
  工作流或增删审核员，修复交给对应子技能。
---

# 排障

先读 [通用规则](../audit-workbench/references/rules.md) 和
[业务模型](../audit-workbench/references/business-model.md) 里的依赖链。环境和项目 ID 按入口的
「定位项目」取得。

## 要什么输入

- **record_id**：必须有。用户给的是飞书记录链接时，取链接里 `record=` 后面的值；给的是题目编号
  或标题时，请用户提供 record_id 或记录链接，不要自己去表里搜。
- **talent_id**：用户说的是「某某看不到」时需要，请用户提供这位审核员的 talent_id。只问「为什么
  没有任务」时不需要。
- **轮次**：一般不用给，工具按任务进度推断。用户明确问某一轮时传 `stage`。

## 查

调用 `trace(env, project_id, record_id, talent_id, stage)`，把 `trace_markdown` 原样展示给用户。

工具沿依赖链逐环检查，每一环只用它自己的证据下结论。结论在 `diagnosis.result`：

- `blocked`：卡在第一处不满足的环节，`next` 是下一步。
- `unverified`：没有查到明确卡点，但有环节查不到，例如读不到飞书记录、读不到工作流启用状态。
  告诉用户哪几环没核验，不要说成正常。
- `all_pass`：按证据各环节都通过，仍然解释不了。把 `next` 里的人工入口给用户，不要猜原因。

## 提交后飞书没变

本轮已有任务时，`trace` 返回里有 `submit`，`trace_markdown` 里是「提交后」一段。直接用
`submit.result` 下结论，不要自己再拿日志和状态推。

判断依据是审核日志、行为事件 `task_submit` 和飞书当前值。`task_submit` 只在回写飞书成功后才记，
但写事件失败不影响提交，所以「没有 task_submit」只能说大概率没提交成功。看题记录（`viewNote`）是
专家端上报的，可能丢，只作参考，不能拿它的有无下结论。

结论是下表里标「查运行日志」的几种时，工具会再用本机 aliyun CLI 按 record_id 查后端运行日志
（SLS，从本轮任务创建起最多 7 天），结果在 `submit.logNote` 和日志表里：

- 日志里有回写飞书失败：结论改为 `writeback_failed`，`message` 里是飞书返回的报错，按报错处理后请
  审核员重新提交。
- 其他情况结论不变，`logNote` 补充确定的事实，例如提交其实已回写成功、提交后入队接口有没有被调用、
  这次提交有哪些字段没回写。回答时以 `logNote` 为准，不再说「大概率」。
- `logNote` 以「运行日志未核验」开头：本机没装 aliyun CLI，或没有日志读权限。照常按 `result` 回答，
  并告诉用户运行日志没查。不要改用 kubectl 或其他方式查日志。

日志表里的 `trace_id` 可以交给研发，在 SLS 里搜它看这次请求的完整过程。

模版一（审核员直接选审核状态）：

| `result` | 含义 | 交给 |
|-|-|-|
| `ok` | 提交已写进飞书，两边一致 | — |
| `feishu_changed` | 提交时飞书已写成功，之后被人或其他自动化改过 | 用户查飞书记录的修改历史 |
| `log_missing` | 回写成功，但审核日志没写上（查运行日志） | 研发，带上 `trace_id` |
| `not_submitted` | 大概率没提交，或回写飞书失败（查运行日志） | 请审核员重新提交 |
| `writeback_failed` | 运行日志确认回写飞书失败 | 按报错处理，再请审核员重新提交 |

模版二（审核员填审核操作列，由飞书工作流改状态）：

| `result` | 含义 | 交给 |
|-|-|-|
| `ok` | 全链路正常，或上次提交已回流、在等再次审核 | — |
| `action_workflow_not_run` | 回写成功，审核操作工作流没跑 | [工作流](../audit-workbench-workflow/SKILL.md) |
| `action_not_cleared` | 状态改了，审核操作列没清空，缺清空步骤 | [工作流](../audit-workbench-workflow/SKILL.md)，在飞书界面人工修补 |
| `enqueue_not_returned` | 两个工作流都跑了，入队工作流没回流平台（查运行日志） | [工作流](../audit-workbench-workflow/SKILL.md) |
| `action_workflow_half` | 回写成功，审核操作列清空了但状态没改，工作流执行到一半失败（查运行日志） | 用户看飞书上这条工作流的运行记录 |
| `not_submitted` | 大概率没提交，或回写飞书失败（查运行日志） | 请审核员重新提交 |
| `writeback_failed` | 运行日志确认回写飞书失败 | 按报错处理，再请审核员重新提交 |
| `not_configured` | 本轮没配审核操作列 | [改配置](../audit-workbench-config/SKILL.md) |

两个模版都可能出现 `unverified`：读不到飞书当前值，告诉用户没核验，稍后重试。

运行日志只保留 90 天，更早的提交查不到原因，如实告诉用户。

## 修

排障只读，不做任何写操作。按卡住的环节转给对应子技能，把这次的证据一起带过去：

| 卡住的环节 | 交给 |
|-|-|
| 配置未发布、入队条件不满足需要换视图、项目已暂停 | [改配置](../audit-workbench-config/SKILL.md) |
| 工作流没排上队、同步失败、需人工同步、没有启用 | [工作流](../audit-workbench-workflow/SKILL.md) |
| 审核员不在名单、没绑定飞书账号 | [审核员](../audit-workbench-auditors/SKILL.md) |
| 记录本身不满足条件、上一轮没通过、任务分给了别人 | 用户在底表上改，说明改哪一列 |

工作流刚启用或刚修好时，已经满足条件的记录不会自动入队，要改动一次这条记录才会触发。修完后
再调用一次 `trace` 确认，不要凭「改好了」就说已解决。
