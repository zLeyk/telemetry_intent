"""Behavioral checks for controlled surface generation, without benchmark data."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import unittest

from telemetry_chatito import assign_styles, render_grammar, render_variants, surface_family


EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "cards.jsonl"


def load_cards():
    return [json.loads(line) for line in EXAMPLES.read_text(encoding="utf-8").splitlines() if line.strip()]


def evidence(rendered, fact_ref):
    return " ".join(rendered.utterance[s["start"] : s["end"]] for s in rendered.spans[fact_ref])


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.cards = load_cards()
        self.by_id = {card["sample_id"]: card for card in self.cards}

    def test_examples_have_distinct_reproducible_variants(self):
        for card in self.cards:
            with self.subTest(card=card["sample_id"]):
                first = render_variants(card)
                self.assertEqual(3, len(first))
                self.assertEqual(3, len({v.utterance for v in first}))
                self.assertEqual(first, render_variants(copy.deepcopy(card)))

    def test_single_metric_and_device_are_both_explicit(self):
        for rendered in render_variants(self.by_id["demo_single"]):
            self.assertIn("demo-sw-A", evidence(rendered, "task:0:/region/denotes"))
            self.assertIn("cpu", evidence(rendered, "task:0:/metric_ids/0").casefold())
            self.assertNotIn("memory", rendered.utterance.casefold())

    def test_multiple_metrics_keep_one_interface_scope(self):
        for rendered in render_variants(self.by_id["demo_multi_metric"]):
            self.assertIn("packet count", evidence(rendered, "task:0:/metric_ids/0").casefold())
            self.assertIn("throughput", evidence(rendered, "task:0:/metric_ids/1").casefold())
            scope = evidence(rendered, "task:0:/region/denotes")
            self.assertIn("Ethernet3/2", scope)
            self.assertIn("demo-sw-B", scope)
            self.assertIn("@multi_metric.shared_task", rendered.spans)
            self.assertFalse(any(ref.startswith("task:1:") for ref in rendered.spans))

    def test_sampling_window_and_stride_retain_separate_roles(self):
        refs = (
            "task:0:/acquire/period",
            "task:0:/aggregate/over",
            "task:0:/aggregate/stride",
        )
        for rendered in render_variants(self.by_id["demo_time_roles"]):
            sampling, window, stride = (evidence(rendered, ref).casefold() for ref in refs)
            self.assertRegex(sampling, r"sampling.*250 milliseconds")
            self.assertIn("23-second", window)
            self.assertIn("window", window)
            self.assertRegex(stride, r"new window.*7 seconds")
            self.assertNotIn("250", window + stride)
            self.assertNotIn("23", sampling + stride)
            self.assertNotIn("7 seconds", sampling + window)

    def test_no_unspecified_sampling_period_is_added(self):
        for rendered in render_variants(self.by_id["demo_single"]):
            self.assertNotIn("task:0:/acquire/period", rendered.spans)
            self.assertNotRegex(rendered.utterance.casefold(), r"\b\d+\s*(?:milli)?seconds?\b")
            self.assertNotIn("sampling every", rendered.utterance.casefold())

    def test_ordered_path_preserves_source_vias_and_destination(self):
        names = ["demo-edge-A", "demo-relay-B", "demo-relay-C", "demo-edge-D"]
        refs = ["/region/starts_at", "/region/via/0", "/region/via/1", "/region/ends_at"]
        for rendered in render_variants(self.by_id["demo_ordered_path"]):
            positions = [rendered.utterance.index(name) for name in names]
            self.assertEqual(sorted(positions), positions)
            for name, ref in zip(names, refs):
                self.assertIn(name, evidence(rendered, "task:0:" + ref))
            self.assertIn("end-to-end", evidence(rendered, "task:0:/metric_ids/0").casefold())

    def test_two_tasks_do_not_swap_metric_scope_associations(self):
        for rendered in render_variants(self.by_id["demo_two_tasks"]):
            self.assertIn("cpu", evidence(rendered, "task:0:/metric_ids/0").casefold())
            self.assertIn("demo-sw-D", evidence(rendered, "task:0:/region/denotes"))
            self.assertIn("memory", evidence(rendered, "task:1:/metric_ids/0").casefold())
            self.assertIn("demo-sw-E", evidence(rendered, "task:1:/region/denotes"))
            first_end = max(s["end"] for key, spans in rendered.spans.items() if key.startswith("task:0:") for s in spans)
            second_start = min(s["start"] for key, spans in rendered.spans.items() if key.startswith("task:1:") for s in spans)
            self.assertLessEqual(first_end, second_start)

        three_tasks = copy.deepcopy(self.by_id["demo_two_tasks"])
        extra = copy.deepcopy(three_tasks["semantic_ir"]["tasks"][0])
        extra["region"]["denotes"]["mention"] = "demo-sw-H"
        three_tasks["semantic_ir"]["tasks"].append(extra)
        for rendered in render_variants(three_tasks):
            self.assertIn("demo-sw-H", evidence(rendered, "task:2:/region/denotes"))
            self.assertNotRegex(rendered.utterance.casefold(), r"\b(?:two|both)\b")

    def test_flow_filters_and_delivery_keep_their_distinct_roles(self):
        for rendered in render_variants(self.by_id["demo_filter_delivery"]):
            self.assertIn("udp", evidence(rendered, "task:0:/flow_conditions/0").casefold())
            port = evidence(rendered, "task:0:/flow_conditions/1").casefold()
            self.assertIn("destination port", port)
            self.assertIn("5353", port)
            self.assertIn("report", evidence(rendered, "task:0:/deliver/kind").casefold())
            self.assertIn("13 seconds", evidence(rendered, "task:0:/deliver/period"))
            self.assertIn("demo-collector-G", evidence(rendered, "task:0:/deliver/destination"))
            self.assertNotIn("task:0:/acquire/period", rendered.spans)

    def test_local_delivery_preserves_export_or_storage_operation(self):
        for kind, noun in (("export", "export"), ("store", "storage")):
            card = copy.deepcopy(self.by_id["demo_single"])
            task = card["semantic_ir"]["tasks"][0]
            task["deliver"] = {
                "kind": kind,
                "requested_loci": [{"kind": "entity", "entity": copy.deepcopy(task["region"]["denotes"])}],
            }
            for rendered in render_variants(card):
                with self.subTest(kind=kind):
                    locus = evidence(rendered, "task:0:/deliver/requested_loci/0").casefold()
                    self.assertIn("local", locus)
                    self.assertIn(noun, locus)
                    self.assertNotIn("reporting", locus)

    def test_all_spans_select_nonempty_text_within_output(self):
        for card in self.cards:
            for rendered in render_variants(card):
                for ref, spans in rendered.spans.items():
                    with self.subTest(card=card["sample_id"], ref=ref):
                        self.assertTrue(spans)
                        for span in spans:
                            self.assertGreaterEqual(span["start"], 0)
                            self.assertGreater(span["end"], span["start"])
                            self.assertLessEqual(span["end"], len(rendered.utterance))
                            self.assertTrue(rendered.utterance[span["start"] : span["end"]].strip())

    def test_structural_family_does_not_depend_on_split_or_entity_names(self):
        card = self.by_id["demo_single"]
        modified = copy.deepcopy(card)
        modified.update(sample_id="different_id", split="unseen", difficulty="hard")
        modified["semantic_ir"]["tasks"][0]["region"]["denotes"]["mention"] = "demo-other-device"
        self.assertEqual(surface_family(card), surface_family(modified))
        modified["semantic_ir"]["tasks"][0]["metric_ids"].append("device_memory")
        self.assertNotEqual(surface_family(card), surface_family(modified))

    def test_balanced_style_assignment_is_order_independent(self):
        copies = []
        for i in range(8):
            card = copy.deepcopy(self.by_id["demo_single"])
            card["sample_id"] = f"balance_{i:02d}"
            copies.append(card)
        styles = assign_styles(copies)
        self.assertEqual(styles, assign_styles(list(reversed(copies))))
        self.assertEqual(set(styles), {card["sample_id"] for card in copies})
        counts = [list(styles.values()).count(style) for style in range(3)]
        self.assertLessEqual(max(counts) - min(counts), 1)

    def test_generation_does_not_mutate_input_cards(self):
        original = copy.deepcopy(self.cards)
        entries = [(c["sample_id"], render_variants(c)) for c in self.cards]
        assign_styles(self.cards)
        for card in self.cards:
            surface_family(card)
        render_grammar(entries)
        self.assertEqual(original, self.cards)

    def test_required_fact_without_text_evidence_is_rejected(self):
        card = copy.deepcopy(self.by_id["demo_single"])
        card["semantic_ir"]["tasks"][0]["provenance_by_fact"] = [{"fact_ref": "/aggregate/stride"}]
        with self.assertRaises(ValueError):
            render_variants(card)

    def test_grammar_has_no_unresolved_slot_references(self):
        grammar = render_grammar([(c["sample_id"], render_variants(c)) for c in self.cards])
        definitions = re.findall(r"^@\[([^\]]+)\]$", grammar, re.MULTILINE)
        references = re.findall(r"@\[([^\]]+)\]", "\n".join(line for line in grammar.splitlines() if line.startswith("    ")))
        self.assertTrue(references)
        self.assertEqual(len(definitions), len(set(definitions)))
        self.assertEqual(set(references), set(definitions))
        for card in self.cards:
            self.assertIn(card["sample_id"], grammar)


if __name__ == "__main__":
    unittest.main()
