import pytest

from tiberium_ai.webbrain import (
    WebBrainAction,
    WebBrainClient,
    WebBrainCommand,
    WebBrainResult,
)


def test_command_validation():
    with pytest.raises(ValueError, match="action must be a valid WebBrainAction"):
        WebBrainCommand(action="invalid_action")

    cmd = WebBrainCommand(
        action=WebBrainAction.NAVIGATE,
        target="https://example.com",
    )
    assert cmd.action == WebBrainAction.NAVIGATE
    assert cmd.target == "https://example.com"
    assert cmd.to_payload() == {
        "action": "navigate",
        "target": "https://example.com",
        "value": None,
    }


def test_offline_fallback_does_not_crash():
    client = WebBrainClient(endpoint="ws://127.0.0.1:59998/extension", timeout=0.1)
    cmd = WebBrainCommand(action=WebBrainAction.NAVIGATE, target="https://example.com")
    result = client.execute(cmd)

    assert isinstance(result, WebBrainResult)
    assert result.ok is False
    assert result.status == "offline"
    assert "connection refused" in result.error.lower() or "offline" in result.error.lower() or "error" in result.error.lower()


def test_simulated_successful_execution():
    class MockTransport:
        def send_and_receive(self, payload, timeout):
            return {"status": "ok", "url": payload["target"], "title": "Example Domain"}

    client = WebBrainClient(transport=MockTransport())
    cmd = WebBrainCommand(action=WebBrainAction.NAVIGATE, target="https://example.com")
    result = client.execute(cmd)

    assert result.ok is True
    assert result.status == "executed"
    assert result.data["title"] == "Example Domain"
