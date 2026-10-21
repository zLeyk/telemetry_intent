"""Build auditable text variants from user-supplied semantic cards."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

from .chatito import default_runtime, verify_expansion
from .renderer import assign_styles, render_grammar, render_variants, surface_family


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_strings(value: Any) -> None:
    if isinstance(value, str):
        if any(ord(char) < 32 for char in value) or any(x in value for x in ("@[", "%[", "~[")):
            raise ValueError("Card strings must be single-line literals without Chatito directives.")
    elif isinstance(value, dict):
        for key, item in value.items():
            _check_strings(key)
            _check_strings(item)
    elif isinstance(value, list):
        for item in value:
            _check_strings(item)


def load_cards(path: Path) -> list[dict[str, Any]]:
    cards = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        card = json.loads(line)
        if not isinstance(card, dict):
            raise ValueError(f"Line {number}: each card must be a JSON object.")
        unexpected = set(card) - {"sample_id", "semantic_ir"}
        if unexpected:
            raise ValueError(f"Line {number}: unsupported card fields {sorted(unexpected)}. See the README input format.")
        sample_id = card.get("sample_id", "")
        if not isinstance(sample_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", sample_id):
            raise ValueError(f"Line {number}: sample_id must be a short ASCII identifier beginning with a letter.")
        if sample_id in seen:
            raise ValueError(f"Duplicate sample_id: {sample_id}")
        seen.add(sample_id)
        ir = card.get("semantic_ir")
        if not isinstance(ir, dict) or not isinstance(ir.get("tasks"), list) or not ir["tasks"]:
            raise ValueError(f"{sample_id}: semantic_ir.tasks must be a nonempty list.")
        for task in ir["tasks"]:
            if not isinstance(task, dict) or not isinstance(task.get("region"), dict):
                raise ValueError(f"{sample_id}: every task needs a region object.")
            if not isinstance(task.get("metric_ids"), list) or not task["metric_ids"]:
                raise ValueError(f"{sample_id}: every task needs a nonempty metric_ids list.")
            if not isinstance(task.get("acquire"), dict):
                raise ValueError(f"{sample_id}: every task needs an acquire object.")
        _check_strings(card)
        cards.append(card)
    if not cards:
        raise ValueError("The input contains no semantic cards.")
    return sorted(cards, key=lambda card: card["sample_id"])


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.write_bytes("".join(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n"
                             for value in values).encode("utf-8"))


def verify_output(output: Path, runtime: Path, node: str) -> dict[str, Any]:
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, digest in manifest["artifacts"].items():
        if Path(name).name != name or name not in {"templates.chatito", "variants.jsonl", "selected.jsonl"}:
            raise ValueError("Unexpected artifact entry in manifest.")
        if sha256(output / name) != digest:
            raise ValueError(f"Artifact has changed since preparation: {name}")
    records = [json.loads(line) for line in (output / "variants.jsonl").read_text(encoding="utf-8").splitlines()]
    expected = {row["chatito_intent"]: [item["utterance"] for item in row["variants"]] for row in records}
    report, raw = verify_expansion(output / "templates.chatito", expected, runtime, node)
    (output / "chatito_raw.json").write_bytes(raw)
    report["runtime_package_lock_sha256"] = sha256(runtime / "package-lock.json")
    manifest["chatito_verification"] = report
    temporary = manifest_path.with_suffix(".tmp")
    _write_json(temporary, manifest)
    temporary.replace(manifest_path)
    return report


def generate(cards_path: Path, output: Path, *, compile_chatito: bool,
             runtime: Path, node: str) -> dict[str, Any]:
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"Output already exists; choose a new directory: {output}")
    cards = load_cards(cards_path)
    styles = assign_styles(cards)
    entries = []
    records = []
    selected = []
    for card in cards:
        sample_id = card["sample_id"]
        variants = render_variants(card)
        for variant in variants:
            if "".join(piece.text for piece in variant.pieces) != variant.utterance:
                raise ValueError(f"Text pieces do not reconstruct the utterance: {sample_id}")
            for spans in variant.spans.values():
                for span in spans:
                    if not 0 <= span["start"] < span["end"] <= len(variant.utterance):
                        raise ValueError(f"Invalid evidence span: {sample_id}")
        entries.append((sample_id, variants))
        record = {
            "sample_id": sample_id,
            "chatito_intent": f"telemetry_{sample_id}",
            "surface_family": surface_family(card),
            "semantic_ir": card["semantic_ir"],
            "variants": [asdict(item) for item in variants],
        }
        records.append(record)
        item = variants[styles[sample_id]]
        selected.append({"sample_id": sample_id, "surface_family": record["surface_family"],
                         "style": styles[sample_id], "utterance": item.utterance, "spans": item.spans})
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".chatito_prepare_", dir=output.parent) as directory:
        work = Path(directory)
        (work / "templates.chatito").write_bytes(render_grammar(entries).encode("utf-8"))
        _write_jsonl(work / "variants.jsonl", records)
        _write_jsonl(work / "selected.jsonl", selected)
        manifest = {
            "format_version": 1,
            "generator": "telemetry-chatito-generator 0.1.0",
            "input_sha256": sha256(cards_path),
            "card_count": len(cards),
            "variants_per_card": 3,
            "selection": "stable sample-ID order, round-robin within structural family",
            "source_files": {path.name: sha256(path) for path in sorted(Path(__file__).parent.glob("*.py"))},
            "artifacts": {name: sha256(work / name) for name in ("templates.chatito", "variants.jsonl", "selected.jsonl")},
            "chatito_verification": {"status": "not_run", "executions": 0},
        }
        _write_json(work / "manifest.json", manifest)
        if compile_chatito:
            verify_output(work, runtime, node)
        work.rename(output)
    return json.loads((output / "manifest.json").read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("generate", "prepare", "verify"):
        command = subcommands.add_parser(name)
        command.add_argument("--output", type=Path, required=True)
        if name != "verify":
            command.add_argument("--cards", type=Path, required=True)
        command.add_argument("--runtime", type=Path, default=default_runtime())
        command.add_argument("--node", default="node")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            result = verify_output(args.output, args.runtime, args.node)
        else:
            result = generate(args.cards, args.output, compile_chatito=args.command == "generate",
                              runtime=args.runtime, node=args.node)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0
