"""Prepared model-free Codex host probe: disposable, initially empty profile only.

Never changes HOME or CODEX_HOME. Not run against the user's active installation.
The optional future host test installs only into its disposable account/profile.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time

transport_spec = importlib.util.spec_from_file_location("parcimonia_host_transport", Path(__file__).with_name("host_transport.py"))
transport_module = importlib.util.module_from_spec(transport_spec)
transport_spec.loader.exec_module(transport_module)
AppServer, ALLOWED_METHODS = transport_module.AppServer, transport_module.ALLOWED_METHODS


def require(value, message):
    if not value:
        raise AssertionError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_candidate_files(plugin, inventory):
    actual = {p.relative_to(plugin).as_posix() for p in plugin.rglob("*") if p.is_file()}
    require(actual == set(inventory) | {"FILES.json"}, "Candidate inventory differs before installation")
    for name, sha in inventory.items():
        relative = Path(name)
        require(not relative.is_absolute() and ".." not in relative.parts, "Invalid candidate path")
        require(digest(plugin / relative) == sha, "Candidate bytes differ before installation: " + name)


def command(argv, cwd, env):
    result = subprocess.run([str(a) for a in argv], cwd=cwd, env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=60)
    require(result.returncode == 0, "Host command failed: " + str(argv[1:3]))
    require(len(result.stdout.encode()) <= 2 * 1024 * 1024, "Command output exceeds budget")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--marketplace", required=True, type=Path)
    parser.add_argument("--codex", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--expected-codex-version", default="0.166.0")
    args = parser.parse_args()
    report = {"schema": "parcimonia.codex-plugin-host-preparation/1", "status": "not_run",
              "candidate_version": "0.4.2", "model_turn_submitted": False,
              "home_environment_changed": False, "portal_submission": "not_run"}
    try:
        assert "turn/start" not in ALLOWED_METHODS
        profile = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).resolve()
        if profile.exists() and any(profile.iterdir()):
            report.update(status="REFUSED_NON_DISPOSABLE_PROFILE", commands_executed=0)
            return 4
        marketplace = args.marketplace.resolve(strict=True)
        plugin = marketplace / "plugins/parcimonia-local"
        inventory = json.loads((plugin / "FILES.json").read_text(encoding="utf-8"))["files"]
        check_candidate_files(plugin, inventory)
        require(args.source_commit is not None and re.fullmatch(r"[0-9a-f]{40}", args.source_commit),
                "A full reviewed source commit is required for a host qualification")
        report.update(source_commit=args.source_commit, inventory_sha256=digest(plugin / "FILES.json"),
                      initially_empty_profile=True)
        env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
        env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        codex = args.codex.resolve(strict=True)
        version = command([codex, "--version"], marketplace, env).strip()
        require(version == "codex-cli " + args.expected_codex_version, "Unexpected Codex version")
        report.update(codex_version=version,
                      version_command_created_profile=profile.exists() and any(profile.iterdir()))
        command([codex, "plugin", "marketplace", "add", marketplace, "--json"], marketplace, env)
        command([codex, "plugin", "add", "parcimonia-local@parcimonia-submission-local", "--json"], marketplace, env)
        with tempfile.TemporaryDirectory(prefix="parcimonia-codex-host-") as temporary:
            work = Path(temporary)
            with AppServer(str(codex), work, env) as host:
                listing = host.rpc("plugin/list", {"cwds": [str(marketplace)], "forceRefetch": False,
                                                   "marketplaceKinds": ["local"]})
                require(not listing.get("marketplaceLoadErrors"), "Marketplace load error")
                market, = [m for m in listing["marketplaces"] if m["name"] == "parcimonia-submission-local"]
                summary, = [p for p in market["plugins"] if p["name"] == "parcimonia-local"]
                require(summary["installed"] and summary["enabled"], "Candidate is not installed and enabled")
                detail = host.rpc("plugin/read", {"marketplacePath": market["path"], "pluginName": "parcimonia-local"})["plugin"]
                require(detail["summary"]["id"] == summary["id"], "Plugin ownership differs")
                require("parcimonia-local" in detail["mcpServers"], "Bundled MCP is absent")
                skills = host.rpc("skills/list", {"cwds": [str(work)], "forceReload": True})
                owned = [s for row in skills["data"] for s in row["skills"]
                         if s["name"] == "parcimonia-local:local-plan" and s.get("pluginId") == summary["id"] and s["enabled"]]
                require(len(owned) == 1, "Enabled candidate-owned skill was not discovered")
                cached_skill = Path(owned[0]["path"]).resolve()
                require(cached_skill.is_relative_to(profile / "plugins") and not cached_skill.is_relative_to(marketplace),
                        "Skill is not loaded from installed cache")
                cache_root = cached_skill.parents[2]
                for name, sha in inventory.items():
                    require(digest(cache_root / name) == sha, "Installed file differs: " + name)
                thread_id = host.rpc("thread/start", {"cwd": str(work), "ephemeral": True,
                    "sandbox": "read-only", "approvalPolicy": "never"})["thread"]["id"]
                deadline = time.monotonic() + 35
                server = None
                while time.monotonic() < deadline:
                    status = host.rpc("mcpServerStatus/list", {"threadId": thread_id,
                        "serverName": "parcimonia-local", "limit": 1})
                    require(not status.get("nextCursor"), "Server status pagination incomplete")
                    matches = [s for s in status["data"] if s.get("pluginId") == summary["id"]]
                    require(len(matches) <= 1, "Ambiguous plugin server ownership")
                    if matches and matches[0].get("runtimeStatus") == "connected" and matches[0]["tools"]:
                        server = matches[0]
                        break
                    if matches and matches[0].get("runtimeStatus") == "failed":
                        raise AssertionError("Candidate bundled MCP failed to connect")
                    time.sleep(0.25)
                require(server is not None, "Candidate-owned server did not connect")
                require(server.get("serverInfo", {}).get("version") == "0.4.2", "Wrong candidate server version")
                require(set(server["tools"]) == {"parcimonia_local_hardware", "parcimonia_local_context", "parcimonia_local_plan"},
                        "Candidate does not own the exact three-tool catalog")
                inputs = json.loads(command([sys.executable, "-I", "-B", plugin / "review/generate_inputs.py"], work, env))["cases"]
                inputs = dict(inputs)
                inputs["P3-repeat"] = inputs["P3"]
                values = {}
                results = {}
                for identity, (tool, arguments) in inputs.items():
                    result = host.rpc("mcpServer/tool/call", {"threadId": thread_id, "server": server["name"],
                        "tool": tool, "arguments": arguments})
                    expected_error = identity in {"N2", "N3"}
                    require(bool(result.get("isError")) == expected_error, "Unexpected tool result: " + identity)
                    results[identity] = "expected_refusal" if expected_error else "completed"
                    if not expected_error:
                        values[identity] = json.loads(result["content"][0]["text"])
                require(values["P2"]["auto_act_allowed"] is False and len(values["P2"]["files"]) == 2, "Context case failed")
                require(values["P1"]["scope"] == "local_host_only_no_model_or_NPU_qualification", "Observation scope changed")
                require({r["id"] for r in values["P2"]["files"]} == {"cache", "cache-test"}, "Wrong context identities")
                require(values["P3-repeat"]["metrics"]["derived_cache_hits"] > 0, "Derivation reuse case failed")
                require(values["P3-repeat"]["files"] == values["P3"]["files"], "Repeat changed source identities")
                require(len(values["P4"]["files"]) == 1 and values["P4"]["omitted"], "Budget case failed")
                require(values["P5"]["selected"] == "warm-cpu" and values["P5"]["auto_act_allowed"] is False, "Route fixture case failed")
                require(values["P5"]["evidence_trust"] == "host_reported_not_independently_attested", "Fixture trust changed")
                require(values["N1"]["status"] == "abstain" and values["N1"]["selected"] is None, "Missing-measurement case failed")
                require(values["N1"]["auto_act_allowed"] is False, "Abstention cannot authorize execution")
                report.update(status="passed", codex_version=version, owned_plugin_id=summary["id"],
                    installed_cache_files_verified=len(inventory), owned_skill_verified=True,
                    positive_cases=5, negative_cases=3, discovery_before_calls=True,
                    case_results=results, native_tool_names=sorted(server["tools"]), server_info=server.get("serverInfo"),
                    model_choice_quality="not_tested", desktop_graphical_workflow="not_tested",
                    methods=sorted(set(host.methods)), transport_input_bytes=host.sent, transport_output_bytes=host.received)
    except Exception as error:
        report.update(status="failed", error_type=type(error).__name__, reason=str(error)[:800])
        return 1
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(json.dumps({"status": report["status"], "model_turn_submitted": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
