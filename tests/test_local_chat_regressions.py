import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import threading
import time

from tiberium_ai.local_chat import chat_completion


ROOT = Path(__file__).resolve().parents[1]


def test_tls_deadline_during_handshake_is_a_sanitized_timeout(monkeypatch):
    client, peer = socket.socketpair()
    with client, peer:
        peer.settimeout(1)
        monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: client)

        def interrupted_handshake(tls_socket, *args, **kwargs):
            # The watchdog's fd shutdown wakes this deterministic stalled peer.
            assert peer.recv(1) == b""
            if tls_socket._sslobj is None:
                raise AttributeError("TLS state disappeared during the handshake")
            raise TimeoutError

        monkeypatch.setattr(ssl.SSLSocket, "do_handshake", interrupted_handshake)
        result = chat_completion(model="fixture", messages=[{"role": "user", "content": "test"}],
                                 base_url="https://127.0.0.1:1234", timeout=0.1)
    assert result["status"] == "timeout"
    assert result["error_type"] == "timeout"
    assert result["inference_attempted"] is False
    assert result["content"] is None and result["retries"] == 0


def test_https_tcp_and_tls_share_one_deadline(monkeypatch):
    timeout, tcp_delay = 0.25, 0.15
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(1)
    port = listener.getsockname()[1]
    release = threading.Event()
    tls_started = threading.Event()
    accepted = []

    def stalled_tls_server():
        try:
            peer, _ = listener.accept()
            accepted.append(peer)
            with peer:
                peer.settimeout(1)
                if peer.recv(1) == b"\x16":
                    tls_started.set()
                # Accept the ClientHello but never answer the TLS handshake.
                release.wait(1)
        except OSError:
            pass

    server = threading.Thread(target=stalled_tls_server, daemon=True)
    server.start()
    real_connect = socket.create_connection
    real_handshake = ssl.SSLSocket.do_handshake
    handshake_timeouts = []

    def delayed_connect(*args, **kwargs):
        # TCP uses part of the budget, without exhausting it on its own.
        time.sleep(tcp_delay)
        return real_connect(*args, **kwargs)

    def observed_handshake(sock, *args, **kwargs):
        handshake_timeouts.append(sock.gettimeout())
        return real_handshake(sock, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", delayed_connect)
    monkeypatch.setattr(ssl.SSLSocket, "do_handshake", observed_handshake)
    try:
        started = time.monotonic()
        result = chat_completion(
            model="deadline-test",
            messages=[{"role": "user", "content": "Test."}],
            base_url=f"https://127.0.0.1:{port}", timeout=timeout,
        )
        elapsed = time.monotonic() - started
    finally:
        release.set()
        server.join(timeout=1)
        listener.close()

    assert tls_started.is_set()
    assert len(accepted) == 1
    assert len(handshake_timeouts) == 1
    assert 0 < handshake_timeouts[0] < timeout - tcp_delay / 2
    assert elapsed < timeout + 0.1
    assert result["status"] == "timeout"
    assert result["inference_attempted"] is False
    assert result["content"] is None
    assert result["retries"] == 0


def test_worker_rejects_huge_temperature_without_traceback():
    request = {
        "schema_version": 1, "task_id": "huge-temperature", "model": "test",
        "messages": [{"role": "user", "content": "Test."}],
        "temperature": 10 ** 400,
    }
    completed = subprocess.run(
        [sys.executable, str(ROOT / "examples" / "local_chat_worker.py")],
        input=json.dumps(request).encode("utf-8"), capture_output=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src"),
             "PYTHONDONTWRITEBYTECODE": "1"},
        cwd=ROOT, timeout=3, check=False,
    )
    assert completed.returncode == 2
    assert completed.stdout == b""
    assert completed.stderr == b"local completion configuration or input failed\n"
