# SPDX-License-Identifier: GPL-3.0-only
"""Stream CAD controls, snapshots, and optional Plasma alerts to the SpacePilot Pro LCD."""

import argparse
from array import array
from contextlib import ExitStack, contextmanager
import ctypes as C
from datetime import datetime
from io import BytesIO
import os
import signal
import sys
from time import monotonic

from button_profiles import action_name, button_action, load_profiles, load_speeds
from lcd_state import (
    LCD_HEIGHT as HEIGHT, LCD_WIDTH as WIDTH, active_controls, notifications_enabled,
    snapshot_path, write_atomic,
)

try:
    import cairo
    import gi

    gi.require_foreign("cairo")
    gi.require_version("GdkPixbuf", "2.0")
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import GdkPixbuf, Gio, GLib, Pango, PangoCairo
except (ImportError, ValueError) as error:
    DISPLAY_DEPENDENCY_ERROR = str(error)
else:
    DISPLAY_DEPENDENCY_ERROR = None


LCD_INTERFACE = 0
LCD_ENDPOINT = 0x02
# G19-compatible frame format documented by libg19 and 3dxdisp-pro.
HEADER = bytes.fromhex("10 0f 00 58 02 00 00 00 00 00 00 3f 01 ef 00") + bytes(i % 256 for i in range(15, 512))
NOTIFICATIONS = "org.freedesktop.Notifications"
NOTIFICATIONS_PATH = "/org/freedesktop/Notifications"
WATCHER_XML = """
<node>
  <interface name="org.kde.NotificationWatcher">
    <method name="Notify">
      <arg type="u" direction="in"/>
      <arg type="s" direction="in"/>
      <arg type="u" direction="in"/>
      <arg type="s" direction="in"/>
      <arg type="s" direction="in"/>
      <arg type="s" direction="in"/>
      <arg type="as" direction="in"/>
      <arg type="a{sv}" direction="in"/>
      <arg type="i" direction="in"/>
    </method>
    <method name="CloseNotification"><arg type="u" direction="in"/></method>
  </interface>
</node>
"""


class DisplayError(RuntimeError):
    pass


@contextmanager
def open_display():
    try:
        usb = C.CDLL("libusb-1.0.so.0")
    except OSError as error:
        raise DisplayError("libusb is missing. Run ./spacemouse install.") from error
    usb.libusb_init.argtypes = [C.POINTER(C.c_void_p)]
    usb.libusb_exit.argtypes, usb.libusb_exit.restype = [C.c_void_p], None
    usb.libusb_open_device_with_vid_pid.argtypes = [C.c_void_p, C.c_uint16, C.c_uint16]
    usb.libusb_open_device_with_vid_pid.restype = C.c_void_p
    usb.libusb_close.argtypes, usb.libusb_close.restype = [C.c_void_p], None
    usb.libusb_claim_interface.argtypes = usb.libusb_release_interface.argtypes = [C.c_void_p, C.c_int]
    usb.libusb_bulk_transfer.argtypes = [C.c_void_p, C.c_ubyte, C.c_char_p, C.c_int, C.POINTER(C.c_int), C.c_uint]
    usb.libusb_error_name.argtypes, usb.libusb_error_name.restype = [C.c_int], C.c_char_p

    def check(result, operation):
        if result < 0:
            raise DisplayError(f"{operation}: {usb.libusb_error_name(result).decode()}")

    with ExitStack() as cleanup:
        context = C.c_void_p()
        check(usb.libusb_init(C.byref(context)), "Could not initialize USB")
        cleanup.callback(usb.libusb_exit, context)
        device = usb.libusb_open_device_with_vid_pid(context, 0x046D, 0xC629)
        if not device:
            raise DisplayError("Could not open the SpacePilot Pro LCD. Check that it is connected and your session has USB access.")
        cleanup.callback(usb.libusb_close, device)
        check(usb.libusb_claim_interface(device, LCD_INTERFACE), "Could not claim the LCD interface")
        cleanup.callback(usb.libusb_release_interface, device, LCD_INTERFACE)

        def write(frame):
            written = C.c_int()
            result = usb.libusb_bulk_transfer(device, LCD_ENDPOINT, frame, len(frame), C.byref(written), 1000)
            check(result, "LCD transfer failed")
            if written.value != len(frame):
                raise DisplayError(f"LCD received {written.value} of {len(frame)} bytes.")

        yield write


class PlasmaNotifications:
    def __init__(self):
        self.owner = None
        self.notification = None
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        info = Gio.DBusNodeInfo.new_for_xml(WATCHER_XML)
        self.object_id = self.bus.register_object("/NotificationWatcher", info.interfaces[0], self.receive, None, None)
        self.watch_id = Gio.bus_watch_name_on_connection(
            self.bus, NOTIFICATIONS, Gio.BusNameWatcherFlags.NONE, self.register, self.unregister,
        )
        self.closed_id = self.bus.signal_subscribe(
            NOTIFICATIONS, NOTIFICATIONS, "NotificationClosed", NOTIFICATIONS_PATH, None,
            Gio.DBusSignalFlags.NONE, self.closed,
        )

    def register(self, connection, _name, owner):
        self.owner = owner
        try:
            connection.call_sync(owner, NOTIFICATIONS_PATH, "org.kde.NotificationManager", "RegisterWatcher",
                                 None, None, Gio.DBusCallFlags.NONE, 1000, None)
        except GLib.Error as error:
            print(f"SpacePilot Pro LCD could not subscribe to Plasma notifications. {error.message}", file=sys.stderr)

    def unregister(self, _connection, _name):
        self.owner = None
        self.notification = None

    def receive(self, _connection, sender, _path, _interface, method, params, reply):
        if sender != self.owner:
            reply.return_dbus_error("org.freedesktop.DBus.Error.AccessDenied", "Expected the Plasma notification server")
            return
        if method == "Notify":
            notification_id = params.get_child_value(0).get_uint32()
            application = params.get_child_value(1).get_string() or "Desktop notification"
            summary = params.get_child_value(4).get_string()
            self.notification = (notification_id, application, summary, monotonic() + 8)
        else:
            self.dismiss(params.get_child_value(0).get_uint32())
        reply.return_value(None)

    def closed(self, _connection, _sender, _path, _interface, _signal, params):
        self.dismiss(params.get_child_value(0).get_uint32())

    def dismiss(self, notification_id):
        if self.notification and self.notification[0] == notification_id:
            self.notification = None

    def current(self):
        if self.notification and monotonic() < self.notification[3]:
            return self.notification[1:3]
        self.notification = None
        return None

    def close(self):
        Gio.bus_unwatch_name(self.watch_id)
        self.bus.signal_unsubscribe(self.closed_id)
        self.bus.unregister_object(self.object_id)


def text(context, value, x, y, size, *, width=276, lines=1, color=(0.93, 0.96, 0.99), bold=False):
    layout = PangoCairo.create_layout(context)
    font = Pango.FontDescription("Sans Bold" if bold else "Sans")
    font.set_absolute_size(size * Pango.SCALE)
    layout.set_font_description(font)
    layout.set_width(width * Pango.SCALE)
    layout.set_height(-lines)
    layout.set_ellipsize(Pango.EllipsizeMode.END)
    layout.set_text(value, -1)
    context.set_source_rgb(*color)
    context.move_to(x, y)
    PangoCairo.show_layout(context, layout)


def dashboard():
    clock = datetime.now().strftime("%H:%M")
    try:
        model = "spacepilot-pro"
        speed = load_speeds().get(model)
        profiles = load_profiles()
        actions = tuple(action_name(button_action(model, button, profiles)) for button in range(12, 16))
        return clock, "Bridge default" if speed is None else f"{speed:.2f}×", actions
    except (OSError, ValueError):
        return clock, "Settings unavailable", ()


def pin_snapshot(source):
    image = GdkPixbuf.Pixbuf.new_from_file_at_scale(os.fspath(source), WIDTH, WIDTH, True)
    image = image.apply_embedded_orientation()
    scale = min(WIDTH / image.get_width(), HEIGHT / image.get_height(), 1)
    if scale < 1:
        image = image.scale_simple(max(1, round(image.get_width() * scale)),
                                   max(1, round(image.get_height() * scale)), GdkPixbuf.InterpType.BILINEAR)
    success, png = image.save_to_bufferv("png", [], [])
    if not success:
        raise DisplayError("Could not prepare the snapshot.")
    write_atomic(snapshot_path(), bytes(png))


def screen_content(alert=None):
    if alert:
        return "notification", alert

    controls = active_controls()
    try:
        snapshot = snapshot_path().read_bytes()
    except OSError:
        snapshot = None
    if snapshot is not None:
        caption = ""
        if controls is not None:
            speed, pan_zoom, rotation, dominant, action = controls
            modes = f"Pan {'on' if pan_zoom else 'off'}   Rot {'on' if rotation else 'off'}   Dom {'on' if dominant else 'off'}"
            caption = action or f"{speed:.2f}×   {modes}"
        return "snapshot", (snapshot, caption)
    if controls is not None:
        return "controls", controls
    return "dashboard", dashboard()


def draw_snapshot(context, snapshot, caption):
    try:
        image = cairo.ImageSurface.create_from_png(BytesIO(snapshot))
    except cairo.Error:
        text(context, "Snapshot unavailable", 22, 22, 22, bold=True)
        return
    image_height = HEIGHT - 27 if caption else HEIGHT
    scale = min(WIDTH / image.get_width(), image_height / image.get_height(), 1)
    context.save()
    context.translate((WIDTH - image.get_width() * scale) / 2, (image_height - image.get_height() * scale) / 2)
    context.scale(scale, scale)
    context.set_source_surface(image)
    context.paint()
    context.restore()
    if caption:
        text(context, caption, 14, 218, 15, width=292, bold=True)


def frame_for(kind, data):
    surface = cairo.ImageSurface(cairo.FORMAT_RGB16_565, HEIGHT, WIDTH)
    context = cairo.Context(surface)
    # The connector maps landscape pixel (x, y) to panel coordinate (y, x).
    context.transform(cairo.Matrix(0, 1, 1, 0, 0, 0))
    context.set_source_rgb(0.04, 0.07, 0.12)
    context.paint()
    accent = (0.45, 0.92, 0.71)
    muted = (0.67, 0.75, 0.83)
    context.set_source_rgb(*accent)
    context.rectangle(0, 0, WIDTH, 4)
    context.fill()
    if kind == "snapshot":
        draw_snapshot(context, *data)
    elif kind == "notification":
        application, summary = data
        text(context, application, 22, 23, 19, color=accent, bold=True)
        text(context, summary, 22, 63, 25, lines=4, bold=True)
    elif kind == "controls":
        speed, pan_zoom, rotation, dominant, action = data
        text(context, "Onshape controls", 22, 20, 22, bold=True)
        text(context, "LIVE SPEED", 22, 55, 14, color=muted, bold=True)
        text(context, f"{speed:.2f}×", 22, 73, 30, color=accent, bold=True)
        labels = (
            ("Pan and zoom", "On" if pan_zoom else "Locked"),
            ("Rotation", "On" if rotation else "Locked"),
            ("Dominant axis", "On" if dominant else "Off"),
        )
        for y, (label, value) in zip((121, 144, 167), labels):
            text(context, label, 22, y, 16, color=muted)
            text(context, value, 213, y, 16, width=85, bold=True)
        if action:
            text(context, action, 22, 202, 17, color=accent, bold=True)
    else:
        clock, speed, actions = data
        text(context, "SpacePilot Pro", 22, 20, 21, bold=True)
        text(context, clock, 247, 22, 18, width=52, color=muted)
        text(context, "ONSHAPE SPEED", 22, 62, 14, color=muted, bold=True)
        text(context, speed, 22, 81, 28, color=accent, bold=True)
        for index, action in enumerate(actions):
            y = 128 + index * 24
            text(context, f"Key {index + 1}", 22, y, 16, width=57, color=muted)
            text(context, action, 92, y, 16, width=205)
    surface.flush()
    pixels = bytes(surface.get_data())
    if sys.byteorder != "little":
        converted = array("H", pixels)
        converted.byteswap()
        pixels = converted.tobytes()
    return HEADER + pixels


def show_once():
    if DISPLAY_DEPENDENCY_ERROR:
        raise DisplayError(f"LCD graphics libraries are unavailable. {DISPLAY_DEPENDENCY_ERROR}")
    with open_display() as write:
        write(frame_for(*screen_content()))


def main():
    parser = argparse.ArgumentParser(prog="spacemouse display", description=__doc__)
    parser.add_argument("--once", action="store_true", help="refresh the LCD once and exit")
    parser.add_argument("--notifications", action="store_true", help="show incoming Plasma notification summaries")
    parser.add_argument("--saved-notifications", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    show_notifications = args.notifications or (args.saved_notifications and notifications_enabled())
    if args.once and show_notifications:
        parser.error("--notifications requires continuously updating the display")
    if DISPLAY_DEPENDENCY_ERROR:
        parser.exit(1, f"SpacePilot Pro LCD requires Pycairo and PyGObject. Run ./spacemouse install. {DISPLAY_DEPENDENCY_ERROR}\n")

    try:
        if args.once:
            show_once()
            print("Updated the SpacePilot Pro LCD.")
            return 0
        with open_display() as write:
            notifications = PlasmaNotifications() if show_notifications else None
            loop = GLib.MainLoop()
            last = None
            status = 0

            def refresh():
                nonlocal last, status
                alert = notifications.current() if notifications else None
                current = screen_content(alert)
                if current != last:
                    try:
                        write(frame_for(*current))
                    except DisplayError as error:
                        print(f"SpacePilot Pro LCD: {error}", file=sys.stderr)
                        status = 1
                        loop.quit()
                        return GLib.SOURCE_REMOVE
                    last = current
                return GLib.SOURCE_CONTINUE

            def stop(_signum, _frame):
                loop.quit()

            refresh()
            if status == 0:
                GLib.timeout_add(500, refresh)
                signal.signal(signal.SIGINT, stop)
                signal.signal(signal.SIGTERM, stop)
                print("Streaming to the SpacePilot Pro LCD.", flush=True)
                loop.run()
            if notifications:
                notifications.close()
                if status == 0 and last[0] == "notification":
                    write(frame_for(*screen_content()))
            return status
    except (DisplayError, GLib.Error) as error:
        print(f"SpacePilot Pro LCD: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
