# Chatito Template Generation for Network Telemetry Intents

**English** | [简体中文](README.zh-CN.md)

This tool converts **each telemetry semantic card into three English wording variants**, exports a Chatito grammar, and runs Chatito to verify the expanded output. Text is composed from semantic fields describing observation scope, metrics, acquisition, aggregation, and delivery.

## Scope

The package includes template construction, lexicalization, deterministic style selection, Chatito execution and verification, and six demonstration cards with fictional device names.

## Quick start

Requirements: Python 3.10 or later, plus Node.js 18 or later and npm to run Chatito.

From the repository root, install the locked Chatito dependencies:

```text
npm --prefix vendor/chatito ci --ignore-scripts
```

Run the complete workflow:

```text
python -B run.py generate --cards examples/cards.jsonl --output outputs/demo
```

This command generates templates and text, runs Chatito in two separate temporary directories, checks that all wording variants are present, and verifies that both runs produce identical output bytes. Results are saved after verification succeeds. The output directory must not already exist.

To generate only the grammar and Python-rendered text:

```text
python -B run.py prepare --cards examples/cards.jsonl --output outputs/preview
```

`prepare` leaves the verification status as `not_run`. After installing the dependencies, verify the prepared output with:

```text
python -B run.py verify --output outputs/preview
```

If Node.js is not on `PATH`, use `--node` to specify its executable. Use `--runtime` to select a different Chatito runtime directory containing `src/bin.ts`, `package-lock.json`, and `node_modules`.

## Input

Input uses UTF-8 JSON Lines, with one semantic card per line. See [examples/cards.jsonl](examples/cards.jsonl).

| Field | Description |
|---|---|
| `sample_id` | Unique identifier of up to 64 characters; starts with an ASCII letter, followed by ASCII letters, digits, underscores, or hyphens |
| `semantic_ir.tasks` | Ordered list of observation tasks |
| `region` | Observation scope and object information for each task |
| `metric_ids` | Nonempty metric list for each task; see `vocabulary.py` for supported metrics |
| `acquire` | Acquisition parameters; use `{}` when no parameters are specified |
| `aggregate`, `deliver`, `lifecycle` | Optional aggregation, delivery, and task-duration parameters |

Sampling intervals, aggregation window lengths, window strides, and delivery intervals are specified separately. Durations use an object with `value` and `unit` fields. Intermediate path nodes are expressed in the order of the `via` list.

## Output

| File | Contents |
|---|---|
| `templates.chatito` | Chatito grammar derived from the input cards, with three wording variants per card |
| `variants.jsonl` | All variants, semantic cards, text fragments, and evidence spans |
| `selected.jsonl` | One variant per card, selected by deterministic round-robin assignment within each structural family |
| `chatito_raw.json` | Chatito's compiled output, saved only after successful verification |
| `manifest.json` | Input, source-code, and output hashes, together with verification status |

Output uses UTF-8 encoding and LF line endings. `spans` use Python string character indices with an inclusive start and exclusive end. Selection and generation are deterministic for a fixed input collection and code version; changing sample identifiers or the input collection may change style assignments.

## Core modules

| File | Purpose |
|---|---|
| `src/telemetry_chatito/renderer.py` | Main rendering interface: three wording variants, structural families, style assignment, and Chatito grammar export |
| `src/telemetry_chatito/base_renderer.py` | Text construction and evidence spans for scope, metrics, stages, and time parameters |
| `src/telemetry_chatito/vocabulary.py` | English metric vocabulary |
| `src/telemetry_chatito/chatito.py` | Chatito execution and expansion verification |
| `src/telemetry_chatito/cli.py` | JSONL input, command-line interface, output, and verification summaries |
| `vendor/chatito/` | Chatito runtime source subset, original MIT license, and dependency lock file |

The `telemetry_chatito` package exports four functions: `render_variants` generates wording variants, `surface_family` computes a structural-family identifier, `assign_styles` assigns styles, and `render_grammar` exports the Chatito grammar.

## Verification

```text
python -B run_tests.py
```

Tests cover temporal roles, path order, task associations, evidence spans, input preservation, deterministic generation, and verification failures. Use the `generate` command above for Chatito integration verification.

Environment and cross-platform check summaries are recorded in [verification/checks.json](verification/checks.json), with demonstration output in `verification/demo/`. Windows verification reused installed JavaScript dependencies; a clean installation from the dependency lock file was checked on Linux.

The `source_files` field in each verification record identifies the code version used for that run. The Linux record retains source hashes from before updates to documentation strings and an input error message. The current version's templates, text, and Chatito output were checked against that record and match.

To check file integrity:

```text
python -B check_package.py
```

## Extension and scope

When adding semantic fields, update text mappings, evidence spans, and tests. Extend the vocabulary when adding metrics.

## Source and licensing

The template code is adapted from this research project's telemetry semantic-card generation module. Chatito is distributed under the MIT license; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for its source, version, and license. No license has been specified for this project's original code.
