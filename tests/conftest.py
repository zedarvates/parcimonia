"""Keep adversarial payloads out of test identifiers and Windows environments."""
import hashlib
import os
from pathlib import Path
import sys


def pytest_make_parametrize_id(config, val, argname):
    if isinstance(val, (str, bytes, bytearray)) and len(val) > 80:
        data = val.encode("utf-8", errors="surrogatepass") if isinstance(val, str) else bytes(val)
        digest = hashlib.sha256(data).hexdigest()[:12]
        return f"{argname}-{type(val).__name__}-length-{len(val)}-{digest}"
    return None


def pytest_sessionfinish(session, exitstatus):
    if exitstatus == 0 and os.environ.get("PARCIMONIA_RELEASE_INSTALL") == "1":
        prefix = Path(sys.prefix).resolve()
        for name, module in list(sys.modules.items()):
            if name == "tiberium_ai" or name.startswith("tiberium_ai."):
                location = Path(module.__file__).resolve()
                assert prefix in location.parents, (name, location)
