"""Keep adversarial payloads out of test identifiers and Windows environments."""
import hashlib


def pytest_make_parametrize_id(config, val, argname):
    if isinstance(val, (str, bytes, bytearray)) and len(val) > 80:
        data = val.encode("utf-8", errors="surrogatepass") if isinstance(val, str) else bytes(val)
        digest = hashlib.sha256(data).hexdigest()[:12]
        return f"{argname}-{type(val).__name__}-length-{len(val)}-{digest}"
    return None
