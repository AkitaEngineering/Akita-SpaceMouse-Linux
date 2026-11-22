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

The installer enables `spacenavd`, downloads the latest stable upstream driver when the distro package is older, and checks the source archive against its published SHA-256 digest. It installs the Onshape bridge in an isolated Python environment for your user account. Your driver configuration lives in `/etc/spnavrc`.

### Verify the download

Download `SHA256SUMS` alongside the archive. Open a terminal in the download folder and run `sha256sum -c SHA256SUMS`. The archive should report `OK`.

## Onshape setup

1. Keep the bridge running. Open <https://127.51.68.120:8181> in your Onshape browser profile and accept the self-signed certificate for that local address. Move the cap and look for motion values on the page.
2. Install a userscript manager in that browser profile and enable the [Onshape Linux userscript recommended by spacenav-ws](https://github.com/RmStorm/spacenav-ws#usage). It allows Onshape to look for the local bridge on Linux.
3. Open or reload an Onshape Part Studio or Assembly. If the browser requests local or loopback access, allow it for Onshape. Click in the viewport and move the cap. [Chrome site permissions](https://support.google.com/chrome/answer/114662)

For everyday use, `spacemouse onshape` starts the bridge if needed and opens Onshape. The bridge listens on this computer only. Leave its terminal open while you work and press Ctrl+C in that terminal to stop it. Use `spacemouse serve --no-browser` to start it without opening a tab.

## Device and app compatibility

| App | How it gets input | Setup |
| --- | --- | --- |
| Onshape | Local bridge fed by `spacenavd` | Follow [Onshape setup](#onshape-setup). |
| Layerling | Direct browser input | In Chrome or Edge, open a design and choose **Workspace settings → Controls → Connect 3D mouse**. Layerling can also pick up devices the browser recognises as game controllers. [Layerling guide](https://layerling.com/guide/view-and-workplane.html) |
| Tinkercad | Community Chrome extension using the Gamepad API | Enable [SpaceMouse in TinkerCAD](https://chromewebstore.google.com/detail/spacemouse-in-tinkercad/nhaenepgppfpehodifndkalcidjhkpjo) and move the cap in an open design. Support depends on Chrome recognising the device. |

The SpacePilot Pro and SpaceMouse Pro have dedicated Onshape maps. The SpaceMouse Pro profile covers wired and recognised wireless variants. Other compatible six-axis devices use the generic profile. [FreeSpacenav device support](https://spacenav.sourceforge.net/)

Release validation covered device detection on CachyOS with a SpacePilot Pro, a public Onshape document in Chromium, and simulated motion and button input. The SpaceMouse Pro profile was tested with simulated input. Layerling's device control and Linux access to the SpacePilot Pro were checked. Physical navigation in Layerling and Tinkercad remains unverified.

## Motion tuning

```sh
spacemouse tune
spacemouse tune --translation 0.75 --rotation 1.2 --dead-zone 4
spacemouse tune --invert-rotation y
spacemouse tune --save
```

`tune` shows the current settings. A multiplier of 1 is normal. Raise the dead zone slightly if the view drifts when you let go of the cap. Changes apply immediately to all apps using `spacenavd`. Use `--save` to keep them across restarts, or `--restore` to reload the saved settings. Use each direct-input app's own controls for Layerling or Tinkercad.

## Onshape button mappings

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

Assignments take effect on the next press and are saved in `~/.config/spacemouse/buttons.json`, or under your configured `XDG_CONFIG_HOME`. Navigation locks and speed changes apply to the current Onshape viewport session. Layerling and the Tinkercad extension handle their own buttons.

## Troubleshooting

| What you see | What to check |
| --- | --- |
| `doctor` cannot reach the driver | Run `systemctl status spacenavd.service` and `journalctl -u spacenavd.service -b`. Use `./spacemouse install` from the release folder to finish setup. |
| The driver is running and the device is missing | Reconnect the USB cable or receiver and run `spacemouse doctor` again. Older serial models need a port set in [`/etc/spnavrc`](https://github.com/FreeSpacenav/spacenavd/blob/v1.4/doc/example-spnavrc). |
| The device is detected and Onshape is still | Run `spacemouse test` and move the cap. If events appear, visit the local test page, check the certificate exception and userscript in the same browser profile, and reload the Onshape document. |
| You want Akita to look at a problem | Run `spacemouse support`, then `spacemouse support bundle`, and email the archive. |
| The Tinkercad extension sees the device and receives no motion | `spacenavd` may have grabbed the device. To share input with the browser, set `grab = false` in `/etc/spnavrc` and run `sudo systemctl restart spacenavd`. [Driver configuration](https://github.com/FreeSpacenav/spacenavd/blob/v1.4/doc/example-spnavrc) |

If you report a problem, include the launcher version, Linux distribution, device model, and browser version. Include the relevant output from `spacemouse doctor` and whether `spacemouse test` showed input. [GitHub issues](https://github.com/AkitaEngineering/Akita-SpaceMouse-Linux/issues)

## Update or uninstall

To update, download and extract the new release, then run `./spacemouse install` from that folder. Restart the running bridge to load the update.

Close the bridge terminal before uninstalling.

```sh
spacemouse uninstall --dry-run
spacemouse uninstall
```

Uninstall removes the user launcher and isolated bridge. It keeps your profiles, `/etc/spnavrc`, the distro driver, and shared packages. Add `--purge` to remove saved button profiles. Add `--restore-driver` to remove an upstream daemon installed by this project and return to the distro service.

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
