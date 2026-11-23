"""Deterministic three-valued lot commonality aggregation over a fixed snapshot.

Every read (summary, members, records) recomputes from the same stored snapshot,
so all views of one analysis version agree without caching derived state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from app.agent_runtime.tools.contracts import ToolPrincipal
from app.tools.lot_commonality.contracts import (
    DEFAULT_LIMITS,
    DIMENSIONS,
    PASS_DIMENSIONS,
    SCOPE_BOUNDARIES,
    UNION_GROUP,
    AnalysisLimits,
    LotCommonalityDataError,
    LotCommonalityInputError,
    LotHistory,
    LotHistoryBatch,
    LotHistorySource,
    parse_create_request,
    parse_offset_datetime,
)

HIT, MISS, UNKNOWN = "hit", "miss", "unknown"
STATUS_ORDER = {HIT: 0, MISS: 1, UNKNOWN: 2}
DIMENSION_ORDER = {name: index for index, name in enumerate(DIMENSIONS)}
NO_CHAMBER = frozenset({"not_applicable", "unknown"})
PASS_KEYS = frozenset(
    {
        "record_ref",
        "source_record_refs",
        "source_pass_id",
        "lot_id",
        "pass_seq",
        "operation_key",
        "layer",
        "step",
        "equipment_id",
        "chamber_granularity",
        "chamber_set_complete",
        "chambers",
        "allocated_wafer_total",
        "recipe",
        "track_in_at",
        "queue_hours",
        "rework",
        "missing_fields",
    }
)
_NO_SUCCESSOR = object()


@dataclass(frozen=True)
class Outcome:
    status: str
    record_refs: tuple[str, ...] = ()
    reasons: tuple[Mapping[str, object], ...] = ()

    def member(self, lot_id: str) -> dict[str, object]:
        return {
            "lot_id": lot_id,
            "status": self.status,
            "record_refs": list(self.record_refs),
            "reasons": [dict(reason) for reason in self.reasons],
        }


@dataclass(frozen=True)
class AnalysisSnapshot:
    """The bounded, re-readable input of one analysis version."""

    request: dict[str, object]
    batch: LotHistoryBatch
    limits: AnalysisLimits = DEFAULT_LIMITS

    def to_dict(self) -> dict[str, object]:
        return {
            "request": self.request,
            "source": self.batch.source,
            "queried_at": self.batch.queried_at,
            "lots": [
                {
                    "lot_id": history.lot_id,
                    "wafer_count": history.wafer_count,
                    "coverage": history.coverage,
                    "passes": list(history.passes),
                }
                for history in self.batch.lots.values()
            ],
            "limits": self.limits.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> AnalysisSnapshot:
        lots = {
            item["lot_id"]: LotHistory(
                item["lot_id"], item["wafer_count"], item["coverage"], tuple(item["passes"])
            )
            for item in value["lots"]
        }
        return cls(
            dict(value["request"]),
            LotHistoryBatch(dict(value["source"]), value["queried_at"], lots),
            AnalysisLimits(**value["limits"]),
        )


@dataclass(frozen=True)
class _LotView:
    lot_id: str
    found: bool
    passes: tuple[dict[str, object], ...]
    records_complete: bool
    coverage_reasons: tuple[Mapping[str, object], ...]
    order_complete: bool
    order_unknown_refs: tuple[str, ...]
    successors: dict[str, object] = field(default_factory=dict)
    state: str = "complete"
    state_reasons: tuple[str, ...] = ()


def _refs(passes) -> tuple[str, ...]:
    return tuple(item["record_ref"] for item in passes)


def _order_key(item: Mapping[str, object]) -> tuple[bool, int, str]:
    seq = item["pass_seq"]
    return (seq is None, seq or 0, item["record_ref"])


def _cutoff_matches(history: LotHistory, operation_key: str) -> list[dict[str, object]]:
    return sorted(
        (item for item in history.passes if item["operation_key"] == operation_key),
        key=_order_key,
    )


def _scoped_passes(
    history: LotHistory, scope: Mapping[str, object]
) -> tuple[list[dict[str, object]], list[str], list[Mapping[str, object]]]:
    """Return in-scope passes, refs whose scope membership is unknown, and why."""

    passes = sorted(history.passes, key=_order_key)
    unknown: list[str] = []
    reasons: list[Mapping[str, object]] = []
    window = scope.get("time_range")
    if window is not None:
        start = parse_offset_datetime(window["start"], "time_range.start")
        end = parse_offset_datetime(window["end"], "time_range.end")
        kept = []
        for item in passes:
            if item["track_in_at"] is None:
                unknown.append(item["record_ref"])
            elif start <= datetime.fromisoformat(item["track_in_at"]) < end:
                kept.append(item)
        passes = kept
    cutoff = scope.get("cutoff")
    if cutoff is not None and cutoff["mode"] == "time":
        limit = parse_offset_datetime(
            cutoff["per_lot"].get(history.lot_id, cutoff["at"]), "cutoff.at"
        )
        kept = []
        for item in passes:
            if item["track_in_at"] is None:
                unknown.append(item["record_ref"])
            elif datetime.fromisoformat(item["track_in_at"]) <= limit:
                kept.append(item)
        passes = kept
    if unknown:
        reasons.append({"code": "FIELD_MISSING", "field": "track_in_at"})
    if cutoff is not None and cutoff["mode"] == "operation":
        matches = _cutoff_matches(history, cutoff["operation_key"])
        occurrence = cutoff["per_lot"].get(history.lot_id, cutoff["occurrence"])
        if occurrence is None and len(matches) == 1:
            occurrence = 1
        if occurrence is None or occurrence > len(matches):
            return [], unknown, [*reasons, {"code": "CUTOFF_NOT_FOUND"}]
        limit_pass = matches[occurrence - 1]
        if limit_pass["pass_seq"] is None:
            return [], [*unknown, limit_pass["record_ref"]], [
                *reasons,
                {"code": "SEQUENCE_UNKNOWN"},
            ]
        kept = []
        sequence_unknown = False
        for item in passes:
            if item["pass_seq"] is None:
                unknown.append(item["record_ref"])
                sequence_unknown = True
            elif item["pass_seq"] <= limit_pass["pass_seq"]:
                kept.append(item)
        passes = kept
        if sequence_unknown:
            reasons.append({"code": "SEQUENCE_UNKNOWN"})
    return passes, unknown, reasons


def _view(lot_id: str, history: LotHistory | None, scope: Mapping[str, object]) -> _LotView:
    if history is None:
        reason = ({"code": "LOT_NOT_FOUND"},)
        return _LotView(lot_id, False, (), False, reason, False, (), {}, "not_found", ("LOT_NOT_FOUND",))
    coverage = history.coverage
    source_reasons: list[Mapping[str, object]] = []
    if coverage["truncated"]:
        source_reasons.append({"code": "SOURCE_TRUNCATED"})
    for failure in coverage["failures"]:
        source_reasons.append({"code": failure["reason"]})
    if coverage["records"] != "complete" and not source_reasons:
        source_reasons.append({"code": "SOURCE_TRUNCATED"})
    if coverage["records"] == "failed":
        codes = tuple(sorted({reason["code"] for reason in source_reasons}))
        return _LotView(lot_id, True, (), False, tuple(source_reasons), False, (), {}, "source_failed", codes)
    passes, scope_unknown, scope_reasons = _scoped_passes(history, scope)
    reasons = (*source_reasons, *scope_reasons)
    records_complete = coverage["records"] == "complete" and not scope_reasons
    gap_refs = [ref for gap in coverage["gaps"] for ref in gap["record_refs"]]
    null_seq = [item["record_ref"] for item in passes if item["pass_seq"] is None]
    order_complete = (
        records_complete
        and coverage["order"] == "complete"
        and not null_seq
        and not coverage["gaps"]
    )
    successors: dict[str, object] = {}
    if not null_seq:
        gap_after = {gap["after_record_ref"] for gap in coverage["gaps"]}
        ordered = [item for item in passes if item["pass_seq"] is not None]
        for index, item in enumerate(ordered):
            if item["record_ref"] in gap_after:
                continue
            successors[item["record_ref"]] = (
                ordered[index + 1] if index + 1 < len(ordered) else _NO_SUCCESSOR
            )
    codes = {reason["code"] for reason in reasons}
    if any(item["missing_fields"] for item in passes):
        codes.add("FIELD_MISSING")
    if not order_complete and (null_seq or coverage["gaps"] or coverage["order"] != "complete"):
        codes.add("SEQUENCE_UNKNOWN")
    order_unknown = tuple(dict.fromkeys([*gap_refs, *null_seq, *scope_unknown]))
    return _LotView(
        lot_id,
        True,
        tuple(passes),
        records_complete,
        reasons,
        order_complete,
        order_unknown,
        successors,
        "complete" if not codes else "incomplete",
        tuple(sorted(codes)),
    )


def _incomplete(view: _LotView, refs=()) -> Outcome:
    return Outcome(UNKNOWN, tuple(refs), view.coverage_reasons)


def _eval_value(view: _LotView, operation_key: str, field_name: str, value: str) -> Outcome:
    at = [item for item in view.passes if item["operation_key"] == operation_key]
    hits = [item for item in at if item[field_name] == value]
    if hits:
        return Outcome(HIT, _refs(hits))
    if not view.records_complete:
        return _incomplete(view)
    missing = [item for item in at if item[field_name] is None]
    if missing:
        return Outcome(UNKNOWN, _refs(missing), ({"code": "FIELD_MISSING", "field": field_name},))
    if at:
        return Outcome(MISS, _refs(at), ({"code": "OTHER_VALUE"},))
    return Outcome(MISS, (), ({"code": "OPERATION_NOT_VISITED"},))


def _eval_chamber(view: _LotView, operation_key: str, equipment_id: str, chamber_key: str) -> Outcome:
    at = [item for item in view.passes if item["operation_key"] == operation_key]
    on_tool = [item for item in at if item["equipment_id"] == equipment_id]
    hits = [
        item
        for item in on_tool
        if any(chamber["chamber_key"] == chamber_key for chamber in item["chambers"])
    ]
    if hits:
        return Outcome(HIT, _refs(hits))
    if not view.records_complete:
        return _incomplete(view)
    missing_tool = [item for item in at if item["equipment_id"] is None]
    if missing_tool:
        return Outcome(UNKNOWN, _refs(missing_tool), ({"code": "FIELD_MISSING", "field": "equipment_id"},))
    missing = [item for item in on_tool if item["chamber_granularity"] == "unknown"]
    if missing:
        return Outcome(UNKNOWN, _refs(missing), ({"code": "FIELD_MISSING", "field": "chamber"},))
    partial = [item for item in on_tool if not item["chamber_set_complete"]]
    if partial:
        return Outcome(UNKNOWN, _refs(partial), ({"code": "CHAMBER_SET_INCOMPLETE"},))
    if at:
        return Outcome(MISS, _refs(at), ({"code": "OTHER_VALUE"},))
    return Outcome(MISS, (), ({"code": "OPERATION_NOT_VISITED"},))


def _eval_path(view: _LotView, from_key: str, to_key: str) -> Outcome:
    starts = [item for item in view.passes if item["operation_key"] == from_key]
    hit_refs: list[str] = []
    for item in starts:
        successor = view.successors.get(item["record_ref"], _NO_SUCCESSOR)
        if successor is not _NO_SUCCESSOR and successor["operation_key"] == to_key:
            hit_refs += [item["record_ref"], successor["record_ref"]]
    if hit_refs:
        return Outcome(HIT, tuple(hit_refs))
    if not view.records_complete:
        return _incomplete(view)
    if not view.order_complete:
        return Outcome(UNKNOWN, view.order_unknown_refs, ({"code": "SEQUENCE_UNKNOWN"},))
    if not starts:
        return Outcome(MISS, (), ({"code": "OPERATION_NOT_VISITED"},))
    refs: list[str] = []
    for item in starts:
        refs.append(item["record_ref"])
        successor = view.successors.get(item["record_ref"], _NO_SUCCESSOR)
        if successor is not _NO_SUCCESSOR:
            refs.append(successor["record_ref"])
    return Outcome(MISS, tuple(refs), ({"code": "NOT_ADJACENT"},))


def _eval_rework(view: _LotView, value: bool) -> Outcome:
    hits = [item for item in view.passes if item["rework"]["is_rework"] is value]
    if hits:
        return Outcome(HIT, _refs(hits))
    if not view.records_complete:
        return _incomplete(view)
    missing = [item for item in view.passes if item["rework"]["is_rework"] is None]
    if missing:
        return Outcome(UNKNOWN, _refs(missing), ({"code": "FIELD_MISSING", "field": "rework"},))
    return Outcome(MISS, (), ({"code": "OTHER_VALUE"},))


def _evaluate(view: _LotView, candidate: Mapping[str, object]) -> Outcome:
    subject = candidate["subject"]
    dimension = candidate["dimension"]
    if dimension == "equipment":
        return _eval_value(view, subject["operation_key"], "equipment_id", subject["equipment_id"])
    if dimension == "recipe":
        return _eval_value(view, subject["operation_key"], "recipe", subject["recipe"])
    if dimension == "chamber":
        return _eval_chamber(view, subject["operation_key"], subject["equipment_id"], subject["chamber_key"])
    return _eval_path(view, subject["from_operation_key"], subject["to_operation_key"])


def _candidate(dimension: str, key: tuple[str, ...]) -> dict[str, object]:
    if dimension == "equipment":
        op, equipment = key
        return {
            "candidate_id": f"eq:{op}:{equipment}",
            "dimension": dimension,
            "subject": {"operation_key": op, "equipment_id": equipment},
            "label": f"{op} · {equipment}",
        }
    if dimension == "chamber":
        op, equipment, chamber = key
        return {
            "candidate_id": f"ch:{op}:{equipment}/{chamber}",
            "dimension": dimension,
            "subject": {
                "operation_key": op,
                "equipment_id": equipment,
                "chamber": chamber,
                "chamber_key": f"{equipment}/{chamber}",
            },
            "label": f"{op} · {equipment} · {chamber}",
        }
    if dimension == "recipe":
        op, recipe = key
        return {
            "candidate_id": f"rc:{op}:{recipe}",
            "dimension": dimension,
            "subject": {"operation_key": op, "recipe": recipe},
            "label": f"{op} · {recipe}",
        }
    source, target = key
    return {
        "candidate_id": f"path:{source}>{target}",
        "dimension": dimension,
        "subject": {"from_operation_key": source, "to_operation_key": target},
        "label": f"{source} → {target}",
    }


def _subject_keys(view: _LotView, dimensions: list[str]) -> set[tuple[str, tuple[str, ...]]]:
    keys: set[tuple[str, tuple[str, ...]]] = set()
    for item in view.passes:
        op = item["operation_key"]
        equipment = item["equipment_id"]
        if "equipment" in dimensions and equipment is not None:
            keys.add(("equipment", (op, equipment)))
        if (
            "chamber" in dimensions
            and equipment is not None
            and item["chamber_granularity"] not in NO_CHAMBER
        ):
            for chamber in item["chambers"]:
                keys.add(("chamber", (op, equipment, chamber["chamber"])))
        if "recipe" in dimensions and item["recipe"] is not None:
            keys.add(("recipe", (op, item["recipe"])))
        successor = view.successors.get(item["record_ref"], _NO_SUCCESSOR)
        if "path_adjacent" in dimensions and successor is not _NO_SUCCESSOR:
            keys.add(("path_adjacent", (op, successor["operation_key"])))
    return keys


def _counts(outcomes) -> dict[str, int]:
    statuses = [outcome.status for outcome in outcomes]
    hit, miss, unknown = (statuses.count(name) for name in (HIT, MISS, UNKNOWN))
    return {"hit": hit, "miss": miss, "unknown": unknown, "denominator": len(statuses)}


class _Evaluation:
    def __init__(self, snapshot: AnalysisSnapshot) -> None:
        self.snapshot = snapshot
        request = snapshot.request
        self.groups = request["groups"]
        self.group_lots = {
            group["group_id"]: list(dict.fromkeys(group["lot_ids"])) for group in self.groups
        }
        self.group_lots[UNION_GROUP] = list(
            dict.fromkeys(lot for group in self.groups for lot in self.group_lots[group["group_id"]])
        )
        self.views = {
            lot: _view(lot, snapshot.batch.lots.get(lot), request["scope"])
            for lot in self.group_lots[UNION_GROUP]
        }
        primary = next(group["group_id"] for group in self.groups if group["role"] == "primary")
        keys: set[tuple[str, tuple[str, ...]]] = set()
        for lot in self.group_lots[primary]:
            keys |= _subject_keys(self.views[lot], request["dimensions"])
        candidates = []
        for dimension, key in keys:
            candidate = _candidate(dimension, key)
            counts = {
                group_id: _counts(_evaluate(self.views[lot], candidate) for lot in self.group_lots[group_id])
                for group_id in [*(group["group_id"] for group in self.groups), UNION_GROUP]
            }
            if counts[primary]["hit"] < 2:
                continue
            candidate["all_shared"] = counts[primary]["hit"] == counts[primary]["denominator"]
            candidate["counts"] = counts
            candidates.append(candidate)
        candidates.sort(
            key=lambda item: (
                -item["counts"][primary]["hit"],
                item["counts"][primary]["unknown"],
                DIMENSION_ORDER[item["dimension"]],
                item["candidate_id"],
            )
        )
        self.candidates = {item["candidate_id"]: item for item in candidates}


def _check_batch(batch: LotHistoryBatch, requested: tuple[str, ...], limits: AnalysisLimits) -> None:
    if not isinstance(batch, LotHistoryBatch) or set(batch.lots) - set(requested):
        raise LotCommonalityDataError()
    rows = 0
    for lot_id, history in batch.lots.items():
        if history.lot_id != lot_id:
            raise LotCommonalityDataError()
        refs = set()
        for item in history.passes:
            if set(item) != PASS_KEYS or item["lot_id"] != lot_id or item["record_ref"] in refs:
                raise LotCommonalityDataError()
            refs.add(item["record_ref"])
        rows += len(history.passes)
    if rows > limits.max_source_rows:
        raise LotCommonalityDataError()


def create_snapshot(
    body: object,
    source: LotHistorySource,
    principal: ToolPrincipal,
    limits: AnalysisLimits = DEFAULT_LIMITS,
) -> AnalysisSnapshot:
    """Validate, read the source once, and freeze the analysis input."""

    request = parse_create_request(body, limits)
    requested = tuple(
        dict.fromkeys(lot for group in request["groups"] for lot in group["lot_ids"])
    )
    batch = source.fetch(requested, principal)
    _check_batch(batch, requested, limits)
    cutoff = request["scope"]["cutoff"]
    if cutoff is not None and cutoff["mode"] == "operation" and cutoff["occurrence"] is None:
        ambiguous = []
        for lot in requested:
            history = batch.lots.get(lot)
            if history is None or lot in cutoff["per_lot"]:
                continue
            matches = _cutoff_matches(history, cutoff["operation_key"])
            if len(matches) > 1:
                ambiguous.append({"lot_id": lot, "record_refs": list(_refs(matches))})
        if ambiguous:
            raise LotCommonalityInputError(
                "截止工序在部分 lot 中出现多次，请为这些 lot 指定出现次数或截止时间。",
                error_code="CUTOFF_AMBIGUOUS",
                context={"lots": ambiguous},
            )
    return AnalysisSnapshot(request, batch, limits)


def summarize(
    snapshot: AnalysisSnapshot, *, analysis_ref: str, created_at: str, expires_at: str | None
) -> dict[str, object]:
    evaluation = _Evaluation(snapshot)
    request = snapshot.request
    groups = []
    for group in request["groups"]:
        lots = evaluation.group_lots[group["group_id"]]
        seen: set[str] = set()
        duplicates: list[str] = []
        for lot in group["lot_ids"]:
            if lot in seen and lot not in duplicates:
                duplicates.append(lot)
            seen.add(lot)
        groups.append(
            {
                "group_id": group["group_id"],
                "name": group["name"],
                "role": group["role"],
                "input_count": len(group["lot_ids"]),
                "unique_count": len(lots),
                "duplicates": duplicates,
                "lot_states": [
                    {
                        "lot_id": lot,
                        "state": evaluation.views[lot].state,
                        "reasons": list(evaluation.views[lot].state_reasons),
                    }
                    for lot in lots
                ],
            }
        )
    overlaps = []
    for lot in sorted(evaluation.group_lots[UNION_GROUP]):
        owners = [group["group_id"] for group in request["groups"] if lot in evaluation.group_lots[group["group_id"]]]
        if len(owners) > 1:
            overlaps.append({"lot_id": lot, "group_ids": owners})
    partial = any(
        history.coverage["truncated"]
        or history.coverage["failures"]
        or history.coverage["records"] == "failed"
        for history in snapshot.batch.lots.values()
    )
    candidates = list(evaluation.candidates.values())
    return {
        "analysis_ref": analysis_ref,
        "status": "partial" if partial else "complete",
        "created_at": created_at,
        "expires_at": expires_at,
        "timezone": request["timezone"],
        "source": dict(snapshot.batch.source, queried_at=snapshot.batch.queried_at),
        "scope": {**request["scope"], "boundaries": dict(SCOPE_BOUNDARIES)},
        "dimensions": list(request["dimensions"]),
        "groups": groups,
        "overlaps": overlaps,
        "union": {"unique_count": len(evaluation.group_lots[UNION_GROUP])},
        "limits": snapshot.limits.to_dict(),
        "candidates": candidates[: snapshot.limits.max_candidates],
        "candidates_truncated": len(candidates) > snapshot.limits.max_candidates,
    }


def _limit(value: object, limits: AnalysisLimits) -> int:
    if value is None:
        return limits.page_limit_default
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= limits.page_limit_max:
        raise LotCommonalityInputError(f"limit 必须是 1～{limits.page_limit_max} 的整数。")
    return value


def _group(evaluation: _Evaluation, value: object) -> list[str]:
    if not isinstance(value, str) or value not in evaluation.group_lots:
        raise LotCommonalityInputError("group_id 不属于本次分析。")
    return evaluation.group_lots[value]


def _pass_condition(item: Mapping[str, object], condition: Mapping[str, object]) -> tuple[bool | None, Mapping[str, object] | None]:
    if "attribute" in condition:
        value = item["rework"]["is_rework"]
        if value is None:
            return None, {"code": "FIELD_MISSING", "field": "rework"}
        return value is condition["value"], None
    subject = condition["candidate"]["subject"]
    dimension = condition["candidate"]["dimension"]
    if item["operation_key"] != subject["operation_key"]:
        return False, None
    if dimension == "recipe":
        if item["recipe"] is None:
            return None, {"code": "FIELD_MISSING", "field": "recipe"}
        return item["recipe"] == subject["recipe"], None
    if item["equipment_id"] is None:
        return None, {"code": "FIELD_MISSING", "field": "equipment_id"}
    if item["equipment_id"] != subject["equipment_id"]:
        return False, None
    if dimension == "equipment":
        return True, None
    if any(chamber["chamber_key"] == subject["chamber_key"] for chamber in item["chambers"]):
        return True, None
    if item["chamber_granularity"] == "unknown":
        return None, {"code": "FIELD_MISSING", "field": "chamber"}
    if not item["chamber_set_complete"]:
        return None, {"code": "CHAMBER_SET_INCOMPLETE"}
    return False, None


def _same_pass(view: _LotView, conditions: list[Mapping[str, object]]) -> Outcome:
    hits: list[dict[str, object]] = []
    unknown: list[dict[str, object]] = []
    reasons: list[Mapping[str, object]] = []
    for item in view.passes:
        values = [_pass_condition(item, condition) for condition in conditions]
        if any(value is False for value, _ in values):
            continue
        if all(value is True for value, _ in values):
            hits.append(item)
            continue
        unknown.append(item)
        reasons.extend(reason for value, reason in values if value is None and reason not in reasons)
    if hits:
        return Outcome(HIT, _refs(hits))
    if not view.records_complete:
        return _incomplete(view)
    if unknown:
        return Outcome(UNKNOWN, _refs(unknown), tuple(reasons))
    operations = {
        condition["candidate"]["subject"]["operation_key"]
        for condition in conditions
        if "candidate" in condition
    }
    relevant = [item for item in view.passes if item["operation_key"] in operations]
    return Outcome(MISS, _refs(relevant), ({"code": "CONDITIONS_NOT_MET"},))


def _any_pass(view: _LotView, conditions: list[Mapping[str, object]]) -> Outcome:
    outcomes = [
        _eval_rework(view, condition["value"])
        if "attribute" in condition
        else _evaluate(view, condition["candidate"])
        for condition in conditions
    ]
    if len(outcomes) == 1:
        return outcomes[0]

    def merged(status: str) -> tuple[str, ...]:
        return tuple(dict.fromkeys(ref for outcome in outcomes if outcome.status == status for ref in outcome.record_refs))

    if any(outcome.status == MISS for outcome in outcomes):
        return Outcome(MISS, merged(MISS), ({"code": "CONDITIONS_NOT_MET"},))
    if any(outcome.status == UNKNOWN for outcome in outcomes):
        reasons: list[Mapping[str, object]] = []
        for outcome in outcomes:
            if outcome.status == UNKNOWN:
                reasons.extend(reason for reason in outcome.reasons if reason not in reasons)
        return Outcome(UNKNOWN, merged(UNKNOWN), tuple(reasons))
    return Outcome(HIT, merged(HIT))


def _conditions(evaluation: _Evaluation, value: object, match_scope: object) -> list[dict[str, object]]:
    if match_scope not in {"same_pass", "any_pass"}:
        raise LotCommonalityInputError("match_scope 只能是 same_pass 或 any_pass。")
    if not isinstance(value, list) or not value or len(value) > 8:
        raise LotCommonalityInputError("conditions 必须是 1～8 个条件。")
    parsed: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, Mapping) and set(item) == {"candidate_id"}:
            candidate = evaluation.candidates.get(item["candidate_id"])
            if candidate is None:
                raise LotCommonalityInputError("candidate_id 不属于本次分析。")
            if match_scope == "same_pass" and candidate["dimension"] not in PASS_DIMENSIONS:
                raise LotCommonalityInputError("same_pass 只接受单次过站可判断的条件。")
            parsed.append({"candidate": candidate})
        elif (
            isinstance(item, Mapping)
            and set(item) == {"attribute", "value"}
            and item["attribute"] == "rework"
            and isinstance(item["value"], bool)
        ):
            parsed.append({"attribute": "rework", "value": item["value"]})
        else:
            raise LotCommonalityInputError("条件格式不符合契约。")
    return parsed


def read_members(
    snapshot: AnalysisSnapshot,
    query: Mapping[str, object],
    *,
    analysis_ref: str,
    offset: int = 0,
) -> tuple[dict[str, object], int | None]:
    """Return one members page and the next offset; the caller owns cursor tokens."""

    if set(query) - {"group_id", "conditions", "match_scope", "status", "limit"}:
        raise LotCommonalityInputError("成员查询字段不符合契约。")
    evaluation = _Evaluation(snapshot)
    lots = _group(evaluation, query.get("group_id"))
    match_scope = query.get("match_scope", "any_pass")
    conditions = _conditions(evaluation, query.get("conditions"), match_scope)
    status = query.get("status")
    if status is not None and status not in STATUS_ORDER:
        raise LotCommonalityInputError("status 只能是 hit、miss 或 unknown。")
    limit = _limit(query.get("limit"), snapshot.limits)
    evaluate = _same_pass if match_scope == "same_pass" and len(conditions) > 1 else _any_pass
    members = sorted(
        (evaluate(evaluation.views[lot], conditions).member(lot) for lot in lots),
        key=lambda member: (STATUS_ORDER[member["status"]], member["lot_id"]),
    )
    counts = _counts(Outcome(member["status"]) for member in members)
    times = [
        snapshot_pass["track_in_at"]
        for member in members
        if member["status"] == HIT
        for snapshot_pass in evaluation.views[member["lot_id"]].passes
        if snapshot_pass["record_ref"] in member["record_refs"] and snapshot_pass["track_in_at"] is not None
    ]
    time_range = None
    if times:
        ordered = sorted(times, key=datetime.fromisoformat)
        time_range = {"first": ordered[0], "last": ordered[-1], "timezone": snapshot.request["timezone"]}
    selected = [member for member in members if status is None or member["status"] == status]
    page = selected[offset : offset + limit]
    next_offset = offset + limit if offset + limit < len(selected) else None
    body = {
        "analysis_ref": analysis_ref,
        "group_id": query["group_id"],
        "query": {"conditions": query["conditions"], "match_scope": match_scope, "status": status},
        "counts": counts,
        "hit_time_range": time_range,
        "members": page,
        "page": {"limit": limit, "returned": len(page), "total": len(selected), "next_cursor": None},
    }
    return body, next_offset


def read_records(
    snapshot: AnalysisSnapshot,
    query: Mapping[str, object],
    *,
    analysis_ref: str,
    offset: int = 0,
) -> tuple[dict[str, object], int | None]:
    """Return in-scope passes for chosen lots, unaltered from the source snapshot."""

    if set(query) - {"group_id", "lot_ids", "candidate_id", "limit"}:
        raise LotCommonalityInputError("明细查询字段不符合契约。")
    evaluation = _Evaluation(snapshot)
    group_lots = set(_group(evaluation, query.get("group_id")))
    lot_ids = query.get("lot_ids")
    if (
        not isinstance(lot_ids, list)
        or not lot_ids
        or len(lot_ids) > snapshot.limits.page_limit_max
        or len(set(lot_ids)) != len(lot_ids)
        or not set(lot_ids) <= group_lots
    ):
        raise LotCommonalityInputError("lot_ids 必须是该组内不重复的 lot。")
    candidate_id = query.get("candidate_id")
    candidate = None
    if candidate_id is not None:
        candidate = evaluation.candidates.get(candidate_id)
        if candidate is None:
            raise LotCommonalityInputError("candidate_id 不属于本次分析。")
    limit = _limit(query.get("limit"), snapshot.limits)
    lots = []
    passes = []
    for lot in lot_ids:
        history = snapshot.batch.lots.get(lot)
        view = evaluation.views[lot]
        lots.append(
            {
                "lot_id": lot,
                "wafer_count": history.wafer_count if history else None,
                "candidate_status": _evaluate(view, candidate).status if candidate else None,
                "coverage": history.coverage if history else None,
            }
        )
        passes.extend(view.passes)
    page = passes[offset : offset + limit]
    next_offset = offset + limit if offset + limit < len(passes) else None
    body = {
        "analysis_ref": analysis_ref,
        "group_id": query["group_id"],
        "candidate_id": candidate_id,
        "lots": lots,
        "passes": page,
        "page": {"limit": limit, "returned": len(page), "total": len(passes), "next_cursor": None},
    }
    return body, next_offset
