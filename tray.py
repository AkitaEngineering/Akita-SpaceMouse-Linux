# SPDX-License-Identifier: GPL-3.0-only
"""KDE StatusNotifierItem for SpaceMouse settings and the LCD stream."""

from pathlib import Path
import sys

try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as Indicator, Gio, GLib, Gtk
except (ImportError, ValueError) as error:
    sys.exit(f"The SpaceMouse tray requires Ayatana AppIndicator. Run spacemouse install. {error}")

from lcd_state import notifications_enabled, set_notifications_enabled


APP_DIR = Path(__file__).resolve().parent
SYSTEMD = "org.freedesktop.systemd1"
BRIDGE_UNIT = "spacemouse-bridge.service"
LCD_UNIT = "spacemouse-lcd.service"
LCD_RUNNING = ("active", "activating", "reloading")


def unit_proxy(path, interface):
    return Gio.DBusProxy.new_for_bus_sync(
        Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None, SYSTEMD, path, f"{SYSTEMD}.{interface}", None,
    )


def unit_state(unit):
    state = unit.get_cached_property("ActiveState")
    return state.get_string() if state is not None else "unknown"


class SpaceMouseTray:
    def __init__(self):
        self.manager = unit_proxy("/org/freedesktop/systemd1", "Manager")
        self.manager.call_sync("Subscribe", None, Gio.DBusCallFlags.NONE, 3000, None)
        self.bridge = self.get_unit(BRIDGE_UNIT)
        self.lcd = self.get_unit(LCD_UNIT)

        self.indicator = Indicator.Indicator.new(
            "akita-spacemouse", "akita-spacemouse", Indicator.IndicatorCategory.HARDWARE,
        )
        self.indicator.set_title("Akita SpaceMouse")
        self.indicator.set_icon_theme_path(str(APP_DIR / "icons"))

        menu = Gtk.Menu()
        settings = Gtk.MenuItem(label="Open SpaceMouse Settings")
        settings.connect("activate", self.open_settings)
        menu.append(settings)

        snapshots = Gtk.MenuItem(label="LCD Snapshots…")
        snapshots.connect("activate", self.open_settings, "--lcd")
        menu.append(snapshots)

        self.lcd_toggle = Gtk.MenuItem(label="Start LCD")
        self.lcd_toggle.connect("activate", self.toggle_lcd)
        menu.append(self.lcd_toggle)

        self.notifications = Gtk.CheckMenuItem(label="Show Plasma notifications on LCD")
        self.notifications.set_active(notifications_enabled())
        self.notification_handler = self.notifications.connect("toggled", self.toggle_notifications)
        menu.append(self.notifications)
        menu.append(Gtk.SeparatorMenuItem())

        self.bridge_status = Gtk.MenuItem()
        self.bridge_status.set_sensitive(False)
        menu.append(self.bridge_status)
        self.lcd_status = Gtk.MenuItem()
        self.lcd_status.set_sensitive(False)
        menu.append(self.lcd_status)
        self.error_status = Gtk.MenuItem()
        self.error_status.set_sensitive(False)
        self.error_status.set_no_show_all(True)
        menu.append(self.error_status)
        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit tray")
        quit_item.connect("activate", lambda _item: Gtk.main_quit())
        menu.append(quit_item)
        menu.show_all()
        self.indicator.set_menu(menu)
        self.indicator.set_secondary_activate_target(settings)
        self.refresh()
        self.indicator.set_status(Indicator.IndicatorStatus.ACTIVE)
        self.bridge.connect("g-properties-changed", self.refresh)
        self.lcd.connect("g-properties-changed", self.refresh)

    def get_unit(self, name):
        response = self.manager.call_sync(
            "LoadUnit", GLib.Variant("(s)", (name,)), Gio.DBusCallFlags.NONE, 3000, None,
        )
        return unit_proxy(response.unpack()[0], "Unit")

    def refresh(self, *_args):
        bridge = unit_state(self.bridge)
        lcd = unit_state(self.lcd)
        self.bridge_status.set_label(f"Onshape bridge: {bridge}")
        self.lcd_status.set_label(f"LCD stream: {lcd}")
        self.lcd_toggle.set_label("Stop LCD" if lcd in LCD_RUNNING else "Start LCD")
        icon = "akita-spacemouse-ready" if bridge == "active" else "akita-spacemouse-warning"
        self.indicator.set_icon_full(icon, f"Akita SpaceMouse. Onshape bridge: {bridge}.")

    def show_error(self, message):
        print(message, file=sys.stderr)
        self.error_status.set_label(message)
        self.error_status.show()

    def open_settings(self, _item, *args):
        self.error_status.hide()
        try:
            Gio.Subprocess.new(
                ["systemd-run", "--user", "--scope", "--collect", "--quiet", "--",
                 sys.executable, "-B", str(APP_DIR / "settings.py"), *args], Gio.SubprocessFlags.NONE,
            )
        except GLib.Error as error:
            self.show_error(f"Could not open SpaceMouse Settings. {error.message}")

    def change_lcd(self, method):
        self.error_status.hide()
        self.manager.call(method, GLib.Variant("(ss)", (LCD_UNIT, "replace")),
                          Gio.DBusCallFlags.NONE, 3000, None, self.lcd_command_finished)

    def lcd_command_finished(self, proxy, result, _data=None):
        try:
            proxy.call_finish(result)
        except GLib.Error as error:
            self.show_error(f"LCD command failed. {error.message}")

    def toggle_lcd(self, _item):
        running = unit_state(self.lcd) in LCD_RUNNING
        self.change_lcd("StopUnit" if running else "StartUnit")

    def toggle_notifications(self, item):
        self.error_status.hide()
        try:
            set_notifications_enabled(item.get_active())
        except OSError as error:
            with item.handler_block(self.notification_handler):
                item.set_active(notifications_enabled())
            self.show_error(f"Could not save the LCD notification setting. {error}")
            return
        if unit_state(self.lcd) in LCD_RUNNING:
            self.change_lcd("RestartUnit")


if __name__ == "__main__":
    try:
        if not Gtk.init_check()[0]:
            sys.exit("SpaceMouse tray requires a graphical session.")
        tray = SpaceMouseTray()
        Gtk.main()
    except GLib.Error as error:
        sys.exit(f"Could not run the SpaceMouse tray. {error.message}")
