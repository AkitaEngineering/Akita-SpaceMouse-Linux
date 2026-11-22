# SPDX-License-Identifier: GPL-3.0-only
import os
from datetime import date
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

from agreement import build_payload, create_issuer_key, export_public, issue_agreement, utc_today
from catalog import CATALOG, SOFTWARE_MODEL, format_money
from diagnostics import build_bundle, bundle_summary, log_event
from support_desk import accept_bundle, close_case


ROOT = Path(__file__).resolve().parents[1]


class CatalogDocumentTest(unittest.TestCase):
    def test_every_sku_is_on_the_sales_documents(self):
        readme = (ROOT / "README.md").read_text()
        commercial = (ROOT / "COMMERCIAL.md").read_text()
        sales = (ROOT / "SALES.md").read_text()
        terms = (ROOT / "SERVICE-TERMS.md").read_text()
        support = (ROOT / "SUPPORT.md").read_text()
        self.assertEqual(len(CATALOG), 15)
        self.assertIn(SOFTWARE_MODEL, readme)
        self.assertIn(SOFTWARE_MODEL, sales)
        self.assertIn(SOFTWARE_MODEL, terms)
        self.assertIn("no licence key", terms)
        self.assertIn("machine id", terms)
        self.assertIn("six years", terms)
        self.assertIn("Ontario", terms)
        self.assertIn("coredumpctl", support)
        self.assertIn("does not phone home", support)
        import hashlib
        self.assertIn(hashlib.sha256((ROOT / "akita-support.pub").read_bytes()).hexdigest(), sales)
        for sku in CATALOG:
            with self.subTest(sku=sku.code):
                for document in (readme, commercial, sales):
                    self.assertIn(sku.code, document)
                    self.assertIn(sku.price, document)
        self.assertEqual(format_money(162900, "CAD"), "C$1,629")

    def test_shipped_public_key_matches_the_issuer_key(self):
        key = Path.home() / ".config/spacemouse/issuer.key"
        if not key.is_file():
            self.skipTest("issuer key is kept on the Akita machine")
        self.assertEqual(export_public(key), (ROOT / "akita-support.pub").read_bytes())


class AgreementDeskTest(unittest.TestCase):
    def setUp(self):
        self.fixture = tempfile.TemporaryDirectory()
        self.addCleanup(self.fixture.cleanup)
        root = Path(self.fixture.name)
        self.key = root / "issuer.key"
        self.public = root / "issuer.pub"
        self.env = {
            **os.environ,
            "HOME": str(root / "home"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_STATE_HOME": str(root / "state"),
            "AKITA_SUPPORT_KEY": str(self.key),
            "AKITA_SUPPORT_PUB": str(self.public),
            "SPACEMOUSE_SECRET_SENTINEL": "sentinel-value-do-not-collect",
        }
        create_issuer_key(self.key, self.public)
        self.ledger = root / "ledger.json"
        self.env["AKITA_DESK_LEDGER"] = str(self.ledger)
        self.previous_env = {name: os.environ.get(name) for name in self.env}
        os.environ.update(self.env)
        self.addCleanup(self.restore_env)

    def restore_env(self):
        for name, value in self.previous_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def issue(self, destination, lines, starts="2026-12-01", ends=None):
        return issue_agreement(
            customer="Northwind CAD", email="it@northwind.example", line_specs=lines,
            starts=date.fromisoformat(starts),
            ends=date.fromisoformat(ends) if ends else None,
            destination=destination,
        )

    def bundle_for(self, agreement, machine_id, name="bundle.tar.gz"):
        identity = f'{{"machine_id": "{machine_id}", "hostname": "cad-{machine_id}"}}\n'.encode()
        path = Path(self.fixture.name) / name
        import io
        import tarfile as tar
        files = {
            "machine.json": identity,
            "manifest.json": b'{"note": "test"}\n',
            "version.txt": b"1.0.3\nASM-LNX-CE\n",
        }
        if agreement is not None:
            files["agreement.json"] = agreement.read_bytes()
        with tar.open(path, "w:gz") as archive:
            for item, data in files.items():
                info = tar.TarInfo(item)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return path

    def test_fleet_order_price_term_and_seat_enforcement(self):
        payload = build_payload(
            agreement_id="ASM-AGR-000001", customer="Northwind CAD", email="it@northwind.example",
            line_specs=[("ASM-FLT-5-CA", 1), ("ASM-ROL-1-CA", 20)], starts=date(2026, 12, 1),
        )
        self.assertEqual(payload["seats"], 25)
        self.assertEqual(payload["total_minor"], 162900)
        self.assertEqual(payload["ends"], "2027-02-28")
        self.assertFalse(payload["time_capped"])
        monthly = build_payload(
            agreement_id="ASM-AGR-000002", customer="Northwind CAD", email="it@northwind.example",
            line_specs=[("ASM-SUB-10-CA", 1)], starts=date(2026, 12, 1),
        )
        self.assertEqual(monthly["ends"], "2026-12-31")
        self.assertEqual(monthly["minutes"], 60)
        self.assertTrue(monthly["time_capped"])

        signed = self.issue(Path(self.fixture.name) / "fleet.json", [("ASM-SET-1-CA", 1)], ends="2026-12-01")
        self.assertEqual(signed["seats"], 1)
        self.assertEqual(signed["minutes"], 45)
        first = self.bundle_for(Path(self.fixture.name) / "fleet.json", "machine-a", "a.tar.gz")
        second = self.bundle_for(Path(self.fixture.name) / "fleet.json", "machine-b", "b.tar.gz")
        code, message = accept_bundle(first, self.ledger, today=date(2026, 12, 1))
        self.assertEqual(code, 0)
        self.assertIn("Covered.", message)
        code, message = accept_bundle(second, self.ledger, today=date(2026, 12, 1))
        self.assertEqual(code, 1)
        self.assertIn("Refused.", message)
        self.assertIn("still runs", message)
        again, replay = accept_bundle(first, self.ledger, today=date(2026, 12, 1))
        self.assertEqual(again, 0)
        self.assertIn("Already recorded", replay)

    def test_expired_and_tampered_agreements_do_not_stop_the_software(self):
        path = Path(self.fixture.name) / "old.json"
        self.issue(path, [("ASM-SUB-10-US", 1)], starts="2020-01-01", ends="2020-01-31")
        code, message = accept_bundle(self.bundle_for(path, "machine-a"), self.ledger, today=utc_today())
        self.assertEqual(code, 1)
        self.assertIn("Refused.", message)
        tampered = Path(self.fixture.name) / "tampered.json"
        text = path.read_text().replace("Northwind CAD", "Someone Else")
        tampered.write_text(text)
        code, message = accept_bundle(self.bundle_for(tampered, "machine-a", "tampered.tar.gz"), self.ledger, today=date(2020, 1, 15))
        self.assertEqual(code, 1)
        self.assertIn("signature", message.lower())

        completed = subprocess.run(
            [ROOT / "spacemouse", "agreement", "install", str(path)],
            env=self.env, text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        status = subprocess.run(
            [ROOT / "spacemouse", "agreement"], env=self.env, text=True, capture_output=True, check=True, timeout=15,
        )
        self.assertIn("expired", status.stdout)
        self.assertIn(SOFTWARE_MODEL, status.stdout)
        buttons = subprocess.run(
            [ROOT / "spacemouse", "buttons", "--model", "spacepilot-pro"],
            env=self.env, text=True, capture_output=True, check=True, timeout=15,
        )
        self.assertIn("key-1", buttons.stdout)

    def test_included_minutes_close_and_then_refuse(self):
        path = Path(self.fixture.name) / "hours.json"
        self.issue(path, [("ASM-SUP-H-EU", 1)], starts=utc_today().isoformat())
        bundle = self.bundle_for(path, "machine-a")
        code, message = accept_bundle(bundle, self.ledger, today=utc_today())
        self.assertEqual(code, 0, message)
        case_id = message.split("Recorded as ", 1)[1].split(".", 1)[0]
        self.assertIn("60 minutes", close_case(case_id, 60, self.ledger))
        extra = self.bundle_for(path, "machine-b", "extra.tar.gz")
        code, message = accept_bundle(extra, self.ledger, today=utc_today())
        self.assertEqual(code, 1)
        self.assertIn("ASM-SUP-H-EU", message)

    def test_support_bundle_stays_local_and_omits_the_environment(self):
        previous = dict(os.environ)
        os.environ.update(self.env)
        try:
            log_event("bridge starting for the test")
            path = build_bundle(Path(self.fixture.name) / "support.tar.gz")
        finally:
            os.environ.clear()
            os.environ.update(previous)
        self.assertIn("stays on this computer", bundle_summary(path))
        with tarfile.open(path, "r:gz") as archive:
            names = set(archive.getnames())
            blob = b"".join(archive.extractfile(name).read() for name in names)
        self.assertIn("manifest.json", names)
        self.assertIn("journal-spacenavd.txt", names)
        self.assertIn("coredumps.txt", names)
        self.assertNotIn("sentinel-value-do-not-collect", blob.decode(errors="replace"))
        self.assertNotIn(b"issuer.key", blob)

    def test_community_bundle_is_saved_and_not_covered(self):
        bundle = self.bundle_for(None, "machine-a")
        code, message = accept_bundle(bundle, self.ledger, today=utc_today())
        self.assertEqual(code, 3)
        self.assertIn("Community bundle.", message)
        self.assertIn("Logs:", message)
