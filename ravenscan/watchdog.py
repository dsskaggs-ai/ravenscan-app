#!/usr/bin/env python3
"""
Main-loop stall detector for RavenScan.
If the GTK main loop stops ticking for longer than the threshold (long enough
for Hyprland's "not responding" dialog), the main thread's stack is appended
to ~/.cache/ravenscan/stall.log so the blocking call can be identified.
"""

import os
import sys
import time
import threading
import traceback

from gi.repository import GLib

LOG_PATH = os.path.expanduser("~/.cache/ravenscan/stall.log")


def start(threshold: float = 2.0):
    main_ident = threading.main_thread().ident
    last_tick = [time.monotonic()]

    def tick():
        last_tick[0] = time.monotonic()
        return True

    GLib.timeout_add(250, tick)

    def watch():
        reported = False
        while True:
            time.sleep(0.5)
            stalled = time.monotonic() - last_tick[0]
            if stalled < threshold:
                reported = False
                continue
            if reported:
                continue
            reported = True
            frame = sys._current_frames().get(main_ident)
            stack = "".join(traceback.format_stack(frame)) if frame else "(no frame)\n"
            try:
                os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
                with open(LOG_PATH, "a") as f:
                    f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} main loop stalled {stalled:.1f}s\n{stack}\n")
            except OSError:
                pass

    threading.Thread(target=watch, daemon=True, name="stall-watchdog").start()
