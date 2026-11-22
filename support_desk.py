# SPDX-License-Identifier: GPL-3.0-only
"""Accept a support bundle and enforce the service agreement.

Seat and time limits apply to paid support. They do not stop the software.
The ledger on this Akita account is the enforcement record. Use one desk.
"""

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile

from agreement import AgreementError, canonical, require_valid
from catalog import hourly_sku
from diagnostics import ALLOWED_BUNDLE_FILES


class DeskError(Exception):
    pass


def ledger_path() -> Path:
    override = os.environ.get("AKITA_DESK_LEDGER")
    if override:
        return Path(override)
    root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return root / "spacemouse-desk" / "ledger.json"


def cases_dir() -> Path:
    return ledger_path().parent / "cases"


def empty_ledger() -> dict:
    return {"agreements": {}, "bundles": {}, "cases": {}, "case_seq": 0}


def load_ledger(path: Path) -> dict:
    if not path.is_file():
        return empty_ledger()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DeskError(f"Could not read the desk ledger ({error}).") from error
    if not isinstance(data, dict):
        raise DeskError("The desk ledger is not valid.")
    data.setdefault("agreements", {})
    data.setdefault("bundles", {})
    data.setdefault("cases", {})
    data.setdefault("case_seq", 0)
    return data


def save_ledger(path: Path, ledger: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def read_bundle(path: Path) -> dict[str, bytes]:
    try:
        if not path.is_file() or path.stat().st_size > 8_000_000:
            raise DeskError("Choose a support bundle up to 8 MB.")
    except OSError as error:
        raise DeskError(f"Could not read the bundle ({error}).") from error
    files: dict[str, bytes] = {}
    total = 0
    try:
        archive = tarfile.open(path, "r:gz")
    except (OSError, tarfile.TarError) as error:
        raise DeskError(f"Could not open the bundle ({error}).") from error
    with archive:
        for member in archive.getmembers():
            name = member.name
            if name not in ALLOWED_BUNDLE_FILES or not member.isfile() or "/" in name:
                raise DeskError(f"Bundle member {name} is not part of a support bundle.")
            if name in files:
                raise DeskError(f"Bundle member {name} is repeated.")
            total += member.size
            if member.size > 2_000_000 or total > 8_000_000:
                raise DeskError("Bundle contents are larger than 8 MB.")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise DeskError(f"Bundle member {name} could not be read.")
            files[name] = extracted.read()
    if "machine.json" not in files:
        raise DeskError("Bundle is missing machine.json.")
    return files


def outcome_code(outcome: str) -> int:
    return {"covered": 0, "refused": 1, "community": 3}[outcome]


def accept_bundle(path: Path, ledger_file: Path | None = None, today: date | None = None) -> tuple[int, str]:
    ledger_file = ledger_file or ledger_path()
    today = today or datetime.now(timezone.utc).date()
    try:
        if not path.is_file() or path.stat().st_size > 8_000_000:
            raise DeskError("Choose a support bundle up to 8 MB.")
        bundle_bytes = path.read_bytes()
    except OSError as error:
        raise DeskError(f"Could not read the bundle ({error}).") from error
    digest = hashlib.sha256(bundle_bytes).hexdigest()
    ledger = load_ledger(ledger_file)
    existing = ledger["bundles"].get(digest)
    if existing:
        case = ledger["cases"][existing]
        return outcome_code(case["outcome"]), f"Already recorded as {existing}.\n{case['summary']}"

    files = read_bundle(path)
    try:
        identity = json.loads(files["machine.json"].decode())
        machine_id = str(identity.get("machine_id") or "")
        hostname = str(identity.get("hostname") or "")
    except (UnicodeError, json.JSONDecodeError, AttributeError) as error:
        raise DeskError(f"machine.json is not valid ({error}).") from error

    outcome = "community"
    summary = "No service agreement in the bundle. The logs are saved and the time is not covered.\n"
    agreement_id = ""
    payload = None
    if "agreement.json" in files:
        try:
            document = json.loads(files["agreement.json"].decode())
            payload = require_valid(document if isinstance(document, dict) else {})
        except (UnicodeError, json.JSONDecodeError, AgreementError) as error:
            outcome = "refused"
            summary = f"The service agreement signature is not valid. {error}\n"
            payload = None
        if payload is not None:
            agreement_id = payload["agreement_id"]
            starts = date.fromisoformat(payload["starts"])
            ends = date.fromisoformat(payload["ends"])
            record = ledger["agreements"].get(agreement_id)
            payload_hash = hashlib.sha256(canonical(payload)).hexdigest()
            if record and record["payload_sha256"] != payload_hash:
                outcome = "refused"
                summary = f"Agreement {agreement_id} was presented with different terms.\n"
            elif today < starts or today > ends:
                outcome = "refused"
                summary = f"Agreement {agreement_id} covers {payload['starts']} through {payload['ends']}.\n"
            else:
                if record is None:
                    record = {
                        "payload_sha256": payload_hash,
                        "customer": payload["customer"],
                        "region": payload["region"],
                        "seats": payload["seats"],
                        "time_capped": payload["time_capped"],
                        "remaining_minutes": payload["minutes"],
                        "used_minutes": 0,
                        "machines": {},
                    }
                    ledger["agreements"][agreement_id] = record
                machines = record["machines"]
                if payload["seats"] is not None and machine_id in ("", "unavailable"):
                    outcome = "refused"
                    summary = f"Agreement {agreement_id} has a workstation cap and this bundle has no machine id.\n"
                elif payload["seats"] is not None and machine_id not in machines and len(machines) >= payload["seats"]:
                    outcome = "refused"
                    summary = (
                        f"Agreement {agreement_id} covers {payload['seats']} workstations. "
                        "This machine is not one of them.\n"
                    )
                elif payload["time_capped"] and record["remaining_minutes"] <= 0:
                    extra = hourly_sku(payload["region"])
                    outcome = "refused"
                    summary = (
                        f"Included time on {agreement_id} is used. "
                        f"Further time uses {extra.code} at {extra.price} per hour.\n"
                    )
                else:
                    outcome = "covered"
                    if machine_id not in machines:
                        machines[machine_id] = {"hostname": hostname, "first_seen": today.isoformat()}
                    used = len(machines)
                    seat_text = f"{used} of {payload['seats']}" if payload["seats"] is not None else f"{used}, with no workstation cap"
                    time_text = (
                        f"{record['remaining_minutes']} minutes left"
                        if payload["time_capped"] else "included time is not capped"
                    )
                    summary = (
                        f"Agreement {agreement_id} for {payload['customer']}. "
                        f"Workstations {seat_text}. {time_text.capitalize()}.\n"
                    )

    ledger["case_seq"] += 1
    case_id = f"CASE-{ledger['case_seq']:06d}"
    case_directory = ledger_file.parent / "cases" / case_id
    case_directory.mkdir(parents=True, exist_ok=True)
    case_directory.chmod(0o700)
    for name, data in files.items():
        target = case_directory / name
        target.write_bytes(data)
        target.chmod(0o600)
    headline = {"covered": "Covered.", "refused": "Refused.", "community": "Community bundle."}[outcome]
    message = (
        f"{headline}\n{summary}"
        f"Recorded as {case_id}.\nLogs: {case_directory}\n"
        "The Community Edition on that workstation still runs.\n"
    )
    ledger["cases"][case_id] = {
        "outcome": outcome,
        "agreement_id": agreement_id,
        "machine_id": machine_id,
        "summary": summary,
        "opened": today.isoformat(),
        "state": "open" if outcome == "covered" else "closed",
        "minutes": 0,
    }
    ledger["bundles"][digest] = case_id
    save_ledger(ledger_file, ledger)
    return outcome_code(outcome), message


def close_case(case_id: str, minutes: int, ledger_file: Path | None = None) -> str:
    if minutes < 1 or minutes > 10000:
        raise DeskError("Record from 1 to 10000 minutes.")
    ledger_file = ledger_file or ledger_path()
    ledger = load_ledger(ledger_file)
    case = ledger["cases"].get(case_id)
    if case is None:
        raise DeskError(f"No case {case_id}.")
    if case["state"] != "open":
        raise DeskError(f"{case_id} is already closed.")
    record = ledger["agreements"][case["agreement_id"]]
    if record["time_capped"] and minutes > record["remaining_minutes"]:
        raise DeskError(
            f"{record['remaining_minutes']} minutes remain on {case['agreement_id']}. "
            "Close the case with that many minutes, then sell an hourly SKU for the rest."
        )
    if record["time_capped"]:
        record["remaining_minutes"] -= minutes
    record["used_minutes"] += minutes
    case["minutes"] = minutes
    case["state"] = "closed"
    save_ledger(ledger_file, ledger)
    left = f" {record['remaining_minutes']} minutes remain." if record["time_capped"] else ""
    return f"Closed {case_id} at {minutes} minutes.{left}\n"


def cases_text(ledger_file: Path | None = None) -> str:
    ledger = load_ledger(ledger_file or ledger_path())
    if not ledger["cases"]:
        return f"No support cases.\nLedger: {ledger_file or ledger_path()}\n"
    lines = []
    for case_id, case in ledger["cases"].items():
        lines.append(
            f"{case_id}  {case['outcome']}  {case['state']}  {case['agreement_id'] or 'community'}  "
            f"{case['minutes']} min  {case['machine_id']}"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spacemouse desk", allow_abbrev=False)
    parser.description = "Record support cases and enforce workstation and time limits for paid agreements."
    commands = parser.add_subparsers(dest="command")
    accept = commands.add_parser("accept", help="check a customer bundle and save its logs")
    accept.add_argument("bundle")
    commands.add_parser("cases", help="list recorded cases")
    commands.add_parser("path", help="show the ledger used for enforcement")
    close = commands.add_parser("close", help="record time and close a covered case")
    close.add_argument("case_id")
    close.add_argument("--minutes", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "path":
            print(ledger_path())
            return 0
        if args.command == "accept":
            code, message = accept_bundle(Path(args.bundle))
            print(message, end="")
            return code
        if args.command == "close":
            print(close_case(args.case_id, args.minutes), end="")
            return 0
        print(cases_text(), end="")
        return 0
    except (DeskError, AgreementError, OSError, KeyError) as error:
        print(f"Akita SpaceMouse: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
