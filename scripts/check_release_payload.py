"""Verify canonical CI archives, install their exact wheel, or record test results.

This is an explicit release/CI command, never a library startup hook. The
qualifier's hashes detect changed bytes; they are not an independent signature.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import sysconfig
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PLATFORM_SKIPS = {"Host has no FIFO support", "FIFO creation unavailable", "POSIX process-group cleanup"}


def verify(directory: Path):
    qualification = json.loads((directory / "qualification.json").read_text(encoding="utf-8"))
    if qualification.get("status") != "passed" or qualification.get("reproducible_from_sdist") is not True:
        raise ValueError("Canonical archive qualification is incomplete")
    artifacts = qualification["artifacts"]
    for name, record in artifacts.items():
        if Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("Archive names must be basenames")
        payload = (directory / "artifacts" / name).read_bytes()
        if len(payload) != record["bytes"] or hashlib.sha256(payload).hexdigest() != record["sha256"]:
            raise ValueError("Archive hash or size mismatch")
    wheel, = (directory / "artifacts").glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        sources = {name: archive.read(name) for name in archive.namelist() if name.endswith(".py")}
        expected = {"tiberium_ai/" + p.relative_to(ROOT / "src/tiberium_ai").as_posix(): p.read_bytes()
                    for p in (ROOT / "src/tiberium_ai").rglob("*.py")}
        if sources != expected:
            raise ValueError("Canonical wheel differs from this checkout's complete Python sources")
    if os.environ.get("GITHUB_REF", "").startswith("refs/tags/"):
        if os.environ["GITHUB_REF_NAME"] != "v" + qualification["version"]:
            raise ValueError("Tag and package versions differ")
    return qualification, wheel


def install(directory: Path):
    qualification, wheel = verify(directory)
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps",
                    "--force-reinstall", str(wheel)], check=True)
    command = Path(sysconfig.get_path("scripts")) / ("parcimonia.exe" if os.name == "nt" else "parcimonia")
    actual = subprocess.check_output([str(command), "--version"], text=True).strip()
    if actual != "Parcimonia " + qualification["version"]:
        raise ValueError("Installed CLI version differs from canonical package")
    subprocess.run([sys.executable, "-I", "-c",
        "import importlib.metadata,tiberium_ai; "
        "assert tiberium_ai.__version__ == importlib.metadata.version('tiberium-ai')"], check=True)


def record(directory: Path, junit: Path | None, output: Path):
    qualification, _ = verify(directory)
    if junit is None:
        runtime, = qualification["runtimes"]
        totals, skipped = runtime["tests"], runtime.get("skipped_cases", [])
    else:
        tree = ET.parse(junit)
        totals = {key: sum(int(s.get(key, "0")) for s in tree.iter("testsuite"))
                  for key in ("tests", "failures", "errors", "skipped")}
        skipped = [{"test": case.get("name"), "reason": skip.get("message")}
                   for case in tree.iter("testcase") for skip in case.findall("skipped")]
    if totals["failures"] or totals["errors"] or any(row["reason"] not in PLATFORM_SKIPS for row in skipped):
        raise ValueError("Release tests failed or omitted an applicable native/backend case")
    if not totals["tests"]:
        raise ValueError("No release tests were recorded")
    result = {"schema": "parcimonia.public-release-validation/1", "version": qualification["version"],
              "commit": os.environ.get("GITHUB_SHA"), "platform": platform.system(),
              "python": platform.python_version(), "tests": totals, "skipped_cases": skipped,
              "tested_canonical_wheel": True, "artifacts": qualification["artifacts"],
              "reproducible_from_sdist": True, "native_codex_requalified": False,
              "savings_claim_allowed": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--junit", type=Path)
    parser.add_argument("--record", type=Path)
    args = parser.parse_args()
    if args.install:
        install(args.directory)
    if args.record:
        record(args.directory, args.junit, args.record)
    if not args.install and not args.record:
        verify(args.directory)


if __name__ == "__main__":
    main()
