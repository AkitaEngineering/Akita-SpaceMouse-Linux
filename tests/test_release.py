# SPDX-License-Identifier: GPL-3.0-only
import asyncio
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from time import monotonic
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import numpy as np

from button_profiles import detect_model, load_profiles, load_speeds, save_speed
from driver import PACKET
from lcd_state import active_controls
from onshape_bridge import Navigation, publish_controls, stream_input


ROOT = Path(__file__).resolve().parents[1]


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.fixture = tempfile.TemporaryDirectory()
        self.addCleanup(self.fixture.cleanup)
        root = Path(self.fixture.name)
        self.stub_bin = root / "bin"
        self.stub_bin.mkdir()
        self.env = {
            **os.environ,
            "HOME": str(root / "home"),
            "PATH": f"{self.stub_bin}{os.pathsep}{os.environ['PATH']}",
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_DATA_HOME": str(root / "data"),
        }

    def run_command(self, *args):
        return subprocess.run(
            [ROOT / "spacemouse", *args], env=self.env, text=True,
            capture_output=True, check=True, timeout=10,
        ).stdout

    def stub_command(self, name, script):
        command = self.stub_bin / name
        command.write_text(f"#!/bin/sh\n{script}\n")
        command.chmod(0o755)

    def write_bridge_unit(self):
        unit = Path(self.env["XDG_CONFIG_HOME"]) / "systemd/user/spacemouse-bridge.service"
        unit.parent.mkdir(parents=True)
        unit.write_text("# Installed by Akita SpaceMouse\n")
        return unit

    def test_version_and_help(self):
        version = (ROOT / "VERSION").read_text().strip()
        self.assertEqual(self.run_command("--version").strip(), f"Akita SpaceMouse for Linux {version}")
        self.assertIn("akitaengineering.com", self.run_command("--help"))
        for command in ("install", "uninstall", "doctor", "test", "tune", "buttons", "settings", "display", "tray", "onshape", "agreement", "support", "desk"):
            with self.subTest(command=command):
                self.assertIn("spacemouse", self.run_command(command, "--help"))

    def test_button_overrides_stay_in_separate_profiles(self):
        pilot = ("buttons", "--model", "spacepilot-pro")
        mouse = ("buttons", "--model", "spacemouse-pro")
        self.assertIn("12  key-1         none", self.run_command(*pilot))
        self.assertIn("button 12", self.run_command(*pilot, "set", "key-1", "top"))
        self.assertIn("12  key-1         top", self.run_command(*pilot))
        self.assertIn(" 0  key-1         none", self.run_command(*mouse))
        self.run_command(*pilot, "default", "12")
        self.assertIn("12  key-1         none", self.run_command(*pilot))

    def test_supported_models_have_separate_button_profiles(self):
        for model, label, action in (
            ("spacemouse", "left-button", "fit"),
            ("spacepilot", "key-1", "left"),
            ("spacenavigator", "left-button", "top"),
        ):
            self.run_command("buttons", "--model", model, "set", label, action)
        with patch.dict(os.environ, self.env):
            self.assertEqual(load_profiles(), {
                "spacemouse": {"0": "fit"},
                "spacepilot": {"0": "left"},
                "spacenavigator": {"0": "top"},
            })

    def test_model_detection_uses_spacenavd_device_types(self):
        with (
            patch("button_profiles.socket.socket"),
            patch("button_profiles.enable_requests"),
            patch("button_profiles.send_request"),
            patch("button_profiles.receive_reply") as reply,
        ):
            for device_type, model in (
                (0x202, "spacemouse-classic"), (0x205, "spacepilot"),
                (0x206, "spacenavigator"), (0x208, "spacenavigator"),
                (0x209, "spacepilot-pro"), (0x20A, "spacemouse-pro"),
                (0x20C, "spacemouse"), (0x20D, "spacemouse-pro"),
                (0x20F, "spacemouse"), (0x210, "generic"),
            ):
                with self.subTest(device_type=device_type):
                    reply.return_value = struct.pack("=6i", device_type, 0, 0, 0, 0, 0), 0
                    self.assertEqual(detect_model(), model)

    def test_launcher_starts_and_reuses_enabled_bridge_service(self):
        self.write_bridge_unit()
        Path(self.env["HOME"]).mkdir()
        self.stub_command("curl", 'test -f "$HOME/bridge-started"')
        self.stub_command("systemctl", """
case "$*" in
    '--user is-enabled --quiet spacemouse-bridge.service') exit 0 ;;
    '--user start spacemouse-bridge.service') printf 'started\\n' >> "$HOME/bridge-started" ;;
    *) exit 2 ;;
esac
""")
        for _ in range(2):
            self.assertIn("Onshape bridge is running", self.run_command("onshape", "--no-browser"))
        self.assertEqual((Path(self.env["HOME"]) / "bridge-started").read_text(), "started\n")

    @unittest.skipIf(os.geteuid() == 0, "Uninstall requires a desktop user")
    def test_uninstall_preview_and_profile_retention(self):
        app = Path(self.env["XDG_DATA_HOME"]) / "spacemouse"
        store = app / "uv-tools"
        tool = store / "spacenav-ws"
        tool.mkdir(parents=True)
        (tool / "uv-receipt.toml").touch()
        (store / ".lock").touch()
        (store / ".gitignore").write_text("*")
        (app / "bin").mkdir()
        (app / "bin" / "spacenav-ws").symlink_to(tool / "bin" / "spacenav-ws")
        shutil.copy2(ROOT / "spacemouse", app / "spacemouse")
        shutil.copy2(ROOT / "settings.py", app / "settings.py")
        shutil.copytree(ROOT / "icons", app / "icons")
        desktop = app.parent / "applications" / "com.akitaengineering.SpaceMouseSettings.desktop"
        desktop.parent.mkdir()
        desktop.write_text("# Installed by Akita SpaceMouse\n[Desktop Entry]\n")
        launcher = Path(self.env["HOME"]) / ".local/bin/spacemouse"
        launcher.parent.mkdir(parents=True)
        launcher.symlink_to(app / "spacemouse")
        unit = self.write_bridge_unit()
        tray = unit.with_name("spacemouse-tray.service")
        lcd = unit.with_name("spacemouse-lcd.service")
        for desktop_unit in (tray, lcd):
            desktop_unit.write_text("# Installed by Akita SpaceMouse\n")
        self.stub_command("systemctl", 'printf "%s\\n" "$*" >> "$HOME/systemctl.log"')
        systemctl_log = Path(self.env["HOME"]) / "systemctl.log"

        self.run_command("buttons", "--model", "spacepilot-pro", "set", "key-1", "fit")
        profile = Path(self.env["XDG_CONFIG_HOME"]) / "spacemouse" / "buttons.json"
        speeds = profile.with_name("speeds.json")
        speeds.write_text('{"spacepilot-pro": 0.5}\n')
        agreement = profile.with_name("agreement.json")
        agreement.write_text("{}\n")
        preview = self.run_command("uninstall", "--dry-run", "--purge")
        self.assertIn("Dry run", preview)
        self.assertIn(str(unit), preview)
        self.assertIn(str(tray), preview)
        self.assertIn(str(lcd), preview)
        self.assertIn(str(desktop), preview)
        self.assertTrue(unit.is_file())
        self.assertTrue(desktop.is_file())
        self.assertFalse(systemctl_log.exists())
        self.assertTrue(launcher.is_symlink())
        self.assertTrue(profile.is_file())
        self.assertTrue(agreement.is_file())
        self.run_command("uninstall")
        self.assertFalse(unit.exists())
        self.assertFalse(tray.exists())
        self.assertFalse(lcd.exists())
        self.assertFalse(desktop.exists())
        self.assertEqual(systemctl_log.read_text().splitlines(), [
            "--user disable --now spacemouse-tray.service",
            "--user disable --now spacemouse-lcd.service",
            "--user disable --now spacemouse-bridge.service",
            "--user daemon-reload",
        ])
        self.assertFalse(launcher.is_symlink())
        self.assertFalse(app.exists())
        self.assertTrue(profile.is_file())
        self.assertTrue(speeds.is_file())
        self.assertTrue(agreement.is_file())
        self.run_command("uninstall", "--purge")
        self.assertFalse(profile.exists())
        self.assertFalse(speeds.exists())
        self.assertFalse(agreement.exists())


class CommercialOfferTest(unittest.TestCase):
    def test_published_rates_match_the_price_list(self):
        readme = (ROOT / "README.md").read_text()
        commercial = (ROOT / "COMMERCIAL.md").read_text()
        self.assertIn("(COMMERCIAL.md)", readme)
        self.assertIn("as many compatible Linux machines", readme)
        self.assertIn("GPL-3.0-only", commercial)
        for price in (
            "US$109", "C$149", "€99",
            "US$149", "C$169", "€119",
            "US$499", "C$649", "€449",
            "US$39", "C$49", "€39",
            "C$199", "€139",
            "C$1,629",
        ):
            with self.subTest(price=price):
                self.assertIn(price, commercial)
                if price != "C$1,629":
                    self.assertIn(price, readme)


class OnshapeInputTest(unittest.IsolatedAsyncioTestCase):
    async def test_lcd_shows_focused_controls_and_expires_button_feedback(self):
        controller = SimpleNamespace(focus=True, subscribed=True)
        navigation = Navigation(0.5)
        with (
            tempfile.TemporaryDirectory() as runtime,
            patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime}),
        ):
            await navigation.press(controller, None, "rotation-toggle")
            task = asyncio.create_task(publish_controls(controller, navigation))
            try:
                await asyncio.sleep(0)
                self.assertEqual(active_controls(), (0.5, True, False, False, "Rotation locked"))
                with patch("lcd_state.monotonic", return_value=monotonic() + 2.6):
                    self.assertEqual(active_controls(), (0.5, True, False, False, ""))
                controller.focus = False
                await asyncio.sleep(0.3)
                self.assertIsNone(active_controls())
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertIsNone(active_controls())

    async def test_split_packet_scales_motion_and_maps_presses(self):
        class Controller:
            focus = True
            subscribed = True
            client_metadata = {"name": "Onshape"}
            update_client = AsyncMock()
            remote_read = AsyncMock(side_effect=(
                np.identity(4).ravel().tolist(),
                np.identity(4).ravel().tolist(),
                [-1, -1, -1, 1, 1, 1],
            ))
            remote_write = AsyncMock()

        controller = Controller()
        reader = asyncio.StreamReader()
        motion = PACKET.pack(0, 10, 15, 20, 1, 2, 3, 16)
        press = PACKET.pack(1, 2, 0, 0, 0, 0, 0, 0)
        release = PACKET.pack(2, 2, 0, 0, 0, 0, 0, 0)
        with (
            tempfile.TemporaryDirectory() as config,
            patch.dict(os.environ, {"XDG_CONFIG_HOME": config, "SPACEMOUSE_ONSHAPE_SENSITIVITY": "1"}),
            patch("onshape_bridge.connected_model", return_value="spacenavigator"),
            patch("onshape_bridge.action_for", return_value="top") as action,
        ):
            save_speed("spacepilot", 1.25)
            save_speed("spacenavigator", 0.5)
            self.assertEqual(load_speeds(), {"spacepilot": 1.25, "spacenavigator": 0.5})
            task = asyncio.create_task(stream_input(controller, reader))
            reader.feed_data(motion[:9])
            await asyncio.sleep(0)
            reader.feed_data(motion[9:] + press + release)
            reader.feed_eof()
            with self.assertRaises(asyncio.IncompleteReadError):
                await asyncio.wait_for(task, 2)
            action.assert_called_once_with(2)

        controller.update_client.assert_awaited_once()
        event = controller.update_client.await_args.args[0]
        self.assertEqual((event.x, event.y, event.z), (5, 10, 7.5))
        self.assertEqual((event.pitch, event.yaw, event.roll), (0.5, 1, 1.5))
        controller.remote_write.assert_awaited_once()
        property_name, matrix = controller.remote_write.await_args.args
        self.assertEqual(property_name, "view.affine")
        np.testing.assert_allclose(np.asarray(matrix).reshape(4, 4)[2, :3], [0, 1, 0])
