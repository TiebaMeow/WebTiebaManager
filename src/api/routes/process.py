import math
from datetime import datetime, timedelta
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from src.db import Database
from src.models import ProcessContextModel, ProcessLogModel
from src.schemas.process import ConditionContext, ProcessOptions, RuleContext
from src.schemas.tieba import Content, Post, User

from ..auth import current_user_depends
from ..server import BaseResponse, app

UNKNOWN_CONTENT = Post(
    pid=0,
    tid=0,
    floor=0,
    title="未知内容",
    user=User(user_id=0, user_name="未知用户", portrait="", nick_name="未知用户", level=0),
    fname="未知",
    reply_num=0,
    create_time=0,
    text="该内容可能因为程序错误而丢失，无法显示具体信息。",
    images=[],
)


def make_unknown_content(pid: int, tid: int = 0) -> Content:
    copy = UNKNOWN_CONTENT.model_copy()
    copy.pid = pid
    copy.tid = tid
    return copy


class ProcessCountData(BaseModel):
    total: dict[str, int]
    hit_rules: dict[str, int]
    whitelist_rules: dict[str, int]
    hint_rules: list[str]


@app.get("/api/process/overview", tags=["process"])
async def get_overview(user: current_user_depends) -> BaseResponse[ProcessCountData]:
    now = datetime.now()
    since = now - timedelta(hours=24)
    async with Database.get_session() as session:
        # 查询过去24小时内所有处理日志
        result = await session.execute(
            select(ProcessLogModel.result_rule, ProcessLogModel.is_whitelist)
            .where(ProcessLogModel.process_time >= since)
            .where(ProcessLogModel.user == user.username)
        )
        rows = result.all()

        result = await session.execute(
            select(ProcessLogModel.result_rule)
            .where(ProcessLogModel.user == user.username, ProcessLogModel.result_rule.isnot(None))
            .distinct()
        )
        hint_rules = [row[0] for row in result.all()]

    total_count = len(rows)
    hit_rule_count: dict[str, int] = {}
    whitelist_count: dict[str, int] = {}

    for rule, is_whitelist in rows:
        if is_whitelist is True:
            whitelist_count[rule] = whitelist_count.get(rule, 0) + 1
        elif is_whitelist is False:
            hit_rule_count[rule] = hit_rule_count.get(rule, 0) + 1

    return BaseResponse(
        data=ProcessCountData(
            total={"all": total_count, "hit": sum(hit_rule_count.values()), "whitelist": sum(whitelist_count.values())},
            hit_rules=hit_rule_count,
            whitelist_rules=whitelist_count,
            hint_rules=hint_rules,
        )
    )


class ProcessData(BaseModel):
    result_rule: str | None
    is_whitelist: bool
    process_time: int
    content: Content | None

    def __hash__(self) -> int:
        """
        仅用于同user的判断，不同user不能混用
        """
        return self.content.pid if self.content else hash(id(self))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProcessData):
            return False
        if self.content and other.content:
            return self.content.pid == other.content.pid
        return self is other


async def attach_content(logs: list[ProcessLogModel]) -> list[ProcessData]:
    contents = await Database.get_full_contents_by_pids([log.pid for log in logs])
    pid_to_content = {content.pid: content for content in contents}

    return [
        ProcessData(
            result_rule=log.result_rule,
            process_time=int(log.process_time.timestamp()),
            is_whitelist=log.is_whitelist or False,
            content=pid_to_content[log.pid] if log.pid in pid_to_content else make_unknown_content(log.pid, log.tid),
        )
        for log in logs
    ]


class SearchParams(BaseModel):
    type: Literal["rule", "tid", "pid", "hit"]
    param: str = ""


class SearchRequest(BaseModel):
    page: int = 1
    page_size: int = 30
    params: list[SearchParams]


class PageInfo(BaseModel):
    total: int
    page_count: int


class SearchResponse(BaseModel):
    data: list[ProcessData]
    page: PageInfo


@app.post("/api/process/search", tags=["process"])
async def search_process(request: SearchRequest, user: current_user_depends) -> BaseResponse[SearchResponse]:
    base_sql = select(ProcessLogModel).where(ProcessLogModel.user == user.username)
    for p in request.params:
        if p.type == "rule":
            base_sql = base_sql.where(ProcessLogModel.result_rule == p.param)

        elif p.type == "tid":
            try:
                tid = int(p.param)
                base_sql = base_sql.where(ProcessLogModel.tid == tid)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid tid: {p.param}") from None

        elif p.type == "pid":
            try:
                pid = int(p.param)
                base_sql = base_sql.where(ProcessLogModel.pid == pid)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid pid: {p.param}") from None

        elif p.type == "hit":
            base_sql = base_sql.where(
                ProcessLogModel.result_rule.isnot(None) & (ProcessLogModel.is_whitelist.is_(False))
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported search type: {p.type}")

    async with Database.get_session() as session:
        count_sql = select(func.count()).select_from(base_sql.subquery())
        total = (await session.execute(count_sql)).scalar_one()

        offset = (request.page - 1) * request.page_size
        sql = base_sql.order_by(ProcessLogModel.process_time.desc()).offset(offset).limit(request.page_size)
        result = await session.execute(sql)
        logs = list(result.scalars().all())

    result = await attach_content(logs)

    return BaseResponse(
        data=SearchResponse(
            data=sorted(result, key=lambda x: x.process_time, reverse=True),
            page=PageInfo(total=total, page_count=math.ceil(total / request.page_size)),
        )
    )


class ProcessContextData(ProcessData):
    rules: list[RuleContext]
    conditions: list[ConditionContext]


async def query_process_context(pid: int, user: current_user_depends):
    async with Database.get_session() as session:
        result = await session.execute(
            select(ProcessLogModel, ProcessContextModel)
            .where(ProcessLogModel.pid == pid, ProcessLogModel.user == user.username)
            .join(
                ProcessContextModel,
                (ProcessLogModel.pid == ProcessContextModel.pid) & (ProcessLogModel.user == ProcessContextModel.user),
            )
        )
        return result.first()


@app.get("/api/process/detail", tags=["process"])
async def get_process_detail(pid: int, user: current_user_depends) -> BaseResponse[ProcessContextData | None]:
    data = await query_process_context(pid, user)

    if not data:
        raise HTTPException(status_code=404, detail="处理记录未找到")

    content = await Database.get_full_content_by_pid(pid)

    return BaseResponse(
        data=ProcessContextData(
            result_rule=data[0].result_rule,
            is_whitelist=data[0].is_whitelist or False,
            process_time=int(data[0].process_time.timestamp()),
            content=content or make_unknown_content(pid, data[0].tid),
            rules=data[1].rules,
            conditions=data[1].conditions,
        )
    )


class ReprocessRequest(BaseModel):
    pid: int
    execute_operations: bool = False
    need_confirm: bool = False


class ReprocessResponse(BaseModel):
    result_rule: str | None
    context: ProcessContextData | None


@app.post("/api/process/reprocess", tags=["process"])
async def reprocess_content(user: current_user_depends, request: ReprocessRequest) -> BaseResponse[ReprocessResponse]:
    content = await Database.get_full_content_by_pid(request.pid)
    if not content:
        raise HTTPException(status_code=404, detail="内容未找到，无法匹配")
    if not content.user.user_id:
        raise HTTPException(status_code=404, detail="内容所属用户未找到，无法匹配")

    user.logger.info(
        f"手动重新处理内容 {content.mark}",
        tid=content.tid,
        pid=content.pid,
        uid=content.user.user_id,
        portrait=content.user.portrait,
    )

    result_rule = await user.process(
        content,
        options=ProcessOptions(execute_operations=request.execute_operations, need_confirm=request.need_confirm),
    )

    context = await query_process_context(request.pid, user)

    if context:
        rule_name = context[0].result_rule
    elif result_rule:
        rule_name = result_rule.name
    else:
        rule_name = None

    return BaseResponse(
        data=ReprocessResponse(
            result_rule=rule_name,
            context=ProcessContextData(
                result_rule=context[0].result_rule,
                is_whitelist=context[0].is_whitelist or False,
                process_time=int(context[0].process_time.timestamp()),
                content=None,
                rules=context[1].rules,
                conditions=context[1].conditions,
            )
            if context
            else None,
        )
    )
