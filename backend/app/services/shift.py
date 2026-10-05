"""入井管理业务规则：缺测与超时分开判定、缺口续接、补登幂等、台账统一口径。

两个容易混淆的异常态：
- 缺测（data_missing）：升井时间没有上报，且人员定位数据存在中断缺口。
  记录上开一段「缺口时段」，等数据恢复后续在原来这条记录上，不新增记录。
- 超时未升（overdue）：入井后持续在线、没有缺口，但超过规定时长仍未升井。
两种原因各自独立成态，不会同时落在一条记录上。

当前时刻通过 ``now_ref`` 注入，方便按存量数据的入井日期做确定性回填与测试。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable

from app.store import store

MODULE = "shift"
PERSONNEL_MODULE = "personnel"
REQUIRED_FIELDS = ["记录编号", "入井人员", "所属班组", "入井时间"]
OPTIONAL_FIELDS = ["携带设备", "出勤区域", "定位终端编号"]

# 入井状态
STATUS_UNDERGROUND = "入井中"
STATUS_LIFTED = "已升井"
STATUS_OVERDUE = "超时未升"
STATUS_MISSING = "缺测"
OPEN_STATUSES = {STATUS_UNDERGROUND, STATUS_OVERDUE, STATUS_MISSING}

# 超过该时长仍未升井即判超时未升（数据未中断的前提下）
MAX_DURATION = timedelta(hours=8)

# 兼容旧状态：老数据里的「已联系」按入井中口径继续判定
LEGACY_STATUS = "已联系"

TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")


def parse_time(value: Any) -> datetime | None:
    """尽量把入井/升井时间解析成时间对象；只给日期时按早八点入井处理。"""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in TIME_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt == "%Y-%m-%d":
                return parsed.replace(hour=8)
            return parsed
        except ValueError:
            continue
    return None


def format_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%Y-%m-%d %H:%M:%S")


class ShiftService:
    def __init__(self, now_ref: Callable[[], datetime] | None = None) -> None:
        # 真实环境取系统时钟；回填与测试可注入固定时刻
        self._now_ref = now_ref or datetime.now

    # ---------- 读取 ----------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        person: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [self._decorate(row) for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
        if person:
            rows = [row for row in rows if person in str(row.get("入井人员", ""))]
        if status:
            rows = [row for row in rows if row.get("入井状态") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def overtime_entries(self) -> list[dict[str, Any]]:
        """值班台账用的超时未升名单，与列表是同一份数据、同一套判定。"""
        return [self._decorate(row) for row in store.rows(MODULE) if self._compute_status(row) == STATUS_OVERDUE]

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._decorate(entry) if entry is not None else None

    def headcount(self) -> dict[str, Any]:
        """在井人数统计的唯一口径，入井管理页与值班台账页共用。

        在井 = 入井中 + 超时未升（缺测是数据没上来，人是否在井未知，不计入）。
        """
        rows = store.rows(MODULE)
        decorated = [self._decorate(row) for row in rows]
        underground = sum(1 for row in decorated if row["入井状态"] in {STATUS_UNDERGROUND, STATUS_OVERDUE})
        return {
            "在井人数": underground,
            "入井中人数": sum(1 for row in decorated if row["入井状态"] == STATUS_UNDERGROUND),
            "超时未升人数": sum(1 for row in decorated if row["入井状态"] == STATUS_OVERDUE),
            "缺测人数": sum(1 for row in decorated if row["入井状态"] == STATUS_MISSING),
            "已升井人数": sum(1 for row in decorated if row["入井状态"] == STATUS_LIFTED),
        }

    # ---------- 写入 ----------

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        if parse_time(values.get("入井时间")) is None:
            return None, ["入井时间格式"]
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "gaps": [],
            "补登": False,
        }
        for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
            if str(values.get(field) or "").strip():
                entry[field] = str(values[field]).strip()
        rows.append(entry)
        return self._decorate(entry), []

    def run_action(self, entry_id: int, action: str, values: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        if action == "上报缺口":
            return self.report_gap(entry_id, values.get("缺口开始"))
        if action == "续接记录":
            return self.resume_gap(entry_id, values.get("缺口结束"))
        if action == "补登升井":
            return self.supplement_lift(entry_id, values.get("升井时间"))
        return None, f"动作「{action}」不属于入井管理可执行范围"

    def report_gap(self, entry_id: int, start_value: Any = None) -> tuple[dict[str, Any] | None, str]:
        """定位数据中断：在原记录上开一段缺口，状态转为缺测；重复上报不生效。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"入井记录 {entry_id} 不存在或已归档"
        if self._lifted_at(entry) is not None:
            return None, "该记录已升井，不能再登记数据缺口"
        gaps = entry.setdefault("gaps", [])
        open_gap = next((gap for gap in gaps if not gap.get("结束时间")), None)
        if open_gap is not None:
            # 已经开过缺口：只记一次，保留首次缺口开始时间
            return self._decorate(entry), "缺口已登记过，开始时间以首次上报为准，不重复记录"
        started = parse_time(start_value) if start_value else self._now_ref()
        if started is None:
            return None, "缺口开始时间格式无法识别，请使用 年-月-日 时:分:秒"
        entry_time = parse_time(entry.get("入井时间"))
        if entry_time is not None and started < entry_time:
            return None, "缺口开始时间不能早于入井时间"
        gaps.append({
            "开始时间": format_time(started),
            "结束时间": None,
            "来源": "值班登记",
        })
        return self._decorate(entry), "数据缺口已登记，记录标记为缺测"

    def resume_gap(self, entry_id: int, end_value: Any = None) -> tuple[dict[str, Any] | None, str]:
        """数据恢复：把缺口接在原记录上；对已闭合的缺口重复续接不生效。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"入井记录 {entry_id} 不存在或已归档"
        gaps = entry.setdefault("gaps", [])
        open_gap = next((gap for gap in gaps if not gap.get("结束时间")), None)
        if open_gap is None:
            if gaps:
                return self._decorate(entry), "缺口已续接过，结束时间以首次续接为准，不重复记录"
            return None, "该记录没有待续接的数据缺口"
        ended = parse_time(end_value) if end_value else self._now_ref()
        if ended is None:
            return None, "缺口结束时间格式无法识别，请使用 年-月-日 时:分:秒"
        started = parse_time(open_gap.get("开始时间"))
        if started is not None and ended < started:
            return None, "缺口结束时间不能早于开始时间"
        open_gap["结束时间"] = format_time(ended)
        status = self._compute_status(entry)
        message = "数据已续接回原记录"
        if status == STATUS_OVERDUE:
            message += "；累计在井时长已超限，转为超时未升"
        return self._decorate(entry), message

    def supplement_lift(self, entry_id: int, lift_value: Any = None) -> tuple[dict[str, Any] | None, str]:
        """补登升井：缺测/超时未升都能回到已升井；补登时刻只记一次，重复补登不生效。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"入井记录 {entry_id} 不存在或已归档"
        if self._lifted_at(entry) is not None:
            return self._decorate(entry), "升井记录已存在，补登不生效（升井时间以首次记录为准）"
        lifted = parse_time(lift_value) if lift_value else self._now_ref()
        if lifted is None:
            return None, "升井时间格式无法识别，请使用 年-月-日 时:分:秒"
        entry_time = parse_time(entry.get("入井时间"))
        if entry_time is not None and lifted < entry_time:
            return None, "升井时间不能早于入井时间"
        # 未闭合的缺口随补登一并闭合：人已确认升井，缺口截止到补登时刻
        open_gap = next((gap for gap in entry.get("gaps", []) if not gap.get("结束时间")), None)
        if open_gap is not None and not open_gap.get("结束时间"):
            open_gap["结束时间"] = format_time(lifted)
            open_gap["闭合方式"] = "补登升井时闭合"
        entry["升井时间"] = format_time(lifted)
        entry["补登"] = True
        entry["补登时刻"] = format_time(self._now_ref())
        return self._decorate(entry), "升井已补登，记录回到已升井（补登时刻仅记录一次）"

    # ---------- 存量回填 ----------

    def backfill_legacy(self) -> dict[str, int]:
        """按入井日期回填存量数据：幂等，只补结构缺失的老记录。

        - 有升井时间：保持已升井，补齐缺口/补登字段；
        - 无升井时间、超过规定时长：开一段缺口（缺测），与“持续在线超时”分开；
        - 已经是新结构的记录原样保留。
        """
        migrated = 0
        for entry in store.rows(MODULE):
            if "gaps" in entry:
                continue
            entry.setdefault("gaps", [])
            entry.setdefault("补登", False)
            migrated += 1
            lifted = self._lifted_at(entry)
            if lifted is not None:
                # 老数据升井时间字段保留，由判定逻辑给出已升井
                continue
            entered = parse_time(entry.get("入井时间"))
            if entered is not None and self._now_ref() - entered > MAX_DURATION:
                entry["gaps"].append({
                    "开始时间": format_time(entered + MAX_DURATION),
                    "结束时间": None,
                    "来源": "存量回填",
                })
        return {"回填记录数": migrated}

    # ---------- 判定与组装 ----------

    def _lifted_at(self, entry: dict[str, Any]) -> datetime | None:
        return parse_time(entry.get("升井时间"))

    def _open_gap(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        return next((gap for gap in entry.get("gaps", []) if not gap.get("结束时间")), None)

    def _compute_status(self, entry: dict[str, Any]) -> str:
        """统一判定：已升井 > 缺测（有未闭合缺口）> 超时未升 > 入井中。"""
        if self._lifted_at(entry) is not None:
            return STATUS_LIFTED
        if self._open_gap(entry) is not None:
            return STATUS_MISSING
        entered = parse_time(entry.get("入井时间"))
        if entered is not None and self._now_ref() - entered > MAX_DURATION:
            # 没有缺口却超过时长仍未升井：按持续在线判超时，人员定位侧应仍在井下
            if self._personnel_online(entry):
                return STATUS_OVERDUE
        return STATUS_UNDERGROUND

    def _personnel_online(self, entry: dict[str, Any]) -> bool:
        """与人员定位在线状态对照：终端在线/低电量视为定位仍在井下；

        终端离线或找不到对应终端时，不能据此判“持续在线超时”，保守按入井中处理，
        由值班人员核实后再登记缺口或补登。
        """
        terminal_no = str(entry.get("定位终端编号") or "").strip()
        if not terminal_no:
            return False
        for row in store.rows(PERSONNEL_MODULE):
            if str(row.get("终端编号") or "").strip() == terminal_no:
                return str(row.get("status") or "") in {"在线", "低电量"}
        return False

    def _decorate(self, entry: dict[str, Any]) -> dict[str, Any]:
        """列表/详情统一补充：实时状态、缺口时段、在井时长、人员定位对照。"""
        result = dict(entry)
        status = self._compute_status(entry)
        result["入井状态"] = status
        result["status"] = status
        result["pending"] = status != STATUS_LIFTED
        result["abnormal"] = status in {STATUS_OVERDUE, STATUS_MISSING}

        gaps = list(entry.get("gaps", []))
        result["gaps"] = [dict(gap) for gap in gaps]
        open_gap = next((gap for gap in gaps if not gap.get("结束时间")), None)
        if open_gap is not None:
            result["缺口开始"] = open_gap["开始时间"]
            result["缺口结束"] = None
            result["缺口时段"] = f"{open_gap['开始时间']} 起数据中断，待续接"
        elif gaps:
            latest = gaps[-1]
            result["缺口开始"] = latest["开始时间"]
            result["缺口结束"] = latest["结束时间"]
            result["缺口时段"] = f"{latest['开始时间']} ~ {latest['结束时间']}（已续接）"
        else:
            result["缺口开始"] = None
            result["缺口结束"] = None
            result["缺口时段"] = None

        result["升井时间显示"] = entry.get("升井时间") if entry.get("升井时间") else None
        entered = parse_time(entry.get("入井时间"))
        lifted = self._lifted_at(entry)
        end = lifted or self._now_ref()
        if entered is not None:
            duration = max(end - entered, timedelta())
            total_seconds = int(duration.total_seconds())
            result["在井时长"] = f"{total_seconds // 3600}小时{(total_seconds % 3600) // 60}分"
            result["已超时"] = lifted is None and duration > MAX_DURATION and open_gap is None
            result["规定时长小时"] = int(MAX_DURATION.total_seconds() // 3600)
        else:
            result["在井时长"] = None
            result["已超时"] = False
            result["规定时长小时"] = int(MAX_DURATION.total_seconds() // 3600)

        result["补登"] = bool(entry.get("补登"))
        result["补登时刻"] = entry.get("补登时刻")
        result["定位终端编号"] = entry.get("定位终端编号")
        result.update(self._personnel_view(entry))
        return result

    def _personnel_view(self, entry: dict[str, Any]) -> dict[str, Any]:
        terminal_no = str(entry.get("定位终端编号") or "").strip()
        if not terminal_no:
            return {"定位终端状态": None, "定位所在位置": None, "定位对照": "未绑定定位终端"}
        for row in store.rows(PERSONNEL_MODULE):
            if str(row.get("终端编号") or "").strip() == terminal_no:
                terminal_status = str(row.get("status") or "")
                location = row.get("所在位置")
                entry_status = self._compute_status(entry)
                online = terminal_status in {"在线", "低电量"}
                if entry_status == STATUS_MISSING:
                    cross = "终端离线，与缺测状态一致" if terminal_status == "离线" else f"终端{terminal_status}，请核实中断原因"
                elif entry_status in {STATUS_UNDERGROUND, STATUS_OVERDUE}:
                    cross = f"终端{terminal_status}，人在井下" if online else "终端未在线，请核实人员位置"
                else:
                    cross = f"终端{terminal_status}"
                return {
                    "定位终端状态": terminal_status,
                    "定位所在位置": location,
                    "定位对照": cross,
                }
        return {"定位终端状态": None, "定位所在位置": None, "定位对照": "未找到该定位终端"}
