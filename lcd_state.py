# SPDX-License-Identifier: GPL-3.0-only
"""Local state shared by the Onshape bridge and the LCD."""

from contextlib import suppress
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic

from button_profiles import config_path, valid_speed
from diagnostics import state_dir


LCD_WIDTH, LCD_HEIGHT = 320, 240


def controls_dir():
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return (Path(runtime) / "spacemouse" if runtime else state_dir()) / "lcd-controls"


def snapshot_path():
    return config_path().with_name("lcd-snapshot.png")


def notifications_enabled():
    return config_path().with_name("lcd-notifications").is_file()


def set_notifications_enabled(enabled):
    path = config_path().with_name("lcd-notifications")
    if enabled:
        write_atomic(path, b"on\n")
    else:
        path.unlink(missing_ok=True)


def write_atomic(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temp = Path(output.name)
        try:
            output.write(data)
            output.close()
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


def active_controls():
    now = monotonic()
    latest = None
    latest_time = (0.0, 0.0)
    with suppress(OSError):
        for path in controls_dir().glob("*.json"):
            try:
                controls = json.loads(path.read_bytes())
                updated = controls["updated"]
                speed = controls["speed"]
                if not 0 <= now - updated < 3 or not valid_speed(speed):
                    continue
                updated_at = (controls["input_at"], updated)
                if updated_at > latest_time:
                    action = controls["action"] if now < controls["action_until"] else ""
                    latest = (speed, controls["pan_zoom"], controls["rotation"], controls["dominant"], action)
                    latest_time = updated_at
            except (OSError, ValueError, TypeError, KeyError):
                continue
    return latest
