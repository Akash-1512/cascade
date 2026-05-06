"""Tests for the cascade MCP server entry point."""

from __future__ import annotations

import pytest

from cascade.mcp.server import main


@pytest.mark.unit
def test_main_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """``--version`` prints the version and exits 0."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "cascade-mcp" in captured.out


@pytest.mark.unit
def test_main_unknown_transport_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    """An unknown ``--transport`` value is rejected by argparse with exit 2."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--transport", "carrier-pigeon"])
    assert exc_info.value.code == 2


@pytest.mark.unit
def test_main_failure_returns_non_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``build_server`` raises, ``main`` returns 1 instead of crashing."""
    from cascade.mcp import server as server_module

    def _explode() -> None:
        raise RuntimeError("intentional failure for testing")

    monkeypatch.setattr(server_module, "build_server", _explode)
    rc = main(["--transport", "stdio"])
    assert rc == 1
