from pathlib import Path
from unittest.mock import patch

from tiberium_ai.reflex_local import probe_optional_local_backend


def test_probe_refuses_without_authorization(tmp_path):
    target = tmp_path / "weights.bin"
    target.write_bytes(b"not-a-model")
    status = probe_optional_local_backend(target, allow_load=False)
    assert status.available is False
    assert status.allow_load is False
    assert "not authorized" in status.reason


def test_probe_missing_file_does_not_download():
    with patch("urllib.request.urlopen") as urlopen:
        status = probe_optional_local_backend(
            Path("C:/definitely-missing-parcimonia-weights.bin"),
            allow_load=True,
        )
    assert status.available is False
    assert "missing" in status.reason
    urlopen.assert_not_called()


def test_probe_present_file_still_does_not_load(tmp_path):
    target = tmp_path / "laya-like.bin"
    target.write_bytes(b"present")
    with patch("urllib.request.urlopen") as urlopen:
        status = probe_optional_local_backend(target, allow_load=True)
    assert status.available is False
    assert "not implemented" in status.reason
    urlopen.assert_not_called()

