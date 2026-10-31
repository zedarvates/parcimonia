"""Build and qualify local release archives without installing into the host profile.

Requires the release extra, pip, a predownloaded pytest wheelhouse, Node, and
explicit installed Python interpreters. No network is needed during qualification.
Output is exclusive-create. Work directories (budget 128 MiB) belong to this run;
they are removed after success, while archives, inventories, JUnit and logs remain.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def qualify(output, interpreters, wheelhouse):
    output.mkdir(parents=True, exist_ok=False)
    logs = output / "logs"
    logs.mkdir()
    work = output / "work"
    work.mkdir()
    artifacts = output / "artifacts"
    artifacts.mkdir()
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    env.update(PYTHONUTF8="1", PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1",
               PIP_NO_INDEX="1", SOURCE_DATE_EPOCH="1793404800")
    report = {"schema": "parcimonia.release-qualification/1", "status": "running",
              "runtimes": [], "scope": "local archives; no publication or active-profile install",
              "savings_claim_allowed": False, "native_codex_requalified": False}

    def run(name, argv, cwd=ROOT, text=None):
        completed = subprocess.run([str(x) for x in argv], cwd=cwd, env=env,
                                   input=text, capture_output=True, text=True,
                                   encoding="utf-8", timeout=600)
        with (logs / (name + ".log")).open("x", encoding="utf-8") as stream:
            stream.write(completed.stdout + completed.stderr)
        if completed.returncode:
            raise RuntimeError(f"{name} failed ({completed.returncode}); see logs")
        return completed.stdout

    try:
        run("build", [sys.executable, "-m", "build", "--no-isolation", "--sdist", "--wheel",
                      "--outdir", artifacts])
        wheel, = artifacts.glob("*.whl")
        source, = artifacts.glob("*.tar.gz")
        with zipfile.ZipFile(wheel) as archive:
            wheel_files = {name: hashlib.sha256(archive.read(name)).hexdigest()
                           for name in archive.namelist()}
            expected = {"tiberium_ai/" + p.relative_to(ROOT / "src/tiberium_ai").as_posix(): sha(p)
                        for p in (ROOT / "src/tiberium_ai").rglob("*.py")}
            actual = {name: digest for name, digest in wheel_files.items() if name.endswith(".py")}
            if actual != expected:
                raise RuntimeError("Wheel does not contain the exact complete Python sources")
            metadata_name, = [name for name in wheel_files if name.endswith(".dist-info/METADATA")]
            metadata = archive.read(metadata_name).decode("utf-8")
            version, = [line.split(": ", 1)[1] for line in metadata.splitlines() if line.startswith("Version: ")]
        write_json(output / "wheel-files.json", wheel_files)
        with tarfile.open(source, "r:gz") as archive:
            members = archive.getmembers()
            source_files = {}
            for member in members:
                parts = Path(member.name).parts
                if (Path(member.name).is_absolute() or ".." in parts
                        or not (member.isfile() or member.isdir())
                        or any(p in {".git", ".venv", "runs", "cloud", "__pycache__"} for p in parts)):
                    raise RuntimeError("Unsafe or unintended source archive member")
                if member.isfile():
                    source_files[member.name] = hashlib.sha256(archive.extractfile(member).read()).hexdigest()
            archive.extractall(work / "source")
        write_json(output / "source-files.json", source_files)
        extracted, = (work / "source").iterdir()
        run("rebuild", [sys.executable, "-m", "build", "--no-isolation", "--sdist", "--wheel",
                        "--outdir", work / "rebuilt"], cwd=extracted)
        for artifact in (wheel, source):
            if sha(artifact) != sha(work / "rebuilt" / artifact.name):
                raise RuntimeError("Rebuild from source is not byte-reproducible: " + artifact.name)
        report["reproducible_from_sdist"] = True

        plugin = extracted / "plugins/parcimonia-local"
        inventory = json.loads((plugin / "FILES.json").read_text(encoding="utf-8"))["files"]
        actual_files = {p.relative_to(plugin).as_posix(): p for p in plugin.rglob("*") if p.is_file()}
        if set(actual_files) != set(inventory) | {"FILES.json"}:
            raise RuntimeError("Plugin inventory differs from its actual files")
        if any(sha(actual_files[name]) != digest for name, digest in inventory.items()):
            raise RuntimeError("Plugin file hash mismatch")
        plugin_version = json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))["version"]
        plugin_zip = artifacts / f"parcimonia-local-{plugin_version}.zip"
        with zipfile.ZipFile(plugin_zip, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, path in sorted(actual_files.items()):
                info = zipfile.ZipInfo("parcimonia-local/" + name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes())
        with zipfile.ZipFile(plugin_zip) as archive:
            archive.extractall(work / "plugin")
        plugin = work / "plugin/parcimonia-local"
        report["plugin_version"] = plugin_version

        # Installed modules must remain installed modules throughout the entire suite.
        (extracted / "conftest.py").write_text(
            "import sys\nfrom pathlib import Path\n"
            "def pytest_sessionfinish(session, exitstatus):\n"
            "    for name, module in list(sys.modules.items()):\n"
            "        if name == 'tiberium_ai' or name.startswith('tiberium_ai.'):\n"
            "            location = Path(module.__file__).resolve()\n"
            "            assert Path(sys.prefix).resolve() in location.parents, (name, location)\n",
            encoding="utf-8")
        for index, interpreter in enumerate(interpreters):
            label = f"python-{index + 1}"
            home = work / label
            run(label + "-venv", [interpreter, "-m", "venv", "--without-pip", home])
            python = home / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            run(label + "-install", [sys.executable, "-m", "pip", "--python", python, "install",
                                    "--no-compile", "--no-index", "--find-links", wheelhouse,
                                    wheel, "pytest==9.1.1"])
            run(label + "-pip-check", [sys.executable, "-m", "pip", "--python", python, "check"])
            probe = run(label + "-imports", [python, "-I", "-c",
                "import importlib,importlib.metadata,json,pkgutil,sys,tiberium_ai; "
                "modules=[x.name for x in pkgutil.walk_packages(tiberium_ai.__path__, 'tiberium_ai.')]; "
                "[importlib.import_module(name) for name in modules]; "
                "assert tiberium_ai.__version__ == importlib.metadata.version('tiberium-ai'); "
                "print(json.dumps({'python':sys.version,'version':tiberium_ai.__version__,"
                "'module_count':len(modules),'location':tiberium_ai.__file__}))"], cwd=home)
            runtime = json.loads(probe)
            if runtime["version"] != version:
                raise RuntimeError("Installed version mismatch")
            command = home / ("Scripts/parcimonia.exe" if os.name == "nt" else "bin/parcimonia")
            if run(label + "-version", [command, "--version"], cwd=home).strip() != f"Parcimonia {version}":
                raise RuntimeError("CLI version mismatch")
            smoke = run(label + "-cli", [command, "rules", "--enforce-rules"], cwd=home,
                        text=json.dumps({"change": {"path": "été.py", "after": "x = 1"}, "rules": []}))
            if json.loads(smoke)["result"]["data"]["verdict"] != "pass":
                raise RuntimeError("Installed CLI failed")
            junit = output / (label + "-tests.xml")
            run(label + "-tests", [python, "-m", "pytest", "-q", "--junitxml=" + str(junit)], cwd=extracted)
            totals = {key: sum(int(s.get(key, "0")) for s in ET.parse(junit).iter("testsuite"))
                      for key in ("tests", "failures", "errors", "skipped")}
            if totals["failures"] or totals["errors"] or totals["skipped"]:
                raise RuntimeError("Full qualification requires every test, including Node checks")
            runtime["tests"] = totals
            report["runtimes"].append(runtime)
            # Actual stdio from the extracted plugin, with list-before-call.
            requests = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-11-25", "capabilities": {},
                    "clientInfo": {"name": "release-qualification", "version": "1"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"cursor": None, "_meta": {}}},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                    "name": "parcimonia_local_context", "arguments": {"query": "été", "documents": []}}},
            ]
            events = run(label + "-plugin-stdio", [python, "-I", "-B", plugin / "server.py"],
                         cwd=plugin, text="".join(json.dumps(r) + "\n" for r in requests))
            responses = [json.loads(line) for line in events.splitlines()]
            if ([r.get("id") for r in responses] != [1, 2, 3]
                    or len(responses[1]["result"]["tools"]) != 3
                    or responses[2]["result"].get("isError") is not False):
                raise RuntimeError("Plugin stdio validation failed")
            content = json.loads(responses[2]["result"]["content"][0]["text"])
            if content.get("auto_act_allowed") is not False:
                raise RuntimeError("Plugin advisory boundary changed")
        report["version"] = version
        report["artifacts"] = {p.name: {"sha256": sha(p), "bytes": p.stat().st_size}
                               for p in sorted(artifacts.iterdir())}
        write_json(output / "SHA256.json", report["artifacts"])
        # The only recursive removal is our exclusive-created work directory.
        if work.resolve().parent != output.resolve() or work.name != "work":
            raise RuntimeError("Invalid cleanup target")
        shutil.rmtree(work)
        report["temporary_work_removed"] = True
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        write_json(output / "qualification.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--wheelhouse", required=True, type=Path)
    parser.add_argument("--python", action="append", required=True, type=Path)
    args = parser.parse_args()
    result = qualify(args.output.resolve(), args.python, args.wheelhouse.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
