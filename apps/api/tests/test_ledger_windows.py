"""The ledger on a host without owner-only, no-follow files (Windows), simulated as in
test_windows_gates.py: it is off with a fixed reason and never touches a file."""
import os
import sys

import pytest

from super_agent_voice import ledger, posix_files, runner


def test_ledger_is_off_without_posix_files(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    for name in ("O_NOFOLLOW", "O_NONBLOCK", "fchmod", "getuid"):
        monkeypatch.delattr(os, name, raising=False)
    assert not posix_files.available()
    with pytest.raises(ledger.LedgerError, match="ledger_off_no_posix_files"):
        ledger.Ledger(tmp_path / "store" / "ledger.db")
    assert not (tmp_path / "store").exists()
    assert runner.Runner  # the modules still import there
