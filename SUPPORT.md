# Support guide

Akita can see logs only after someone on the workstation creates a bundle and sends it. The Community Edition does not phone home. There is no always-on crash collector.

## What this machine can read

```sh
spacemouse support
```

That command reports:

- the local launcher log, `~/.local/state/spacemouse/spacemouse.log`
- the bridge crash log, `~/.local/state/spacemouse/crash.log`
- whether `journalctl -u spacenavd.service` is readable
- whether `coredumpctl` lists a core dump for spacenavd, spacemouse, or the Onshape bridge
- whether a service agreement is installed

The launcher log records bridge start, client connect and disconnect, and a failed connection to spacenavd. The crash log receives a Python fatal-error dump when the bridge process hits a low-level crash. Those files start empty until the bridge has run on that version.

The spacenavd journal is the driver log. On a desktop where the user can read the system journal, the bundle copies the last 400 lines. If journalctl cannot read the unit, the bundle says so.

Core dump files are not copied. They can contain process memory. The bundle only lists matching crashes. If Akita needs the core, ask the customer to confirm and then send that one file:

```sh
coredumpctl info PID
coredumpctl dump PID --output crash.core
```

## Customer steps

```sh
spacemouse agreement install agreement.json
spacemouse support bundle
```

Email the `.tar.gz` to [info@akitaengineering.com](mailto:info@akitaengineering.com). The archive stays on the workstation until the customer sends it. It holds the version, distribution, kernel, hostname, machine id, doctor output, journal excerpt, local logs, button profile, `/etc/spnavrc` when that file exists, and the agreement.

## Akita desk

Use one Akita login as the desk. The enforcement record is `~/.local/share/spacemouse-desk/ledger.json` on that login. A second empty ledger would count the same workstations again. Back up the `spacemouse-desk` directory with the issuer key.

```sh
spacemouse desk path
spacemouse desk accept ~/Downloads/support-20261201T150000Z.tar.gz
spacemouse desk cases
spacemouse desk close CASE-000001 --minutes 25
```

`accept` saves the bundle and prints one of three results:

- **Covered.** The signature is valid, the date is inside the agreement, the machine id fits in the workstation count, and capped time is left. Exit 0.
- **Refused.** The signature, date, workstation count, or included time failed. The logs are still saved. Exit 1. The software on the customer machine keeps running.
- **Community bundle.** There is no agreement in the archive. The logs are saved and the time is not covered. Exit 3.

Closing a covered case records the minutes. When the agreement caps time, the close is refused if it would pass the remaining minutes. Pilot and rollout time is recorded and is not capped. Included monthly and setup time is spent in actual minutes.

The same bundle file is recorded once. Sending it again prints the existing case id.
