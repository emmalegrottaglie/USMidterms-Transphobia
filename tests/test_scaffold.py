from pathlib import Path

import pytest

from monitor import ROOT

CANONICAL = Path(r"C:/Russian bot tracker/terminal-design-system/terminal.css")


def test_design_system_is_a_synced_copy():
    if not CANONICAL.parent.parent.is_dir():
        pytest.skip("bot tracker repo not present")
    copy = ROOT / "terminal-design-system" / "terminal.css"
    assert copy.read_bytes() == CANONICAL.read_bytes()
