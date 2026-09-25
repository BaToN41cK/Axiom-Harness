"""Tests for shared formatting helpers (W1.3 live elapsed timer)."""

from __future__ import annotations

from axiom.shared import formatting as fmt


def test_status_line_elapsed_active():
    line = fmt.status_line("thinking", active=True, elapsed=4.8)
    assert "Thinking" in line
    assert "4.8s" in line


def test_status_line_elapsed_inactive():
    line = fmt.status_line("completed", active=False, elapsed=4.8)
    assert "Completed" in line
    assert "4.8s" not in line


def test_status_line_elapsed_none():
    line = fmt.status_line("thinking", active=True, elapsed=None)
    assert "Thinking" in line
    # No elapsed suffix when the caller did not provide a real start time.
    assert "0.0s" not in line


def test_status_line_elapsed_zero():
    line = fmt.status_line("thinking", active=True, elapsed=0.0)
    assert "Thinking" in line
    assert "0.0s" in line


def test_status_line_elapsed_with_duration():
    line = fmt.status_line("thinking", active=True, elapsed=4.8, duration_ms=5000)
    assert "Thinking" in line
    assert "4.8s" in line
    assert "5.0s" in line
