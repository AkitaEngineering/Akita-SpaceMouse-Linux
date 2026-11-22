import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import numpy as np

from driver import PACKET
from onshape_bridge import stream_input


ROOT = Path(__file__).resolve().parents[1]


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.fixture = tempfile.TemporaryDirectory()
        self.addCleanup(self.fixture.cleanup)
        root = Path(self.fixture.name)
        self.env = {
            **os.environ,
            "HOME": str(root / "home"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_DATA_HOME": str(root / "data"),
        }

    def run_command(self, *args):
        return subprocess.run(
            [ROOT / "spacemouse", *args], env=self.env, text=True,
            capture_output=True, check=True, timeout=10,
        ).stdout

    def test_version_and_help(self):
        version = (ROOT / "VERSION").read_text().strip()
        self.assertEqual(self.run_command("--version").strip(), f"Akita SpaceMouse for Linux {version}")
        self.assertIn("akitaengineering.com", self.run_command("--help"))
        for command in ("install", "uninstall", "doctor", "test", "tune", "buttons", "onshape"):
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
        launcher = Path(self.env["HOME"]) / ".local/bin/spacemouse"
        launcher.parent.mkdir(parents=True)
        launcher.symlink_to(app / "spacemouse")

        self.run_command("buttons", "--model", "spacepilot-pro", "set", "key-1", "fit")
        profile = Path(self.env["XDG_CONFIG_HOME"]) / "spacemouse" / "buttons.json"
        self.assertIn("Dry run", self.run_command("uninstall", "--dry-run", "--purge"))
        self.assertTrue(launcher.is_symlink())
        self.assertTrue(profile.is_file())
        self.run_command("uninstall")
        self.assertFalse(launcher.is_symlink())
        self.assertFalse(app.exists())
        self.assertTrue(profile.is_file())
        self.run_command("uninstall", "--purge")
        self.assertFalse(profile.exists())


class OnshapeInputTest(unittest.IsolatedAsyncioTestCase):
    async def test_split_packet_and_press_only_mapping(self):
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
        with patch("onshape_bridge.action_for", return_value="top") as action:
            task = asyncio.create_task(stream_input(controller, reader))
            reader.feed_data(motion[:9])
            await asyncio.sleep(0)
            reader.feed_data(motion[9:] + press + release)
            reader.feed_eof()
            with self.assertRaises(asyncio.IncompleteReadError):
                await asyncio.wait_for(task, 2)
            action.assert_called_once_with(2)

        controller.update_client.assert_awaited_once()
        self.assertEqual(controller.update_client.await_args.args[0].x, 10)
        controller.remote_write.assert_awaited_once()
        property_name, matrix = controller.remote_write.await_args.args
        self.assertEqual(property_name, "view.affine")
        np.testing.assert_allclose(np.asarray(matrix).reshape(4, 4)[2, :3], [0, 1, 0])
