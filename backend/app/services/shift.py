"""入井管理业务规则：缺测与超时分开判定，补登只记一次，值班台账共用同一份数据。

口径约定（全平台只在这里定义，值班台账直接复用，不另算一份）：
- 升井缺测：升井时间没有上报（数据中断），列表按空态展示并标出缺口时段，
  只说明数据没上来，不代表人员仍在井下；
- 超时未升：上报正常，但自入井时刻起超过规定时长仍未登记升井；
- 两种原因各自独立判定，绝不合并成一条记录；
- 在井人数 = 入井中 + 超时未升 + 已联系（均未登记升井）；升井缺测单列待核实。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.config import settings
from app.store import store

MODULE = "shift"
PERSONNEL_MODULE = "personnel"

REQUIRED_FIELDS = ["入井人员", "所属班组"]
STATUS_FLOW = ["入井中", "升井缺测", "超时未升"]
STATUS_MANUAL = ["已升井", "已联系"]
STATUS_ORDER = STATUS_FLOW + STATUS_MANUAL
ACTIONS = ["登记升井", "补登升井", "续传恢复", "超时联系"]
# 未登记升井且上报正常（非缺测）的状态，计入在井人数
IN_MINE_STATUSES = ("入井中", "超时未升", "已联系")

TIME_FMT = "%Y-%m-%d %H:%M"


def _parse_dt(value: Any) -> datetime | None:
    """把字符串时间解析成 datetime；支持带时分与仅日期两种，解析不了返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in (TIME_FMT, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _fmt(moment: datetime) -> str:
    return moment.strftime(TIME_FMT)


class ShiftService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        now = datetime.now()
        rows = store.rows(MODULE)
        for row in rows:
            self._refresh(row, now)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None
        self._refresh(row, datetime.now())
        detail = dict(row)
        detail["状态说明"] = self._explain(row)
        detail["定位参考"] = self._locate(row)
        return detail

    def summary(self) -> dict[str, Any]:
        """在井人数与超时/缺测名单：值班台账页面复用的就是这同一份统计。"""
        now = datetime.now()
        rows = store.rows(MODULE)
        for row in rows:
            self._refresh(row, now)
        counts = {status: 0 for status in STATUS_ORDER}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return {
            "统计时刻": _fmt(now),
            "在井人数": sum(counts[status] for status in IN_MINE_STATUSES),
            "口径": "在井人数=入井中+超时未升+已联系（均未登记升井）；升井缺测为数据缺口，单列待核实",
            "counts": counts,
            "超时未升名单": [row for row in rows if row["status"] == "超时未升"],
            "升井缺测名单": [row for row in rows if row["status"] == "升井缺测"],
        }

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        now = datetime.now()
        next_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        entry = {
            "id": next_id,
            "记录编号": str(values.get("记录编号") or "").strip() or f"SHIF-{next_id:04d}",
            "入井人员": values.get("入井人员"),
            "所属班组": values.get("所属班组"),
            "入井时间": str(values.get("入井时间") or "").strip() or _fmt(now),
            "升井时间": None,
            "携带设备": str(values.get("携带设备") or "").strip(),
            "出勤区域": str(values.get("出勤区域") or "").strip(),
            "最近上报": _fmt(now),
            "数据中断": False,
            "缺口开始": None,
            "缺口结束": None,
            "补登时刻": None,
        }
        rows.append(entry)
        self._refresh(entry, now)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"入井记录 {entry_id} 不存在或已归档"
        now = datetime.now()
        self._refresh(entry, now)
        status = entry["status"]

        if action == "登记升井":
            if status == "升井缺测":
                return None, "该记录升井数据缺失，请用「补登升井」补录，补登时刻只记一次"
            if status not in ("入井中", "超时未升", "已联系"):
                return None, f"当前状态「{status}」无需登记升井"
            entry["升井时间"] = str(values.get("升井时间") or "").strip() or _fmt(now)
            entry["status"] = "已升井"
            self._refresh(entry, now)
            return entry, "入井记录已登记升井"

        if action == "补登升井":
            if entry.get("补登时刻"):
                return None, f"该记录已于 {entry['补登时刻']} 补登过，重复补登不生效"
            if status != "升井缺测":
                return None, f"当前状态「{status}」不是升井缺测，无需补登"
            entry["升井时间"] = str(values.get("升井时间") or "").strip() or _fmt(now)
            entry["补登时刻"] = _fmt(now)
            entry["数据中断"] = False
            entry["status"] = "已升井"
            self._refresh(entry, now)
            return entry, "升井时间已补登，补登时刻仅记录这一次"

        if action == "续传恢复":
            if status != "升井缺测":
                return None, f"当前状态「{status}」不存在数据缺口，无需续接"
            entry["数据中断"] = False
            entry["最近上报"] = _fmt(now)
            entry["缺口结束"] = _fmt(now)
            self._refresh(entry, now)
            return entry, f"数据已在原记录 {entry.get('记录编号')} 上续接，未新建记录，当前状态「{entry['status']}」"

        if action == "超时联系":
            if status != "超时未升":
                return None, f"当前状态「{status}」不是超时未升，不能执行超时联系"
            entry["status"] = "已联系"
            self._refresh(entry, now)
            return entry, "已联系超时未升人员，待确认升井后登记"

        return None, f"动作「{action}」不属于入井管理可执行范围"

    def _evaluate(self, row: dict[str, Any], now: datetime) -> str:
        """按事实字段推导状态；人工终态（已联系）保持不动，已升井以升井时间为准。"""
        if str(row.get("升井时间") or "").strip():
            return "已升井"
        if row.get("status") == "已联系":
            return "已联系"
        if row.get("数据中断") or not str(row.get("最近上报") or "").strip():
            return "升井缺测"
        entered = _parse_dt(row.get("入井时间"))
        if entered and now - entered > timedelta(hours=settings.shift_max_hours):
            return "超时未升"
        return "入井中"

    def _refresh(self, row: dict[str, Any], now: datetime) -> None:
        """把推导结果写回记录：状态、缺口时段、在井时长与统计标记。"""
        status = self._evaluate(row, now)
        row["status"] = status
        row["入井状态"] = status
        if not str(row.get("升井时间") or "").strip():
            row["升井时间"] = None

        # 缺口时段：起点取最后一次上报，没有上报记录就取入井时间；
        # 上一段缺口已续接又再次中断的，从新的中断点另起一段
        if status == "升井缺测" and (not row.get("缺口开始") or row.get("缺口结束")):
            row["缺口开始"] = row.get("最近上报") or row.get("入井时间")
            row["缺口结束"] = None
        if row.get("缺口开始"):
            end = str(row.get("缺口结束") or "").strip()
            if end:
                row["缺口时段"] = f"{row['缺口开始']} 至 {end}（已续接）"
            else:
                row["缺口时段"] = f"{row['缺口开始']} 至 今（数据中断）"
        else:
            row["缺口时段"] = None

        entered = _parse_dt(row.get("入井时间"))
        if entered and status in STATUS_FLOW + ["已联系"]:
            hours = (now - entered).total_seconds() / 3600
            row["在井时长"] = f"{hours:.1f} 小时"
        else:
            row["在井时长"] = None

        row["pending"] = status != "已升井"
        row["abnormal"] = status in ("升井缺测", "超时未升")

    def _explain(self, row: dict[str, Any]) -> str:
        status = row.get("status")
        if status == "升井缺测":
            return (
                f"升井时间未上报：自 {row.get('缺口开始') or '未知'} 起数据中断，"
                f"缺口时段 {row.get('缺口时段')}。缺测只说明数据没上来，不代表人员仍在井下；"
                "可用「续传恢复」在原记录上接续，或用「补登升井」补录升井时间。"
            )
        if status == "超时未升":
            return (
                f"定位上报正常，但入井已超过规定时长 {settings.shift_max_hours} 小时仍未登记升井；"
                "请先「超时联系」核实，确认升井后「登记升井」。"
            )
        if status == "入井中":
            return f"上报正常，未超过规定时长 {settings.shift_max_hours} 小时。"
        if status == "已联系":
            return "超时未升后已联系本人及班组，待确认升井后登记。"
        if status == "已升井":
            text = f"已于 {row.get('升井时间')} 登记升井。"
            if row.get("补登时刻"):
                text += f"升井时间为补登，补登时刻 {row['补登时刻']}（补登只记一次）。"
            return text
        return ""

    def _locate(self, row: dict[str, Any]) -> str:
        """与人员定位的在线状态对照：按姓名找同名终端，找不到就明说。"""
        name = str(row.get("入井人员") or "").strip()
        if not name:
            return "未填写入井人员，无法比对定位终端"
        matches = [
            item for item in store.rows(PERSONNEL_MODULE)
            if str(item.get("携带人员") or "").strip() == name
        ]
        if not matches:
            return "人员定位中未找到同名终端，请核对终端绑定"
        return "；".join(
            f"{item.get('终端编号')}·{item.get('status')}·{item.get('所在位置')}" for item in matches
        )
