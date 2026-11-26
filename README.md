# Akita SpaceMouse for Linux

Use a 3Dconnexion SpaceMouse, SpacePilot, or SpaceNavigator with Onshape on Linux. The launcher installs the driver and the local Onshape bridge, gives you a live input test, and lets you tune motion and map buttons.

The [GPLv3](LICENSE) Community Edition is an [Akita Engineering](https://www.akitaengineering.com) project.

## Get started

Install and run the Community Edition on as many compatible Linux machines as you like. The installer uses public downloads and runs without an Akita account or licence key. Paid setup, fleet deployment, and support are optional.

You need a Linux desktop with systemd, internet access, and sudo access for system setup. The installer supports Arch Linux and CachyOS, Debian, Ubuntu, Fedora, and derivatives that use the corresponding package repositories.

1. Open the [latest GitHub release](https://github.com/AkitaEngineering/Akita-SpaceMouse-Linux/releases/latest) and download the named `.tar.gz` archive. Extract it and open a terminal in the extracted folder.
2. Plug in your device and run these commands as your regular desktop user.

   ```sh
   ./spacemouse install
   ./spacemouse doctor
   ./spacemouse
   ```

3. Complete the [one-time Onshape setup](#onshape-setup) in the same browser profile you use for CAD.

After setup, run `spacemouse onshape` from any folder. If your shell cannot find it, run `~/.local/bin/spacemouse onshape` or use `./spacemouse onshape` from the extracted folder. Run `spacemouse --help` for commands and `spacemouse --version` for the installed version.

The installer enables `spacenavd` at boot, downloads the latest stable upstream driver when the distro package is older, and checks the source archive against its published SHA-256 digest. It installs the Onshape bridge in an isolated Python environment and starts it as a background service that runs automatically when you sign in. Your driver configuration lives in `/etc/spnavrc`.

### Verify the download

Download `SHA256SUMS` alongside the archive. Open a terminal in the download folder and run `sha256sum -c SHA256SUMS`. The archive should report `OK`.

## Onshape setup

1. Keep the bridge running. Open <https://127.51.68.120:8181> in your Onshape browser profile and accept the self-signed certificate for that local address. Move the cap and look for motion values on the page.
2. Install a userscript manager in that browser profile and enable the [Onshape Linux userscript recommended by spacenav-ws](https://github.com/RmStorm/spacenav-ws#usage). It allows Onshape to look for the local bridge on Linux.
3. Open or reload an Onshape Part Studio or Assembly. If the browser requests local or loopback access, allow it for Onshape. Click in the viewport and move the cap. [Chrome site permissions](https://support.google.com/chrome/answer/114662)

For everyday use, open Onshape in your browser or run `spacemouse onshape`. The background bridge listens on this computer only and restarts automatically if it exits. Use `spacemouse serve --no-browser` to start it without opening a tab.

To check the bridge service or temporarily stop it, run `systemctl --user status spacemouse-bridge.service` or `systemctl --user stop spacemouse-bridge.service`. To turn automatic startup off or back on, use `systemctl --user disable --now spacemouse-bridge.service` or `systemctl --user enable --now spacemouse-bridge.service`. Running the installer enables it again.

To start the bridge before sign-in and keep it running after sign-out, run `loginctl enable-linger "$USER"`. This applies to all enabled user services for your account. [systemd user lingering](https://www.freedesktop.org/software/systemd/man/latest/loginctl.html#enable-linger%20%5BUSER%E2%80%A6%5D)

## Device and app compatibility

| App | How it gets input | Setup |
| --- | --- | --- |
| Onshape | Local bridge fed by `spacenavd` | Follow [Onshape setup](#onshape-setup). |
| Layerling | Direct browser input | In Chrome or Edge, open a design and choose **Workspace settings → Controls → Connect 3D mouse**. Layerling can also pick up devices the browser recognises as game controllers. [Layerling guide](https://layerling.com/guide/view-and-workplane.html) |
| Tinkercad | Community Chrome extension using the Gamepad API | Enable [SpaceMouse in TinkerCAD](https://chromewebstore.google.com/detail/spacemouse-in-tinkercad/nhaenepgppfpehodifndkalcidjhkpjo) and move the cap in an open design. Support depends on Chrome recognising the device. |

SpaceMouse Compact and Wireless, SpaceMouse Pro and Pro Wireless, SpacePilot, SpacePilot Pro, and SpaceNavigator have dedicated Onshape profiles. The SpaceMouse Classic and Plus profile uses numeric button IDs. Other compatible six-axis devices use the generic profile. [FreeSpacenav device support](https://spacenav.sourceforge.net/)

Release validation covered device detection on CachyOS with a SpacePilot Pro, a public Onshape document in Chromium, and simulated motion and button input. The SpaceMouse Pro profile was tested with simulated input. Layerling's device control and Linux access to the SpacePilot Pro were checked. Physical navigation in Layerling and Tinkercad remains unverified.

## Motion tuning

```sh
spacemouse tune
spacemouse tune --translation 0.75 --rotation 1.2 --dead-zone 4
spacemouse tune --invert-rotation y
spacemouse tune --save
```

`tune` shows the current settings. A multiplier of 1 is normal. Raise the dead zone slightly if the view drifts when you let go of the cap. Changes apply immediately to all apps using `spacenavd`. Use `--save` to keep them across restarts, or `--restore` to reload the saved settings. Use each direct-input app's own controls for Layerling or Tinkercad.

For Onshape, open **SpaceMouse Settings**, select your model, and clear **Use bridge default** to adjust **Overall speed**. Choose a multiplier from `0.25` to `4`. The panel saves each profile's speed and the bridge picks it up while you work. **Use bridge default** restores the default speed for that profile.

The bridge default is `1` unless you set `SPACEMOUSE_ONSHAPE_SENSITIVITY` in a systemd user-service drop-in. Run `systemctl --user edit spacemouse-bridge.service` to set it.

```ini
[Service]
Environment=SPACEMOUSE_ONSHAPE_SENSITIVITY=0.5
```

Run `systemctl --user restart spacemouse-bridge.service` to apply it to new Onshape connections.

## Onshape button mappings

Open **Application Launcher → System → SpaceMouse Settings** in KDE Plasma, or run `spacemouse settings`. Select a device profile and choose an action for each button. The app starts on the detected profile when available. You can edit any profile with the device unplugged, show numeric button IDs, and select **Default** to reset an assignment. Changes save automatically and take effect on the next button press.

Fit, labelled view buttons, and rotation lock have default actions on the Pro models. The SpacePilot Pro also has defaults for roll, pan/zoom lock, dominant axis, and speed. Mapped buttons run once per press in the focused Onshape viewport.

```sh
spacemouse buttons
spacemouse buttons watch
spacemouse buttons actions
spacemouse buttons set key-1 isometric
spacemouse buttons set key-2 none
spacemouse buttons default key-1
```

`watch` shows a button's label and ID when you press it. Use either in `set` or `default`. If you already remap buttons in `/etc/spnavrc`, use the IDs printed by `watch`. To edit a profile with the device unplugged, specify its model before the subcommand.

```sh
spacemouse buttons --model spacemouse-pro set key-1 fit
spacemouse buttons --model spacepilot-pro list
```

The app saves button assignments in `~/.config/spacemouse/buttons.json` and overall speeds in `speeds.json` in the same directory, or under your configured `XDG_CONFIG_HOME`. The speed and navigation lock buttons adjust the current Onshape viewport session. Layerling and the Tinkercad extension handle their own buttons.

## SpacePilot Pro LCD

Choose **Start LCD** from the UFO tray icon to stream to the SpacePilot Pro's built-in LCD. With an Onshape viewport focused, the LCD shows the live speed, pan and zoom lock, rotation lock, dominant-axis mode, and a brief confirmation when you trigger a mapped action. When the viewport loses focus or closes, the dashboard shows the clock, saved speed, and the first four key assignments. For terminal use, `spacemouse display` streams in the foreground and `spacemouse display --once` refreshes the LCD once.

Open **LCD Snapshots…** from the tray or **SpaceMouse Settings → LCD…** to pin a CAD view.

- **Capture region…** opens KDE Spectacle so you can select the viewport in Onshape or FreeCAD.
- **Pin image…** opens a local PNG or JPEG, such as an exported FreeCAD render or a saved screenshot.
- **Clear snapshot** returns the screen to the live controls or dashboard.

The snapshot fits the LCD while keeping its proportions. It stays pinned across sessions and shows a compact controls caption while you work in Onshape.

Use **Show Plasma notifications on LCD** in the tray to briefly display the app name and summary of incoming notifications. The tray remembers this setting. The display then returns to the current CAD view or dashboard. For a foreground stream with notifications, run `spacemouse display --notifications`.

If Linux denies LCD access, add this rule to `/etc/udev/rules.d/70-akita-spacepilot-pro-lcd.rules`, run `sudo udevadm control --reload-rules`, and reconnect the device.

```udev
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="046d", ATTR{idProduct}=="c629", TAG+="uaccess"
```

The display uses the LCD interface documented by [3dxdisp-pro](https://github.com/MiguelDLM/3dxdisp-pro) and [libg19](https://github.com/jgeboski/libg19). `spacenavd` continues to handle motion and buttons.

## System tray

The UFO icon appears in KDE Plasma's system tray when you sign in. Its green dot means the Onshape bridge service is active. Amber means it needs attention. Use the tray menu for **Open SpaceMouse Settings**, **LCD Snapshots…**, and **Start LCD** or **Stop LCD**. Run `spacemouse tray` to bring back the icon after quitting it.

## Troubleshooting

| What you see | What to check |
| --- | --- |
| `doctor` cannot reach the driver | Run `systemctl status spacenavd.service` and `journalctl -u spacenavd.service -b`. Use `./spacemouse install` from the release folder to finish setup. |
| `doctor` says the bridge is stopped | Run `systemctl --user status spacemouse-bridge.service` and `journalctl --user -u spacemouse-bridge.service -b`. Use `systemctl --user start spacemouse-bridge.service` to start it. |
| The driver is running and the device is missing | Reconnect the USB cable or receiver and run `spacemouse doctor` again. Older serial models need a port set in [`/etc/spnavrc`](https://github.com/FreeSpacenav/spacenavd/blob/v1.4/doc/example-spnavrc). |
| The device is detected and Onshape is still | Run `spacemouse test` and move the cap. If events appear, visit the local test page, check the certificate exception and userscript in the same browser profile, and reload the Onshape document. |
| You want Akita to look at a problem | Run `spacemouse support`, then `spacemouse support bundle`, and email the archive. |
| The Tinkercad extension sees the device and receives no motion | `spacenavd` may have grabbed the device. To share input with the browser, set `grab = false` in `/etc/spnavrc` and run `sudo systemctl restart spacenavd`. [Driver configuration](https://github.com/FreeSpacenav/spacenavd/blob/v1.4/doc/example-spnavrc) |

If you report a problem, include the launcher version, Linux distribution, device model, and browser version. Include the relevant output from `spacemouse doctor` and whether `spacemouse test` showed input. [GitHub issues](https://github.com/AkitaEngineering/Akita-SpaceMouse-Linux/issues)

## Update or uninstall

To update, download and extract the new release, then run `./spacemouse install` from that folder. The installer restarts the background bridge to load the update. If you started the bridge in a terminal with an older version, stop it with Ctrl+C before updating.

Uninstall stops and removes the tray, LCD stream, and background bridge.

```sh
spacemouse uninstall --dry-run
spacemouse uninstall
```

Uninstall removes the settings app, its menu entry, the user launcher, and the isolated bridge. It keeps your profiles, `/etc/spnavrc`, the distro driver, and shared packages. Add `--purge` to remove saved button profiles and motion speeds. Add `--restore-driver` to remove an upstream daemon installed by this project and return to the distro service.

## Paid setup, fleet deployment, and support

Akita Engineering sells remote setup, fleet deployment, and support. The Community Edition stays free, including the right to install it on every compatible machine. The fee pays for Akita's work. The [price list](COMMERCIAL.md) states what each service includes, how tax is handled, and how to ask for a quote.

Prices exclude tax. Use the column for the billing customer's country. Other countries are quoted on request.

| Service | United States | Canada | European Union |
| --- | ---: | ---: | ---: |
| Remote setup for one workstation, up to 45 minutes. ASM-SET-1-US, ASM-SET-1-CA, ASM-SET-1-EU | US$109 | C$149 | €99 |
| On-demand troubleshooting, per hour. ASM-SUP-H-US, ASM-SUP-H-CA, ASM-SUP-H-EU | US$149 | C$169 | €119 |
| Fleet pilot, up to five workstations on one Linux and browser configuration. ASM-FLT-5-US, ASM-FLT-5-CA, ASM-FLT-5-EU | US$499 | C$649 | €449 |
| Assisted rollout after a successful pilot, per additional matching workstation. ASM-ROL-1-US, ASM-ROL-1-CA, ASM-ROL-1-EU | US$39 | C$49 | €39 |
| Monthly team support, up to ten covered workstations and one pooled hour. ASM-SUB-10-US, ASM-SUB-10-CA, ASM-SUB-10-EU | US$149 | C$199 | €139 |

[Email Akita Engineering](mailto:info@akitaengineering.com?subject=Akita%20SpaceMouse%20services) with the billing country, Linux distributions, browser, device models, and workstation count. The software model is ASM-LNX-CE. [Sales sheet](SALES.md) · [Service terms](SERVICE-TERMS.md)

## Service agreements and support logs

A service agreement covers paid work. It is not a licence key. Install the file Akita sends, then build a bundle when you want help. The bundle stays on this computer until you email it.

```sh
spacemouse agreement install agreement.json
spacemouse agreement
spacemouse support
spacemouse support bundle
```

`support` shows whether this machine can read the driver journal, the local log, and the crash list. Akita checks covered workstations and included time when the bundle is accepted. [Support guide](SUPPORT.md)

## License

Copyright © 2026 Akita Engineering. The Community Edition is licensed under the GNU General Public License version 3.0 only (GPL-3.0-only). [Full license text](LICENSE)

## Development and credits

Run the checks from the repository root.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install spacenav-ws
bash -n spacemouse
bash -n install.sh
.venv/bin/python -m unittest discover -s tests -v
```

Akita SpaceMouse uses [FreeSpacenav](https://github.com/FreeSpacenav/spacenavd) for device support and [spacenav-ws](https://github.com/RmStorm/spacenav-ws) for the Onshape protocol. The Pro button layouts use the [Blender HID button order](https://github.com/blender/blender/blob/main/intern/ghost/intern/GHOST_NDOFManager.cc) and [FreeSpacenav's logical button order](https://github.com/FreeSpacenav/spacenavd/blob/v1.4/src/dev.c). SpaceMouse, SpacePilot, and SpaceNavigator are 3Dconnexion product names.
