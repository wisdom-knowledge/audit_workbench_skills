"""MCP server entry. Started by the MCP client over stdio, one process per session."""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from . import browser_login, errors, setup_check
from .auth import TokenStore
from .client import AdminClient
from .envs import get_env
from .service import AuditWorkbenchService

INSTRUCTIONS = """\
审核工作台管理端工具，调用已有的 /api/v1/admin 接口，权限和版本冲突检查都在后端。

每个环境第一次使用前调用一次 check_setup，把 setup_markdown 原样展示；ready=false 时先按「处理」列解决。

使用顺序：
1. get_editor 读取项目现状，记下 summary 里的 draft_updated_at 与 published_version。
2. parse_feishu 解析底表字段，parse_view_filter 解析入队视图。
3. save_draft 保存草稿，base_updated_at 原样回传第 1 步读到的 draft_updated_at，不做时区换算。
4. check_readiness 检查草稿；有 blocker 先修，unverified 项要另行确认。
5. publish 发布，base_version 传第 1 步读到的 published_version（从未发布传 0）。
6. wait_workflows 等待飞书工作流同步出结果；timed_out 时稍后再用 get_workflows 查询。
7. 工作流 failed 时，按 lastError 排除原因后用 retry_workflows 只重试那一轮，再 wait_workflows。

新项目推荐配置（替代第 2、3 步的手工配置）：
a. get_editor 判断模版类型；parse_feishu 取底表字段；ensure_app_collaborator 设置人才招聘协作者；get_field_groups 取字段分组。
b. get_reference_configs 取参考项目。按分组和语义判断轮次数，再逐轮产出对齐表：
   {"rounds":[{"round":1,
     "fields":[{"field_id":"<本底表字段ID>","matches":{"<参考项目ID>":"<该项目同轮对应字段名或 null>"}}],
     "roles":{"status|reviewer|talent_id|audit_advice|audit_action":{"field_id":"…","basis":"exact|semantic|none","reason":"…"}},
     "status_mapping":{"<飞书选项>":{"target":"<平台状态>","basis":"exact|semantic|none","reason":"…"}}}]}
   fields 只放本底表里的字段；名称相同才算 exact，凭语义判断的一律 semantic。
c. suggest_draft 保存草稿。推荐配置分三步确认，每步只展示一段、等用户确认后再进下一步：
   2.1 report_markdown（展示字段）→ 2.2 mapping_markdown（字段映射和状态枚举映射）→ 2.3 views_markdown（入队视图链接）。
   mappings_to_confirm=false 时 2.2 只展示结论，不等用户确认。
d. 用户给出视图链接后调用 set_enqueue_views；要改字段或映射时，get_editor 读草稿后用 save_draft 保存。

发布与交接：
e. pre_publish_checklist 展示发布前清单，用户确认后 publish。
f. created_workflows 等待同步并列出已创建的工作流，用户确认后 enable_workflows。
g. 用户提供审核员 talent_id 后 add_auditors，再 check_auditor_binding；未绑定的务必提醒。

中途恢复时调用 onboard_status，按返回的 stage 接着做。
排查某条记录时调用 trace，把 trace_markdown 原样展示。

所有写操作默认只返回预览（confirm=false），把预览给用户看并得到同意后，再带 confirm=true 调用。
例外：suggest_draft 在项目没有草稿时直接保存；set_enqueue_views 只写用户在对话中给出的链接，直接保存。
生产环境（env=prod）的写操作还要传 confirm_project_id，值与 project_id 相同。
返回 conflict 时先 get_editor 重新读取，不要强行覆盖。返回 unauthorized 时调用 login。
"""

EnvArg = Annotated[Literal["boe", "prod"], Field(description="目标环境：boe 测试，prod 生产")]
ProjectIdArg = Annotated[int, Field(gt=0, description="平台项目 ID")]
ConfirmArg = Annotated[
    bool, Field(description="false 只返回预览不执行；用户确认后传 true 才执行")
]
ConfirmProjectIdArg = Annotated[
    int | None,
    Field(description="仅生产环境需要：再填一次 project_id，防止误操作"),
]
TalentIdsArg = Annotated[
    list[int], Field(min_length=1, max_length=500, description="审核员 talent_id 列表")
]
ConfigArg = Annotated[
    dict[str, Any],
    Field(description="完整编辑配置，结构与 get_editor 返回的 draft.config 相同"),
]

mcp = FastMCP("audit-workbench", instructions=INSTRUCTIONS)
_tokens = TokenStore()
_service = AuditWorkbenchService(AdminClient(_tokens))


def _structured_errors(fn: Callable[..., Awaitable[dict[str, Any]]]):
    """Report AuditWorkbenchError as an MCP tool error whose text is a JSON payload."""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return await fn(*args, **kwargs)
        except errors.AuditWorkbenchError as exc:
            raise exc.to_tool_error() from exc

    return wrapper


def _tool(description: str):
    def decorator(fn):
        return mcp.tool(description=description)(_structured_errors(fn))

    return decorator


@_tool("打开管理端登录页，登录后把登录态保存在本进程内存中。其他工具返回 unauthorized 时使用。会弹出浏览器窗口，最多等待 timeout 秒。")
async def login(
    env: EnvArg,
    timeout: Annotated[int, Field(ge=30, le=600)] = 300,
) -> dict[str, Any]:
    target = get_env(env)
    try:
        await asyncio.to_thread(_tokens.login, target, timeout)
    except browser_login.LoginError as exc:
        raise errors.AuditWorkbenchError(
            errors.UNAUTHORIZED, f"登录未完成：{exc}"
        ) from exc
    return {"ok": True, "env": env, "logged_in": True}


@_tool("授权检查：确认该环境的管理端登录态、lark-cli 用户身份和阿里云日志读权限（可选），并返回插件版本。每个环境第一次使用前调用一次，把 setup_markdown 原样展示给用户。ready=false 时先按 fix 处理。只读。")
async def check_setup(env: EnvArg) -> dict[str, Any]:
    return await setup_check.check_setup(_service.client, env)


@_tool("读取项目的审核工作台配置：草稿、已发布版本、平台常量、字段目录与运行状态。summary 里是后续保存和发布要回传的版本基线。")
async def get_editor(env: EnvArg, project_id: ProjectIdArg) -> dict[str, Any]:
    return await _service.get_editor(env, project_id)


@_tool("解析飞书多维表格链接，返回 app_token、table_id、view_id 与字段列表。传 project_id 时后端会同时更新该项目的字段目录。")
async def parse_feishu(
    env: EnvArg,
    table_url: Annotated[str, Field(description="底表链接，支持 /base/ 与 /wiki/")],
    project_id: Annotated[int | None, Field(gt=0)] = None,
) -> dict[str, Any]:
    return await _service.parse_feishu(env, table_url, project_id)


@_tool("解析入队视图链接中的筛选条件，返回条件列表与可读摘要。链接须含 table= 与 view=。")
async def parse_view_filter(
    env: EnvArg,
    view_url: Annotated[str, Field(description="飞书视图链接")],
) -> dict[str, Any]:
    return await _service.parse_view_filter(env, view_url)


@_tool("查询项目审核员名单与统计，可按 talent_id 精确或按姓名模糊筛选。")
async def list_auditors(
    env: EnvArg,
    project_id: ProjectIdArg,
    skip: Annotated[int, Field(ge=0)] = 0,
    limit: Annotated[int, Field(ge=1, le=500)] = 50,
    talent_id: int | None = None,
    talent_name: str | None = None,
) -> dict[str, Any]:
    return await _service.list_auditors(env, project_id, skip, limit, talent_id, talent_name)


@_tool("添加项目审核员。写操作：默认只返回预览。")
async def add_auditors(
    env: EnvArg,
    project_id: ProjectIdArg,
    talent_ids: TalentIdsArg,
    confirm: ConfirmArg = False,
    confirm_project_id: ConfirmProjectIdArg = None,
) -> dict[str, Any]:
    return await _service.add_auditors(env, project_id, talent_ids, confirm, confirm_project_id)


@_tool("移除项目审核员（软删）。写操作：默认只返回预览。")
async def remove_auditors(
    env: EnvArg,
    project_id: ProjectIdArg,
    talent_ids: TalentIdsArg,
    confirm: ConfirmArg = False,
    confirm_project_id: ConfirmProjectIdArg = None,
) -> dict[str, Any]:
    return await _service.remove_auditors(
        env, project_id, talent_ids, confirm, confirm_project_id
    )


@_tool("保存审核工作台草稿。base_updated_at 原样传 get_editor 的 summary.draft_updated_at（无草稿传 null）；不一致时返回 conflict 而不是覆盖。写操作：默认只返回预览。")
async def save_draft(
    env: EnvArg,
    project_id: ProjectIdArg,
    config: ConfigArg,
    base_updated_at: Annotated[str | None, Field(description="草稿版本基线，原样回传")],
    wizard_step: Annotated[int, Field(ge=1, le=3)] = 1,
    feishu_app_token: str | None = None,
    feishu_table_id: str | None = None,
    feishu_view_id: str | None = None,
    confirm: ConfirmArg = False,
    confirm_project_id: ConfirmProjectIdArg = None,
) -> dict[str, Any]:
    return await _service.save_draft(
        env,
        project_id,
        config,
        base_updated_at,
        wizard_step,
        feishu_app_token,
        feishu_table_id,
        feishu_view_id,
        confirm,
        confirm_project_id,
    )


@_tool("删除审核工作台草稿，不可恢复，已发布版本不受影响。写操作：默认只返回预览。")
async def discard_draft(
    env: EnvArg,
    project_id: ProjectIdArg,
    confirm: ConfirmArg = False,
    confirm_project_id: ConfirmProjectIdArg = None,
) -> dict[str, Any]:
    return await _service.discard_draft(env, project_id, confirm, confirm_project_id)


@_tool("发布审核工作台配置。base_version 传 get_editor 的 summary.published_version（从未发布传 0）。校验失败返回 validation_failed 与逐条原因。写操作：默认只返回预览。")
async def publish(
    env: EnvArg,
    project_id: ProjectIdArg,
    config: ConfigArg,
    base_version: Annotated[int, Field(ge=0)],
    confirm: ConfirmArg = False,
    confirm_project_id: ConfirmProjectIdArg = None,
) -> dict[str, Any]:
    return await _service.publish(
        env, project_id, config, base_version, confirm, confirm_project_id
    )


@_tool("按当前已发布配置把工作流任务重置为 PENDING，Worker 约 10 秒内重新写飞书；不等待写入结果。没有已发布版本时返回 validation_failed。写操作：默认只返回预览。")
async def retry_workflows(
    env: EnvArg,
    project_id: ProjectIdArg,
    stages: Annotated[list[int] | None, Field(description="限定轮次，不传为全部")] = None,
    kind: Annotated[
        Literal["ENQUEUE", "AUDIT_ACTION"] | None, Field(description="不传为全部")
    ] = None,
    force_update: Annotated[
        bool, Field(description="true 时即使内容未变也重写，会覆盖飞书界面上的手工修改")
    ] = False,
    confirm: ConfirmArg = False,
    confirm_project_id: ConfirmProjectIdArg = None,
) -> dict[str, Any]:
    return await _service.retry_workflows(
        env, project_id, stages, kind, force_update, confirm, confirm_project_id
    )


@_tool("切换项目运行状态：ACTIVE 生效中，PAUSED 暂停（配置端写操作与专家端提交都不可用）。写操作：默认只返回预览。")
async def set_runtime_status(
    env: EnvArg,
    project_id: ProjectIdArg,
    runtime_status: Literal["ACTIVE", "PAUSED"],
    confirm: ConfirmArg = False,
    confirm_project_id: ConfirmProjectIdArg = None,
) -> dict[str, Any]:
    return await _service.set_runtime_status(
        env, project_id, runtime_status, confirm, confirm_project_id
    )


@_tool("发布前检查清单：发布校验、工作流能否生成、审核状态枚举映射、审核员。不传 config 时检查已保存的草稿（没有草稿则检查已发布配置）。level 为 blocker 会导致发布失败，warning 不阻断发布但会影响使用，unverified 是这里查不到、需要另行确认的项，不算通过。")
async def check_readiness(
    env: EnvArg,
    project_id: ProjectIdArg,
    config: Annotated[
        dict[str, Any] | None,
        Field(description="要检查的配置；不传则用已保存草稿"),
    ] = None,
) -> dict[str, Any]:
    return await _service.check_readiness(env, project_id, config)


@_tool("只做后端发布预检，返回 errors（会导致发布失败）与 workflowErrors（发布成功但工作流建不出来）。不写库、不发布，会调用飞书只读接口。")
async def validate_config(
    env: EnvArg, project_id: ProjectIdArg, config: ConfigArg
) -> dict[str, Any]:
    return await _service.validate_config(env, project_id, config)


@_tool("查询一次各轮飞书工作流的同步状态。display_status：pending 排队、running 执行中、retrying 失败后待自动重试、synced 已同步、failed 已到重试上限（需 retry_workflows）。problems 列出需要处理的问题。")
async def get_workflows(env: EnvArg, project_id: ProjectIdArg) -> dict[str, Any]:
    return await _service.get_workflows(env, project_id)


@_tool("发布或重试后等待工作流同步出结果：每隔 interval 秒查询一次，全部同步完成、出现失败或待重试、或到达 timeout 时返回。timed_out=true 表示仍未完成，不代表成功。")
async def wait_workflows(
    env: EnvArg,
    project_id: ProjectIdArg,
    timeout: Annotated[int, Field(ge=10, le=180)] = 90,
    interval: Annotated[int, Field(ge=2, le=30)] = 5,
) -> dict[str, Any]:
    return await _service.wait_workflows(env, project_id, timeout, interval)


@_tool("推荐配置第 1 步：取最近 limit 个同模版已发布项目的精简配置（字段按名称表示），供语义对齐。按发布时间倒序，排除当前项目。count 为 0 时没有可参考的项目，不要推荐。")
async def get_reference_configs(
    env: EnvArg,
    project_id: ProjectIdArg,
    workbench_type: Annotated[Literal[1, 2], Field(description="1=模版一，2=模版二")],
    limit: Annotated[int, Field(ge=1, le=10)] = 5,
) -> dict[str, Any]:
    return await _service.get_reference_configs(env, project_id, workbench_type, limit)


@_tool("推荐配置第 2 步：用 lark-cli 以用户身份读取当前底表的字段分组（分组名 → 字段 ID）。app_token / table_id 取自 parse_feishu。ok=false 时退回只按字段名判断，并把相关推荐的 basis 降为 semantic。")
async def get_field_groups(
    env: EnvArg,
    app_token: Annotated[str, Field(min_length=1)],
    table_id: Annotated[str, Field(min_length=1)],
) -> dict[str, Any]:
    return await _service.get_field_groups(env, app_token, table_id)


@_tool("推荐配置第 3 步：按对齐表组装草稿并保存，返回三段依次展示的文本：report_markdown（2.1 展示字段）、mapping_markdown（2.2 字段映射和状态枚举映射）、views_markdown（2.3 入队视图链接），以及配置页链接。每段等用户确认后再展示下一段。计票、置信度、布局都由工具按规则计算。项目没有草稿时直接保存；已有草稿时只返回预览，用户同意覆盖后带 confirm=true 再调用。alignment 格式见工具 instructions。")
async def suggest_draft(
    env: EnvArg,
    project_id: ProjectIdArg,
    table_url: Annotated[str, Field(description="本项目底表链接")],
    workbench_type: Annotated[Literal[1, 2], Field(description="1=模版一，2=模版二")],
    alignment: Annotated[dict[str, Any], Field(description="Agent 产出的对齐表")],
    limit: Annotated[int, Field(ge=1, le=10)] = 5,
    confirm: ConfirmArg = False,
    confirm_project_id: ConfirmProjectIdArg = None,
) -> dict[str, Any]:
    return await _service.suggest_draft(
        env, project_id, table_url, workbench_type, alignment, limit, confirm, confirm_project_id
    )


@_tool("把用户给出的各轮入队视图链接写入现有草稿并保存。key 为轮次 ID（round-1、round-2…）。每个链接先解析，解析失败则不保存。返回各轮视图的筛选条件摘要和 views_markdown（原样展示给用户核对，含还差的轮次和配置页链接）。")
async def set_enqueue_views(
    env: EnvArg,
    project_id: ProjectIdArg,
    view_urls: Annotated[dict[str, str], Field(description="{轮次 ID: 视图链接}")],
) -> dict[str, Any]:
    return await _service.set_enqueue_views(env, project_id, view_urls)


@_tool("初始化：用 lark-cli 以用户身份把「人才招聘」应用设为底表可管理协作者（不在就添加，权限不够就升级）。后端 Worker 用这个应用建工作流，发布前必须完成。app_token 取自 parse_feishu。用户已授权直接执行，结果要告诉用户。")
async def ensure_app_collaborator(
    env: EnvArg, app_token: Annotated[str, Field(min_length=1)]
) -> dict[str, Any]:
    return await _service.ensure_app_collaborator(env, app_token)


@_tool("发布前确认清单：配置页链接、发布后会创建的工作流（模版二提示审核操作工作流需人工修补），以及发布前必须处理的问题。把 checklist_markdown 原样展示给用户；用户回复确认后再调用 publish（base_version 用返回的 base_version）。")
async def pre_publish_checklist(env: EnvArg, project_id: ProjectIdArg) -> dict[str, Any]:
    return await _service.pre_publish_checklist(env, project_id)


@_tool("发布后：等待工作流同步，再回读每条工作流在飞书上的启用状态和人工修补状态。把 workflows_markdown 原样展示给用户，由用户确认后调用 enable_workflows。")
async def created_workflows(
    env: EnvArg,
    project_id: ProjectIdArg,
    timeout: Annotated[int, Field(ge=10, le=180)] = 90,
) -> dict[str, Any]:
    return await _service.created_workflows(env, project_id, timeout)


@_tool("启用已同步的工作流；模版二的审核操作工作流要回读确认已人工修补才启用。启用后回读状态。写操作：默认只返回预览，用户确认后带 confirm=true。")
async def enable_workflows(
    env: EnvArg,
    project_id: ProjectIdArg,
    confirm: ConfirmArg = False,
    confirm_project_id: ConfirmProjectIdArg = None,
) -> dict[str, Any]:
    return await _service.enable_workflows(env, project_id, confirm, confirm_project_id)


@_tool("续接用：一次读取配置、工作流同步与飞书启用状态、审核员名单和飞书绑定，按接入阶段顺序判断项目停在哪一步。返回 stage（1–6）、stage_name、reason 和各项缺口。只读。")
async def onboard_status(env: EnvArg, project_id: ProjectIdArg) -> dict[str, Any]:
    return await _service.onboard_status(env, project_id)


@_tool("排障：按 record_id 查一条记录为什么没进专家端、提交后飞书为什么没变。沿依赖链（配置发布→项目未暂停→上一轮通过→入队条件→工作流同步与启用→任务→分配→审核员名单）给出第一处不满足的环节、证据和下一步；本轮已有任务时另给提交后判断（按审核日志、task_submit 事件和飞书当前值，模版二含审核操作列）；每轮列出飞书当前状态与平台任务状态。把 trace_markdown 原样展示给用户。只读。")
async def trace(
    env: EnvArg,
    project_id: ProjectIdArg,
    record_id: Annotated[str, Field(min_length=1, max_length=255, description="飞书记录 record_id")],
    talent_id: Annotated[int | None, Field(gt=0, description="只看这位审核员；不传按任务或底表上的审核员")] = None,
    stage: Annotated[int | None, Field(ge=1, description="排查哪一轮；不传按任务进度推断")] = None,
) -> dict[str, Any]:
    return await _service.trace(env, project_id, record_id, talent_id, stage)


@_tool("检查项目审核员是否已绑定飞书账号（读飞书用户绑定表）。把 binding_markdown 原样展示给用户，未绑定的用 🔴 标出，务必提醒用户通知审核员在专家端自行绑定。")
async def check_auditor_binding(
    env: EnvArg,
    project_id: ProjectIdArg,
    talent_ids: Annotated[list[int] | None, Field(description="只查这些人；不传查全部启用中的审核员")] = None,
) -> dict[str, Any]:
    return await _service.check_auditor_binding(env, project_id, talent_ids)


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
