# SPDX-License-Identifier: GPL-3.0-only
"""Use spacenav-ws for Onshape with complete packets and predictable disconnects."""

import asyncio
from contextlib import suppress
from dataclasses import replace
import logging

import numpy as np
import uvicorn
from spacenav_ws.main import CERT_FILE, KEY_FILE, app as upstream_app
from spacenav_ws.controller import create_mouse_controller
from spacenav_ws.spacenav import from_message
from spacenav_ws.wamp import WampSession
from starlette.applications import Starlette
from starlette.routing import Mount, WebSocketRoute
from starlette.websockets import WebSocketDisconnect

from button_profiles import ROLLS, VIEWS, button_action, detect_model, load_profiles
from driver import PACKET, SOCKET_PATH


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
    def __init__(self):
        self.pan_zoom = True
        self.rotation = True
        self.dominant = False
        self.speed = 1.0

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
            self.speed = min(self.speed * 1.25, 4.0)
        elif action == "speed-down":
            self.speed = max(self.speed / 1.25, 0.25)


def action_for(button):
    try:
        model = detect_model()
    except (OSError, RuntimeError):
        model = "generic"
    try:
        profiles = load_profiles()
    except (OSError, ValueError) as error:
        logging.warning("Using default button assignments. %s", error)
        profiles = {}
    return button_action(model, button, profiles)


async def stream_input(controller, reader):
    navigation = Navigation()
    while True:
        packet = PACKET.unpack(await reader.readexactly(PACKET.size))
        kind, button, *_ = packet
        if not (controller.focus and controller.subscribed):
            continue
        if controller.client_metadata.get("name") not in ("Onshape", "WebThreeJS Sample"):
            continue
        if kind == 0:
            event = navigation.motion(from_message(packet))
            await controller.update_client(event)
        elif kind == 1:
            action = await asyncio.to_thread(action_for, button)
            if controller.focus and controller.subscribed:
                await navigation.press(controller, from_message(packet), action)


async def onshape_websocket(websocket):
    try:
        reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)
    except OSError:
        await websocket.close(code=1013)
        return

    try:
        controller = await create_mouse_controller(WampSession(websocket), reader)
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(stream_input(controller, reader))
            tasks.create_task(controller.wamp_state_handler.start_wamp_message_stream())
    except* WebSocketDisconnect:
        pass
    except* (asyncio.IncompleteReadError, ConnectionError):
        with suppress(WebSocketDisconnect, RuntimeError):
            await websocket.close(code=1013, reason="spacenavd disconnected")
    finally:
        writer.close()
        with suppress(OSError):
            await writer.wait_closed()


app = Starlette(routes=[WebSocketRoute("/", onshape_websocket), Mount("/", app=upstream_app)])


if __name__ == "__main__":
    uvicorn.run(app, host="127.51.68.120", port=8181, ssl_certfile=CERT_FILE, ssl_keyfile=KEY_FILE)
