"""Per-device Onshape button assignments for spacenavd's logical button IDs."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import socket
import struct
import sys
from tempfile import NamedTemporaryFile

from driver import PACKET, SOCKET_PATH, enable_requests, receive, receive_reply, send_request


DEVICE_TYPE = 0x2005
DEVICE_MODELS = {0x209: "spacepilot-pro", 0x20A: "spacemouse-pro", 0x20D: "spacemouse-pro"}
BUTTON_LABELS = {
    # SpacePilot Pro uses the shared 3Dconnexion HID button sequence.
    "spacepilot-pro": (
        "menu", "fit", "top", "left", "right", "front", "bottom", "back",
        "roll-cw", "roll-ccw", "iso1", "iso2", "key-1", "key-2", "key-3", "key-4",
        "key-5", "key-6", "key-7", "key-8", "key-9", "key-10", "escape", "alt",
        "shift", "ctrl", "rotate", "pan-zoom", "dominant", "plus", "minus",
    ),
    # spacenavd compacts the SpaceMouse Pro's non-contiguous HID button IDs.
    "spacemouse-pro": (
        "key-1", "key-2", "key-3", "key-4", "menu", "fit", "top", "right",
        "front", "iso", "rotate", "escape", "alt", "shift", "ctrl",
    ),
    "generic": (),
}
VIEWS = ("front", "back", "top", "bottom", "left", "right", "isometric")
ROLLS = ("roll-cw", "roll-ccw")
ACTIONS = (
    *VIEWS, *ROLLS, "fit", "front-fit", "rotation-toggle", "pan-zoom-toggle",
    "dominant-toggle", "speed-up", "speed-down", "none",
)
DEFAULT_ACTIONS = {
    **{action: action for action in (*VIEWS, *ROLLS)},
    "fit": "fit",
    "iso": "isometric",
    "iso1": "isometric",
    "iso2": "isometric",
    "rotate": "rotation-toggle",
    "pan-zoom": "pan-zoom-toggle",
    "dominant": "dominant-toggle",
    "plus": "speed-up",
    "minus": "speed-down",
}
MAX_BUTTON_ID = 63
BUTTON_IDS = frozenset(str(number) for number in range(MAX_BUTTON_ID + 1))


def config_path():
    config_dir = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config_dir / "spacemouse" / "buttons.json"


def detect_model():
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        connection.connect(SOCKET_PATH)
        enable_requests(connection)
        send_request(connection, DEVICE_TYPE)
        data, status = receive_reply(connection, DEVICE_TYPE)
        if status == 0:
            return DEVICE_MODELS.get(struct.unpack_from("=i", data)[0], "generic")
    return "generic"


def load_profiles():
    path = config_path()
    try:
        profiles = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(profiles, dict):
        raise ValueError(f"Invalid button profiles in {path}")
    for model, buttons in profiles.items():
        if model not in BUTTON_LABELS or not isinstance(buttons, dict):
            raise ValueError(f"Invalid model profile {model!r} in {path}")
        for button, action in buttons.items():
            if button not in BUTTON_IDS or action not in ACTIONS:
                raise ValueError(f"Invalid mapping for button {button!r} in {path}")
    return profiles


def save_assignment(model, button, action):
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        profiles = load_profiles()
        profile = profiles.setdefault(model, {})
        if action is None:
            profile.pop(str(button), None)
        else:
            profile[str(button)] = action
        if not profile:
            profiles.pop(model)

        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            try:
                json.dump(profiles, output, indent=2, sort_keys=True)
                output.write("\n")
                output.close()
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)


def button_label(model, button):
    labels = BUTTON_LABELS[model]
    return labels[button] if 0 <= button < len(labels) else "unlabelled"


def button_action(model, button, profiles):
    assigned = profiles.get(model, {}).get(str(button))
    if assigned is not None:
        return assigned
    if model == "generic":
        return "front-fit"
    return DEFAULT_ACTIONS.get(button_label(model, button), "none")


def button_number(model, text):
    if text.isdecimal() and 0 <= int(text) <= MAX_BUTTON_ID:
        return int(text)
    labels = BUTTON_LABELS[model]
    if text in labels:
        return labels.index(text)
    raise ValueError(f"Unknown button {text!r} for {model}. Use a listed label or ID 0–{MAX_BUTTON_ID}.")


def watch(model):
    print(f"Press a button on {model}. Ctrl+C stops the test.", flush=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(SOCKET_PATH)
        while True:
            event, button, *_ = PACKET.unpack(receive(connection, PACKET.size))
            if event == 1:
                action = button_action(model, button, load_profiles())
                print(f"Button {button:2d}  {button_label(model, button):12s}  {action}", flush=True)


def main():
    parser = argparse.ArgumentParser(
        prog="spacemouse buttons",
        description="Show or edit button mappings for the focused Onshape viewport.",
        epilog="Example: spacemouse buttons set key-1 isometric",
    )
    parser.add_argument("--model", choices=BUTTON_LABELS, help="choose a profile instead of detecting the device")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("list", help="show buttons and their actions (default)")
    commands.add_parser("watch", help="identify the IDs of pressed buttons")
    commands.add_parser("actions", help="show all assignable actions")
    assign = commands.add_parser("set", help="assign an action to a button")
    assign.add_argument("button", help="button ID or label")
    assign.add_argument("action", choices=ACTIONS)
    reset = commands.add_parser("default", help="restore a button's default action")
    reset.add_argument("button", help="button ID or label")
    args = parser.parse_args()

    try:
        if args.command == "actions":
            print("\n".join(ACTIONS))
            return 0
        model = args.model or detect_model()
        if args.command == "watch":
            watch(model)
        elif args.command in ("set", "default"):
            button = button_number(model, args.button)
            save_assignment(model, button, getattr(args, "action", None))
            action = button_action(model, button, load_profiles())
            print(f"{model} button {button} ({button_label(model, button)}) → {action}")
        else:
            profiles = load_profiles()
            ids = set(range(len(BUTTON_LABELS[model])))
            ids.update(int(number) for number in profiles.get(model, {}))
            print(f"Onshape button profile for {model}")
            if not ids:
                print("Buttons default to front-fit. Use spacemouse buttons watch to find IDs.")
            for button in sorted(ids):
                action = button_action(model, button, profiles)
                print(f"{button:2d}  {button_label(model, button):12s}  {action}")
    except KeyboardInterrupt:
        return 130
    except (ValueError, RuntimeError, OSError) as error:
        print(f"Akita SpaceMouse buttons: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
