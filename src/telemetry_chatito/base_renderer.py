"""English clause construction with semantic fact-to-text offsets.

Adapted from the telemetry dataset's template renderer.
Offsets are Python string indices with an exclusive end position.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .vocabulary import METRIC_SURFACES


@dataclass(frozen=True)
class SurfacePiece:
    text: str
    fact_refs: tuple[str, ...] = ()
    slot_kind: str = "text"


@dataclass(frozen=True)
class RenderedSurface:
    utterance: str
    spans: dict[str, list[dict[str, int]]]
    pieces: tuple[SurfacePiece, ...]
    syntax_form: str


class SurfaceComposer:
    def __init__(self) -> None:
        self.pieces: list[SurfacePiece] = []
        self.spans: defaultdict[str, list[dict[str, int]]] = defaultdict(list)
        self.offset = 0

    def add(
        self,
        text: str,
        *fact_refs: str,
        slot_kind: str = "text",
    ) -> None:
        if not text:
            return
        start = self.offset
        self.pieces.append(SurfacePiece(text, tuple(fact_refs), slot_kind))
        self.offset += len(text)
        for fact_ref in fact_refs:
            self.spans[fact_ref].append({"start": start, "end": self.offset})

    def mark(self, fact_ref: str, start: int, end: int) -> None:
        self.spans[fact_ref].append({"start": start, "end": end})

    @property
    def text(self) -> str:
        return "".join(piece.text for piece in self.pieces)


def render_surface(card: Mapping[str, Any], variant: int) -> RenderedSurface:
    composer = SurfaceComposer()
    tasks = card["semantic_ir"]["tasks"]
    if len(tasks) > 1:
        composer.add(
            ("Run two independent observation tasks: " if len(tasks) == 2
             else "Run independent observation tasks: "),
            "@multi_task.independent",
            slot_kind="task_relation",
        )
    syntax_form = _syntax_form(card, variant)
    for task_index, task in enumerate(tasks):
        if task_index:
            composer.add(" Separately, ")
        _render_task(composer, task_index, task, variant, syntax_form)
    expected_tagged = {
        f"{task_index}:{record['fact_ref']}"
        for task_index, task in enumerate(tasks)
        for record in task.get("provenance_by_fact", ())
    }
    actual_tagged = {
        ref.removeprefix("task:") for ref in composer.spans if ref.startswith("task:")
    }
    if not expected_tagged <= actual_tagged:
        missing = sorted(expected_tagged - actual_tagged)
        raise ValueError(f"{card['sample_id']} renderer fact refs missing={missing}")
    return RenderedSurface(
        utterance=composer.text,
        spans=dict(composer.spans),
        pieces=tuple(composer.pieces),
        syntax_form=syntax_form,
    )


def _syntax_form(card: Mapping[str, Any], variant: int) -> str:
    tasks = card["semantic_ir"]["tasks"]
    has_stages = any(
        task["acquire"]
        or task.get("aggregate")
        or task.get("deliver")
        or task.get("lifecycle")
        for task in tasks
    )
    has_flow = any(task.get("flow_conditions") for task in tasks)
    if not has_stages and len(tasks) == 1:
        return ("imperative", "question", "passive", "declarative")[variant % 4]
    if has_flow:
        return "condition_fronted" if variant % 2 else "imperative"
    return ("imperative", "declarative", "passive")[variant % 3]


def _task_ref(task_index: int, fact_ref: str) -> str:
    return f"task:{task_index}:{fact_ref}"


def _render_task(
    composer: SurfaceComposer,
    task_index: int,
    task: Mapping[str, Any],
    variant: int,
    syntax_form: str,
) -> None:
    lifecycle = task.get("lifecycle", {})
    if lifecycle.get("duration") is not None:
        composer.add("For the next ")
        composer.add(
            _duration_text(lifecycle["duration"]),
            _task_ref(task_index, "/lifecycle/duration"),
            slot_kind="lifecycle_time",
        )
        composer.add(", ")

    flow_fronted = syntax_form == "condition_fronted" and task.get("flow_conditions")
    if flow_fronted:
        composer.add("for " if composer.offset else "For ")
        if task["region"]["scope_type"] == "unspecified":
            composer.add(
                "traffic",
                _task_ref(task_index, "/region/scope_type"),
                slot_kind="region",
            )
            composer.add(" where ")
            _add_flow(composer, task_index, task["flow_conditions"], include_lead=False)
        else:
            _add_flow(composer, task_index, task["flow_conditions"])
        composer.add(", ")

    mode = task["acquire"].get("mode")
    metric_start = composer.offset
    if mode:
        verb = {"poll": "Poll", "probe": "Probe", "stream": "Stream"}[mode]
        if composer.offset:
            verb = verb.lower()
        composer.add(
            verb,
            _task_ref(task_index, "/acquire/mode"),
            slot_kind="acquire_mode",
        )
        composer.add(" ")
        _add_metrics(composer, task_index, task["metric_ids"])
    elif syntax_form == "question":
        composer.add("What is the current ")
        _add_metrics(composer, task_index, task["metric_ids"])
    elif syntax_form == "passive":
        _add_metrics(
            composer,
            task_index,
            task["metric_ids"],
            capitalize=composer.offset == 0,
        )
        composer.add(" should be measured")
    else:
        action = ("Measure", "Monitor", "Track", "Collect")[variant % 4]
        if composer.offset:
            action = action.lower()
        composer.add(action + " ")
        _add_metrics(composer, task_index, task["metric_ids"])

    if len(task["metric_ids"]) > 1:
        composer.mark("@multi_metric.shared_task", metric_start, composer.offset)
    if not (flow_fronted and task["region"]["scope_type"] == "unspecified"):
        composer.add(" ")
        _add_region(
            composer,
            task_index,
            task["region"],
            flow_attached=bool(task.get("flow_conditions")),
        )
    if task.get("flow_conditions") and not flow_fronted:
        if task["region"]["scope_type"] == "unspecified":
            composer.add(" where ")
            _add_flow(composer, task_index, task["flow_conditions"], include_lead=False)
        else:
            composer.add(" for ")
            _add_flow(composer, task_index, task["flow_conditions"])

    acquire = task["acquire"]
    if acquire.get("period") is not None:
        composer.add(", ")
        composer.add(
            f"sampling every {_duration_text(acquire['period'])}",
            _task_ref(task_index, "/acquire/period"),
            slot_kind="acquire_time",
        )
    if acquire.get("count") is not None:
        composer.add(", ")
        composer.add(
            f"taking {acquire['count']} samples",
            _task_ref(task_index, "/acquire/count"),
            slot_kind="acquire_count",
        )
    if acquire.get("sampling_ratio") is not None:
        composer.add(" at ")
        composer.add(
            f"{_ratio_text(acquire['sampling_ratio'])} sampling ratio",
            _task_ref(task_index, "/acquire/sampling_ratio"),
            slot_kind="sampling_ratio",
        )
    for source_index, source in enumerate(acquire.get("data_sources", [])):
        composer.add(", ")
        text = f"using {source['mention']}"
        if source.get("owner") and source["owner"]["mention"] not in source["mention"]:
            text += f" owned by device {source['owner']['mention']}"
        composer.add(
            text,
            _task_ref(task_index, f"/acquire/data_sources/{source_index}"),
            slot_kind="data_source",
        )
    _add_loci(composer, task_index, task, "acquire")
    composer.add("?" if syntax_form == "question" else ".")

    aggregate = task.get("aggregate")
    if aggregate:
        composer.add(" ")
        composer.add(("Compute", "Calculate", "Return")[variant % 3] + " the ")
        composer.add(
            _operator_text(aggregate["operator"]),
            _task_ref(task_index, "/aggregate/operator"),
            slot_kind="aggregate_operator",
        )
        composer.add(" ")
        composer.add(
            _aggregate_over_text(aggregate["over"]),
            _task_ref(task_index, "/aggregate/over"),
            slot_kind="aggregate_scope",
        )
        if aggregate.get("stride") is not None:
            composer.add(", ")
            composer.add(
                f"starting a new window every {_duration_text(aggregate['stride'])}",
                _task_ref(task_index, "/aggregate/stride"),
                slot_kind="aggregate_stride",
            )
        _add_loci(composer, task_index, task, "aggregate")
        composer.add(".")

    deliver = task.get("deliver")
    if deliver:
        composer.add(" ")
        verb = {"report": "Report", "export": "Export", "store": "Store"}[deliver["kind"]]
        composer.add(
            verb,
            _task_ref(task_index, "/deliver/kind"),
            slot_kind="deliver_kind",
        )
        composer.add(" the results")
        if deliver.get("period") is not None:
            composer.add(" ")
            composer.add(
                f"every {_duration_text(deliver['period'])}",
                _task_ref(task_index, "/deliver/period"),
                slot_kind="deliver_time",
            )
        if deliver.get("batch") is not None:
            composer.add(" in ")
            composer.add(
                f"batches of {deliver['batch']}",
                _task_ref(task_index, "/deliver/batch"),
                slot_kind="deliver_batch",
            )
        if deliver.get("destination") is not None:
            composer.add(" to ")
            composer.add(
                f"collector {deliver['destination']['mention']}",
                _task_ref(task_index, "/deliver/destination"),
                slot_kind="deliver_destination",
            )
        if deliver.get("retention") is not None:
            composer.add(" with ")
            composer.add(
                f"retention for {_duration_text(deliver['retention'])}",
                _task_ref(task_index, "/deliver/retention"),
                slot_kind="retention_time",
            )
        _add_loci(composer, task_index, task, "deliver")
        composer.add(".")


def _add_metrics(
    composer: SurfaceComposer,
    task_index: int,
    metric_ids: Sequence[str],
    *,
    capitalize: bool = False,
) -> None:
    for index, metric_id in enumerate(metric_ids):
        if index:
            composer.add(" and ")
        text = METRIC_SURFACES[metric_id]
        if capitalize and index == 0:
            text = text[0].upper() + text[1:]
        composer.add(
            text,
            _task_ref(task_index, f"/metric_ids/{index}"),
            slot_kind="metric",
        )


def _add_region(
    composer: SurfaceComposer,
    task_index: int,
    region: Mapping[str, Any],
    *,
    flow_attached: bool = False,
) -> None:
    scope = region["scope_type"]
    scope_ref = _task_ref(task_index, "/region/scope_type")
    if scope == "unspecified":
        composer.add(
            "for traffic" if flow_attached else "for selected traffic",
            scope_ref,
            slot_kind="region",
        )
        return
    if region.get("denotes") is not None:
        labels = {
            "entity": "on device",
            "interface": "on interface",
            "link": "on named link",
            "path": "on named path",
            "network_region": "in network region",
        }
        mention = region["denotes"]["mention"]
        lead = labels[scope]
        if scope in {"link", "path"} and mention.casefold().startswith(f"the {scope} from "):
            lead = "on"
        composer.add(
            f"{lead} {mention}",
            scope_ref,
            _task_ref(task_index, "/region/denotes"),
            slot_kind="region",
        )
        return
    if region.get("contains"):
        composer.add("across the network region", scope_ref, slot_kind="region_type")
        if region.get("starts_at") and region.get("ends_at"):
            composer.add(" from ")
            composer.add(
                region["starts_at"]["mention"],
                _task_ref(task_index, "/region/starts_at"),
                slot_kind="region_start",
            )
            composer.add(" to ")
            composer.add(
                region["ends_at"]["mention"],
                _task_ref(task_index, "/region/ends_at"),
                slot_kind="region_end",
            )
        composer.add(" containing devices ")
        for index, item in enumerate(region["contains"]):
            if index:
                composer.add(", " if index < len(region["contains"]) - 1 else ", and ")
            composer.add(
                item["mention"],
                _task_ref(task_index, f"/region/contains/{index}"),
                slot_kind="region_member",
            )
        return
    noun = {"link": "link", "path": "path", "network_region": "network region"}[scope]
    composer.add(f"along the {noun} ", scope_ref, slot_kind="region_type")
    composer.add("from ")
    composer.add(
        region["starts_at"]["mention"],
        _task_ref(task_index, "/region/starts_at"),
        slot_kind="region_start",
    )
    for index, via in enumerate(region.get("via", [])):
        composer.add(" via ")
        composer.add(
            f"hop {via['order']} at {via['mention']}",
            _task_ref(task_index, f"/region/via/{index}"),
            slot_kind="region_via",
        )
    composer.add(" to ")
    composer.add(
        region["ends_at"]["mention"],
        _task_ref(task_index, "/region/ends_at"),
        slot_kind="region_end",
    )


def _add_flow(
    composer: SurfaceComposer,
    task_index: int,
    conditions: Sequence[Mapping[str, Any]],
    *,
    include_lead: bool = True,
) -> None:
    if include_lead:
        composer.add("traffic where ")
    labels = {
        "tenant": "tenant",
        "src_ip": "source IP",
        "dst_ip": "destination IP",
        "protocol": "protocol",
        "dst_port": "destination port",
    }
    operators = {"eq": "equals", "neq": "does not equal", "gt": "is above", "lt": "is below"}
    for index, condition in enumerate(conditions):
        if index:
            composer.add(" and ")
        if condition["field"] == "tenant" and condition["op"] == "eq":
            value = str(condition["value"])
            article = "the " if value.casefold().endswith(" tenant") else ""
            text = f"the flow belongs to {article}{value}"
        else:
            text = (
                f"{labels.get(condition['field'], condition['field'])} "
                f"{operators.get(condition['op'], condition['op'])} {condition['value']}"
            )
        composer.add(
            text,
            _task_ref(task_index, f"/flow_conditions/{index}"),
            slot_kind="flow_condition",
        )


def _add_loci(
    composer: SurfaceComposer,
    task_index: int,
    task: Mapping[str, Any],
    operation: str,
) -> None:
    stage = task.get(operation, {})
    for index, locus in enumerate(stage.get("requested_loci", [])):
        composer.add(", ")
        composer.add(
            f"with {operation} execution at {_locus_text(task['region'], locus)}",
            _task_ref(task_index, f"/{operation}/requested_loci/{index}"),
            slot_kind=f"{operation}_locus",
        )


def _locus_text(region: Mapping[str, Any], locus: Mapping[str, Any]) -> str:
    if locus["kind"] == "entity":
        return f"device {locus['entity']['mention']}"
    if locus["kind"] == "members":
        quantifier = str(locus["quantifier"]).replace("_", " ")
        noun = "member" if locus["quantifier"] in {"one", "any_capable"} else "members"
        return f"{quantifier} region {noun}"
    role = locus["role"]
    if role == "via":
        order = int(locus["via_order"])
        via = next(item for item in region.get("via", []) if int(item["order"]) == order)
        return f"via hop {order} at {via['mention']}"
    if role == "source" and region.get("starts_at"):
        return f"the region source {region['starts_at']['mention']}"
    if role == "destination" and region.get("ends_at"):
        return f"the region destination {region['ends_at']['mention']}"
    if region.get("contains"):
        return f"the region {role} represented by {region['contains'][0]['mention']}"
    return f"the region {role}"


def _duration_text(duration: Mapping[str, Any], *, hyphenated: bool = False) -> str:
    names = {"ms": "millisecond", "s": "second", "min": "minute", "h": "hour"}
    value = duration["value"]
    unit = names.get(duration["unit"], str(duration["unit"]))
    if value != 1 and not hyphenated:
        unit += "s"
    return f"{value}{'-' if hyphenated else ' '}{unit}"


def _ratio_text(value: Any) -> str:
    number = float(value) * 100
    return f"{number:g} percent"


def _operator_text(operator: str) -> str:
    return {"max": "maximum", "mean": "mean", "p95": "95th percentile"}[operator]


def _aggregate_over_text(over: Mapping[str, Any]) -> str:
    if over["kind"] == "time":
        return f"over {_duration_text(over['window'], hyphenated=True)} windows"
    if over["kind"] == "flows":
        return "across flows"
    return "across region members"
