# SPDX-License-Identifier: GPL-3.0-only
"""GTK 4 settings for Onshape controls and the SpacePilot Pro LCD."""

from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk, Gio, GLib, Gtk
except (ImportError, ValueError):
    sys.exit("SpaceMouse Settings requires GTK 4 and PyGObject. Run ./spacemouse install to set them up.")

from button_profiles import (
    ACTIONS, BUTTON_LABELS, MAX_BUTTON_ID, MAX_SPEED, MIN_SPEED, MODEL_NAMES,
    action_name, button_action, button_label, connected_model, load_profiles, load_speeds, save_assignment, save_speed,
)
from lcd_state import snapshot_path
from spacepilot_display import DISPLAY_DEPENDENCY_ERROR, DisplayError, pin_snapshot, show_once


APP_ID = "com.akitaengineering.SpaceMouseSettings"
ICON_NAME = "akita-spacemouse"
MODELS = tuple(MODEL_NAMES)
BUTTON_NAMES = {
    "iso": "Isometric",
    "iso1": "Isometric 1",
    "iso2": "Isometric 2",
    "pan-zoom": "Pan and Zoom",
    "plus": "Speed +",
    "minus": "Speed −",
    "roll-cw": "Roll Clockwise",
    "roll-ccw": "Roll Counterclockwise",
}
ASSIGNMENTS = (None, *ACTIONS)
SAVE_HINT = "Changes save automatically for the selected device profile."


class LCDWindow(Gtk.Window):
    def __init__(self, parent):
        super().__init__(title="SpacePilot Pro LCD", transient_for=parent, modal=True, default_width=500)
        self.set_icon_name(ICON_NAME)
        self.chooser = None
        self.spectacle = shutil.which("spectacle")
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        for edge in (content.set_margin_top, content.set_margin_bottom, content.set_margin_start, content.set_margin_end):
            edge(20)
        self.set_child(content)

        self.preview = Gtk.Picture(can_shrink=True, hexpand=True)
        self.preview.set_size_request(320, 240)
        content.append(self.preview)

        buttons = Gtk.Box(spacing=10)
        content.append(buttons)
        choose = Gtk.Button(label="Pin image…")
        choose.connect("clicked", self.choose_image)
        buttons.append(choose)
        self.capture = Gtk.Button(label="Capture region…")
        self.capture.set_visible(self.spectacle is not None)
        self.capture.connect("clicked", self.capture_region)
        buttons.append(self.capture)
        self.clear = Gtk.Button(label="Clear snapshot")
        self.clear.connect("clicked", self.clear_image)
        buttons.append(self.clear)

        self.status = Gtk.Label(xalign=0, wrap=True)
        content.append(self.status)
        self.refresh_preview()
        self.status.set_label("Pin a CAD view or leave the LCD on live controls.")

    def refresh_preview(self):
        image = snapshot_path()
        self.clear.set_sensitive(image.is_file())
        # A fresh GFile forces the picture to reload even though the pin's path stays the same.
        self.preview.set_paintable(None)
        if image.is_file():
            self.preview.set_file(Gio.File.new_for_path(str(image)))

    def update_lcd(self, message):
        self.refresh_preview()
        try:
            show_once()
        except DisplayError:
            self.status.set_label(f"{message} A running LCD stream will pick up the change.")
        else:
            self.status.set_label(f"{message} LCD updated.")

    def pin_image(self, source):
        try:
            if DISPLAY_DEPENDENCY_ERROR:
                raise DisplayError(DISPLAY_DEPENDENCY_ERROR)
            pin_snapshot(source)
        except (DisplayError, GLib.Error, OSError) as error:
            self.status.set_label(f"Could not pin the image. {error}")
        else:
            self.update_lcd("Snapshot pinned.")

    def clear_image(self, _button):
        try:
            snapshot_path().unlink(missing_ok=True)
        except OSError as error:
            self.status.set_label(f"Could not clear the snapshot. {error}")
        else:
            self.update_lcd("Snapshot cleared.")

    def choose_image(self, _button):
        self.chooser = Gtk.FileChooserNative.new("Pin a CAD snapshot", self, Gtk.FileChooserAction.OPEN, "Pin", "Cancel")
        image_filter = Gtk.FileFilter(name="PNG and JPEG images")
        image_filter.add_mime_type("image/png")
        image_filter.add_mime_type("image/jpeg")
        self.chooser.add_filter(image_filter)
        self.chooser.connect("response", self.image_chosen)
        self.chooser.show()

    def image_chosen(self, chooser, response):
        if response == Gtk.ResponseType.ACCEPT:
            source = chooser.get_file()
            if source and source.get_path():
                self.pin_image(source.get_path())
            else:
                self.status.set_label("Choose an image saved on this computer.")
        chooser.destroy()
        self.chooser = None

    def capture_region(self, _button):
        temporary = TemporaryDirectory(prefix="spacemouse-capture-")
        path = Path(temporary.name) / "capture.png"
        self.set_visible(False)
        self.get_transient_for().set_visible(False)
        try:
            process = Gio.Subprocess.new(
                [self.spectacle, "--new-instance", "--background", "--region", "--nonotify", "--output", str(path)],
                Gio.SubprocessFlags.NONE,
            )
        except GLib.Error as error:
            temporary.cleanup()
            self.status.set_label(f"Could not launch Spectacle. {error.message}")
            self.get_transient_for().present()
            self.present()
            return
        self.capture.set_sensitive(False)
        self.status.set_label("Select the CAD viewport in Spectacle.")
        process.wait_async(None, self.capture_finished, (temporary, path))

    def capture_finished(self, process, result, capture):
        temporary, path = capture
        self.capture.set_sensitive(True)
        try:
            process.wait_finish(result)
            if process.get_successful() and path.is_file():
                self.pin_image(path)
            else:
                self.status.set_label("No region captured.")
        except GLib.Error as error:
            self.status.set_label(f"Capture did not finish. {error.message}")
        finally:
            temporary.cleanup()
            self.get_transient_for().present()
            self.present()


class SettingsWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="SpaceMouse Settings", default_width=670, default_height=620)
        self.set_icon_name(ICON_NAME)
        self.lcd_window = None

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_start(24)
        content.set_margin_end(24)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        self.set_child(content)

        title_bar = Gtk.Box(spacing=12)
        content.append(title_bar)
        logo = Gtk.Image.new_from_icon_name(ICON_NAME)
        logo.set_pixel_size(32)
        title_bar.append(logo)
        heading = Gtk.Label(label="Onshape controls", xalign=0, hexpand=True)
        heading.add_css_class("title-1")
        title_bar.append(heading)
        lcd_button = Gtk.Button(label="LCD…")
        lcd_button.set_tooltip_text("Pin a CAD snapshot to the SpacePilot Pro LCD")
        lcd_button.connect("clicked", self.open_lcd)
        title_bar.append(lcd_button)

        toolbar = Gtk.Box(spacing=12)
        content.append(toolbar)
        profile_label = Gtk.Label(label="_Device profile", use_underline=True)
        toolbar.append(profile_label)
        self.profile = Gtk.DropDown.new_from_strings(list(MODEL_NAMES.values()))
        self.profile.set_hexpand(True)
        self.profile.set_halign(Gtk.Align.START)
        profile_label.set_mnemonic_widget(self.profile)
        toolbar.append(self.profile)

        self.speed_row = Gtk.Box(spacing=12)
        content.append(self.speed_row)
        speed_label = Gtk.Label(label="_Overall speed", use_underline=True, hexpand=True, xalign=0)
        self.speed_row.append(speed_label)
        self.speed = Gtk.SpinButton.new_with_range(MIN_SPEED, MAX_SPEED, 0.05)
        self.speed.set_digits(2)
        self.speed.set_numeric(True)
        self.speed.set_tooltip_text("Speed multiplier for pan, zoom, and rotation. 1.00 is normal speed.")
        self.speed_row.append(self.speed)
        speed_label.set_mnemonic_widget(self.speed)
        self.use_default_speed = Gtk.CheckButton(label="Use bridge default")
        self.speed_row.append(self.use_default_speed)
        self.speed_handler = self.speed.connect("value-changed", self.change_speed)
        self.default_speed_handler = self.use_default_speed.connect("toggled", self.change_speed)
        self.saved_speed = None

        button_header = Gtk.Box(spacing=12)
        content.append(button_header)
        button_heading = Gtk.Label(label="Button mappings", hexpand=True, xalign=0)
        button_heading.add_css_class("heading")
        button_header.append(button_heading)
        self.show_all = Gtk.CheckButton(label="Show all button IDs")
        button_header.append(self.show_all)

        self.rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, show_separators=True)
        self.scroller = Gtk.ScrolledWindow(vexpand=True, has_frame=True)
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_child(self.rows)
        content.append(self.scroller)

        self.status = Gtk.Label(xalign=0, wrap=True)
        content.append(self.status)

        self.profile.set_selected(MODELS.index(connected_model()))
        self.profile.connect("notify::selected", self.refresh)
        self.show_all.connect("toggled", self.refresh)
        self.refresh()

    def open_lcd(self, *_args):
        if self.lcd_window is None:
            self.lcd_window = LCDWindow(self)
            self.lcd_window.connect("close-request", self.close_lcd)
        self.lcd_window.present()

    def close_lcd(self, _window):
        self.lcd_window = None
        return False

    def set_status(self, message, error=False):
        self.status.set_label(message)
        self.status.set_css_classes(["error" if error else "dim-label"])

    def show_speed(self):
        use_default = self.saved_speed is None
        with self.speed.handler_block(self.speed_handler), self.use_default_speed.handler_block(self.default_speed_handler):
            self.speed.set_value(1.0 if use_default else self.saved_speed)
            self.speed.set_visible(not use_default)
            self.use_default_speed.set_active(use_default)

    def change_speed(self, *_args):
        model = MODELS[self.profile.get_selected()]
        value = None if self.use_default_speed.get_active() else round(self.speed.get_value(), 2)
        try:
            save_speed(model, value)
        except (OSError, ValueError) as error:
            self.show_speed()
            self.set_status(f"Could not save speed. {error}", error=True)
            return

        self.saved_speed = value
        self.show_speed()
        self.set_status(f"Saved overall speed for {MODEL_NAMES[model]}.")

    def refresh(self, *_args):
        model = MODELS[self.profile.get_selected()]
        labels = BUTTON_LABELS[model]
        self.show_all.set_visible(bool(labels))
        self.set_status(SAVE_HINT)
        self.speed_row.set_sensitive(True)
        try:
            self.saved_speed = load_speeds().get(model)
        except (OSError, ValueError) as error:
            self.saved_speed = None
            self.speed_row.set_sensitive(False)
            self.set_status(f"Could not load motion speeds. {error}", error=True)
        self.show_speed()
        while row := self.rows.get_first_child():
            self.rows.remove(row)

        try:
            saved = load_profiles().get(model, {})
        except (OSError, ValueError) as error:
            self.set_status(f"Could not load button profiles. {error}", error=True)
            return

        if not labels or self.show_all.get_active():
            ids = range(MAX_BUTTON_ID + 1)
        else:
            ids = sorted(set(range(len(labels))) | {int(button) for button in saved})
        for button in ids:
            self.add_button(model, button, saved.get(str(button)))
        self.scroller.get_vadjustment().set_value(0)

    def add_button(self, model, button, assignment):
        slug = button_label(model, button)
        name = f"Button {button}" if slug == "unlabelled" else BUTTON_NAMES.get(slug, slug.replace("-", " ").title())
        row = Gtk.ListBoxRow(activatable=False, selectable=False)
        content = Gtk.Box(spacing=12, margin_start=14, margin_end=14, margin_top=8, margin_bottom=8)
        row.set_child(content)
        content.append(Gtk.Label(label=name, xalign=0, hexpand=True))
        if slug != "unlabelled":
            identifier = Gtk.Label(label=f"ID {button}", width_chars=5, xalign=0)
            identifier.add_css_class("dim-label")
            content.append(identifier)

        default = action_name(button_action(model, button, {}))
        choices = [f"Default ({default})", *map(action_name, ACTIONS)]
        action = Gtk.DropDown.new_from_strings(choices)
        action.set_size_request(235, -1)
        action.set_selected(ASSIGNMENTS.index(assignment))
        action.update_property([Gtk.AccessibleProperty.LABEL], [f"Action for {name}"])
        content.append(action)

        def save(dropdown, _property):
            nonlocal assignment
            new_assignment = ASSIGNMENTS[dropdown.get_selected()]
            try:
                save_assignment(model, button, new_assignment)
            except (OSError, ValueError) as error:
                with dropdown.handler_block(handler):
                    dropdown.set_selected(ASSIGNMENTS.index(assignment))
                self.set_status(f"Could not save {name}. {error}", error=True)
                return
            assignment = new_assignment
            self.set_status(f"Saved {name} for {MODEL_NAMES[model]}.")

        handler = action.connect("notify::selected", save)
        self.rows.append(row)


def activate(app):
    window = app.get_active_window() or SettingsWindow(app)
    window.present()
    return window


def command_line(app, command):
    window = activate(app)
    if command.get_options_dict().contains("lcd"):
        window.open_lcd()
    return 0


def load_icons(_app):
    Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(str(Path(__file__).resolve().parent / "icons"))


if __name__ == "__main__":
    application = Gtk.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
    application.add_main_option("lcd", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, "Open LCD snapshots", None)
    application.connect("startup", load_icons)
    application.connect("activate", activate)
    application.connect("command-line", command_line)
    sys.exit(application.run(sys.argv))
