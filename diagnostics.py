# SPDX-License-Identifier: GPL-3.0-only
"""Local logs and the support bundle a customer chooses to send.

Nothing in this module uploads data. Core dump files stay on the workstation.
The bundle lists matching crashes and copies the driver journal when it is readable.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tarfile
from io import BytesIO

from agreement import agreement_path, status_text
from catalog import SOFTWARE_MODEL


ALLOWED_BUNDLE_FILES = frozenset({
    "manifest.json", "access.txt", "agreement.json", "agreement-status.txt",
    "doctor.txt", "os-release.txt", "uname.txt", "version.txt", "machine.json",
    "spacemouse.log", "crash.log", "journal-spacenavd.txt", "coredumps.txt",
    "spnavrc.txt", "buttons.json",
})
CORE_MARKERS = ("spacenavd", "spacemouse", "onshape_bridge")


def state_dir() -> Path:
    root = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    return root / "spacemouse"


def log_file() -> Path:
    return state_dir() / "spacemouse.log"


def crash_file() -> Path:
    return state_dir() / "crash.log"


def app_dir() -> Path:
    return Path(__file__).resolve().parent


def log_event(message: str) -> None:
    try:
        path = log_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > 262144:
            path.write_bytes(path.read_bytes()[-131072:])
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {message.rstrip()}\n")
    except OSError:
        return


def machine_identity() -> dict:
    machine_id = "unavailable"
    try:
        text = Path("/etc/machine-id").read_text(encoding="utf-8").strip()
        if text:
            machine_id = text
    except OSError:
        pass
    return {"machine_id": machine_id, "hostname": socket.gethostname(), "model": SOFTWARE_MODEL}


def _run(command: list[str], timeout: int = 8) -> tuple[str, str]:
    if shutil.which(command[0]) is None:
        return f"{command[0]} is not installed.\n", "unavailable"
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"{command[0]} did not finish ({error}).\n", "unavailable"
    text = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0 and not result.stdout:
        return text or f"{command[0]} exited {result.returncode}.\n", "unavailable"
    return text, "ok"


def journal_text() -> tuple[str, str]:
    return _run(["journalctl", "-u", "spacenavd.service", "-n", "400", "--no-pager", "-o", "short-iso"])


def coredump_text() -> tuple[str, str]:
    text, status = _run(["coredumpctl", "list", "--no-pager", "--no-legend"])
    if status != "ok":
        return text, status
    matched = [line for line in text.splitlines() if any(marker in line.lower() for marker in CORE_MARKERS)]
    if not matched:
        return "No core dumps for spacenavd, spacemouse, or the Onshape bridge.\n", "none"
    return "\n".join(matched) + "\n", "ok"


def read_os_release() -> str:
    wanted = {"ID", "ID_LIKE", "NAME", "VERSION", "VERSION_ID", "PRETTY_NAME"}
    try:
        lines = Path("/etc/os-release").read_text(encoding="utf-8").splitlines()
    except OSError as error:
        return f"os-release is not readable ({error}).\n"
    kept = [line for line in lines if line.split("=", 1)[0] in wanted]
    return ("\n".join(kept) + "\n") if kept else "os-release had no distribution fields.\n"


def doctor_text() -> tuple[str, str]:
    text, status = _run([str(app_dir() / "spacemouse"), "doctor"], timeout=10)
    return text, status


def access_report() -> str:
    identity = machine_identity()
    journal, journal_status = journal_text()
    cores, core_status = coredump_text()
    local = log_file()
    crash = crash_file()
    journal_words = {"ok": "readable", "none": "empty", "unavailable": "not readable"}[journal_status]
    core_words = {"ok": "listed", "none": "none for this software", "unavailable": "not readable"}[core_status]
    lines = [
        f"Software model: {SOFTWARE_MODEL}",
        "The Community Edition does not send logs anywhere.",
        f"Local log: {local} ({'present' if local.is_file() else 'absent'})",
        f"Crash log: {crash} ({'present' if crash.is_file() else 'absent'})",
        f"spacenavd journal: {journal_words}" + (f", {len(journal.splitlines())} lines" if journal_status == "ok" else ""),
        f"Core dumps for this software: {core_words}",
        f"Machine id: {identity['machine_id']}",
        status_text().rstrip(),
        "Run spacemouse support bundle to write an archive. It stays on this computer until you email it.",
        "The archive lists matching core dumps. It does not copy the core files.",
    ]
    return "\n".join(lines) + "\n"


def _optional_file(path: Path, missing: str) -> tuple[bytes, str]:
    try:
        if path.is_file():
            return path.read_bytes(), "ok"
    except OSError as error:
        return f"{path} is not readable ({error}).\n".encode(), "unavailable"
    return missing.encode(), "absent"


def build_bundle(destination: Path | None = None) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = destination or state_dir() / "bundles" / f"support-{stamp}.tar.gz"
    version = (app_dir() / "VERSION").read_text(encoding="utf-8").strip()
    uname = os.uname()
    files: dict[str, tuple[bytes, str]] = {
        "version.txt": (f"{version}\n{SOFTWARE_MODEL}\n".encode(), "ok"),
        "uname.txt": (f"{uname.sysname} {uname.release} {uname.machine}\n".encode(), "ok"),
        "os-release.txt": (read_os_release().encode(), "ok"),
        "machine.json": (json.dumps(machine_identity(), indent=2).encode() + b"\n", "ok"),
        "agreement-status.txt": (status_text().encode(), "ok"),
        "access.txt": (b"", "ok"),
    }
    journal, journal_status = journal_text()
    cores, core_status = coredump_text()
    doctor, doctor_status = doctor_text()
    files["journal-spacenavd.txt"] = (journal.encode(), journal_status)
    files["coredumps.txt"] = (cores.encode(), core_status)
    files["doctor.txt"] = (doctor.encode(), doctor_status)
    missing = []
    for name, path in (
        ("spacemouse.log", log_file()),
        ("crash.log", crash_file()),
        ("spnavrc.txt", Path("/etc/spnavrc")),
        ("buttons.json", Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "spacemouse" / "buttons.json"),
        ("agreement.json", agreement_path()),
    ):
        data, status = _optional_file(path, "")
        if status == "ok":
            files[name] = (data, status)
        else:
            missing.append(name)
    manifest = {
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": SOFTWARE_MODEL,
        "version": version,
        "files": {name: {"bytes": len(data), "status": status} for name, (data, status) in files.items() if name != "access.txt"},
        "missing": missing,
        "note": "Akita receives this archive only when you send it. Core dump files are not included.",
    }
    files["manifest.json"] = (json.dumps(manifest, indent=2).encode() + b"\n", "ok")
    files["access.txt"] = (access_report().encode(), "ok")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, "w:gz") as archive:
        for name, (data, _status) in files.items():
            if name not in ALLOWED_BUNDLE_FILES:
                raise RuntimeError(f"Refusing to pack {name}.")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o600
            archive.addfile(info, BytesIO(data))
    destination.chmod(0o600)
    return destination


def bundle_summary(path: Path) -> str:
    with tarfile.open(path, "r:gz") as archive:
        names = archive.getnames()
    lines = [
        f"Wrote {path}",
        "This archive stays on this computer. Email it to info@akitaengineering.com to ask Akita for help.",
        "It contains the driver journal excerpt, the local log, the crash log, and a list of matching core dumps.",
        "It does not contain core dump files, browser passwords, or page contents.",
        "Files: " + ", ".join(names),
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "log":
        log_event(" ".join(argv[1:]))
        return 0
    parser = argparse.ArgumentParser(prog="spacemouse support", allow_abbrev=False)
    parser.description = "Show which logs this machine can read, or write a support bundle you can email."
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("access", help="show journal, crash, and agreement access")
    bundle = commands.add_parser("bundle", help="write a support archive on this computer")
    bundle.add_argument("--output")
    args = parser.parse_args(argv)
    if args.command == "bundle":
        path = build_bundle(Path(args.output) if args.output else None)
        print(bundle_summary(path), end="")
        return 0
    print(access_report(), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
