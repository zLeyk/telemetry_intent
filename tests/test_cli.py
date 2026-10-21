import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from telemetry_chatito.cli import generate, load_cards, verify_output
from telemetry_chatito.chatito import verify_expansion

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_unverified_preparation_is_explicit_and_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            left, right = Path(directory) / "a", Path(directory) / "b"
            args = {"compile_chatito": False, "runtime": Path(directory), "node": "node"}
            first = generate(ROOT / "examples/cards.jsonl", left, **args)
            second = generate(ROOT / "examples/cards.jsonl", right, **args)
            self.assertEqual(first["chatito_verification"], {"status": "not_run", "executions": 0})
            self.assertEqual(first, second)
            self.assertEqual(first["card_count"], 6)
            for name in first["artifacts"]:
                self.assertEqual((left / name).read_bytes(), (right / name).read_bytes())
            with self.assertRaises(FileExistsError):
                generate(ROOT / "examples/cards.jsonl", left, **args)

    def test_duplicate_and_directive_inputs_are_rejected(self):
        row = json.loads((ROOT / "examples/cards.jsonl").read_text().splitlines()[0])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cards.jsonl"
            path.write_text(json.dumps(row) + "\n" + json.dumps(row), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                load_cards(path)
            bad = copy.deepcopy(row)
            bad["semantic_ir"]["tasks"][0]["region"]["denotes"]["mention"] = "@[injected]"
            path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "directives"):
                load_cards(path)

    def test_modified_output_cannot_reuse_old_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            generate(ROOT / "examples/cards.jsonl", output, compile_chatito=False,
                     runtime=Path(directory), node="node")
            (output / "templates.chatito").write_text("modified", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed"):
                verify_output(output, Path(directory), "node")

    def test_verification_rejects_missing_variant_and_nondeterminism(self):
        with tempfile.TemporaryDirectory() as directory:
            grammar = Path(directory) / "test.chatito"
            grammar.write_text("demo", encoding="utf-8")
            with patch("telemetry_chatito.chatito.compile_once", return_value=(b"one", {"demo": ["a"]})):
                with self.assertRaisesRegex(ValueError, "omitted"):
                    verify_expansion(grammar, {"demo": ["a", "b"]}, Path(directory))
            with patch("telemetry_chatito.chatito.compile_once", side_effect=[(b"a", {"demo": ["a"]}), (b"b", {"demo": ["a"]})]):
                with self.assertRaisesRegex(ValueError, "different"):
                    verify_expansion(grammar, {"demo": ["a"]}, Path(directory))


if __name__ == "__main__":
    unittest.main()
