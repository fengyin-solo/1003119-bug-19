"""值班台账：不另存数据，在井人数与超时未升名单直接复用入井管理的同一份记录。"""
from __future__ import annotations

from typing import Any

from app.services.shift import ShiftService


class DutyLedgerService:
    """只读视图：所有数字都来自 ShiftService.summary()，保证两个页面是同一份。"""

    def __init__(self, shift_service: ShiftService | None = None) -> None:
        self._shift = shift_service or ShiftService()

    def ledger(self) -> dict[str, Any]:
        summary = self._shift.summary()
        return {
            "统计时刻": summary["统计时刻"],
            "在井人数": summary["在井人数"],
            "口径": summary["口径"],
            "counts": summary["counts"],
            "超时未升名单": summary["超时未升名单"],
            "升井缺测名单": summary["升井缺测名单"],
            "来源": "入井管理（/api/shift）同一份记录，本页不另存数据",
        }
