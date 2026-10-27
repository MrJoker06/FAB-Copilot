from __future__ import annotations

from datetime import date


def _metadata_rerank(candidates: list[dict], filters: dict, limit: int, source_types: list[str] | None) -> list[dict]:
    allowed_sources = set(source_types or ("personal", "knowledge", "case"))
    ranked: list[dict] = []
    source_ranks = {"personal": 0, "knowledge": 0, "case": 0}
    for candidate in candidates:
        source_type = candidate["source_type"]
        if source_type not in allowed_sources:
            continue
        source_ranks[source_type] += 1
        lexical_rank = source_ranks[source_type]
        score = 100.0 / (60 + lexical_rank)
        reasons = [f"{source_type} lexical rank {lexical_rank}"]
        process_step = filters.get("process_step")
        equipment_id = filters.get("equipment_id")
        defect_type = filters.get("defect_type")

        if source_type == "knowledge":
            steps = {item.strip() for item in candidate.get("process_steps", "").split(",")}
            if process_step and process_step not in steps and "ALL" not in steps:
                continue
            if process_step:
                score += 1.4
                reasons.append(f"process={process_step}")
            authority = int(candidate.get("authority", 0))
            score += authority * 0.12
            reasons.append(f"authority={authority}/5")
            searchable = f"{candidate.get('tags', '')} {candidate.get('title', '')} {candidate.get('section', '')}".lower()
            if defect_type and defect_type.lower() in searchable:
                score += 1.6
                reasons.append(f"defect={defect_type}")
        elif source_type == "case":
            if candidate.get("case_status") != "Validated":
                continue
            candidate_step = candidate.get("process_step")
            family = candidate.get("equipment_family")
            if process_step and process_step not in {candidate_step, family} and family != "ALL":
                continue
            if process_step:
                score += 1.3
                reasons.append(f"process={process_step}")
            if equipment_id and candidate.get("equipment_id") == equipment_id:
                score += 2.2
                reasons.append("exact equipment")
            elif equipment_id and family == equipment_id.split("-", 1)[0]:
                score += 0.8
                reasons.append("equipment family")
            if defect_type and candidate.get("defect_type", "").lower() == defect_type.lower():
                score += 1.8
                reasons.append(f"defect={defect_type}")
            elif defect_type:
                continue
            confidence = float(candidate.get("root_cause_confidence", 0))
            score += confidence * 0.8
            reasons.append(f"validated confidence={confidence:.2f}")
            if not any((process_step, equipment_id, defect_type)):
                score -= 0.8
                reasons.append("no structured case match")
            try:
                age_days = (date.today() - date.fromisoformat(candidate["occurred_date"])).days
                recency = max(0.0, 1.0 - age_days / 730) * 0.25
                score += recency
            except (KeyError, ValueError):
                pass
        else:
            candidate_steps = set(candidate.get("process_steps") or [])
            if process_step and candidate_steps and process_step not in candidate_steps:
                continue
            score += 1.8
            reasons.append("current user private knowledge")
            if process_step and process_step in candidate_steps:
                score += 1.5
                reasons.append(f"process={process_step}")
            candidate_equipment = set(candidate.get("equipment_ids") or [])
            if equipment_id and equipment_id in candidate_equipment:
                score += 2.2
                reasons.append("exact equipment")
            searchable = f"{candidate.get('title', '')} {' '.join(candidate.get('tags') or [])}".lower()
            if defect_type and defect_type.lower() in searchable:
                score += 1.4
                reasons.append(f"defect={defect_type}")

        candidate["retrieval"] = {
            "lexical_rank": lexical_rank,
            "final_score": round(score, 4),
            "confidence": "high" if score >= 4.5 else ("medium" if score >= 2.0 else "low"),
            "selection_reason": reasons,
            "filters": filters,
        }
        ranked.append(candidate)

    ranked.sort(key=lambda item: item["retrieval"]["final_score"], reverse=True)
    selected: list[dict] = []
    if limit >= 2:
        for source_type in ("personal", "knowledge", "case"):
            first = next((item for item in ranked if item["source_type"] == source_type), None)
            if first is not None and first["retrieval"]["confidence"] != "low":
                selected.append(first)
            if len(selected) >= limit:
                break
    for item in ranked:
        if item not in selected:
            selected.append(item)
        if len(selected) >= limit:
            break
    selected.sort(key=lambda item: item["retrieval"]["final_score"], reverse=True)
    return selected[:limit]
