# SPDX-License-Identifier: GPL-3.0-only
"""Use spacenav-ws for Onshape with complete packets and predictable disconnects."""

import asyncio
from contextlib import suppress
from dataclasses import replace
import json
import logging
import os
from time import monotonic
from uuid import uuid4

import numpy as np
import uvicorn
from spacenav_ws.main import CERT_FILE, KEY_FILE, app as upstream_app
from spacenav_ws.controller import create_mouse_controller
from spacenav_ws.spacenav import from_message
from spacenav_ws.wamp import WampSession
from starlette.applications import Starlette
from starlette.routing import Mount, WebSocketRoute
from starlette.websockets import WebSocketDisconnect

from button_profiles import (
    MAX_SPEED, MIN_SPEED, ROLLS, VIEWS, action_name, button_action, connected_model, load_profiles, load_speeds,
)
from diagnostics import crash_file, log_event, state_dir
from driver import PACKET, SOCKET_PATH
from lcd_state import controls_dir, write_atomic


VIEW_DIRECTIONS = {
    # Relative to the right, up, and outward axes in Onshape's front view.
    "front": ((0, 0, 1), (0, 1, 0)),
    "back": ((0, 0, -1), (0, 1, 0)),
    "left": ((-1, 0, 0), (0, 1, 0)),
    "right": ((1, 0, 0), (0, 1, 0)),
    "top": ((0, 1, 0), (0, 0, -1)),
    "bottom": ((0, -1, 0), (0, 0, 1)),
    "isometric": ((1, 1, 1), (0, 1, 0)),
    "roll-cw": ((0, 0, 1), (1, 0, 0)),
    "roll-ccw": ((0, 0, 1), (-1, 0, 0)),
}
TRANSLATION = ("x", "y", "z")
ROTATION = ("pitch", "yaw", "roll")


def orient_camera(current, front, bounds, action):
    outward, up_reference = np.asarray(VIEW_DIRECTIONS[action]) @ front[:3, :3]
    outward /= np.linalg.norm(outward)
    right = np.cross(up_reference, outward)
    right /= np.linalg.norm(right)
    up = np.cross(outward, right)
    axes = np.array((right, up, outward))

    midpoint = (bounds[:3] + bounds[3:]) / 2
    local_offset = (current[3, :3] - midpoint) @ current[:3, :3].T
    oriented = current.copy()
    oriented[:3, :3] = axes
    oriented[3, :3] = midpoint + local_offset @ axes
    return oriented


async def fit_view(controller):
    bounds = np.asarray(await controller.remote_read("model.extents"), dtype=float)
    affine = np.asarray(await controller.remote_read("view.affine"), dtype=float).reshape(4, 4)
    extents = await controller.remote_read("view.extents")
    width = extents[3] - extents[0]
    height = extents[4] - extents[1]
    if width <= 0 or height <= 0:
        return
    aspect = width / height
    half_width, half_height, _ = np.abs(affine[:3, :3]) @ ((bounds[3:] - bounds[:3]) / 2)
    height = max(half_height, half_width / aspect)
    if height <= 0:
        return
    height *= 1.2
    width = height * aspect
    midpoint = (bounds[:3] + bounds[3:]) / 2
    offset = affine[3, :3] - midpoint
    # Keep the camera's depth while centering the part in the view plane.
    outward = affine[2, :3]
    affine[3, :3] = midpoint + np.dot(offset, outward) * outward
    await controller.remote_write("view.affine", affine.reshape(-1).tolist())
    await controller.remote_write("view.extents", [-width, -height, extents[2], width, height, extents[5]])


class Navigation:
    def __init__(self, speed):
        self.pan_zoom = True
        self.rotation = True
        self.dominant = False
        self.speed = speed
        self.input_at = 0.0
        self.action = ""
        self.action_until = 0.0

    def motion(self, event):
        axes = {name: getattr(event, name) * self.speed if self.pan_zoom else 0 for name in TRANSLATION}
        axes.update({name: getattr(event, name) * self.speed if self.rotation else 0 for name in ROTATION})
        if self.dominant:
            largest = max(axes, key=lambda name: abs(axes[name]))
            axes = {name: value if name == largest else 0 for name, value in axes.items()}
        return replace(event, **axes)

    async def press(self, controller, event, action):
        if action == "front-fit":
            await controller.update_client(event)
        elif action == "fit":
            await fit_view(controller)
        elif action in (*VIEWS, *ROLLS):
            current = np.asarray(await controller.remote_read("view.affine"), dtype=float).reshape(4, 4)
            reference = current
            if action in VIEWS:
                reference = np.asarray(await controller.remote_read("views.front"), dtype=float).reshape(4, 4)
            bounds = np.asarray(await controller.remote_read("model.extents"), dtype=float)
            view = orient_camera(current, reference, bounds, action)
            await controller.remote_write("view.affine", view.reshape(-1).tolist())
        elif action == "rotation-toggle":
            self.rotation = not self.rotation
        elif action == "pan-zoom-toggle":
            self.pan_zoom = not self.pan_zoom
        elif action == "dominant-toggle":
            self.dominant = not self.dominant
        elif action == "speed-up":
            self.speed = min(self.speed * 1.25, MAX_SPEED)
        elif action == "speed-down":
            self.speed = max(self.speed / 1.25, MIN_SPEED)

        if action != "none":
            self.action = {
                "rotation-toggle": "Rotation unlocked" if self.rotation else "Rotation locked",
                "pan-zoom-toggle": "Pan and zoom unlocked" if self.pan_zoom else "Pan and zoom locked",
                "dominant-toggle": "Dominant axis on" if self.dominant else "Dominant axis off",
            }.get(action, action_name(action))
            self.action_until = monotonic() + 2.5


def initial_speed() -> float:
    try:
        speed = float(os.environ.get("SPACEMOUSE_ONSHAPE_SENSITIVITY", "1"))
        if MIN_SPEED <= speed <= MAX_SPEED:
            return speed
    except ValueError:
        pass
    logging.warning("Set SPACEMOUSE_ONSHAPE_SENSITIVITY between %g and %g. Using 1.", MIN_SPEED, MAX_SPEED)
    return 1.0


def speed_for_device():
    model = connected_model()
    try:
        return model, load_speeds().get(model)
    except (OSError, ValueError) as error:
        logging.warning("Using the default motion speed. %s", error)
        return model, None


def action_for(button):
    model = connected_model()
    try:
        profiles = load_profiles()
    except (OSError, ValueError) as error:
        logging.warning("Using default button assignments. %s", error)
        profiles = {}
    return button_action(model, button, profiles)


async def stream_input(controller, reader, navigation=None):
    if navigation is None:
        navigation = Navigation(initial_speed())
    default_speed = navigation.speed
    speed_profile = None
    check_speed_at = 0.0
    now = asyncio.get_running_loop().time
    while True:
        packet = PACKET.unpack(await reader.readexactly(PACKET.size))
        kind, button, *_ = packet
        if kind not in (0, 1) or not (controller.focus and controller.subscribed):
            continue
        if controller.client_metadata.get("name") not in ("Onshape", "WebThreeJS Sample"):
            continue
        if now() >= check_speed_at:
            profile = await asyncio.to_thread(speed_for_device)
            if profile != speed_profile:
                speed_profile = profile
                _, speed = profile
                navigation.speed = default_speed if speed is None else speed
            check_speed_at = now() + 1
            if not (controller.focus and controller.subscribed):
                continue
        navigation.input_at = monotonic()
        if kind == 0:
            event = navigation.motion(from_message(packet))
            await controller.update_client(event)
        else:
            action = await asyncio.to_thread(action_for, button)
            if controller.focus and controller.subscribed:
                await navigation.press(controller, from_message(packet), action)


async def publish_controls(controller, navigation):
    path = controls_dir() / f"{uuid4().hex}.json"
    published = None
    published_at = 0.0
    try:
        while True:
            with suppress(OSError):
                if controller.focus and controller.subscribed:
                    state = vars(navigation).copy()
                    now = monotonic()
                    if state != published or now - published_at >= 1:
                        write_atomic(path, json.dumps({**state, "updated": now}).encode())
                        published, published_at = state, now
                elif published is not None:
                    path.unlink(missing_ok=True)
                    published = None
            await asyncio.sleep(0.25)
    finally:
        with suppress(OSError):
            path.unlink(missing_ok=True)


async def onshape_websocket(websocket):
    try:
        reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)
    except OSError as error:
        log_event(f"Onshape bridge could not reach spacenavd: {error}")
        await websocket.close(code=1013)
        return

    try:
        log_event("Onshape client connected")
        controller = await create_mouse_controller(WampSession(websocket), reader)
        navigation = Navigation(initial_speed())
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(stream_input(controller, reader, navigation))
            tasks.create_task(controller.wamp_state_handler.start_wamp_message_stream())
            if controller.client_metadata.get("name") == "Onshape":
                tasks.create_task(publish_controls(controller, navigation))
    except* WebSocketDisconnect:
        log_event("Onshape client disconnected")
    except* (asyncio.IncompleteReadError, ConnectionError):
        log_event("spacenavd disconnected from the Onshape bridge")
        with suppress(WebSocketDisconnect, RuntimeError):
            await websocket.close(code=1013, reason="spacenavd disconnected")
    finally:
        writer.close()
        with suppress(OSError):
            await writer.wait_closed()


app = Starlette(routes=[WebSocketRoute("/", onshape_websocket), Mount("/", app=upstream_app)])


def main():
    import faulthandler
    import traceback

    try:
        state_dir().mkdir(parents=True, exist_ok=True)
        crash = open(crash_file(), "a", encoding="utf-8")
        faulthandler.enable(crash, all_threads=True)
    except OSError:
        pass
    log_event(f"Onshape bridge starting pid {os.getpid()}")
    try:
        uvicorn.run(app, host="127.51.68.120", port=8181, ssl_certfile=CERT_FILE, ssl_keyfile=KEY_FILE)
    except Exception:
        log_event(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
