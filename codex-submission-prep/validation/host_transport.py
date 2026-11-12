# Transport adapted from Botte Secrete verify_codex_plugin_host.py (MIT).
# Source provenance is recorded in SOURCES.json beside this module.
import json
import queue
import subprocess
import sys
import threading
import time
MAX_LINE = 2 * 1024 * 1024
MAX_TOTAL = 16 * 1024 * 1024
TIMEOUT = 45
ALLOWED_METHODS = {"initialize", "plugin/list", "plugin/read", "skills/list", "thread/start", "mcpServerStatus/list", "mcpServer/tool/call"}
def require(value, message):
    if not value:
        raise AssertionError(message)

class AppServer:
    """Bounded NDJSON transport; the allowlist excludes every model-turn method."""

    def __init__(self, codex, cwd, env):
        self.codex, self.cwd, self.env = codex, cwd, env
        self.sequence = self.sent = self.received = 0
        self.lines = queue.Queue(maxsize=256)
        self.stderr = bytearray()
        self.methods = []

    def __enter__(self):
        self.process = subprocess.Popen([self.codex, "app-server", "--stdio"],
                                        cwd=self.cwd, env=self.env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def read_stdout():
            while True:
                raw = self.process.stdout.readline(MAX_LINE + 1)
                try:
                    self.lines.put(raw or None, timeout=TIMEOUT)
                except queue.Full:
                    return
                if not raw or len(raw) > MAX_LINE:
                    return

        def read_stderr():
            while True:
                raw = self.process.stderr.read(1024)
                if not raw:
                    return
                self.stderr.extend(raw[:max(0, 4096 - len(self.stderr))])

        self.reader = threading.Thread(target=read_stdout, daemon=True)
        self.errors = threading.Thread(target=read_stderr, daemon=True)
        self.reader.start()
        self.errors.start()
        try:
            self.rpc("initialize", {"clientInfo": {"name": "parcimonia-plugin-qualification", "version": "1"},
                                    "capabilities": {"experimentalApi": True}})
            self.send({"method": "initialized"})
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise
        return self

    def send(self, value):
        raw = (json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
        self.sent += len(raw)
        self.process.stdin.write(raw)
        self.process.stdin.flush()

    def rpc(self, method, params=None):
        require(method in ALLOWED_METHODS, "unapproved app-server method: " + method)
        self.methods.append(method)
        self.sequence += 1
        request_id = self.sequence
        self.send({"id": request_id, "method": method, "params": params or {}})
        deadline = time.monotonic() + TIMEOUT
        while True:
            remaining = deadline - time.monotonic()
            require(remaining > 0, "app-server response timeout: " + method)
            try:
                raw = self.lines.get(timeout=remaining)
            except queue.Empty as exc:
                raise AssertionError("app-server response timeout: " + method) from exc
            require(raw is not None, "app-server exited before response: " + method)
            require(len(raw) <= MAX_LINE, "app-server line exceeds bound")
            self.received += len(raw)
            require(self.received <= MAX_TOTAL, "app-server output exceeds bound")
            message = json.loads(raw)
            if "method" in message:
                # No approval, elicitation, execution or authentication is delegated
                # to a server-initiated request during this qualification.
                if "id" in message:
                    self.send({"id": message["id"], "error": {"code": -32601,
                              "message": "Host qualification declines server requests"}})
                continue
            require(message.get("id") == request_id, "unexpected response identity")
            require("error" not in message, "app-server RPC failed: " + method + "; " +
                    json.dumps(message.get("error"), ensure_ascii=True)[:1500])
            return message["result"]

    def __exit__(self, exc_type, exc_value, traceback):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.reader.join(timeout=1)
        self.errors.join(timeout=1)
        return False
