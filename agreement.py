# SPDX-License-Identifier: GPL-3.0-only
"""Sign and check service agreements.

The signature proves Akita issued the agreement. It is checked when Akita
accepts a support bundle. The Community Edition keeps running without one.
"""

import argparse
import base64
import calendar
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from catalog import CAPPED_KINDS, SKUS, SOFTWARE_MODEL, format_money


class AgreementError(Exception):
    pass


def config_dir() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "spacemouse"


def agreement_path() -> Path:
    return config_dir() / "agreement.json"


def key_path() -> Path:
    override = os.environ.get("AKITA_SUPPORT_KEY")
    if override:
        return Path(override)
    return config_dir() / "issuer.key"


def pub_path() -> Path:
    override = os.environ.get("AKITA_SUPPORT_PUB")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "akita-support.pub"


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def openssl(args: list[str]) -> subprocess.CompletedProcess:
    if shutil.which("openssl") is None:
        raise AgreementError("OpenSSL is required to sign or check a service agreement.")
    try:
        return subprocess.run(["openssl", *args], check=True, capture_output=True)
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode(errors="replace").strip()
        raise AgreementError(detail or "OpenSSL could not complete the request.") from error


def export_public(key: Path) -> bytes:
    return openssl(["pkey", "-in", str(key), "-pubout"]).stdout


def create_issuer_key(key: Path, pub_out: Path | None = None) -> bytes:
    if key.exists():
        raise AgreementError(f"The issuer key already exists at {key}. It was not overwritten.")
    key.parent.mkdir(parents=True, exist_ok=True)
    key.parent.chmod(0o700)
    openssl(["genpkey", "-algorithm", "ED25519", "-out", str(key)])
    key.chmod(0o600)
    public = export_public(key)
    if pub_out is not None:
        pub_out.parent.mkdir(parents=True, exist_ok=True)
        pub_out.write_bytes(public)
        pub_out.chmod(0o644)
    return public


def require_matching_key() -> Path:
    key = key_path()
    public = pub_path()
    if not key.is_file():
        raise AgreementError(
            f"The issuer key is not at {key}. Run spacemouse agreement keygen on the Akita machine."
        )
    if not public.is_file():
        raise AgreementError(f"The public key is not at {public}.")
    if export_public(key) != public.read_bytes():
        raise AgreementError(
            "The issuer key does not match the public key shipped with Akita SpaceMouse. "
            "Agreements signed with it would fail on customer machines."
        )
    return key


def signature_valid(payload: dict, signature: str, public: Path | None = None) -> bool:
    public = public or pub_path()
    if shutil.which("openssl") is None or not public.is_file():
        raise AgreementError("OpenSSL and the Akita public key are required to check a service agreement.")
    try:
        raw = base64.b64decode(signature, validate=True)
    except (TypeError, ValueError):
        return False
    with tempfile.TemporaryDirectory() as directory:
        body = Path(directory) / "body"
        sig = Path(directory) / "body.sig"
        body.write_bytes(canonical(payload))
        sig.write_bytes(raw)
        result = subprocess.run(
            ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(public), "-rawin", "-in", str(body), "-sigfile", str(sig)],
            capture_output=True,
        )
    return result.returncode == 0


def sign_payload(payload: dict, key: Path) -> str:
    with tempfile.TemporaryDirectory() as directory:
        body = Path(directory) / "body"
        body.write_bytes(canonical(payload))
        signature = openssl(["pkeyutl", "-sign", "-inkey", str(key), "-rawin", "-in", str(body)]).stdout
    return base64.b64encode(signature).decode()


def add_month(day: date) -> date:
    year = day.year + (day.month == 12)
    month = 1 if day.month == 12 else day.month + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def default_end(starts: date, sku) -> date:
    if sku.kind == "subscription":
        return add_month(starts) - timedelta(days=1)
    return starts + timedelta(days=sku.default_days - 1)


def parse_line(text: str) -> tuple[str, int]:
    code, separator, quantity = text.partition(":")
    if not separator:
        return code, 1
    if not quantity.isdigit() or quantity.startswith("0") and quantity != "0":
        raise AgreementError(f"Quantity in {text} must be a whole number.")
    return code, int(quantity)


def build_payload(*, agreement_id: str, customer: str, email: str, line_specs: list[tuple[str, int]], starts: date, ends: date | None = None) -> dict:
    customer = customer.strip()
    email = email.strip()
    if not customer or len(customer) > 200:
        raise AgreementError("Enter the customer name, up to 200 characters.")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise AgreementError("Enter the customer email address.")
    if not line_specs:
        raise AgreementError("Add at least one SKU.")
    parsed = []
    for code, quantity in line_specs:
        sku = SKUS.get(code)
        if sku is None:
            raise AgreementError(f"Unknown SKU {code}.")
        if quantity < 1 or quantity > 10000:
            raise AgreementError(f"Quantity for {code} must be from 1 to 10000.")
        parsed.append((sku, quantity))
    region = parsed[0][0].region
    currency = parsed[0][0].currency
    if any(sku.region != region for sku, _quantity in parsed):
        raise AgreementError("Use SKUs from one billing country on an agreement.")

    seats = 0
    seated = False
    minutes = 0
    capped = False
    total = 0
    lines = []
    end_dates = []
    for sku, quantity in parsed:
        line_minutes = sku.minutes * quantity if sku.kind in CAPPED_KINDS else 0
        if sku.kind in CAPPED_KINDS:
            capped = True
            minutes += line_minutes
        if sku.seats is None:
            line_seats = None
        else:
            seated = True
            line_seats = sku.seats * quantity
            seats += line_seats
        line_total = sku.minor * quantity
        total += line_total
        lines.append({
            "sku": sku.code, "name": sku.name, "quantity": quantity,
            "seats": line_seats, "minutes": line_minutes, "minor": line_total,
        })
        end_dates.append(default_end(starts, sku))
    if ends is None:
        ends = max(end_dates)
    if ends < starts:
        raise AgreementError("The end date is before the start date.")
    return {
        "v": 1,
        "agreement_id": agreement_id,
        "product_model": SOFTWARE_MODEL,
        "customer": customer,
        "email": email,
        "region": region,
        "currency": currency,
        "lines": lines,
        "seats": seats if seated else None,
        "minutes": minutes,
        "time_capped": capped and minutes > 0,
        "total_minor": total,
        "starts": starts.isoformat(),
        "ends": ends.isoformat(),
    }


def next_agreement_id(key: Path) -> str:
    sequence = key.with_name("agreement.seq")
    current = int(sequence.read_text()) if sequence.is_file() else 0
    current += 1
    sequence.write_text(f"{current}\n")
    sequence.chmod(0o600)
    return f"ASM-AGR-{current:06d}"


def issue_agreement(*, customer: str, email: str, line_specs: list[tuple[str, int]], starts: date, ends: date | None, destination: Path) -> dict:
    key = require_matching_key()
    payload = build_payload(
        agreement_id=next_agreement_id(key), customer=customer, email=email,
        line_specs=line_specs, starts=starts, ends=ends,
    )
    document = {"payload": payload, "signature": sign_payload(payload, key)}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    destination.chmod(0o644)
    return payload


def load_document(source: Path) -> dict:
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AgreementError(f"Could not read the service agreement ({error}).") from error
    if not isinstance(document, dict) or not isinstance(document.get("payload"), dict):
        raise AgreementError("This file is not a service agreement.")
    return document


def require_payload(payload: dict) -> dict:
    required = (
        "v", "agreement_id", "product_model", "customer", "email", "region", "currency",
        "lines", "seats", "minutes", "time_capped", "total_minor", "starts", "ends",
    )
    if payload.get("v") != 1 or any(key not in payload for key in required):
        raise AgreementError("This service agreement is missing required fields.")
    if payload["product_model"] != SOFTWARE_MODEL:
        raise AgreementError("This service agreement is for a different product.")
    agreement_id = payload["agreement_id"]
    if not (isinstance(agreement_id, str) and len(agreement_id) == 14 and agreement_id.startswith("ASM-AGR-") and agreement_id[8:].isdigit()):
        raise AgreementError("The agreement id is not valid.")
    if not isinstance(payload["lines"], list) or not payload["lines"]:
        raise AgreementError("The agreement has no SKU lines.")
    if payload["seats"] is not None and (not isinstance(payload["seats"], int) or payload["seats"] < 1):
        raise AgreementError("The workstation count is not valid.")
    if not isinstance(payload["minutes"], int) or payload["minutes"] < 0 or not isinstance(payload["time_capped"], bool):
        raise AgreementError("The included time is not valid.")
    try:
        date.fromisoformat(payload["starts"])
        date.fromisoformat(payload["ends"])
    except (TypeError, ValueError) as error:
        raise AgreementError("The agreement dates are not valid.") from error
    return payload


def require_valid(document: dict) -> dict:
    payload = require_payload(document["payload"])
    if not signature_valid(payload, document.get("signature", "")):
        raise AgreementError("The service agreement signature is not valid.")
    return payload


@dataclass(frozen=True)
class AgreementStatus:
    state: str
    payload: dict | None
    detail: str


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def inspect_agreement(source: Path | None = None, today: date | None = None) -> AgreementStatus:
    source = source or agreement_path()
    today = today or utc_today()
    if not source.is_file():
        return AgreementStatus("absent", None, "No service agreement is installed.")
    try:
        payload = require_valid(load_document(source))
    except AgreementError as error:
        return AgreementStatus("invalid", None, str(error))
    starts = date.fromisoformat(payload["starts"])
    ends = date.fromisoformat(payload["ends"])
    if today < starts:
        return AgreementStatus("pending", payload, f"Coverage starts on {payload['starts']}.")
    if today > ends:
        return AgreementStatus("expired", payload, f"Coverage ended on {payload['ends']}.")
    return AgreementStatus("active", payload, f"Covered from {payload['starts']} through {payload['ends']}.")


def status_text(source: Path | None = None, today: date | None = None) -> str:
    found = inspect_agreement(source, today)
    lines = [
        f"Software model: {SOFTWARE_MODEL}",
        "The Community Edition runs with or without a service agreement.",
    ]
    if found.payload is None:
        lines.append(found.detail)
        return "\n".join(lines) + "\n"
    payload = found.payload
    seat_text = "no workstation cap" if payload["seats"] is None else f"{payload['seats']} workstations"
    time_text = f"{payload['minutes']} minutes" if payload["time_capped"] else "not capped"
    lines.extend((
        f"Agreement: {payload['agreement_id']}",
        f"Customer: {payload['customer']}",
        f"Email: {payload['email']}",
        f"Status: {found.state}. {found.detail}",
        f"Workstations: {seat_text}",
        f"Included time: {time_text}",
        f"Price before tax: {format_money(payload['total_minor'], payload['currency'])}",
    ))
    for line in payload["lines"]:
        lines.append(f"SKU: {line['sku']} x{line['quantity']} — {line['name']}")
    if found.state == "active":
        lines.append("Fleet seat use is checked when Akita accepts a support bundle.")
    return "\n".join(lines) + "\n"


def install_agreement(source: Path) -> dict:
    document = load_document(source)
    payload = require_valid(document)
    destination = agreement_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({"payload": payload, "signature": document["signature"]}, indent=2) + "\n", encoding="utf-8")
    destination.chmod(0o644)
    return payload


def parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise AgreementError(f"{text} is not a YYYY-MM-DD date.") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spacemouse agreement", allow_abbrev=False)
    parser.description = "Show, install, or issue a paid service agreement. This does not lock the Community Edition."
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("status", help="show the installed agreement")
    install = commands.add_parser("install", help="install a signed agreement file")
    install.add_argument("file")
    verify = commands.add_parser("verify", help="check a signed agreement file")
    verify.add_argument("file")
    issue = commands.add_parser("issue", help="sign an agreement with the Akita issuer key")
    issue.add_argument("--customer", required=True)
    issue.add_argument("--email", required=True)
    issue.add_argument("--line", action="append", default=[])
    issue.add_argument("--sku")
    issue.add_argument("--quantity", type=int, default=1)
    issue.add_argument("--starts")
    issue.add_argument("--ends")
    issue.add_argument("--out", required=True)
    keygen = commands.add_parser("keygen", help="create the Akita issuer key")
    keygen.add_argument("--pub-out")
    args = parser.parse_args(argv)
    try:
        if args.command in (None, "status"):
            found = inspect_agreement()
            print(status_text(), end="")
            return 0 if found.state != "invalid" else 1
        if args.command == "verify":
            print(status_text(Path(args.file)), end="")
            return 0 if inspect_agreement(Path(args.file)).state != "invalid" else 1
        if args.command == "install":
            payload = install_agreement(Path(args.file))
            print(f"Installed {payload['agreement_id']} for {payload['customer']}.")
            print("The Community Edition runs either way. Akita checks this file when a support bundle is accepted.")
            return 0
        if args.command == "keygen":
            create_issuer_key(key_path(), Path(args.pub_out) if args.pub_out else None)
            print(f"Issuer key: {key_path()}")
            print("Back up that file. Store it offline. A new key needs a software release with the matching public key.")
            if args.pub_out:
                print(f"Public key: {args.pub_out}")
            else:
                print("Pass --pub-out to write the matching public key.")
            return 0
        specs = [parse_line(line) for line in args.line]
        if args.sku:
            specs.append((args.sku, args.quantity))
        starts = parse_date(args.starts) if args.starts else utc_today()
        ends = parse_date(args.ends) if args.ends else None
        payload = issue_agreement(
            customer=args.customer, email=args.email, line_specs=specs,
            starts=starts, ends=ends, destination=Path(args.out),
        )
        seat_text = "no workstation cap" if payload["seats"] is None else f"{payload['seats']} workstations"
        print(f"Wrote {args.out}")
        print(f"Agreement {payload['agreement_id']} for {payload['customer']}.")
        print(f"{seat_text}. Included time {payload['minutes']} minutes. {payload['starts']} through {payload['ends']}.")
        print(f"Price before tax: {format_money(payload['total_minor'], payload['currency'])}.")
        print("Send this file to the customer. They install it with spacemouse agreement install.")
        return 0
    except AgreementError as error:
        print(f"Akita SpaceMouse: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
