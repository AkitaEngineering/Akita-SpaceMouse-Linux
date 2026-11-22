"""Device diagnostics and live configuration through spacenavd's Unix socket."""

import argparse
import math
import socket
import struct
import sys

# Match the path used by spacenav-ws.
SOCKET_PATH = "/var/run/spnav.sock"

# Native protocol v1: https://github.com/FreeSpacenav/spacenavd/blob/v1.4/src/proto.h
PACKET = struct.Struct("=8i")
PROTOCOL_V1 = struct.pack("=I", 0x7FAA5501)
SET_EVENT_MASK = 0x1003
DEVICE_NAME = 0x2000
SET_SENSITIVITY, GET_SENSITIVITY = 0x3000, 0x3001
SET_AXIS_SENSITIVITY, GET_AXIS_SENSITIVITY = 0x3002, 0x3003
SET_DEAD_ZONE, GET_DEAD_ZONE = 0x3004, 0x3005
SET_INVERT, GET_INVERT = 0x3006, 0x3007
SAVE_CONFIG, RESTORE_CONFIG = 0x3FFE, 0x3FFF


def receive(connection, size):
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise RuntimeError("spacenavd closed the connection.")
        data.extend(chunk)
    return data


def send_request(connection, command, *values):
    connection.sendall(PACKET.pack(command, *values, *([0] * (7 - len(values)))))


def receive_reply(connection, command):
    while True:
        packet = receive(connection, PACKET.size)
        reply, *data = PACKET.unpack(packet)
        if reply == command:
            return packet[4:28], data[-1]
        if reply >= SET_EVENT_MASK:
            raise RuntimeError(f"Unexpected response from spacenavd (0x{reply:x}).")
        # Input or device change events can arrive before the mask is set.


def request(connection, command, *values, fmt="=6i"):
    send_request(connection, command, *values)
    data, status = receive_reply(connection, command)
    if status:
        if command == SAVE_CONFIG:
            raise RuntimeError("Settings are live, but spacenavd could not save its configuration.")
        raise RuntimeError(f"spacenavd rejected request 0x{command:x}.")
    return struct.unpack(fmt, data)


def enable_requests(connection):
    connection.sendall(PROTOCOL_V1)
    try:
        while receive(connection, 4) != PROTOCOL_V1:
            # Before negotiation, any pending input is sent in 32-byte frames.
            receive(connection, PACKET.size - 4)
    except TimeoutError as error:
        raise RuntimeError("This command requires spacenavd 1.0 or newer. Run spacemouse install to update it.") from error
    request(connection, SET_EVENT_MASK, 0)


def show_device(connection):
    send_request(connection, DEVICE_NAME)
    name = bytearray()
    while True:
        data, remaining = receive_reply(connection, DEVICE_NAME)
        if remaining < 0:
            print("spacenavd is running. Plug in a supported 3Dconnexion device and retry.")
            return 1
        remaining &= 0xFFFF
        name.extend(data[: min(remaining, len(data))])
        if remaining <= len(data):
            print(f"Detected by spacenavd: {name.decode(errors='replace').strip()}")
            return 0


def test_input(connection):
    connection.settimeout(None)
    print("Move the cap or press a button. Ctrl+C stops the test.", flush=True)
    while True:
        event, *values = PACKET.unpack(receive(connection, PACKET.size))
        if event == 0:
            x, y, z, rx, ry, rz, period = values
            print(f"Motion  X {x:5d} Y {y:5d} Z {z:5d}  RX {rx:5d} RY {ry:5d} RZ {rz:5d}  {period} ms", flush=True)
        elif event in (1, 2):
            action = "pressed" if event == 1 else "released"
            print(f"Button {values[0]} {action}", flush=True)


def axis_flags(axes):
    return [int(axis in axes) for axis in "xyz"]


def axis_names(flags):
    return "".join(axis for axis, enabled in zip("xyz", flags) if enabled) or "none"


def float_bits(*values):
    return struct.unpack(f"={len(values)}i", struct.pack(f"={len(values)}f", *values))


def tune(connection, args):
    sensitivity, *_ = request(connection, GET_SENSITIVITY, fmt="=6f")
    axis_gain = list(request(connection, GET_AXIS_SENSITIVITY, fmt="=6f"))
    inverted = list(request(connection, GET_INVERT))
    dead_zones = [request(connection, GET_DEAD_ZONE, axis)[1] for axis in range(6)]

    if args.sensitivity is not None and args.sensitivity != sensitivity:
        request(connection, SET_SENSITIVITY, *float_bits(args.sensitivity))
        sensitivity = args.sensitivity
    if args.translation is not None or args.rotation is not None:
        if args.translation is not None:
            axis_gain[:3] = [args.translation] * 3
        if args.rotation is not None:
            axis_gain[3:] = [args.rotation] * 3
        request(connection, SET_AXIS_SENSITIVITY, *float_bits(*axis_gain))
    if args.invert_translation is not None or args.invert_rotation is not None:
        if args.invert_translation is not None:
            inverted[:3] = axis_flags(args.invert_translation)
        if args.invert_rotation is not None:
            inverted[3:] = axis_flags(args.invert_rotation)
        request(connection, SET_INVERT, *inverted)
    if args.dead_zone is not None:
        for axis, threshold in enumerate(dead_zones):
            if args.dead_zone != threshold:
                request(connection, SET_DEAD_ZONE, axis, args.dead_zone)
        dead_zones = [args.dead_zone] * 6
    if args.save:
        request(connection, SAVE_CONFIG)
        print("Saved the current spacenavd settings.")
    print(f"Sensitivity   {sensitivity:g}")
    print("Translation   " + " / ".join(f"{value:g}" for value in axis_gain[:3]))
    print("Rotation      " + " / ".join(f"{value:g}" for value in axis_gain[3:]))
    print("Dead zone     " + " / ".join(map(str, dead_zones)))
    print(f"Inversion     translation {axis_names(inverted[:3])}, rotation {axis_names(inverted[3:])}")


def gain(value):
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 10:
        raise argparse.ArgumentTypeError("use a multiplier from 0 to 10")
    return number


def dead_zone(value):
    threshold = int(value)
    if not 0 <= threshold <= 2**31 - 1:
        raise argparse.ArgumentTypeError("use a non-negative 32-bit integer")
    return threshold


def axes_to_invert(value):
    if value.lower() == "none":
        return ""
    if value and set(value.lower()) <= set("xyz"):
        return value.lower()
    raise argparse.ArgumentTypeError("use any combination of x, y, z or 'none'")


def main():
    command = sys.argv[1]
    parser = argparse.ArgumentParser(prog=f"spacemouse {command}", allow_abbrev=False)
    if command == "test":
        parser.description = "Watch motion and button events from the connected device. Press Ctrl+C to stop."
    if command == "tune":
        parser.description = "Show or change live motion settings for all spacenavd clients."
        parser.add_argument("--sensitivity", type=gain, metavar="GAIN", help="overall multiplier, 0–10")
        parser.add_argument("--translation", type=gain, metavar="GAIN", help="set the X/Y/Z translation multipliers")
        parser.add_argument("--rotation", type=gain, metavar="GAIN", help="set the X/Y/Z rotation multipliers")
        parser.add_argument("--dead-zone", type=dead_zone, metavar="N", help="ignore motion below N on the six motion axes")
        parser.add_argument("--invert-translation", type=axes_to_invert, metavar="AXES", help="invert any of x, y, z or clear with 'none'")
        parser.add_argument("--invert-rotation", type=axes_to_invert, metavar="AXES", help="invert any of x, y, z or clear with 'none'")
        persistence = parser.add_mutually_exclusive_group()
        persistence.add_argument("--save", action="store_true", help="save the current daemon settings across restarts")
        persistence.add_argument("--restore", action="store_true", help="reload the daemon's saved settings")
    args = parser.parse_args(sys.argv[2:])
    if command == "tune" and args.restore and any(
        value is not None for key, value in vars(args).items() if key not in ("save", "restore")
    ):
        parser.error("--restore must be used by itself")

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(2)
            try:
                connection.connect(SOCKET_PATH)
            except OSError as error:
                raise RuntimeError(f"Cannot connect to spacenavd at {SOCKET_PATH} ({error.strerror}).") from error
            if command == "socket":
                return 0
            if command == "test":
                test_input(connection)
            enable_requests(connection)
            if command == "device":
                return show_device(connection)
            if args.restore:
                request(connection, RESTORE_CONFIG)
                print("Reloaded the saved spacenavd settings.")
            tune(connection, args)
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError) as error:
        print(f"Akita SpaceMouse: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
