"""Deterministic non-production shift windows, checks and their source records."""

from datetime import date, datetime, time, timedelta, timezone

ROLES = ("PE", "EE")
SHIFT_TZ = timezone(timedelta(hours=8))
CHECK_REFERENCE_PATTERN = r"^(PE|EE)/20[0-9]{2}-[0-9]{2}-[0-9]{2}/(day|night)/[a-z-]{1,24}$"


class ChecklistError(ValueError):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code


def allowed_roles(principal):
    if getattr(principal, "authentication_scheme", "") != "verified":
        return ROLES
    roles = {role.upper() for role in principal.roles}
    return tuple(role for role in ROLES if role in roles)


def _window(work_date, shift):
    start = datetime.combine(work_date, time(8 if shift == "day" else 20), SHIFT_TZ)
    end = start + timedelta(hours=12)
    return start, end


def checklist(principal, role, work_date, shift):
    if role not in allowed_roles(principal):
        raise ChecklistError(403, "CAPABILITY_DENIED", "当前身份无权查看该岗位的开班检查")
    if shift not in {"day", "night"} or not 2000 <= work_date.year < 2100:
        raise ChecklistError(422, "VALIDATION_ERROR", "无效的班次或日期")
    start, end = _window(work_date, shift)
    report = "/display_mock_data/reports/"
    updated = (start + timedelta(minutes=30)).isoformat()
    previous = start - timedelta(hours=12)
    if role == "PE":
        samples = [
            ("lots", "暂挂 / 重点 Lot", "exception", "MES 批次队列（合成）", report + "wip.html",
             [{"object": "LOT-SHIFT-001", "detail": "暂挂待复核", "observed_at": updated}]),
            ("metrology", "制程量测", "unavailable" if shift == "night" else "clear", "SPC 量测（合成）",
             report + "spc.html", []),
        ]
    else:
        samples = [
            ("alarms", "设备报警", "exception", "设备事件时间线（合成）", report + "alarms.html",
             [{"object": "CMP-02", "detail": "设备温度报警待排查", "observed_at": updated}]),
            ("equipment", "设备状态", "error" if shift == "night" else "clear", "设备状态报表（合成）",
             report + "equipment.html", []),
        ]
    samples.append(
        ("handover", "上一班未结事项", "exception", "值班交接台账（合成）", None, [
            {
                "object": "HO-PE-001" if role == "PE" else "HO-EE-001",
                "detail": "等待量测复核" if role == "PE" else "等待设备点检确认",
                "observed_at": (previous + timedelta(hours=11)).isoformat(),
                "follow_up": "本班工程师确认并回填交接台账",
            }
        ])
    )
    scope = {"start": start.isoformat(), "end": end.isoformat()}
    checks = [
        {
            "id": check_id, "reference": f"{role}/{work_date}/{shift}/{check_id}",
            "title": title, "status": status, "source": source, "report_url": href,
            "updated_at": updated if status in {"clear", "exception"} else None,
            "count": len(records) if status in {"clear", "exception"} else None,
            "window": {"start": previous.isoformat(), "end": start.isoformat()} if check_id == "handover" else scope,
            "origin": "previous_shift" if check_id == "handover" else "current_shift",
            "records": records,
        }
        for check_id, title, status, source, href, records in samples
    ]
    return {"role": role, "work_date": work_date.isoformat(), "shift": shift,
            "window": scope, "checks": checks, "data_mode": "synthetic"}


def read_check(principal, reference):
    role, work_date, shift, check_id = reference.split("/")
    try:
        day = date.fromisoformat(work_date)
    except ValueError:
        raise ChecklistError(422, "VALIDATION_ERROR", "无效的班次日期") from None
    result = checklist(principal, role, day, shift)
    for check in result["checks"]:
        if check["id"] == check_id:
            return check
    raise ChecklistError(404, "RESULT_UNAVAILABLE", "开班检查项不存在")
