"""Pure inference rules shared by legacy and native knowledge retrieval."""

from __future__ import annotations

import re
from collections.abc import Mapping

from ..manufacturing.processes import (
    ANALYSIS_SCOPES,
    MANUFACTURING_STEPS,
    matched_process_step,
)

PROCESS_STEPS = ANALYSIS_SCOPES

PROCESS_SEARCH_EXPANSIONS = {
    "LITHO": "photolithography lithography introduction intro overview purpose principle fundamentals basics process photoresist exposure reticle mask",
    "ETCH": "etch etching plasma dry etch wet etch reactive ion RIE",
    "CVD": "chemical vapor deposition CVD film thickness deposition",
    "PVD": "physical vapor deposition PVD sputter sputtering metal deposition",
    "DIFFUSION": "diffusion furnace oxidation anneal thermal process",
    "IMPLANT": "ion implantation implant dopant dose energy",
    "CMP": "chemical mechanical polishing planarization slurry pad conditioner",
    "CLEAN": "wet clean cleaning rinse scrubber chemical bath",
    "METROLOGY": "metrology measurement inspection CD SEM overlay thickness",
}


def infer_filters_from_aliases(
    query: str,
    process_step: str | None,
    equipment_id: str | None,
    defect_type: str | None,
    defect_aliases: Mapping[str, object],
) -> dict[str, str | None]:
    """Preserve the legacy server-side focus inference without source access."""
    upper = query.upper()
    equipment_families = "|".join(re.escape(step) for step in MANUFACTURING_STEPS)
    inferred_equipment = (
        equipment_id.upper()
        if equipment_id
        else next(iter(re.findall(rf"\b(?:{equipment_families})-\d+\b", upper)), None)
    )
    inferred_step = process_step.upper() if process_step else None
    if inferred_step is None and inferred_equipment:
        inferred_step = inferred_equipment.split("-", 1)[0]
    if inferred_step is None:
        inferred_step = next(
            (step for step in PROCESS_STEPS if re.search(rf"\b{step}\b", upper)), None
        )
    if inferred_step is None:
        inferred_step = matched_process_step(query)
    lower = query.lower().replace(" ", "")
    inferred_defect = defect_type or next(
        (
            name
            for name, aliases in defect_aliases.items()
            if any(alias.lower().replace(" ", "") in lower for alias in aliases)
        ),
        None,
    )
    return {
        "process_step": inferred_step,
        "equipment_id": inferred_equipment,
        "defect_type": inferred_defect,
    }
