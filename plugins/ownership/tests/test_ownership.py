#!/usr/bin/env python3
"""End-to-end checks for the ownership tooling: install, init, cards, ledger, and the
decision contract. Needs Typst (CLI or `pip install typst`); skips cleanly without it."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ownership.py"


def have_typst():
    if shutil.which("typst"):
        return True
    try:
        import typst  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(have_typst(), "Typst not installed")
class Ownership(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = dict(os.environ, TYPST_PACKAGE_PATH=str(self.root / "pkg"),
                        OWNERSHIP_CONFIG=str(self.root / "config.json"),
                        XDG_DATA_HOME=str(self.root / "xdg"), APPDATA=str(self.root / "appdata"))
        self.run_ok("install")

    def run_cmd(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                              encoding="utf-8", env=self.env, cwd=cwd or self.root)

    def run_ok(self, *args, cwd=None):
        r = self.run_cmd(*args, cwd=cwd)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r.stdout

    def paper(self, body, name="demo"):
        d = self.root / name / "docs" / "paper"
        self.run_ok("init", str(d), "--name", name)
        p = d / "main.typ"
        p.write_text(p.read_text(encoding="utf-8") + "\n" + body, encoding="utf-8")
        return p

    def test_skeleton_compiles_and_is_empty(self):
        p = self.paper("")
        self.assertIn("empty", self.run_ok("ledger", str(p)))

    def test_init_never_overwrites(self):
        p = self.paper("Mine.")
        r = self.run_cmd("init", str(p.parent), "--name", "demo")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Mine.", p.read_text(encoding="utf-8"))

    def test_cards_export_basic_cloze_and_connects(self):
        p = self.paper('#card("Why archive at P(normal) >= tau?", "Below tau the cheap model is unsure.", connects: "Calibration")\n'
                       '#card("The gate escalates when {{c1::P(normal) < tau}}.", "", cloze: true)\n')
        out = self.run_ok("cards", str(p), "--out", str(self.root / "anki"))
        basic = (self.root / "anki" / "ownership-demo-basic.tsv").read_text(encoding="utf-8")
        cloze = (self.root / "anki" / "ownership-demo-cloze.tsv").read_text(encoding="utf-8")
        self.assertIn("#deck:Elenchus::Ownership::demo", basic)
        self.assertIn("el-connects", basic)
        self.assertIn("P(normal) &gt;= tau", basic)
        self.assertIn("{{c1::", cloze)
        self.assertIn("1 basic", out)

    def test_duplicate_card_fronts_fail(self):
        p = self.paper('#card("Same?", "a")\n#card("Same?", "b")\n')
        self.assertNotEqual(self.run_cmd("cards", str(p), "--out", str(self.root / "anki")).returncode, 0)

    def elenchus_gate(self, topic, mode="propose"):
        """Pass a real gate through the Elenchus engine, the way the hooks drive it."""
        engine = SCRIPT.parent.parent.parent / "elenchus" / "scripts" / "elenchus.py"
        env = dict(self.env, ELENCHUS_DIR=str(self.root / ".elenchus"))
        def call(args, payload=None):
            r = subprocess.run([sys.executable, str(engine), *args], input=json.dumps(payload) if payload else "",
                               capture_output=True, text=True, encoding="utf-8", env=env, cwd=self.root)
            return r
        prompt = lambda text: call(["hook-prompt"], {"cwd": str(self.root), "session_id": "s", "prompt": text})
        cli = lambda *a: call(["--session", "s", *a])
        prompt(f"/elenchus:learn {mode} {topic}")
        prompt("Choose it on dev so test stays untouched.")
        for _ in range(2):
            self.assertEqual(cli("challenge", "--text", "What if dev is too small?").returncode, 0)
            prompt("Then the threshold is noisy; I would report an interval.")
        self.assertEqual(cli("verdict", "--note", "defended").returncode, 0)
        prompt("reflect: dev picks tau, test only measures; a small dev split makes tau unstable.")
        r = cli("assess", "--result", "accept", "--mechanism", "separates selection from measurement",
                "--transfer", "applied it to the hard tier", "--limit", "small dev split", "--note", "sound")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_decisions_need_a_passed_gate(self):
        p = self.paper('#decision("Threshold chosen on dev", origin: "mine")\nBecause test must stay untouched.\n'
                       '#decision("Retry three times on timeout", origin: "inherited", where: "providers.mjs:41")\n')
        out = self.run_ok("ledger", "-v", str(p))
        self.assertIn("in progress", out)
        self.assertIn("0/2 tested, 1 inherited", out)
        self.assertIn("untested: Threshold chosen on dev", out)
        self.assertIn("providers.mjs:41", out)

    def test_own_binds_a_real_elenchus_gate(self):
        p = self.paper('#decision("Threshold chosen on dev", origin: "inherited", where: "gatelib.mjs:12")\n')
        self.assertNotEqual(self.run_cmd("own", str(p), "Threshold chosen on dev").returncode, 0)  # no gate yet
        self.elenchus_gate("Threshold chosen on dev")
        out = self.run_ok("own", str(p), "Threshold chosen on dev")
        self.assertIn("Owned", out)
        src = p.read_text(encoding="utf-8")
        self.assertIn('origin: "mine"', src)
        self.assertRegex(src, r'gate: "[0-9a-f]{32}"')
        self.assertEqual(len(list((p.parent / "gates").glob("*.json"))), 1)
        self.assertIn("owned", self.run_ok("ledger", str(p)).split()[1])

    def test_unrelated_gate_does_not_count(self):
        p = self.paper('#decision("Use SQLite", origin: "mine")\n')
        self.elenchus_gate("TLS handshakes")
        r = self.run_cmd("own", str(p), "Use SQLite")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("TLS handshakes", r.stderr)

    def test_deleted_gate_record_breaks_ownership(self):
        p = self.paper('#decision("Threshold chosen on dev")\n')
        self.elenchus_gate("Threshold chosen on dev")
        self.run_ok("own", str(p), "Threshold chosen on dev")
        for f in (p.parent / "gates").glob("*.json"):
            f.unlink()
        out = self.run_ok("ledger", str(p))
        self.assertIn("in progress", out)
        self.assertIn("gate records missing", out)

    def test_unknown_origin_fails(self):
        p = self.paper('#decision("x", origin: "mostly")\n')
        self.assertNotEqual(self.run_cmd("ledger", str(p)).returncode, 0)

    def test_ledger_flags_code_changed_since_paper(self):
        p = self.paper('#decision("x")\nMine.\n')
        repo = p.parent.parent.parent
        git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True)
        git("init", "-q")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "t")
        git("add", "-A")
        git("commit", "-qm", "paper")
        self.assertNotIn("commits outside", self.run_ok("ledger", str(p)))
        (repo / "code.py").write_text("print(1)\n")
        git("add", "-A")
        git("commit", "-qm", "code")
        self.assertIn("1 commits outside the paper", self.run_ok("ledger", str(p)))

    def test_ledger_reads_config(self):
        lib = self.root / "library"
        self.run_ok("init", str(lib / "projects" / "public-harness"), "--name", "public-harness")
        (self.root / "config.json").write_text(json.dumps({"library": str(lib)}), encoding="utf-8")
        self.assertIn("public-harness", self.run_ok("ledger"))


if __name__ == "__main__":
    unittest.main()
