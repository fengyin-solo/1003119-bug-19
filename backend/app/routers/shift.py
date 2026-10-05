"""入井管理接口：维护入井记录，覆盖登记升井、补登升井、续传恢复、超时联系等动作。

缺测（升井时间未上报）与超时（超过规定时长未升井）在服务层分开判定，
本层只透传参数，不做业务判断。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.shift import ShiftService

router = APIRouter(prefix="/api/shift", tags=["入井管理"])

service = ShiftService()

LIST_FIELDS = ["记录编号", "入井人员", "所属班组", "入井时间", "升井时间", "缺口时段", "补登时刻", "在井时长", "入井状态"]
STATUSES = ["入井中", "升井缺测", "超时未升", "已升井", "已联系"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按记录编号检索"),
    status: str | None = Query(default=None, description="入井中、升井缺测、超时未升、已升井、已联系"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按记录编号与状态过滤入井管理列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/summary")
def get_summary() -> dict[str, Any]:
    """在井人数与超时/缺测名单：值班台账页面复用的就是这同一份统计。"""
    return service.summary()


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条入井记录明细，附带状态说明与人员定位对照；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"入井记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条入井记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="入井记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条入井记录执行登记升井、补登升井、续传恢复、超时联系；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出入井管理清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "shift", "total": total, "items": items}
