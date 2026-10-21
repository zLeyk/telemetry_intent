"""Deterministic telemetry text variants and Chatito grammar emission.

The method renders English from supplied semantic specifications. It does not
sample cases, assign evaluation splits, or construct reference intent graphs.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any, Mapping, Sequence

from .base_renderer import RenderedSurface, SurfacePiece, render_surface
from .vocabulary import METRIC_SURFACES


SURFACE_STYLE_COUNT = 3


_TASK_REF_RE = re.compile(r"^task:(\d+):(/.*)$")


_LOCUS_REF_RE = re.compile(
    r"^task:(\d+):/(acquire|aggregate|deliver)/requested_loci/(\d+)$"
)


_FLOW_REF_RE = re.compile(r"^task:(\d+):/flow_conditions/(\d+)$")


_VIA_REF_RE = re.compile(r"^task:(\d+):/region/via/(\d+)$")


def surface_family(card: Mapping[str, Any]) -> str:
    """Return a stable family for cards that share the same surface structure."""

    shape = [_task_surface_shape(task) for task in card["semantic_ir"]["tasks"]]
    encoded = json.dumps(shape, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("ascii")).hexdigest()[:12]
    return f"family-{digest}"


def assign_styles(
    cards: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    """Round-robin styles within each structural family in stable Sample-ID order."""

    by_family: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for card in cards:
        by_family[surface_family(card)].append(card)
    styles: dict[str, int] = {}
    for family in sorted(by_family):
        ordered = sorted(by_family[family], key=lambda item: str(item["sample_id"]))
        for index, card in enumerate(ordered):
            styles[str(card["sample_id"])] = index % SURFACE_STYLE_COUNT
    return styles


def render_variants(
    card: Mapping[str, Any],
) -> tuple[RenderedSurface, RenderedSurface, RenderedSurface]:
    """Render three deterministic, fact-preserving natural variants for one card."""

    variants = tuple(
        _naturalize_rendered(card, render_surface(card, style), style)
        for style in range(SURFACE_STYLE_COUNT)
    )
    if len({item.utterance for item in variants}) != SURFACE_STYLE_COUNT:
        raise ValueError(f"{card['sample_id']} surface variants are not distinct")
    return variants  # type: ignore[return-value]


def render_grammar(
    entries: Sequence[tuple[str, Sequence[RenderedSurface]]],
) -> str:
    """Build a grammar with three fact-equivalent realizations per routed intent."""

    blocks = [
        "# Generated from user-supplied telemetry semantic specifications.",
        "# Three deterministic realizations per input specification.",
        "",
    ]
    aliases: list[tuple[str, str]] = []
    for sample_id, variants in entries:
        if len(variants) != SURFACE_STYLE_COUNT:
            raise ValueError(f"{sample_id} must provide exactly three Chatito realizations")
        patterns: list[str] = []
        for style, rendered in enumerate(variants):
            pattern, rendered_aliases = _chatito_pattern(sample_id, style, rendered)
            patterns.append(pattern)
            aliases.extend(rendered_aliases)
        if len(set(patterns)) != SURFACE_STYLE_COUNT:
            raise ValueError(f"{sample_id} Chatito patterns are not distinct")
        blocks.append(
            f"%[telemetry_{sample_id}]('training': '3', 'distribution': 'even')"
        )
        blocks.extend(f"    {pattern}" for pattern in patterns)
        blocks.append("")
    for alias, value in aliases:
        blocks.extend([f"@[{alias}]", f"    {value}", ""])
    return "\n".join(blocks).rstrip() + "\n"


def _task_surface_shape(task: Mapping[str, Any]) -> dict[str, Any]:
    region = task["region"]
    if region.get("denotes"):
        relation = "denotes"
    elif region.get("contains"):
        relation = "contains"
    else:
        relation = "boundary"
    acquire = task.get("acquire", {})
    aggregate = task.get("aggregate")
    deliver = task.get("deliver")
    flow_shape = [
        [condition.get("field"), condition.get("op")]
        for condition in task.get("flow_conditions", ())
    ]
    loci = [
        [operation, locus.get("kind"), locus.get("role"), locus.get("quantifier")]
        for operation in ("acquire", "aggregate", "deliver")
        for locus in task.get(operation, {}).get("requested_loci", ())
    ]
    return {
        "region": [region.get("scope_type"), relation, len(region.get("via", ()))],
        "metric_count": len(task.get("metric_ids", ())),
        "flow": flow_shape,
        "acquire": {
            "mode": acquire.get("mode"),
            "period": "period" in acquire,
            "count": "count" in acquire,
            "sampling_ratio": "sampling_ratio" in acquire,
            "data_sources": len(acquire.get("data_sources", ())),
        },
        "aggregate": None
        if aggregate is None
        else [
            aggregate.get("operator"),
            aggregate.get("over", {}).get("kind"),
            "stride" in aggregate,
        ],
        "deliver": None
        if deliver is None
        else [
            deliver.get("kind"),
            "period" in deliver,
            "batch" in deliver,
            "destination" in deliver,
            "retention" in deliver,
        ],
        "lifecycle": bool(task.get("lifecycle", {}).get("duration")),
        "loci": loci,
    }


def _naturalize_rendered(
    card: Mapping[str, Any], rendered: RenderedSurface, style: int
) -> RenderedSurface:
    tasks = card["semantic_ir"]["tasks"]
    profile = _surface_profile(str(card["sample_id"]))
    old_offset = 0
    new_offset = 0
    boundaries: dict[int, int] = {0: 0}
    pieces: list[SurfacePiece] = []
    for index, piece in enumerate(rendered.pieces):
        text = _natural_piece_text(
            tasks, rendered.pieces, index, piece, style, profile
        )
        pieces.append(SurfacePiece(text, piece.fact_refs, piece.slot_kind))
        old_offset += len(piece.text)
        new_offset += len(text)
        boundaries[old_offset] = new_offset

    spans: dict[str, list[dict[str, int]]] = {}
    for fact_ref, fact_spans in rendered.spans.items():
        mapped: list[dict[str, int]] = []
        for span in fact_spans:
            if span["start"] not in boundaries or span["end"] not in boundaries:
                raise ValueError(f"surface span is not piece-aligned: {fact_ref}:{span}")
            mapped.append(
                {"start": boundaries[span["start"]], "end": boundaries[span["end"]]}
            )
        spans[fact_ref] = mapped

    syntax = f"{rendered.syntax_form}_{_PROFILE_NAMES[profile]}"
    return RenderedSurface(
        utterance="".join(piece.text for piece in pieces),
        spans=spans,
        pieces=tuple(pieces),
        syntax_form=syntax,
    )


def _natural_piece_text(
    tasks: Sequence[Mapping[str, Any]],
    pieces: Sequence[SurfacePiece],
    index: int,
    piece: SurfacePiece,
    style: int,
    profile: int,
) -> str:
    ref = piece.fact_refs[0] if piece.fact_refs else ""
    if piece.slot_kind == "task_relation" and len(tasks) > 1 and style == 2:
        return "Handle both observations: " if len(tasks) == 2 else "Handle these observations: "
    flow_match = _FLOW_REF_RE.match(ref)
    if flow_match:
        task_index, condition_index = map(int, flow_match.groups())
        return _flow_condition_text(
            tasks[task_index]["flow_conditions"][condition_index], style, profile
        )
    if piece.slot_kind == "metric":
        metric_match = _TASK_REF_RE.match(ref)
        if metric_match is not None:
            task_index = int(metric_match.group(1))
            metric_index_match = re.fullmatch(
                r"/metric_ids/(\d+)", metric_match.group(2)
            )
            if metric_index_match is not None:
                task = tasks[task_index]
                metric_index = int(metric_index_match.group(1))
                if (
                    task["metric_ids"][metric_index] == "throughput"
                    and task["region"]["scope_type"] == "unspecified"
                    and task.get("flow_conditions")
                ):
                    return "Throughput" if piece.text[:1].isupper() else "throughput"
    locus_match = _LOCUS_REF_RE.match(ref)
    if locus_match:
        task_index = int(locus_match.group(1))
        operation = locus_match.group(2)
        locus_index = int(locus_match.group(3))
        task = tasks[task_index]
        locus = task[operation]["requested_loci"][locus_index]
        region = task["region"]
        location = _natural_locus_text(region, locus)
        if operation == "deliver":
            operation_text = {
                "report": "reporting",
                "export": "export",
                "store": "storage",
            }[task["deliver"]["kind"]]
        else:
            operation_text = {"acquire": "acquisition", "aggregate": "aggregation"}[
                operation
            ]
        if _same_region_entity_locus(region, locus):
            return {
                "acquire": "with local acquisition",
                "aggregate": "with aggregation performed locally",
                "deliver": f"with local {operation_text}",
            }[operation]
        if locus.get("kind") == "region_role":
            return f"with {operation_text} at {_coincident_region_role_text(region, locus)}"
        return f"with {operation_text} at {location}"
    via_match = _VIA_REF_RE.match(ref)
    if via_match:
        task_index, via_index = map(int, via_match.groups())
        return str(tasks[task_index]["region"]["via"][via_index]["mention"])
    if piece.slot_kind == "acquire_mode":
        mode_match = _TASK_REF_RE.match(ref)
        if mode_match is None:
            raise ValueError(f"acquire mode piece lacks a task reference: {ref}")
        mode = str(tasks[int(mode_match.group(1))]["acquire"]["mode"])
        text = {
            "poll": ("Poll", "Use polling to collect", "Use polling to measure"),
            "probe": ("Probe", "Use probes to collect", "Use probes to measure"),
            "stream": ("Stream", "Use streaming to collect", "Use streaming to measure"),
        }[mode][style]
        return text if piece.text[:1].isupper() else text[:1].lower() + text[1:]
    if piece.slot_kind == "deliver_destination":
        destination_match = _TASK_REF_RE.match(ref)
        if destination_match is None:
            raise ValueError(f"deliver destination lacks a task reference: {ref}")
        destination = tasks[int(destination_match.group(1))]["deliver"]["destination"]
        if destination.get("entity_kind") == "collector":
            return f"the telemetry collector named {destination['mention']}"
    if piece.slot_kind == "region_type":
        region_match = _TASK_REF_RE.match(ref)
        if region_match is not None:
            region = tasks[int(region_match.group(1))]["region"]
            if _is_unnamed_explicit_member_set(region):
                return "on devices"
    if piece.text == "What is the current " and any(
        len(task.get("metric_ids", ())) > 1 for task in tasks
    ):
        return (
            "What are the current ",
            "Can you check the current ",
            "Could you provide the current ",
            "Do you have the current ",
        )[profile]
    if piece.text == " where " and index + 1 < len(pieces):
        next_ref = pieces[index + 1].fact_refs[0] if pieces[index + 1].fact_refs else ""
        next_flow = _FLOW_REF_RE.match(next_ref)
        if next_flow:
            task_index, condition_index = map(int, next_flow.groups())
            condition = tasks[task_index]["flow_conditions"][condition_index]
            if condition.get("field") == "tenant" and condition.get("op") == "eq":
                value = str(condition.get("value", ""))
                if style == 0 and value.casefold().endswith(" tenant"):
                    return " whose "
                return " "
    if piece.text == " Separately, " and len(tasks) > 1 and style == 2:
        return " Also, "
    if piece.text == " via " and index + 1 < len(pieces):
        next_ref = pieces[index + 1].fact_refs[0] if pieces[index + 1].fact_refs else ""
        next_via = _VIA_REF_RE.match(next_ref)
        if next_via and int(next_via.group(2)) > 0:
            return ", then "
    if piece.text == " containing devices " and index > 0:
        previous_ref = pieces[index - 1].fact_refs[0] if pieces[index - 1].fact_refs else ""
        region_match = _TASK_REF_RE.match(previous_ref)
        if region_match is not None:
            region = tasks[int(region_match.group(1))]["region"]
            if _is_unnamed_explicit_member_set(region):
                return " "
    if piece.slot_kind == "region_type" and piece.text == "along the network region ":
        region_match = _TASK_REF_RE.match(ref)
        if region_match is not None:
            region = tasks[int(region_match.group(1))]["region"]
            if region.get("starts_at") and region.get("ends_at"):
                return "across the network region extending from source "
        return "across the network region "
    if piece.text == "from " and index > 0:
        previous_ref = pieces[index - 1].fact_refs[0] if pieces[index - 1].fact_refs else ""
        region_match = _TASK_REF_RE.match(previous_ref)
        if region_match is not None:
            region = tasks[int(region_match.group(1))]["region"]
            if (
                region.get("scope_type") == "network_region"
                and not region.get("contains")
            ):
                return ""
    if piece.text == " to " and index > 0:
        previous_ref = pieces[index - 1].fact_refs[0] if pieces[index - 1].fact_refs else ""
        region_match = _TASK_REF_RE.match(previous_ref)
        if region_match is not None:
            region = tasks[int(region_match.group(1))]["region"]
            if (
                region.get("scope_type") == "network_region"
                and not region.get("contains")
            ):
                return " to destination "
    if piece.text == " should be measured" and style == 2 and any(
        len(task.get("metric_ids", ())) > 1 for task in tasks
    ):
        return (
            " should be monitored",
            " need to be tracked",
            " require monitoring",
            " should be kept under observation",
        )[profile]
    return _natural_literal(piece.text, style, profile)


_PROFILE_NAMES = ("direct", "request", "operational", "concise")


def _surface_profile(sample_id: str) -> int:
    # Preserve the original hash namespace so existing ASCII IDs retain wording.
    digest = hashlib.sha256(f"task010-surface-profile:{sample_id}".encode("utf-8"))
    return int(digest.hexdigest()[:8], 16) % len(_PROFILE_NAMES)


def _natural_literal(text: str, style: int, profile: int) -> str:
    if style == 0:
        choices = (
            {"Measure ": "Track ", "measure ": "track "},
            {"Measure ": "Monitor ", "measure ": "monitor "},
            {"Measure ": "Observe ", "measure ": "observe "},
            {"Measure ": "Record ", "measure ": "record "},
        )
        return choices[profile].get(text, text)
    if style == 1:
        choices = (
            {
                "What is the current ": "What is the ",
                "Monitor ": "Capture ",
                "monitor ": "capture ",
            },
            {
                "What is the current ": "Can you check the ",
                "Monitor ": "Observe ",
                "monitor ": "observe ",
            },
            {
                "What is the current ": "Could you provide the current ",
                "Monitor ": "Record ",
                "monitor ": "record ",
            },
            {
                "What is the current ": "Do you have the current ",
                "Monitor ": "Track ",
                "monitor ": "track ",
            },
        )
        return choices[profile].get(text, text)
    choices = (
        {
            " should be measured": " should be monitored",
            "Track ": "Measure ",
            "track ": "measure ",
        },
        {
            " should be measured": " needs to be tracked",
            "Track ": "Observe ",
            "track ": "observe ",
        },
        {
            " should be measured": " requires monitoring",
            "Track ": "Record ",
            "track ": "record ",
        },
        {
            " should be measured": " should be kept under observation",
            "Track ": "Capture ",
            "track ": "capture ",
        },
    )
    return choices[profile].get(text, text)


def _flow_condition_text(
    condition: Mapping[str, Any], style: int, profile: int
) -> str:
    field = str(condition["field"])
    operator = str(condition["op"])
    value = str(condition["value"])
    if field == "tenant" and operator == "eq":
        target = f"the {value}" if value.casefold().endswith(" tenant") else value
        if style == 0:
            if value.casefold().endswith(" tenant"):
                return f"tenant is {target}"
            return (
                f"assigned to {target}",
                f"belonging to {target}",
                f"associated with {target}",
                f"in {target}",
            )[profile]
        if style == 1:
            return (
                f"assigned to {target}",
                f"belonging to {target}",
                f"associated with {target}",
                f"in {target}",
            )[profile]
        return (
            f"assigned to {target}",
            f"belonging to {target}",
            f"in {target}",
            f"associated with {target}",
        )[profile]
    label = {
        "tenant": "tenant",
        "src_ip": "source IP",
        "dst_ip": "destination IP",
        "protocol": "protocol",
        "dst_port": "destination port",
    }.get(field, field.replace("_", " "))
    relation = {
        "eq": ("is", "equals", "matches"),
        "neq": ("is not", "does not equal", "differs from"),
        "gt": ("is above", "exceeds", "is greater than"),
        "lt": ("is below", "is less than", "falls below"),
    }.get(operator)
    if relation is None:
        raise ValueError(f"unsupported flow operator for a natural surface: {operator}")
    return f"{label} {relation[style]} {value}"


def _natural_locus_text(region: Mapping[str, Any], locus: Mapping[str, Any]) -> str:
    kind = str(locus["kind"])
    if kind == "entity":
        return f"device {locus['entity']['mention']}"
    if kind == "members":
        return {
            "all": "every member of the region",
            "one": "one member of the region",
            "any_capable": "any suitable member of the region",
        }[str(locus["quantifier"])]
    role = str(locus["role"])
    if role == "via":
        order = int(locus["via_order"])
        item = next(item for item in region.get("via", ()) if int(item["order"]) == order)
        if len(region.get("via", ())) == 1:
            return f"the intermediate point {item['mention']}"
        ordinal = {1: "first", 2: "second", 3: "third"}.get(order, f"number {order}")
        return f"the {ordinal} intermediate point, {item['mention']}"
    if role == "source" and region.get("starts_at"):
        return f"source {region['starts_at']['mention']}"
    if role == "destination" and region.get("ends_at"):
        return f"destination {region['ends_at']['mention']}"
    return f"the region {role}"


def _same_region_entity_locus(
    region: Mapping[str, Any], locus: Mapping[str, Any]
) -> bool:
    if locus.get("kind") != "entity" or not region.get("denotes"):
        return False
    return str(locus["entity"].get("mention")) == str(region["denotes"].get("mention"))


def _coincident_region_role_text(
    region: Mapping[str, Any], locus: Mapping[str, Any]
) -> str:
    role = str(locus["role"])
    scope = "path" if region.get("scope_type") == "path" else "region"
    if role == "source" and region.get("starts_at"):
        return f"the {scope} source"
    if role == "destination" and region.get("ends_at"):
        return f"the {scope} destination"
    if role == "via":
        return _natural_locus_text(region, locus).replace(
            "the intermediate point ", "the intermediate point at "
        )
    return _natural_locus_text(region, locus)


def _is_unnamed_explicit_member_set(region: Mapping[str, Any]) -> bool:
    return bool(region.get("contains")) and not any(
        region.get(field) for field in ("starts_at", "ends_at", "name", "group", "denotes")
    )


def _chatito_pattern(
    sample_id: str, style: int, rendered: RenderedSurface
) -> tuple[str, list[tuple[str, str]]]:
    pattern: list[str] = []
    aliases: list[tuple[str, str]] = []
    slot_serial = 0
    for piece in rendered.pieces:
        if not piece.fact_refs:
            pattern.append(piece.text)
            continue
        whitespace = re.fullmatch(r"(\s*)(.*?)(\s*)", piece.text, flags=re.DOTALL)
        if whitespace is None:
            raise AssertionError("slot whitespace split failed")
        leading, core, trailing = whitespace.groups()
        if not core:
            pattern.append(piece.text)
            continue
        slot_serial += 1
        kind = re.sub(r"[^a-z0-9]+", "_", piece.slot_kind.casefold()).strip("_")
        alias = (
            f"telemetry_{sample_id}_v{style + 1}_"
            f"{kind}_{slot_serial:02d}"
        )
        pattern.extend((leading, f"@[{alias}]", trailing))
        aliases.append((alias, core))
    return "".join(pattern), aliases
