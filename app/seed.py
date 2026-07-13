from __future__ import annotations

import argparse
import json
import math
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .config import PROJECT_DIR, get_settings
from .database import db_session, initialize
from .processes import MANUFACTURING_STEPS


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


def _seed_knowledge(connection) -> int:
    catalog_path = PROJECT_DIR / "knowledge" / "catalog.json"
    catalog_items = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog = {item["source"]: item for item in catalog_items}
    markdown_paths = [PROJECT_DIR / "knowledge" / item["source"] for item in catalog_items]
    markdown_sources = {path.name for path in (PROJECT_DIR / "knowledge").glob("*.md")}
    if markdown_sources != set(catalog):
        raise ValueError(f"知识目录与文档不一致: files={sorted(markdown_sources)}, catalog={sorted(catalog)}")
    connection.execute("DELETE FROM knowledge_documents")
    connection.execute("DELETE FROM knowledge_chunks")
    connection.execute("DELETE FROM sqlite_sequence WHERE name = 'knowledge_chunks'")
    for item in catalog_items:
        connection.execute(
            """INSERT INTO knowledge_documents(
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
                "INSERT INTO knowledge_chunks(title, source, section, content) VALUES (?, ?, ?, ?)",
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
    connection.execute("INSERT INTO knowledge_trigram_fts(knowledge_trigram_fts) VALUES ('rebuild')")
    return count


def _seed_cases(connection) -> int:
    path = PROJECT_DIR / "cases" / "historical_cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
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
    connection.execute("DELETE FROM historical_cases")
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
            """INSERT INTO historical_cases(
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
    connection.execute("INSERT INTO case_trigram_fts(case_trigram_fts) VALUES ('rebuild')")
    return len(cases)


def seed_reference_data(path: Path | None = None) -> dict:
    db_path = path or get_settings().database_path
    initialize(db_path)
    with db_session(db_path) as connection:
        knowledge_count = _seed_knowledge(connection)
        case_count = _seed_cases(connection)
        connection.commit()
    return {"knowledge_chunks": knowledge_count, "historical_cases": case_count}


def generate_database(path: Path | None = None, days: int = 730, seed: int = 20260712) -> dict:
    db_path = path or get_settings().database_path
    initialize(db_path)
    rng = random.Random(seed)
    end_day = date.today()
    as_of = datetime.combine(end_day, time(23, 59, 59))
    start_day = end_day - timedelta(days=days - 1)
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
        daily_lots = rng.randint(10, 16)
        for _ in range(daily_lots):
            product, node, route, baseline_yield = rng.choices(
                PRODUCTS, weights=[25, 18, 22, 15, 20], k=1
            )[0]
            lot_id = f"L{current_day:%y%m%d}-{lot_sequence:05d}"
            lot_sequence += 1
            wafer_count = 25
            start_dt = datetime.combine(current_day, time(rng.randint(0, 23), rng.randint(0, 59)))
            age_days = (end_day - current_day).days
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
                if equipment == affected_equipment and age_days < active_days:
                    drift = (active_days - age_days) / active_days
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
                wafer_maps.append((
                    lot_id, rng.randint(1, wafer_count), last_run_dt.isoformat(timespec="seconds"),
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
            state_start = datetime.combine(current_day, time(0, rng.randint(0, 20)))
            productive_minutes = rng.uniform(860, 1330)
            equipment_states.append((equipment, rng.choice(["A", "B"]), state_start.isoformat(timespec="seconds"), round(productive_minutes, 1), "Productive", "Production lots"))
            if rng.random() < 0.62:
                other_state = rng.choices(
                    ["Standby", "Engineering", "Scheduled Downtime", "Unscheduled Downtime", "Non-Scheduled"],
                    [46, 18, 19, 7, 10], k=1,
                )[0]
                equipment_states.append((
                    equipment, rng.choice(["A", "B"]),
                    (state_start + timedelta(minutes=productive_minutes)).isoformat(timespec="seconds"),
                    round(max(10.0, 1440.0 - productive_minutes), 1), other_state,
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

    with db_session(db_path) as connection:
        connection.execute("DELETE FROM sensor_readings")
        connection.execute("DELETE FROM wafer_maps")
        connection.execute("DELETE FROM equipment_state_intervals")
        connection.execute("DELETE FROM simulation_scenarios")
        connection.execute("DELETE FROM defect_records")
        connection.execute("DELETE FROM process_runs")
        connection.execute("DELETE FROM equipment_events")
        connection.execute("DELETE FROM lots")
        connection.executemany("INSERT INTO lots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", lots)
        connection.executemany(
            """INSERT INTO process_runs(
                lot_id, process_step, equipment_id, chamber, recipe, run_time,
                temperature_c, pressure_torr, duration_sec, thickness_nm,
                uniformity_pct, defect_density, measurement_name, measurement_value,
                measurement_unit, spec_lsl, spec_usl, pass_flag, excursion_code,
                operation_seq, layer_name, queue_hours, rework_flag, scenario_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            runs,
        )
        connection.executemany(
            "INSERT INTO equipment_events(equipment_id, event_time, event_type, duration_minutes, severity, reason) VALUES (?, ?, ?, ?, ?, ?)",
            events,
        )
        connection.executemany(
            "INSERT INTO defect_records(lot_id, detected_time, process_step, defect_type, count, disposition) VALUES (?, ?, ?, ?, ?, ?)",
            defects,
        )
        connection.executemany(
            """INSERT INTO equipment_state_intervals(
                   equipment_id, chamber, start_time, duration_minutes, semi_e10_state, reason
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            equipment_states,
        )
        connection.executemany(
            """INSERT INTO wafer_maps(
                   lot_id, wafer_no, detected_time, process_step, equipment_id,
                   pattern_class, tested_dies, failed_dies, map_seed
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            wafer_maps,
        )
        scenario_rows = []
        for step, definition in SCENARIO_DEFINITIONS.items():
            scenario_id, equipment_id, active_days, scenario_type, root_cause, signals = definition
            scenario_rows.append((
                scenario_id, step, equipment_id, scenario_type,
                (end_day - timedelta(days=active_days - 1)).isoformat(), end_day.isoformat(),
                root_cause, signals, "SECOM-shape + SEMI-E10 + WM-811K-patterns + NIST-SPC", 0,
            ))
        connection.executemany(
            """INSERT INTO simulation_scenarios(
                   scenario_id, process_step, equipment_id, scenario_type, start_date,
                   end_date, root_cause, observable_signals, source_profile, visible_to_agent
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            scenario_rows,
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
                sample_time = datetime.fromisoformat(run["run_time"]) + timedelta(seconds=signal_index * 3)
                sensor_batch.append((
                    run["lot_id"], run["operation_seq"], run["process_step"], run["equipment_id"],
                    run["chamber"], sample_time.isoformat(timespec="seconds"), signal_name, value,
                    unit, is_missing, is_outlier,
                ))
                if len(sensor_batch) >= 25000:
                    connection.executemany(
                        """INSERT INTO sensor_readings(
                               lot_id, operation_seq, process_step, equipment_id, chamber,
                               sample_time, signal_name, signal_value, signal_unit, is_missing, is_outlier
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        sensor_batch,
                    )
                    sensor_count += len(sensor_batch)
                    sensor_batch.clear()
        if sensor_batch:
            connection.executemany(
                """INSERT INTO sensor_readings(
                       lot_id, operation_seq, process_step, equipment_id, chamber,
                       sample_time, signal_name, signal_value, signal_unit, is_missing, is_outlier
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                sensor_batch,
            )
            sensor_count += len(sensor_batch)
        knowledge_count = _seed_knowledge(connection)
        case_count = _seed_cases(connection)
        connection.commit()

    return {
        "database": str(db_path),
        "date_range": [start_day.isoformat(), end_day.isoformat()],
        "lots": len(lots),
        "process_runs": len(runs),
        "equipment_events": len(events),
        "equipment_state_intervals": len(equipment_states),
        "defect_records": len(defects),
        "sensor_readings": sensor_count,
        "wafer_maps": len(wafer_maps),
        "simulation_scenarios": len(SCENARIO_DEFINITIONS),
        "knowledge_chunks": knowledge_count,
        "historical_cases": case_count,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate deterministic semiconductor fab history")
    parser.add_argument("--days", type=int, default=730)
    parser.add_argument("--force", action="store_true", help="Regenerate even when the database exists")
    args = parser.parse_args()
    target = get_settings().database_path
    if target.exists() and not args.force:
        print(f"Database already exists: {target}. Use --force to regenerate.")
    else:
        print(generate_database(target, days=args.days))
