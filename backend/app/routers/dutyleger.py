"""值班台账接口：在井人数统计与超时未升名单，数据与入井管理同源。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services.dutyleger import DutyLedgerService

router = APIRouter(prefix="/api/dutyleger", tags=["值班台账"])

service = DutyLedgerService()


@router.get("")
def get_ledger() -> dict[str, Any]:
    """值班台账总览：在井人数、状态分布、超时未升名单与待核实缺测名单。"""
    return service.ledger()


@router.get("/export")
def export_ledger() -> dict[str, Any]:
    """导出值班台账的超时未升名单。"""
    data = service.ledger()
    items = data["超时未升名单"]
    return {"module": "dutyleger", "total": len(items), "items": items}
