"""入井管理接口：维护入井记录，覆盖登记入井、缺口上报/续接、补登升井等动作。

缺测（定位数据中断）与超时未升（超过规定时长仍未升井）是两种独立状态，
在井人数统计口径由 ShiftService.headcount 统一提供，值班台账直接复用。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.shift import ShiftService, STATUS_OVERDUE

router = APIRouter(prefix="/api/shift", tags=["入井管理"])

service = ShiftService()

# 进程启动时按入井日期回填存量数据；回填幂等，重启不会重复开缺口
service.backfill_legacy()

LIST_FIELDS = ["记录编号", "入井人员", "所属班组", "入井时间", "升井时间", "携带设备", "出勤区域", "入井状态"]
STATUSES = ["入井中", "已升井", "超时未升", "缺测"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按记录编号检索"),
    status: str | None = Query(default=None, description="入井中、已升井、超时未升、缺测"),
    person: str | None = Query(default=None, description="按入井人员姓名检索"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按记录编号、人员与状态过滤入井管理列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"状态仅支持：{'、'.join(STATUSES)}")
    items, total = service.list_entries(keyword=keyword, status=status, person=person, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/headcount")
def headcount() -> dict[str, Any]:
    """在井人数统计的唯一出口，值班台账页与本页共用这一份数据。"""
    return service.headcount()


@router.get("/overtime")
def overtime_list() -> dict[str, Any]:
    """值班台账用的超时未升名单：数据来自入井管理，不另存一份。"""
    items = service.overtime_entries()
    return {"module": "shift", "status": STATUS_OVERDUE, "total": len(items), "items": items}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出入井管理清单：返回当前全量数据（含缺口与补登信息）。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "shift", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条入井记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"入井记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条入井记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing == ["入井时间格式"]:
        return ActionResult(ok=False, message="入井时间格式无法识别，请使用 年-月-日 时:分:秒")
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="入井记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """缺口上报、缺口续接、补登升井；重复执行只保留首次记录，不允许的动作会被拦下。"""
    action = str(payload.values.get("action") or "").strip()
    values = {key: value for key, value in payload.values.items() if key != "action"}
    entry, message = service.run_action(entry_id, action, values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    # 幂等场景（重复补登/重复续接）返回 ok=True，由 message 说明未改动，便于前端提示
    return ActionResult(ok=True, message=message, entry=entry)
