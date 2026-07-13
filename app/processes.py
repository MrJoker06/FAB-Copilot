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
    "LITHO": ("光刻", "曝光", "litho"),
    "ETCH": ("刻蚀", "蚀刻", "etch"),
    "CVD": ("化学气相沉积", "cvd"),
    "PVD": ("物理气相沉积", "溅射", "pvd"),
    "DIFFUSION": ("扩散", "炉管", "氧化炉", "diffusion"),
    "IMPLANT": ("离子注入", "注入机", "implant"),
    "CMP": ("化学机械研磨", "化学机械抛光", "cmp"),
    "CLEAN": ("清洗", "湿法", "clean"),
    "METROLOGY": ("量测", "测量", "检测", "metrology"),
}

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
