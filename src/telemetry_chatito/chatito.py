"""Execute the pinned Chatito CLI and check its actual output."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any


def default_runtime() -> Path:
    return Path(__file__).resolve().parents[2] / "vendor" / "chatito"


def compile_once(grammar: Path, runtime: Path, node: str = "node") -> tuple[bytes, dict[str, list[str]]]:
    runtime = runtime.resolve()
    node_path = shutil.which(node)
    if node_path is None:
        raise RuntimeError("Node.js was not found. Install Node.js 18+ or pass --node PATH.")
    register = runtime / "node_modules" / "ts-node" / "register"
    if not register.is_dir():
        raise RuntimeError(f"Chatito dependencies are missing. Run npm ci --ignore-scripts in {runtime}")
    for relative in ("src/bin.ts", "parser/chatito.js", "tsconfig.json"):
        if not (runtime / relative).is_file():
            raise RuntimeError(f"Incomplete Chatito runtime: {relative}")
    env = os.environ.copy()
    env.update({
        "NODE_PATH": str(runtime / "node_modules"),
        "TS_NODE_PROJECT": str(runtime / "tsconfig.json"),
        "TS_NODE_TRANSPILE_ONLY": "1",
    })
    with tempfile.TemporaryDirectory(prefix="telemetry_chatito_") as directory:
        command = [node_path, "-r", str(register), str(runtime / "src/bin.ts"),
                   str(grammar.resolve()), f"--outputPath={directory}",
                   "--trainingFileName=compiled.json", "--autoAliases=restrict"]
        result = subprocess.run(command, env=env, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=120, check=False)
        if result.returncode:
            raise RuntimeError(f"Chatito exited with {result.returncode}:\n{result.stderr or result.stdout}")
        output = Path(directory) / "compiled.json"
        if not output.is_file():
            raise RuntimeError("Chatito completed without the expected compiled.json.")
        raw = output.read_bytes()
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ValueError("Unexpected Chatito output format.")
    surfaces = {key: ["".join(str(token["value"]) for token in tokens)
                      for tokens in examples] for key, examples in decoded.items()}
    return raw, surfaces


def verify_expansion(grammar: Path, expected: dict[str, list[str]], runtime: Path,
                     node: str = "node") -> tuple[dict[str, Any], bytes]:
    """Run Chatito twice; require exact variant membership and byte reproducibility."""
    first, actual = compile_once(grammar, runtime, node)
    second, repeated = compile_once(grammar, runtime, node)
    if first != second or actual != repeated:
        raise ValueError("Two actual Chatito executions produced different outputs.")
    if set(actual) != set(expected):
        raise ValueError("Chatito intent IDs differ from the expected grammar inventory.")
    for key, variants in expected.items():
        if len(actual[key]) != len(variants) or sorted(actual[key]) != sorted(variants):
            raise ValueError(f"Chatito changed or omitted a text variant for {key}.")
    return {
        "status": "passed",
        "executions": 2,
        "byte_identical": first == second,
        "exact_variant_match": True,
        "intent_count": len(actual),
        "variant_count": sum(map(len, actual.values())),
        "compiled_sha256": hashlib.sha256(first).hexdigest(),
        "grammar_sha256": hashlib.sha256(grammar.read_bytes()).hexdigest(),
    }, first
