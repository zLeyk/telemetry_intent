"""Verify the file hashes of this distributed method package."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent
manifest = json.loads((root / "SHA256SUMS.json").read_text(encoding="utf-8"))
errors = []
for entry in manifest["files"]:
    path = (root / entry["path"]).resolve()
    if not path.is_relative_to(root):
        errors.append(f"Invalid path: {entry['path']}")
    elif not path.is_file():
        errors.append(f"Missing: {entry['path']}")
    elif hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        errors.append(f"Changed: {entry['path']}")
if errors:
    print("\n".join(errors))
    raise SystemExit(1)
print(f"PASS: {len(manifest['files'])} distributed files match their SHA-256 records.")
