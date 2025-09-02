"""Cross-platform hotkey helper.

Primary implementation uses `pynput` GlobalHotKeys which works on Windows, macOS and Linux.
If `pynput` is not available, the module documents a possible Windows-only fallback using pywin32.

API:
    start_hotkey(hotkey, callback) -> stop_callable

hotkey format examples:
    '<ctrl>+<alt>+g' or 'ctrl+alt+g'

The returned stop_callable stops the listener when called.
"""
from __future__ import annotations

import platform
import threading
from typing import Callable

_listener = None


def _normalize_hotkey(hk: str) -> str:
    # normalize common forms to pynput style e.g. 'ctrl+alt+g' -> '<ctrl>+<alt>+g'
    hk = hk.strip().lower()
    parts = hk.replace(' ', '').split('+')
    norm = []
    for p in parts:
        if p in ('ctrl', 'control'):
            norm.append('<ctrl>')
        elif p in ('alt',):
            norm.append('<alt>')
        elif p in ('shift',):
            norm.append('<shift>')
        elif p in ('cmd', 'super', 'win'):
            # on macOS use <cmd>, on Windows <cmd> maps to Windows key via pynput
            norm.append('<cmd>')
        else:
            norm.append(p)
    return '+'.join(norm)


def start_hotkey(hotkey: str, callback: Callable[[], None]):
    """Start a global hotkey listener.

    Returns a callable that stops the listener when invoked.

    Requires package `pynput` to be installed. If unavailable, raises ImportError.
    """
    global _listener

    try:
        from pynput import keyboard
    except Exception as e:
        raise ImportError("pynput is required for cross-platform hotkeys") from e

    hotkey_pynput = _normalize_hotkey(hotkey)

    # Build mapping for GlobalHotKeys
    mapping = {hotkey_pynput: callback}

    gh = keyboard.GlobalHotKeys(mapping)

    # run listener in a daemon thread so it does not block process exit
    thread = threading.Thread(target=gh.start, daemon=True)
    thread.start()

    _listener = gh

    def stop():
        try:
            gh.stop()
        except Exception:
            pass

    return stop


if __name__ == '__main__':
    # simple demo: press Ctrl+Alt+G to print message
    def cb():
        print('Hotkey pressed')

    print('Starting demo hotkey: Ctrl+Alt+G')
    stopper = start_hotkey('ctrl+alt+g', cb)
    try:
        # keep main thread alive
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stopper()
