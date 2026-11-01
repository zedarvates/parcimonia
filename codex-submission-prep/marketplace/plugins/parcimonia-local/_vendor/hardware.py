"""Read live local capacity without a model, LAN scan or persistent identifiers."""
from __future__ import annotations

import csv
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time


def memory_capacity():
    if os.name == "nt":
        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in (
                    "total", "available", "commit_limit", "commit_available",
                    "virtual", "virtual_available", "extended")]
        value = Memory()
        value.length = ctypes.sizeof(value)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
            return None, None, None
        return value.total, value.available, value.commit_available
    if platform.system() == "Linux":
        try:
            rows = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
            values = {row.split(":")[0]: int(row.split()[1]) * 1024 for row in rows}
            limit, used = values.get("CommitLimit"), values.get("Committed_AS")
            commit = max(0, limit - used) if limit is not None and used is not None else None
            return values.get("MemTotal"), values.get("MemAvailable"), commit
        except (OSError, ValueError, IndexError):
            pass
    return None, None, None


def gpu_capacity():
    executable = shutil.which("nvidia-smi")
    if not executable:
        return []
    try:
        result = subprocess.run(
            [executable, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=2,
            check=False, **({"creationflags": 0x08000000} if os.name == "nt" else {}))
        if result.returncode or len(result.stdout) > 32768:
            return []
        devices = []
        for row in csv.reader(io.StringIO(result.stdout)):
            if len(row) != 3:
                return []
            name, total, free = row
            total, free = int(total.strip()) * 1024 ** 2, int(free.strip()) * 1024 ** 2
            if not 0 <= free <= total or not 1 <= len(name.strip()) <= 160:
                return []
            devices.append({"name": name.strip(), "total_bytes": total, "free_bytes": free})
        return devices[:32]
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def observe():
    total, ram, commit = memory_capacity()
    gpus = gpu_capacity()
    profile = {"os": platform.system(), "architecture": platform.machine(),
               "logical_cpus": os.cpu_count(), "ram_total_bytes": total,
               "gpus": [{"name": gpu["name"], "total_bytes": gpu["total_bytes"]} for gpu in gpus]}
    key = hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    try:
        disk = shutil.disk_usage(Path(__file__).resolve().parent).free
    except OSError:
        disk = None
    return {"profile": profile, "snapshot": {
        "observed_at": time.time(), "hardware_key": key,
        "ram_available_bytes": ram, "commit_available_bytes": commit,
        "disk_free_bytes": disk, "gpu_free_bytes": [gpu["free_bytes"] for gpu in gpus],
        "heavy_busy": None}, "scope": "local_host_only_no_model_or_NPU_qualification"}
