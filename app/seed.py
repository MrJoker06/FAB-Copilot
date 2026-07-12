from __future__ import annotations

import argparse
import math
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .config import PROJECT_DIR, get_settings
from .database import connect, initialize


PRODUCTS = [
    ("Orion-A1", 28, "Logic28", 0.944),
    ("Orion-A2", 28, "Logic28", 0.936),
    ("Nova-P1", 14, "FinFET14", 0.914),
    ("Nova-P2", 14, "FinFET14", 0.902),
    ("Atlas-M1", 40, "Mixed40", 0.958),
]
STEPS = {
    "LITHO": ["LITHO-01", "LITHO-02", "LITHO-03"],
    "ETCH": ["ETCH-01", "ETCH-02", "ETCH-03"],
    "CVD": ["CVD-01", "CVD-02", "CVD-03"],
    "CMP": ["CMP-01", "CMP-02", "CMP-03"],
}
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
}
DEFECTS = {
    "LITHO": ["Overlay", "Focus", "Particle"],
    "ETCH": ["Residue", "Micro-trench", "CD Shift"],
    "CVD": ["Particle", "Thickness", "Non-uniformity"],
    "CMP": ["Scratch", "Dishing", "Erosion"],
}


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _seed_knowledge(connection) -> int:
    connection.execute("DELETE FROM knowledge_fts")
    connection.execute("DELETE FROM knowledge_chunks")
    count = 0
    for path in sorted((PROJECT_DIR / "knowledge").glob("*.md")):
        title = path.stem.replace("_", " ")
        section = "概述"
        buffer: list[str] = []

        def flush() -> None:
            nonlocal count, buffer
            content = "\n".join(buffer).strip()
            if not content:
                return
            cursor = connection.execute(
                "INSERT INTO knowledge_chunks(title, source, section, content) VALUES (?, ?, ?, ?)",
                (title, path.name, section, content),
            )
            connection.execute(
                "INSERT INTO knowledge_fts(rowid, title, section, content) VALUES (?, ?, ?, ?)",
                (cursor.lastrowid, title, section, content),
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
    return count


def generate_database(path: Path | None = None, days: int = 548, seed: int = 20260712) -> dict:
    db_path = path or get_settings().database_path
    initialize(db_path)
    rng = random.Random(seed)
    end_day = date.today()
    start_day = end_day - timedelta(days=days - 1)
    lots: list[tuple] = []
    runs: list[tuple] = []
    events: list[tuple] = []
    defects: list[tuple] = []
    lot_sequence = 1

    for day_index in range(days):
        current_day = start_day + timedelta(days=day_index)
        seasonal = math.sin(day_index / 34) * 0.006
        daily_lots = rng.randint(3, 6)
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
            for step_index, (step, equipment_options) in enumerate(STEPS.items()):
                equipment = rng.choice(equipment_options)
                run_dt = start_dt + timedelta(hours=(step_index + 1) * cycle_time / 5)
                chamber = rng.choice(["A", "B"])
                recipe = f"{step}-{node}N-R{rng.randint(1, 3)}"
                excursion = None
                defect_density = max(0.01, rng.lognormvariate(-2.6, 0.45))

                if step == "LITHO":
                    temp, pressure, duration = rng.gauss(22, 0.35), rng.gauss(760, 3), rng.gauss(74, 4)
                    thickness, uniformity = None, None
                elif step == "ETCH":
                    temp, pressure, duration = rng.gauss(58, 1.8), rng.gauss(0.09, 0.008), rng.gauss(96, 6)
                    thickness, uniformity = None, None
                elif step == "CVD":
                    temp, pressure, duration = rng.gauss(405, 3.2), rng.gauss(2.2, 0.08), rng.gauss(184, 8)
                    thickness = rng.gauss(100, 1.45)
                    uniformity = max(0.5, rng.gauss(1.85, 0.28))
                    if equipment == "CVD-02" and age_days < 70:
                        drift = (70 - age_days) / 70
                        thickness += 3.5 * drift
                        uniformity += 0.9 * drift
                        defect_density += 0.12 * drift
                        if thickness > 103.0 or uniformity > 2.55:
                            excursion = "CVD-THK-HI"
                            equipment_penalty += 0.018
                else:
                    temp, pressure, duration = rng.gauss(24, 0.6), rng.gauss(3.1, 0.12), rng.gauss(132, 8)
                    thickness, uniformity = None, None
                    if equipment == "CMP-03" and age_days < 95:
                        drift = (95 - age_days) / 95
                        defect_density += 0.28 * drift
                        if defect_density > 0.34:
                            excursion = "CMP-SCRATCH"
                            equipment_penalty += 0.024

                pass_flag = int(excursion is None and defect_density < 0.48)
                lot_runs.append((
                    lot_id, step, equipment, chamber, recipe, run_dt.isoformat(timespec="seconds"),
                    round(temp, 3), round(pressure, 4), round(duration, 2),
                    round(thickness, 3) if thickness is not None else None,
                    round(uniformity, 3) if uniformity is not None else None,
                    round(defect_density, 4), pass_flag, excursion,
                ))
                defect_probability = 0.12 + (0.15 if excursion else 0)
                if rng.random() < defect_probability:
                    defect_type = rng.choice(DEFECTS[step])
                    if excursion == "CMP-SCRATCH":
                        defect_type = "Scratch"
                    elif excursion == "CVD-THK-HI":
                        defect_type = rng.choice(["Thickness", "Non-uniformity"])
                    count = max(1, int(rng.lognormvariate(1.7, 0.55) * (2 if excursion else 1)))
                    disposition = rng.choices(["Accept", "Rework", "Scrap"], [65, 28, 7], k=1)[0]
                    defects.append((lot_id, run_dt.isoformat(timespec="seconds"), step, defect_type, count, disposition))

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

    with connect(db_path) as connection:
        connection.execute("DELETE FROM defect_records")
        connection.execute("DELETE FROM process_runs")
        connection.execute("DELETE FROM equipment_events")
        connection.execute("DELETE FROM lots")
        connection.executemany("INSERT INTO lots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", lots)
        connection.executemany(
            """INSERT INTO process_runs(
                lot_id, process_step, equipment_id, chamber, recipe, run_time,
                temperature_c, pressure_torr, duration_sec, thickness_nm,
                uniformity_pct, defect_density, pass_flag, excursion_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        knowledge_count = _seed_knowledge(connection)
        connection.commit()

    return {
        "database": str(db_path),
        "date_range": [start_day.isoformat(), end_day.isoformat()],
        "lots": len(lots),
        "process_runs": len(runs),
        "equipment_events": len(events),
        "defect_records": len(defects),
        "knowledge_chunks": knowledge_count,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate deterministic semiconductor fab history")
    parser.add_argument("--days", type=int, default=548)
    parser.add_argument("--force", action="store_true", help="Regenerate even when the database exists")
    args = parser.parse_args()
    target = get_settings().database_path
    if target.exists() and not args.force:
        print(f"Database already exists: {target}. Use --force to regenerate.")
    else:
        print(generate_database(target, days=args.days))
