"""Keeping "heirloom gui" going in the background: one window at a time, and starting with Windows."""
import threading
import time

import pytest

from heirloom.gui.background import claim_window, start_with_windows, startup_command


def test_a_second_window_brings_back_the_first(tmp_path):
    shown = threading.Event()
    port_file = tmp_path / 'window.port'
    assert claim_window(port_file, shown.set), 'the first window is the one'
    assert not claim_window(port_file, lambda: pytest.fail('the second window must not answer')), \
        'a second one asks the first to show itself, and does not open'
    assert shown.wait(5)


def test_a_stale_port_file_is_taken_over(tmp_path):
    port_file = tmp_path / 'window.port'
    port_file.write_text('1')
    started = time.monotonic()
    assert claim_window(port_file, lambda: None), 'no window answers on that port, so this one opens'
    assert time.monotonic() - started < 1, 'without waiting for the refusal'
    assert port_file.read_text() != '1'


def test_starting_with_windows_needs_the_installer():
    assert startup_command() is None, 'not frozen, so there is no heirloom-gui.exe to start'
    with pytest.raises(ValueError):
        start_with_windows(True)
