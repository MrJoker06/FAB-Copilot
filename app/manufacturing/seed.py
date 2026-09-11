from __future__ import annotations

import argparse
import json
import math
import os
import random
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from ..config import PROJECT_DIR
from ..database import db_session, department_paths, ensure_department_databases, initialize, writable_table
from .processes import MANUFACTURING_STEPS


DEFAULT_SIMULATION_END_DATE = "2026-12-25"
MARKET_PROFILE_ID = "public-2026-market-anchors-v1"
MARKET_PROFILE = {
    "profile_id": MARKET_PROFILE_ID,
    "classification": "synthetic_non_production",
    "forecast_start": "2026-08-11",
    "source_basis": {
        "semi_world_fab_forecast": {
            "url": "https://www.semi.org/en/products-services/market-data/world-fab-forecast",
            "anchor": "installed capacity trend approximately +5% in 2026 and 2027",
        },
        "tsmc_2025_annual_report": {
            "url": "https://investor.tsmc.com/static/annualReports/2025/english/index.html",
            "anchor": "2026 shipment outlook 16-17 million 12-inch equivalent wafers; capacity 17-18 million",
        },
        "umc_2025q2_results": {
            "url": "https://www.umc.com/en/News/press_release/Content/investor/20250730",
            "anchor": "2025 Q2 utilization 76%; 22/28nm revenue share 40%",
        },
    },
    "engineering_assumptions": {
        "scope": "Synthetic non-production fab records; not real fab records or operating guidance.",
        "technology_mix": "28nm targets approximately 40% of lots; remaining 14nm and 40nm are synthetic mix assumptions.",
        "productive_utilization": "Daily equipment productive utilization targets 76-86%, with E10 nonproductive variation.",
        "volume_ramp": "Deterministic approximately 5% compound annual lot-volume ramp.",
        "yield_cycle_recipe_sensor": "Yield, cycle time, recipes, scenarios, sensors, specifications and root causes are engineering assumptions.",
    },
}


PRODUCTS = [
    ("Orion-A1", 28, "Logic28", 0.944),
    ("Orion-A2", 28, "Logic28", 0.936),
    ("Nova-P1", 14, "FinFET14", 0.914),
    ("Nova-P2", 14, "FinFET14", 0.902),
    ("Atlas-M1", 40, "Mixed40", 0.958),
]
STEPS = {
    "LITHO": ["LITHO-01", "LITHO-02", "LITHO-03"],
    "ETCH": ["ETCH-01", "ETCH-02", "ETCH-03", "ETCH-04"],
    "CVD": ["CVD-01", "CVD-02", "CVD-03"],
    "PVD": ["PVD-01", "PVD-02", "PVD-03"],
    "DIFFUSION": ["DIFFUSION-01", "DIFFUSION-02", "DIFFUSION-03"],
    "IMPLANT": ["IMPLANT-01", "IMPLANT-02", "IMPLANT-03"],
    "CMP": ["CMP-01", "CMP-02", "CMP-03"],
    "CLEAN": ["CLEAN-01", "CLEAN-02", "CLEAN-03"],
    "METROLOGY": ["METROLOGY-01", "METROLOGY-02", "METROLOGY-03"],
}
assert tuple(STEPS) == MANUFACTURING_STEPS
EVENT_REASONS = {
    "LITHO": {
        "Alarm": ["Focus servo warning", "Reticle handler timeout", "Stage temperature unstable"],
        "Unscheduled Down": ["Exposure source fault", "Wafer stage encoder fault", "Vacuum chuck leak"],
    },
    "ETCH": {
        "Alarm": ["Chamber pressure unstable", "RF matching warning", "Endpoint signal weak"],
        "Unscheduled Down": ["Vacuum pump fault", "RF generator fault", "Endpoint sensor failure"],
    },
    "CVD": {
        "Alarm": ["Chamber pressure unstable", "Temperature interlock", "MFC deviation"],
        "Unscheduled Down": ["Vacuum pump fault", "Heater zone fault", "MFC controller failure"],
    },
    "CMP": {
        "Alarm": ["Slurry flow low", "Pad conditioner torque high", "Carrier pressure unstable"],
        "Unscheduled Down": ["Platen motor fault", "Slurry pump failure", "Carrier head leak"],
    },
    "PVD": {
        "Alarm": ["Target power unstable", "Base pressure high", "Cooling water warning"],
        "Unscheduled Down": ["DC power supply fault", "Cryopump fault", "Target clamp failure"],
    },
    "DIFFUSION": {
        "Alarm": ["Tube temperature deviation", "Gas cabinet warning", "Boat loader timeout"],
        "Unscheduled Down": ["Heater zone failure", "Quartz tube leak", "Exhaust interlock"],
    },
    "IMPLANT": {
        "Alarm": ["Beam current unstable", "Dose monitor warning", "Source pressure high"],
        "Unscheduled Down": ["Ion source failure", "Magnet power fault", "End station vacuum fault"],
    },
    "CLEAN": {
        "Alarm": ["Chemical concentration warning", "Spin speed deviation", "Rinse resistivity low"],
        "Unscheduled Down": ["Chemical pump fault", "Robot transfer fault", "Exhaust flow interlock"],
    },
    "METROLOGY": {
        "Alarm": ["Reference drift warning", "Autofocus retry high", "Stage repeatability warning"],
        "Unscheduled Down": ["Light source failure", "Stage controller fault", "Detector communication fault"],
    },
}
DEFECTS = {
    "LITHO": ["Overlay", "Focus", "Particle"],
    "ETCH": ["Residue", "Micro-trench", "CD Shift"],
    "CVD": ["Particle", "Thickness", "Non-uniformity"],
    "CMP": ["Scratch", "Dishing", "Erosion"],
    "PVD": ["Thickness", "Particle", "Peeling"],
    "DIFFUSION": ["Sheet Resistance", "Slip", "Oxide Non-uniformity"],
    "IMPLANT": ["Dose Shift", "Channeling", "Particle"],
    "CLEAN": ["Particle", "Watermark", "Metal Contamination"],
    "METROLOGY": ["Measurement Drift", "False Defect", "Correlation"],
}

MEASUREMENTS = {
    "LITHO": ("Overlay X", "nm", -4.0, 4.0, 0.0, 0.65),
    "ETCH": ("CD bias", "nm", -3.0, 3.0, 0.0, 0.55),
    "CVD": ("Film thickness", "nm", 95.0, 105.0, 100.0, 1.45),
    "PVD": ("Film thickness", "nm", 48.0, 52.0, 50.0, 0.34),
    "DIFFUSION": ("Sheet resistance", "ohm/sq", 95.0, 105.0, 100.0, 1.05),
    "IMPLANT": ("Dose index", "% target", 98.0, 102.0, 100.0, 0.36),
    "CMP": ("Removal rate", "nm/min", 285.0, 315.0, 300.0, 3.2),
    "CLEAN": ("Particle adders", "count", None, 5.0, 1.2, 0.55),
    "METROLOGY": ("Gauge correlation", "R2", 0.90, None, 0.97, 0.012),
}

# Repeated module visits approximate a layered wafer route instead of treating each
# process family as a single pass. The exact recipes remain synthetic.
ROUTE_SEQUENCE = (
    ("CLEAN", "FEOL-START"), ("DIFFUSION", "WELL"), ("IMPLANT", "WELL"),
    ("LITHO", "GATE"), ("ETCH", "GATE"), ("CVD", "SPACER"),
    ("ETCH", "SPACER"), ("CLEAN", "POST-ETCH"), ("IMPLANT", "SOURCE-DRAIN"),
    ("DIFFUSION", "ANNEAL"), ("CVD", "ILD"), ("CMP", "ILD"),
    ("METROLOGY", "ILD"), ("LITHO", "METAL-1"), ("ETCH", "VIA-1"),
    ("PVD", "METAL-1"), ("CMP", "METAL-1"), ("METROLOGY", "FINAL"),
)

SENSOR_PROFILES = {
    "LITHO": [("Focus offset", "nm", 0.0, 18.0), ("Exposure dose", "mJ/cm2", 24.0, 0.35), ("Overlay X", "nm", 0.0, 1.0), ("Alignment score", "index", 0.94, 0.025), ("Stage temperature", "C", 22.0, 0.12), ("Resist thickness", "nm", 1100.0, 18.0)],
    "ETCH": [("RF source power", "W", 900.0, 18.0), ("RF bias power", "W", 185.0, 6.0), ("Chamber pressure", "Torr", 0.09, 0.006), ("Endpoint time", "s", 88.0, 4.5), ("CF4 flow", "sccm", 82.0, 1.7), ("CD bias", "nm", 0.0, 0.7)],
    "CVD": [("Wafer temperature", "C", 405.0, 2.2), ("Chamber pressure", "Torr", 2.2, 0.06), ("SiH4 flow", "sccm", 145.0, 2.8), ("Deposition rate", "nm/min", 32.5, 0.8), ("Film thickness", "nm", 100.0, 1.5), ("Within-wafer non-uniformity", "%", 1.85, 0.24)],
    "PVD": [("DC target power", "kW", 8.2, 0.16), ("Base pressure", "Torr", 0.000006, 0.000001), ("Argon flow", "sccm", 42.0, 1.1), ("Deposition rate", "nm/min", 21.0, 0.55), ("Film thickness", "nm", 50.0, 0.36), ("Film stress", "MPa", 120.0, 14.0)],
    "DIFFUSION": [("Zone 1 temperature", "C", 925.0, 2.5), ("Zone 2 temperature", "C", 925.0, 2.2), ("Zone 3 temperature", "C", 925.0, 2.6), ("O2 flow", "slm", 8.0, 0.15), ("Boat position", "mm", 0.0, 0.35), ("Sheet resistance", "ohm/sq", 100.0, 1.1)],
    "IMPLANT": [("Beam current", "mA", 4.8, 0.15), ("Dose monitor", "% target", 100.0, 0.35), ("Implant energy", "keV", 45.0, 0.25), ("Tilt angle", "deg", 7.0, 0.08), ("End station vacuum", "Torr", 0.00002, 0.000003), ("Source pressure", "Torr", 0.004, 0.0003)],
    "CMP": [("Carrier pressure", "psi", 3.1, 0.1), ("Platen current", "A", 12.5, 0.55), ("Slurry flow", "ml/min", 220.0, 6.0), ("Pad conditioner torque", "Nm", 3.8, 0.22), ("Removal rate", "nm/min", 300.0, 3.4), ("WIWNU", "%", 2.1, 0.3)],
    "CLEAN": [("Chemical concentration", "%", 2.0, 0.06), ("UPW resistivity", "Mohm-cm", 18.1, 0.12), ("Filter differential pressure", "kPa", 32.0, 2.0), ("Spin speed", "rpm", 1450.0, 16.0), ("Contact angle", "deg", 12.0, 1.2), ("Particle adders", "count", 1.2, 0.7)],
    "METROLOGY": [("Reference bias", "nm", 0.0, 0.18), ("Repeatability", "nm", 0.42, 0.06), ("Tool correlation", "R2", 0.97, 0.012), ("Autofocus retries", "count", 0.5, 0.55), ("Stage temperature", "C", 22.0, 0.1), ("Reference wafer age", "runs", 70.0, 24.0)],
}

SCENARIO_DEFINITIONS = {
    "LITHO": ("SIM-LITHO-OVERLAY", "LITHO-02", 80, "LITHO-OVL-HI", "Reticle alignment reference drift", "Overlay X,Alignment score,Reference bias"),
    "ETCH": ("SIM-ETCH-ENDPOINT", "ETCH-04", 75, "ETCH-CD-HI", "Endpoint window shifted by chamber wall condition", "Endpoint time,CD bias,Chamber pressure"),
    "CVD": ("SIM-CVD-THICKNESS", "CVD-02", 70, "CVD-THK-HI", "MFC zero drift after extended chamber seasoning", "Film thickness,SiH4 flow,Within-wafer non-uniformity"),
    "PVD": ("SIM-PVD-TARGET", "PVD-02", 55, "PVD-THK-LOW", "Target erosion changes deposition rate", "DC target power,Deposition rate,Film thickness"),
    "DIFFUSION": ("SIM-DIFF-ZONE", "DIFFUSION-03", 65, "DIFF-RS-HI", "Furnace center-zone thermocouple bias", "Zone 2 temperature,Sheet resistance,Boat position"),
    "IMPLANT": ("SIM-IMP-DOSE", "IMPLANT-03", 45, "IMP-DOSE-HI", "Dose monitor gain drift", "Dose monitor,Beam current,Source pressure"),
    "CMP": ("SIM-CMP-PAD", "CMP-03", 95, "CMP-SCRATCH", "Pad conditioner wear and slurry agglomeration", "Pad conditioner torque,Platen current,Particle adders"),
    "CLEAN": ("SIM-CLEAN-PARTICLE", "CLEAN-02", 60, "CLEAN-PARTICLE-HI", "Recirculation filter loading", "Particle adders,Filter differential pressure,UPW resistivity"),
    "METROLOGY": ("SIM-METRO-CAL", "METROLOGY-02", 50, "METRO-CORR-LOW", "Reference wafer calibration interval exceeded", "Tool correlation,Reference bias,Reference wafer age"),
}

WAFER_PATTERNS = ["None", "Center", "Donut", "Edge-Loc", "Edge-Ring", "Loc", "Random", "Scratch", "Near-Full"]
WAFER_PATTERN_WEIGHTS = [85.2, 1.0, 0.7, 2.4, 1.8, 3.2, 3.0, 1.5, 1.2]


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _seed_knowledge(connection, database_path: Path | None = None) -> int:
    catalog_path = PROJECT_DIR / "knowledge" / "catalog.json"
    catalog_items = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog = {item["source"]: item for item in catalog_items}
    markdown_paths = [PROJECT_DIR / "knowledge" / item["source"] for item in catalog_items]
    markdown_sources = {path.name for path in (PROJECT_DIR / "knowledge").glob("*.md")}
    if markdown_sources != set(catalog):
        raise ValueError(f"知识目录与文档不一致: files={sorted(markdown_sources)}, catalog={sorted(catalog)}")
    documents_table = writable_table("knowledge_documents", database_path)
    chunks_table = writable_table("knowledge_chunks", database_path)
    fts_table = "knowledge_trigram_fts" if database_path is not None else "knowledge.knowledge_trigram_fts"
    sequence_table = "sqlite_sequence" if database_path is not None else "knowledge.sqlite_sequence"
    connection.execute(f"DELETE FROM {chunks_table}")
    connection.execute(f"DELETE FROM {documents_table}")
    connection.execute(f"DELETE FROM {sequence_table} WHERE name = 'knowledge_chunks'")
    for item in catalog_items:
        connection.execute(
            f"""INSERT INTO {documents_table}(
                   source, title, doc_type, version, status, effective_date, owner,
                   authority, process_steps, equipment_families, tags
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item["source"], item["title"], item["doc_type"], item["version"],
                item["status"], item["effective_date"], item["owner"], item["authority"],
                ", ".join(item["process_steps"]), ", ".join(item["equipment_families"]),
                ", ".join(item["tags"]),
            ),
        )
    count = 0
    for path in markdown_paths:
        title = catalog[path.name]["title"]
        section = "概述"
        buffer: list[str] = []

        def flush() -> None:
            nonlocal count, buffer
            content = "\n".join(buffer).strip()
            if not content:
                return
            connection.execute(
                f"INSERT INTO {chunks_table}(title, source, section, content) VALUES (?, ?, ?, ?)",
                (title, path.name, section, content),
            )
            count += 1
            buffer = []

        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                flush()
                section = line[3:].strip()
            elif not line.startswith("# "):
                buffer.append(line)
        flush()
    connection.execute(f"INSERT INTO {fts_table}(knowledge_trigram_fts) VALUES ('rebuild')")
    return count


def _seed_cases(connection, database_path: Path | None = None) -> int:
    case_path = PROJECT_DIR / "cases" / "historical_cases.json"
    cases = json.loads(case_path.read_text(encoding="utf-8"))
    governance_path = PROJECT_DIR / "cases" / "catalog.json"
    governance_items = json.loads(governance_path.read_text(encoding="utf-8"))
    governance = {item["case_id"]: item for item in governance_items}
    required = {
        "case_id", "title", "process_step", "equipment_id", "occurred_date",
        "severity", "problem", "solution", "result", "summary", "tags",
    }
    governance_required = {
        "case_id", "equipment_family", "defect_type", "symptoms", "root_cause",
        "root_cause_confidence", "validation_method", "recurrence_status",
        "approved_by", "case_status",
    }
    case_ids = {item["case_id"] for item in cases}
    if case_ids != set(governance):
        raise ValueError("案例正文与治理目录的 case_id 不一致")
    cases_table = writable_table("historical_cases", database_path)
    fts_table = "case_trigram_fts" if database_path is not None else "knowledge.case_trigram_fts"
    connection.execute(f"DELETE FROM {cases_table}")
    for item in cases:
        missing = required.difference(item)
        if missing:
            raise ValueError(f"案例 {item.get('case_id', '<unknown>')} 缺少字段: {sorted(missing)}")
        governance_item = governance[item["case_id"]]
        governance_missing = governance_required.difference(governance_item)
        if governance_missing:
            raise ValueError(f"案例治理 {item['case_id']} 缺少字段: {sorted(governance_missing)}")
        original_tags = item["tags"] if isinstance(item["tags"], list) else [str(item["tags"])]
        tags = ", ".join(dict.fromkeys(original_tags + governance_item["symptoms"]))
        connection.execute(
            f"""INSERT INTO {cases_table}(
                   case_id, title, process_step, equipment_id, occurred_date, severity,
                   problem, solution, result, summary, tags, equipment_family, defect_type,
                   symptoms, root_cause, root_cause_confidence, validation_method,
                   recurrence_status, approved_by, case_status
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item["case_id"], item["title"], item["process_step"], item["equipment_id"],
                item["occurred_date"], item["severity"], item["problem"], item["solution"],
                item["result"], item["summary"], tags, governance_item["equipment_family"],
                governance_item["defect_type"], ", ".join(governance_item["symptoms"]),
                governance_item["root_cause"], governance_item["root_cause_confidence"],
                governance_item["validation_method"], governance_item["recurrence_status"],
                governance_item["approved_by"], governance_item["case_status"],
            ),
        )
    connection.execute(f"INSERT INTO {fts_table}(case_trigram_fts) VALUES ('rebuild')")
    return len(cases)


def seed_reference_data(path: Path | None = None) -> dict:
    initialize(path)
    with db_session(path) as connection:
        knowledge_count = _seed_knowledge(connection, path)
        case_count = _seed_cases(connection, path)
        connection.commit()
    return {"knowledge_chunks": knowledge_count, "historical_cases": case_count}


def _parse_end_date(value: date | str | None) -> date:
    """Resolve an explicit simulation horizon without a wall-clock fallback."""
    if value is None:
        value = os.getenv("FAB_SIMULATION_END_DATE", DEFAULT_SIMULATION_END_DATE)
    if isinstance(value, datetime):
        raise ValueError("end_date must be an ISO date (YYYY-MM-DD), not a datetime")
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError("end_date must be a date, ISO date string, or None")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("end_date must be a strict ISO date (YYYY-MM-DD)") from exc
    if parsed.isoformat() != value:
        raise ValueError("end_date must be a strict ISO date (YYYY-MM-DD)")
    return parsed


def _scenario_anchor_day(end_day: date, forecast_start: date) -> date:
    """Keep deterministic detectable scenarios in the observed, non-forecast segment."""
    return min(end_day, forecast_start - timedelta(days=1))


def _scenario_window(start_day: date, anchor_day: date, active_days: int) -> tuple[date, date] | None:
    scenario_start = max(start_day, anchor_day - timedelta(days=active_days - 1))
    return (scenario_start, anchor_day) if scenario_start <= anchor_day else None


def generate_database(
    path: Path | None = None,
    days: int = 730,
    seed: int = 20260712,
    end_date: date | str | None = None,
) -> dict:
    if days <= 0:
        raise ValueError("days must be positive")
    initialize(path)
    db_path = path or department_paths()["main"]
    rng = random.Random(seed)
    end_day = _parse_end_date(end_date)
    as_of = datetime.combine(end_day, time(23, 59, 59))
    start_day = end_day - timedelta(days=days - 1)
    profile_forecast_start = date.fromisoformat(MARKET_PROFILE["forecast_start"])
    forecast_start = min(max(profile_forecast_start, start_day), end_day)
    scenario_anchor_day = _scenario_anchor_day(end_day, forecast_start)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lots: list[tuple] = []
    runs: list[tuple] = []
    events: list[tuple] = []
    defects: list[tuple] = []
    equipment_states: list[tuple] = []
    wafer_maps: list[tuple] = []
    lot_sequence = 1

    for day_index in range(days):
        current_day = start_day + timedelta(days=day_index)
        seasonal = math.sin(day_index / 34) * 0.006
        # Expected volume follows a deterministic 5% compound annual ramp.
        daily_lots = max(1, round(rng.uniform(11, 15) * (1.05 ** (day_index / 365))))
        for _ in range(daily_lots):
            product, node, route, baseline_yield = rng.choices(
                PRODUCTS, weights=[24, 16, 22, 14, 24], k=1
            )[0]
            lot_id = f"L{current_day:%y%m%d}-{lot_sequence:05d}"
            lot_sequence += 1
            wafer_count = 25
            start_dt = datetime.combine(current_day, time(rng.randint(0, 23), rng.randint(0, 59)))
            priority = rng.choices(["Normal", "Hot", "Super Hot"], [84, 13, 3], k=1)[0]
            base_cycle = {28: 118, 14: 151, 40: 96}[node]
            hold_hours = max(0.0, rng.gauss(3.2, 5.0)) if rng.random() < 0.22 else 0.0
            cycle_time = max(55.0, rng.gauss(base_cycle, 13) + hold_hours)
            complete_dt = start_dt + timedelta(hours=cycle_time)
            status = "Completed"
            if complete_dt.date() > end_day:
                status = rng.choices(["Running", "Hold"], [78, 22], k=1)[0]
                complete_value = None
            else:
                complete_value = complete_dt.isoformat(timespec="seconds")

            equipment_penalty = 0.0
            lot_runs: list[tuple] = []
            lot_scenarios: list[tuple[str, str, datetime, str]] = []
            last_equipment = "CLEAN-01"
            last_step = "CLEAN"
            last_run_dt = start_dt
            for step_index, (step, layer_name) in enumerate(ROUTE_SEQUENCE):
                equipment_options = STEPS[step]
                equipment = rng.choice(equipment_options)
                run_dt = start_dt + timedelta(hours=(step_index + 1) * cycle_time / (len(ROUTE_SEQUENCE) + 1))
                chamber = rng.choice(["A", "B"])
                recipe = f"{step}-{node}N-R{rng.randint(1, 3)}"
                excursion = None
                scenario_id = None
                defect_density = max(0.01, rng.lognormvariate(-2.6, 0.45))
                queue_hours = max(0.03, rng.lognormvariate(-0.25, 0.65))
                rework_flag = int(rng.random() < 0.018)

                measurement_name, measurement_unit, spec_lsl, spec_usl, target, sigma = MEASUREMENTS[step]
                measurement_value = rng.gauss(target, sigma)

                if step == "LITHO":
                    temp, pressure, duration = rng.gauss(22, 0.35), rng.gauss(760, 3), rng.gauss(74, 4)
                    thickness, uniformity = None, None
                elif step == "ETCH":
                    temp, pressure, duration = rng.gauss(58, 1.8), rng.gauss(0.09, 0.008), rng.gauss(96, 6)
                    thickness, uniformity = None, None
                elif step == "CVD":
                    temp, pressure, duration = rng.gauss(405, 3.2), rng.gauss(2.2, 0.08), rng.gauss(184, 8)
                    thickness = rng.gauss(100, 1.45)
                    measurement_value = thickness
                    uniformity = max(0.5, rng.gauss(1.85, 0.28))
                    measurement_value = thickness
                elif step == "CMP":
                    temp, pressure, duration = rng.gauss(24, 0.6), rng.gauss(3.1, 0.12), rng.gauss(132, 8)
                    thickness, uniformity = None, None
                elif step == "PVD":
                    temp, pressure, duration = rng.gauss(190, 3.0), rng.gauss(0.006, 0.0008), rng.gauss(145, 7)
                    thickness, uniformity = measurement_value, max(0.4, rng.gauss(1.5, 0.22))
                elif step == "DIFFUSION":
                    temp, pressure, duration = rng.gauss(925, 4.5), rng.gauss(760, 4), rng.gauss(3100, 120)
                    thickness, uniformity = None, max(0.4, rng.gauss(1.7, 0.24))
                elif step == "IMPLANT":
                    temp, pressure, duration = rng.gauss(23, 0.5), rng.gauss(0.00002, 0.000004), rng.gauss(82, 5)
                    thickness, uniformity = None, None
                elif step == "CLEAN":
                    temp, pressure, duration = rng.gauss(48, 1.2), rng.gauss(760, 3), rng.gauss(240, 12)
                    thickness, uniformity = None, None
                    measurement_value = max(0.0, measurement_value)
                else:
                    temp, pressure, duration = rng.gauss(22, 0.4), rng.gauss(760, 3), rng.gauss(54, 4)
                    thickness, uniformity = None, None

                definition = SCENARIO_DEFINITIONS[step]
                defined_id, affected_equipment, active_days, scenario_code, _, _ = definition
                scenario_age_days = (scenario_anchor_day - run_dt.date()).days
                if equipment == affected_equipment and 0 <= scenario_age_days < active_days:
                    drift = (active_days - scenario_age_days) / active_days
                    scenario_id = defined_id
                    if step == "LITHO":
                        measurement_value += 3.8 * drift
                    elif step == "ETCH":
                        measurement_value += 3.6 * drift
                    elif step == "CVD":
                        measurement_value += 3.5 * drift
                        thickness = measurement_value
                        uniformity += 0.9 * drift
                    elif step == "PVD":
                        measurement_value -= 2.2 * drift
                        thickness = measurement_value
                    elif step == "DIFFUSION":
                        measurement_value += 6.5 * drift
                    elif step == "IMPLANT":
                        measurement_value += 2.15 * drift
                    elif step == "CMP":
                        measurement_value -= 18.0 * drift
                        defect_density += 0.30 * drift
                    elif step == "CLEAN":
                        measurement_value += 5.2 * drift
                    elif step == "METROLOGY":
                        measurement_value -= 0.09 * drift
                    outside_spec = (
                        (spec_lsl is not None and measurement_value < spec_lsl)
                        or (spec_usl is not None and measurement_value > spec_usl)
                        or (step == "CMP" and defect_density > 0.34)
                    )
                    if outside_spec:
                        excursion = scenario_code
                        equipment_penalty += 0.012 + 0.014 * drift
                        if run_dt <= as_of:
                            lot_scenarios.append((scenario_id, step, run_dt, equipment))

                in_spec = not (
                    (spec_lsl is not None and measurement_value < spec_lsl)
                    or (spec_usl is not None and measurement_value > spec_usl)
                )
                pass_flag = int(excursion is None and in_spec and defect_density < 0.48)
                if run_dt <= as_of:
                    lot_runs.append((
                        lot_id, step, equipment, chamber, recipe, run_dt.isoformat(timespec="seconds"),
                        round(temp, 3), round(pressure, 4), round(duration, 2),
                        round(thickness, 3) if thickness is not None else None,
                        round(uniformity, 3) if uniformity is not None else None,
                        round(defect_density, 4), measurement_name, round(measurement_value, 4),
                        measurement_unit, spec_lsl, spec_usl, pass_flag, excursion,
                        step_index + 1, layer_name, round(queue_hours, 3), rework_flag, scenario_id,
                    ))
                    last_equipment = equipment
                    last_step = step
                    last_run_dt = run_dt
                defect_probability = 0.12 + (0.15 if excursion else 0)
                if run_dt <= as_of and rng.random() < defect_probability:
                    defect_type = rng.choice(DEFECTS[step])
                    if excursion == "CMP-SCRATCH":
                        defect_type = "Scratch"
                    elif excursion == "CVD-THK-HI":
                        defect_type = rng.choice(["Thickness", "Non-uniformity"])
                    count = max(1, int(rng.lognormvariate(1.7, 0.55) * (2 if excursion else 1)))
                    disposition = rng.choices(["Accept", "Rework", "Scrap"], [65, 28, 7], k=1)[0]
                    defects.append((lot_id, run_dt.isoformat(timespec="seconds"), step, defect_type, count, disposition))

            if last_run_dt <= as_of:
                pattern = rng.choices(WAFER_PATTERNS, weights=WAFER_PATTERN_WEIGHTS, k=1)[0]
                map_step = last_step
                if lot_scenarios and rng.random() < 0.72:
                    _, map_step, last_run_dt, last_equipment = lot_scenarios[-1]
                    pattern = {
                        "LITHO": "Loc", "ETCH": "Edge-Ring", "CVD": "Center",
                        "PVD": "Donut", "DIFFUSION": "Edge-Loc", "IMPLANT": "Loc",
                        "CMP": "Scratch", "CLEAN": "Random", "METROLOGY": "Near-Full",
                    }[map_step]
                tested_dies = rng.randint(520, 760)
                failed_dies = rng.randint(0, 4) if pattern == "None" else rng.randint(8, 95)
                detected_time = min(last_run_dt, as_of)
                wafer_maps.append((
                    lot_id, rng.randint(1, wafer_count), detected_time.isoformat(timespec="seconds"),
                    map_step, last_equipment, pattern, tested_dies, failed_dies, rng.randint(1, 2_000_000_000),
                ))

            actual_yield = _clip(
                baseline_yield + seasonal + rng.gauss(0, 0.018) - equipment_penalty - hold_hours * 0.0003,
                0.72,
                0.995,
            )
            good_wafers = round(wafer_count * actual_yield)
            lots.append((
                lot_id, product, node, route, priority, start_dt.isoformat(timespec="seconds"),
                complete_value, status, wafer_count, good_wafers, round(actual_yield, 4),
                round(cycle_time, 2), round(hold_hours, 2),
            ))
            runs.extend(lot_runs)

        for equipment in [item for values in STEPS.values() for item in values]:
            state_start = datetime.combine(current_day, time.min)
            productive_minutes = rng.uniform(0.76 * 1440, 0.86 * 1440)
            other_state = rng.choices(
                ["Standby", "Engineering", "Scheduled Downtime", "Unscheduled Downtime", "Non-Scheduled"],
                [46, 18, 19, 7, 10], k=1,
            )[0]
            # Round only after calculating the complement, preserving exactly 1,440 minutes.
            productive_minutes = round(productive_minutes, 1)
            nonproductive_minutes = round(1440.0 - productive_minutes, 1)
            chamber = rng.choice(["A", "B"])
            equipment_states.append((equipment, chamber, state_start.isoformat(timespec="seconds"), productive_minutes, "Productive", "Production lots"))
            equipment_states.append((
                equipment, chamber,
                (state_start + timedelta(minutes=productive_minutes)).isoformat(timespec="seconds"), nonproductive_minutes, other_state,
                {"Standby": "No production demand", "Engineering": "Process qualification", "Scheduled Downtime": "Preventive maintenance", "Unscheduled Downtime": "Equipment fault", "Non-Scheduled": "Facility calendar"}[other_state],
            ))
            if rng.random() < 0.018:
                event_type = rng.choices(["Alarm", "PM", "Unscheduled Down"], [54, 31, 15], k=1)[0]
                severity = {"Alarm": "Medium", "PM": "Info", "Unscheduled Down": "High"}[event_type]
                duration = rng.uniform(8, 75) if event_type != "PM" else rng.uniform(90, 300)
                if event_type == "PM":
                    reason = rng.choice(["Scheduled module clean", "Consumable replacement", "Calibration"])
                else:
                    equipment_step = equipment.split("-", 1)[0]
                    reason = rng.choice(EVENT_REASONS[equipment_step][event_type])
                event_dt = datetime.combine(current_day, time(rng.randint(0, 23), rng.randint(0, 59)))
                events.append((equipment, event_dt.isoformat(timespec="seconds"), event_type, round(duration, 1), severity, reason))

    with db_session(path) as connection:
        tables = {name: writable_table(name, path) for name in (
            "lots", "process_runs", "sensor_readings", "equipment_state_intervals",
            "equipment_events", "defect_records", "wafer_maps", "simulation_scenarios",
            "simulation_metadata",
        )}
        connection.execute(f"DELETE FROM {tables['sensor_readings']}")
        connection.execute(f"DELETE FROM {tables['wafer_maps']}")
        connection.execute(f"DELETE FROM {tables['equipment_state_intervals']}")
        connection.execute(f"DELETE FROM {tables['simulation_scenarios']}")
        connection.execute(f"DELETE FROM {tables['simulation_metadata']}")
        connection.execute(f"DELETE FROM {tables['defect_records']}")
        connection.execute(f"DELETE FROM {tables['process_runs']}")
        connection.execute(f"DELETE FROM {tables['equipment_events']}")
        connection.execute(f"DELETE FROM {tables['lots']}")
        connection.executemany(
            f"INSERT INTO {tables['lots']} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            lots,
        )
        connection.executemany(
            f"""INSERT INTO {tables['process_runs']}(
                lot_id, process_step, equipment_id, chamber, recipe, run_time,
                temperature_c, pressure_torr, duration_sec, thickness_nm,
                uniformity_pct, defect_density, measurement_name, measurement_value,
                measurement_unit, spec_lsl, spec_usl, pass_flag, excursion_code,
                operation_seq, layer_name, queue_hours, rework_flag, scenario_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            runs,
        )
        connection.executemany(
            f"INSERT INTO {tables['equipment_events']}(equipment_id, event_time, event_type, duration_minutes, severity, reason) VALUES (?, ?, ?, ?, ?, ?)",
            events,
        )
        connection.executemany(
            f"INSERT INTO {tables['defect_records']}(lot_id, detected_time, process_step, defect_type, count, disposition) VALUES (?, ?, ?, ?, ?, ?)",
            defects,
        )
        connection.executemany(
            f"""INSERT INTO {tables['equipment_state_intervals']}(
                   equipment_id, chamber, start_time, duration_minutes, semi_e10_state, reason
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            equipment_states,
        )
        connection.executemany(
            f"""INSERT INTO {tables['wafer_maps']}(
                   lot_id, wafer_no, detected_time, process_step, equipment_id,
                   pattern_class, tested_dies, failed_dies, map_seed
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            wafer_maps,
        )
        scenario_rows = []
        for step, definition in SCENARIO_DEFINITIONS.items():
            scenario_id, equipment_id, active_days, scenario_type, root_cause, signals = definition
            scenario_window = _scenario_window(start_day, scenario_anchor_day, active_days)
            if scenario_window is None:
                continue
            scenario_start, scenario_end = scenario_window
            scenario_rows.append((
                scenario_id, step, equipment_id, scenario_type,
                scenario_start.isoformat(), scenario_end.isoformat(),
                root_cause, signals, "SECOM-shape + SEMI-E10 + WM-811K-patterns + NIST-SPC", 0,
            ))
        connection.executemany(
            f"""INSERT INTO {tables['simulation_scenarios']}(
                   scenario_id, process_step, equipment_id, scenario_type, start_date,
                   end_date, root_cause, observable_signals, source_profile, visible_to_agent
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            scenario_rows,
        )
        connection.execute(
            f"""INSERT INTO {tables['simulation_metadata']}(
                   singleton_id, profile_id, classification, start_date, end_date, forecast_start,
                   generated_at, seed, source_basis_json, engineering_assumptions_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                1, MARKET_PROFILE_ID, MARKET_PROFILE["classification"], start_day.isoformat(), end_day.isoformat(),
                forecast_start.isoformat(), generated_at, seed,
                json.dumps(MARKET_PROFILE["source_basis"], sort_keys=True, separators=(",", ":")),
                json.dumps(MARKET_PROFILE["engineering_assumptions"], sort_keys=True, separators=(",", ":")),
            ),
        )

        sensor_count = 0
        sensor_batch: list[tuple] = []
        cursor = connection.execute(
            """SELECT lot_id, operation_seq, process_step, equipment_id, chamber, run_time,
                      measurement_name, measurement_value, scenario_id
               FROM process_runs ORDER BY run_id"""
        )
        for run in cursor:
            for signal_index, (signal_name, unit, mean, sigma) in enumerate(SENSOR_PROFILES[run["process_step"]]):
                is_missing = int(rng.random() < 0.014)
                is_outlier = int(rng.random() < (0.12 if run["scenario_id"] else 0.0025))
                if is_missing:
                    value = None
                elif signal_name == run["measurement_name"]:
                    value = run["measurement_value"]
                else:
                    value = rng.gauss(mean, sigma)
                    if run["scenario_id"] and is_outlier:
                        value += sigma * rng.choice([-1, 1]) * rng.uniform(2.0, 4.2)
                    if unit in {"count", "Torr", "sccm", "slm", "W", "kW", "A", "ml/min", "rpm", "runs"}:
                        value = max(0.0, value)
                    if unit == "R2":
                        value = _clip(value, 0.0, 1.0)
                    value = round(value, 6)
                sample_time = min(
                    datetime.fromisoformat(run["run_time"]) + timedelta(seconds=signal_index * 3), as_of
                )
                sensor_batch.append((
                    run["lot_id"], run["operation_seq"], run["process_step"], run["equipment_id"],
                    run["chamber"], sample_time.isoformat(timespec="seconds"), signal_name, value,
                    unit, is_missing, is_outlier,
                ))
                if len(sensor_batch) >= 25000:
                    connection.executemany(
                        f"""INSERT INTO {tables['sensor_readings']}(
                               lot_id, operation_seq, process_step, equipment_id, chamber,
                               sample_time, signal_name, signal_value, signal_unit, is_missing, is_outlier
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        sensor_batch,
                    )
                    sensor_count += len(sensor_batch)
                    sensor_batch.clear()
        if sensor_batch:
            connection.executemany(
                f"""INSERT INTO {tables['sensor_readings']}(
                       lot_id, operation_seq, process_step, equipment_id, chamber,
                       sample_time, signal_name, signal_value, signal_unit, is_missing, is_outlier
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                sensor_batch,
            )
            sensor_count += len(sensor_batch)
        knowledge_count = _seed_knowledge(connection, path)
        case_count = _seed_cases(connection, path)
        connection.commit()

    return {
        "database": str(db_path),
        "date_range": [start_day.isoformat(), end_day.isoformat()],
        "horizon": {"start_date": start_day.isoformat(), "end_date": end_day.isoformat()},
        "forecast_boundary": forecast_start.isoformat(),
        "profile_id": MARKET_PROFILE_ID,
        "lots": len(lots),
        "process_runs": len(runs),
        "equipment_events": len(events),
        "equipment_state_intervals": len(equipment_states),
        "defect_records": len(defects),
        "sensor_readings": sensor_count,
        "wafer_maps": len(wafer_maps),
        "simulation_scenarios": len(scenario_rows),
        "knowledge_chunks": knowledge_count,
        "historical_cases": case_count,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate deterministic semiconductor fab history")
    parser.add_argument("--days", type=int, default=730)
    parser.add_argument("--end-date", type=_parse_end_date, default=None, help="Strict ISO horizon end date (YYYY-MM-DD)")
    parser.add_argument("--force", action="store_true", help="Regenerate even when the database exists")
    return parser


def _main(
    argv: list[str] | None,
    *,
    ensure_databases=ensure_department_databases,
    session=db_session,
    generate=generate_database,
) -> int:
    args = build_parser().parse_args(argv)
    ensure_databases()
    with session() as connection:
        has_data = bool(connection.execute("SELECT EXISTS(SELECT 1 FROM lots LIMIT 1)").fetchone()[0])
    if has_data and not args.force:
        paths = ", ".join(str(path) for path in department_paths().values())
        print(f"Department databases already exist: {paths}. Use --force to regenerate.")
    else:
        print(generate(days=args.days, end_date=args.end_date))
    return 0


def main(argv: list[str] | None = None) -> int:
    return _main(
        argv,
        ensure_databases=ensure_department_databases,
        session=db_session,
        generate=generate_database,
    )


if __name__ == "__main__":
    raise SystemExit(main())
