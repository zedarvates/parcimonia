"""Explicit, read-only local runtime diagnostics; never runs inference.

``/v1/models`` may list unloaded models when LM Studio JIT loading is enabled.
Reachability is therefore deliberately separate from inference readiness.
No response body, subprocess stderr, credentials or environment is recorded.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import math
import os
import platform
import re
import shutil
import socket
import ssl
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

__all__ = ["probe_models", "collect_inventory", "diagnose_local", "write_diagnostic"]

_PRIVATE_V4 = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))
_PRIVATE_V6 = ipaddress.ip_network("fc00::/7")
_MAX_MODELS = 512


def _positive_number(value: object, name: str, maximum: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f"{name} must be a finite positive number at most {maximum:g}.")
    return float(value)


def _endpoint(base_url: str, allow_lan: bool) -> tuple[str, str, int, str]:
    if type(allow_lan) is not bool:
        raise ValueError("allow_lan must be a boolean.")
    if not isinstance(base_url, str) or not base_url or base_url.strip() != base_url:
        raise ValueError("base_url must be an HTTP(S) local origin.")
    # Reject controls before urlsplit silently removes some of them.
    if any(ord(char) <= 32 or ord(char) == 127 for char in base_url):
        raise ValueError("base_url must not contain whitespace or controls.")
    try:
        parts = urlsplit(base_url)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise ValueError("base_url is not a valid local origin.") from None
    if (
        parts.scheme not in ("http", "https") or not host
        or parts.username is not None or parts.password is not None
        or parts.query or parts.fragment or parts.path not in ("", "/", "/v1", "/v1/")
    ):
        raise ValueError("base_url must be a local HTTP(S) origin without credentials or query.")
    if host.lower() == "localhost":
        # Pin this spelling to loopback rather than consulting DNS or a proxy.
        host = "127.0.0.1"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError("base_url requires localhost or a literal local IP address.") from None
    private = (
        any(address in network for network in _PRIVATE_V4)
        if address.version == 4 else address in _PRIVATE_V6
    )
    if not address.is_loopback and not (allow_lan and private):
        raise ValueError("only loopback is allowed unless allow_lan explicitly permits a private IP.")
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    if not 1 <= port <= 65535:
        raise ValueError("base_url port must be between 1 and 65535.")
    origin_host = f"[{host}]" if address.version == 6 else host
    return parts.scheme, host, port, f"{parts.scheme}://{origin_host}:{port}"


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON key")
        out[key] = value
    return out


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON value")


def _model_ids(raw: bytes) -> list[str]:
    payload = json.loads(
        raw.decode("utf-8"), object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("models response must contain a data list")
    if len(payload["data"]) > _MAX_MODELS:
        raise ValueError("too many model entries")
    ids: list[str] = []
    for entry in payload["data"]:
        identifier = entry.get("id") if isinstance(entry, dict) else None
        if (
            not isinstance(identifier, str) or not identifier.strip()
            or len(identifier) > 256
            or any(ord(char) < 32 or ord(char) == 127 for char in identifier)
            or identifier in ids
        ):
            raise ValueError("invalid model identifier")
        ids.append(identifier)
    return ids


def probe_models(
    base_url: str = "http://127.0.0.1:1234", *, allow_lan: bool = False,
    timeout: float = 3.0, max_response_bytes: int = 262144,
) -> dict[str, Any]:
    """Perform exactly one bounded GET, with no redirects or inferred readiness.

    Literal private LAN addresses require an explicit opt-in. Hostnames other
    than localhost are refused so DNS cannot move a request to a public host.
    Proxy environment variables are not consulted for this local-only probe.
    """
    timeout = _positive_number(timeout, "timeout", 60)
    if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 1048576:
        raise ValueError("max_response_bytes must be an integer from 1 to 1048576.")
    scheme, host, port, origin = _endpoint(base_url, allow_lan)
    result: dict[str, Any] = {
        "origin": origin, "path": "/v1/models", "method": "GET",
        "status": "unreachable", "http_status": None, "model_ids": [],
        "model_count": None, "loaded_state": "not_observed",
        "inference_ready": None, "inference_attempted": False,
        "error_type": None, "latency_ms": None,
    }
    started = time.monotonic()
    deadline = started + timeout
    connection: http.client.HTTPConnection | None = None
    watchdog: threading.Timer | None = None
    expired = threading.Event()
    try:
        if scheme == "https":
            connection = http.client.HTTPSConnection(
                host, port, timeout=timeout, context=ssl.create_default_context(),
            )
        else:
            connection = http.client.HTTPConnection(host, port, timeout=timeout)
        connection.connect()
        sock = connection.sock
        assert sock is not None
        def expire() -> None:
            expired.set()
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        # Socket read timeouts alone can be reset by dripped HTTP headers.
        # Interrupt header parsing as well as body reads at the absolute limit.
        watchdog = threading.Timer(max(0, deadline - time.monotonic()), expire)
        watchdog.daemon = True
        watchdog.start()
        sock.settimeout(max(0.000001, deadline - time.monotonic()))
        connection.request("GET", "/v1/models", headers={"Accept": "application/json"})
        sock.settimeout(max(0.000001, deadline - time.monotonic()))
        response = connection.getresponse()
        result["http_status"] = response.status
        if 300 <= response.status < 400:
            result.update(status="redirect_refused", error_type="redirect_refused")
            return result
        if response.status != 200:
            result.update(status="http_error", error_type="http_error")
            return result
        length = response.getheader("Content-Length")
        declared = None
        if length is not None:
            try:
                declared = int(length)
            except ValueError:
                raise ValueError("invalid content length") from None
            if declared < 0:
                raise ValueError("invalid content length")
            if declared > max_response_bytes:
                result.update(status="response_too_large", error_type="response_too_large")
                return result
        data = bytearray()
        while True:
            if response.isclosed():
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            sock.settimeout(remaining)
            chunk = response.read1(min(65536, max_response_bytes + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > max_response_bytes:
                result.update(status="response_too_large", error_type="response_too_large")
                return result
        if declared is not None and len(data) != declared:
            raise ValueError("incomplete response")
        if time.monotonic() >= deadline:
            raise TimeoutError
        ids = _model_ids(bytes(data))
        result.update(status="reachable", model_ids=ids, model_count=len(ids))
    except (socket.timeout, TimeoutError):
        result.update(status="timeout", error_type="timeout")
    except (UnicodeError, ValueError, RecursionError, http.client.HTTPException):
        error = "timeout" if expired.is_set() else "invalid_response"
        result.update(status=error, error_type=error)
    except OSError:
        if expired.is_set():
            result.update(status="timeout", error_type="timeout")
        else:
            result.update(status="unreachable", error_type="connection_failed")
    finally:
        if watchdog is not None:
            watchdog.cancel()
        if connection is not None:
            connection.close()
        result["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
    return result


def _fixed_command(arguments: tuple[str, ...], timeout: float) -> tuple[str, str | None]:
    executable = shutil.which(arguments[0])
    if executable is None:
        return "not_installed", None
    try:
        completed = subprocess.run(
            [executable, *arguments[1:]], capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except (OSError, UnicodeError, subprocess.SubprocessError):
        return "failed", None
    if completed.returncode != 0 or len(completed.stdout) > 65536:
        return "failed", None
    return "observed", completed.stdout


def collect_inventory(disk_path: str | Path = ".", *, command_timeout: float = 3.0) -> dict[str, Any]:
    """Observe this machine only; no SSH, remote discovery, logs or environment."""
    command_timeout = _positive_number(command_timeout, "command_timeout", 15)
    ram_total = ram_available = None
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            name, _, value = line.partition(":")
            if name in ("MemTotal", "MemAvailable"):
                fields = value.split()
                if len(fields) == 2 and fields[1] == "kB":
                    values[name] = int(fields[0]) * 1024
        ram_total, ram_available = values.get("MemTotal"), values.get("MemAvailable")
    except (OSError, ValueError, UnicodeError):
        pass
    disk = {"total_bytes": None, "used_bytes": None, "free_bytes": None}
    try:
        usage = shutil.disk_usage(disk_path)
        disk = {"total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free}
    except OSError:
        pass
    gpu_status, raw = _fixed_command((
        "nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version",
        "--format=csv,noheader,nounits",
    ), command_timeout)
    gpus = []
    if raw is not None:
        try:
            for line in raw.splitlines():
                name, total, free, driver = [part.strip() for part in line.split(",")]
                total_mb, free_mb = float(total), float(free)
                if (
                    not name or len(name) > 128 or len(driver) > 64
                    or any(ord(char) < 32 or ord(char) == 127 for char in name + driver)
                    or not all(math.isfinite(v) and v >= 0 for v in (total_mb, free_mb))
                    or free_mb > total_mb or len(gpus) >= 32
                ):
                    raise ValueError
                gpus.append({"name": name, "memory_total_mib": total_mb,
                             "memory_free_mib": free_mb, "driver_version": driver})
        except ValueError:
            gpu_status, gpus = "unparseable", []
    lms_status, version_raw = _fixed_command(("lms", "--version"), command_timeout)
    version = None
    if version_raw is not None:
        match = re.search(r"\b\d+\.\d+(?:\.\d+)?(?:[-+][A-Za-z0-9.-]+)?\b", version_raw)
        version = match.group(0) if match else None
        if version is None:
            lms_status = "unparseable"
    return {
        "scope": "caller_machine_only", "system": platform.system(),
        "machine": platform.machine(), "logical_cpu_count": os.cpu_count(),
        "ram_total_bytes": ram_total, "ram_available_bytes": ram_available,
        "disk": disk, "nvidia": {"status": gpu_status, "gpus": gpus},
        "lms_cli": {"status": lms_status, "version": version},
        "hailo": "not_inspected", "pcie_topology": "not_inspected",
    }


def diagnose_local(
    base_url: str = "http://127.0.0.1:1234", *, allow_lan: bool = False,
    timeout: float = 3.0, disk_path: str | Path = ".",
) -> dict[str, Any]:
    endpoint = probe_models(base_url, allow_lan=allow_lan, timeout=timeout)
    return {
        "kind": "local-diagnostic", "schema_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "inference_attempted": False, "saving_claim": False,
        "endpoint": endpoint, "inventory": collect_inventory(disk_path),
        "limits": [
            "Model listing does not establish loaded state or inference readiness.",
            "Inventory describes the caller, not a remote endpoint host.",
            "No service repair, inference, model load or download was attempted.",
        ],
    }


def write_diagnostic(path: str | Path, report: dict[str, Any]) -> None:
    """Create a new report with owner-only permissions where supported."""
    output = Path(path)
    encoded = (json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(output, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
