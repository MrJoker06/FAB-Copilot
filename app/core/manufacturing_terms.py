from __future__ import annotations


MANUFACTURING_STEPS = (
    "LITHO",
    "ETCH",
    "CVD",
    "PVD",
    "DIFFUSION",
    "IMPLANT",
    "CMP",
    "CLEAN",
    "METROLOGY",
)

ANALYSIS_SCOPES = MANUFACTURING_STEPS + ("EQUIPMENT", "WIP", "YIELD")
PROCESS_STEP_PATTERN = "^(" + "|".join(MANUFACTURING_STEPS) + ")$"

PROCESS_ALIASES = {
    "LITHO": ("光刻", "曝光", "litho", "lithography", "photolithography"),
    "ETCH": ("刻蚀", "蚀刻", "etch", "etching"),
    "CVD": ("化学气相沉积", "cvd", "chemical vapor deposition"),
    "PVD": ("物理气相沉积", "溅射", "pvd", "physical vapor deposition", "sputtering"),
    "DIFFUSION": ("扩散", "炉管", "氧化炉", "diffusion", "oxidation furnace"),
    "IMPLANT": ("离子注入", "注入机", "implant", "ion implantation"),
    "CMP": ("化学机械研磨", "化学机械抛光", "cmp", "chemical mechanical polishing"),
    "CLEAN": ("清洗", "湿法", "clean", "cleaning", "wet clean"),
    "METROLOGY": ("量测", "测量", "检测", "metrology", "inspection"),
}


def matched_process_step(text: str) -> str | None:
    compact = text.lower().replace(" ", "")
    return next(
        (
            step
            for step, aliases in PROCESS_ALIASES.items()
            if step.lower() in text.lower()
            or any(alias.lower().replace(" ", "") in compact for alias in aliases)
        ),
        None,
    )


def process_query_terms(text: str) -> tuple[str, ...]:
    step = matched_process_step(text)
    if step is None:
        return ()
    return tuple(dict.fromkeys((*PROCESS_ALIASES[step], step.lower())))

PROCESS_LABELS = {
    "LITHO": "光刻",
    "ETCH": "刻蚀",
    "CVD": "化学气相沉积",
    "PVD": "物理气相沉积",
    "DIFFUSION": "扩散/炉管",
    "IMPLANT": "离子注入",
    "CMP": "化学机械研磨",
    "CLEAN": "清洗",
    "METROLOGY": "量测",
}
