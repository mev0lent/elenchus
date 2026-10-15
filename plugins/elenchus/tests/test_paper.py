#!/usr/bin/env python3
"""/elenchus:paper and /elenchus:own through the real hooks and CLI, on both engines.
Owning requires a formal statement: a labeled equation, invariant, definition or algorithm."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gates import Gates  # noqa: E402

HERE = Path(__file__).resolve().parent
VIBE = HERE.parent.parent / "elenchus-vibe" / "scripts" / "elenchus.py"
TITLE = "Archive iff P(normal) >= tau"
MODEL = '''$ "archive"(x) <==> P("normal" | x) >= tau $ <eq-gate>
#algorithm("Triage", input: [$x$], output: [archive or escalate])[
  + $p <- P("normal" | x)$
  + *if* $p >= tau$ *then* archive *else* escalate
] <alg-triage>
'''
DECISIONS = (f'#decision("{TITLE}", origin: "inherited", formal: (<eq-gate>, <alg-triage>), where: "gatelib.mjs:12")\n'
             '#decision("Retry three times", origin: "inherited", where: "providers.mjs:41")\n'
             '#decision("Cache by model version", origin: "mine", formal: <eq-missing>)\n')


def have_typst():
    if shutil.which("typst"):
        return True
    try:
        import typst  # noqa: F401
        return True
    except ImportError:
        return False


def fill(p: Path):
    t = p.read_text(encoding="utf-8")
    t = t.replace("\n= Decisions\n", "\n" + MODEL + "\n= Decisions\n", 1)
    t = t.replace("\n= Limits and open questions\n", "\n" + DECISIONS + "\n= Limits and open questions\n", 1)
    p.write_text(t, encoding="utf-8")


class Paper(Gates):
    def setUp(self):
        super().setUp()
        self.env["ELENCHUS_PAPERS"] = str(self.cwd / "papers.json")

    def ctx(self, r):
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else ""

    def make_paper(self, filled=True):
        r = self.cli("paper", "init", "--path", "docs/paper", "--name", "demo")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        p = self.cwd / "docs" / "paper" / "main.typ"
        if filled:
            fill(p)
        return p

    def pass_own_gate(self, title=TITLE):
        c = self.ctx(self.prompt(f"/elenchus:own {title}"))
        s = self.state()
        self.assertEqual((s["mode"], s["own"]), ("propose", title))
        self.assertIn("OWN GATE", c)
        self.prompt("Archive only when the cheap model is confident enough.")
        for _ in range(2):
            self.assertIn("eq-gate", self.ctx(self.prompt("Because tau is fixed on dev.")))
            self.assertEqual(self.cli("challenge", "--text", "What happens at p = tau exactly?").returncode, 0)
        self.prompt("Equality archives; that is the >= in Equation 1.")
        self.assertEqual(self.cli("verdict", "--note", "defended").returncode, 0)
        self.prompt("reflect: the >= puts the boundary on the archive side, so tau is the lowest confidence we trust.")
        return self.accept()

    def test_paper_command_guides_setup_then_status(self):
        self.assertIn("paper init", self.ctx(self.prompt("/elenchus:paper")))
        self.assertFalse(self.state()["active"])
        self.make_paper(filled=False)
        self.assertIn("paper build", self.ctx(self.prompt("/elenchus:paper")))
        self.assertIn("State: empty", self.cli("paper", "status").stdout)

    def test_session_note_only_with_a_paper(self):
        self.assertEqual(self.hook("session", source="startup").stdout.strip(), "")
        self.make_paper()
        self.assertIn("Never formalize a decision for the user", self.hook("session", source="startup").stdout)

    def test_own_needs_a_paper(self):
        self.assertIn("no owner's paper", self.ctx(self.prompt(f"/elenchus:own {TITLE}")))
        self.assertFalse(self.state()["active"])

    def test_own_refuses_what_is_not_formalized(self):
        self.make_paper()
        for title, says in (("Retry three times", "no formal statement"),
                            ("Cache by model version", "<eq-missing>"),
                            ("Something unknown", "no decision titled")):
            c = self.ctx(self.prompt(f"/elenchus:own {title}"))
            self.assertIn("not ready to own", c)
            self.assertIn(says, c)
            self.assertFalse(self.state()["active"])
            self.assertIn(says, self.cli("paper", "check", "--title", title).stdout)
        self.assertIn("Ready", self.cli("paper", "check", "--title", TITLE).stdout)

    def test_status_flags_unformalized(self):
        self.make_paper()
        out = self.cli("paper", "status").stdout
        self.assertIn("inherited: Retry three times  [not formalized]", out)

    def test_own_binds_the_gate_and_keeps_the_formal_statement(self):
        p = self.make_paper()
        r = self.pass_own_gate()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("marked owned", r.stdout)
        src = p.read_text(encoding="utf-8")
        self.assertRegex(src, r'#decision\("Archive iff P\(normal\) >= tau", formal: \(<eq-gate>, <alg-triage>\), '
                              r'where: "gatelib.mjs:12", origin: "mine", gate: "[0-9a-f]{32}"\)')
        self.assertIn("lowest confidence we trust", src)
        self.assertEqual(len(list((p.parent / "gates").glob("*.json"))), 1)
        self.assertIn("1 owned, 1 mine but untested, 1 inherited", self.cli("paper", "status").stdout)

    def test_own_title_is_case_insensitive(self):
        self.make_paper()
        self.prompt("/elenchus:own archive IFF p(normal) >= tau")
        self.assertEqual(self.state()["own"], TITLE)

    def test_learn_does_not_bind(self):
        p = self.make_paper()
        self.prompt(f"/elenchus:own {TITLE}")
        self.prompt("/elenchus:learn explain TLS")
        self.assertEqual((self.state()["own"], self.state()["own_brief"]), ("", ""))
        self.verdict()
        self.prompt("reflect: certificates authenticate, session keys encrypt.")
        self.accept()
        self.assertNotIn('gate: "', p.read_text(encoding="utf-8"))

    def test_one_gate_binds_a_related_formalized_decision_from_any_session(self):
        p = self.make_paper()
        self.assertEqual(self.pass_own_gate().returncode, 0)
        self.assertNotEqual(self.cli("paper", "bind", "--title", "Retry three times", sid="later").returncode, 0)  # not formalized
        t = p.read_text(encoding="utf-8").replace('#decision("Retry three times", origin: "inherited", where: "providers.mjs:41")',
                                                  '#decision("Retry three times", origin: "mine", formal: <alg-triage>)')
        p.write_text(t, encoding="utf-8")
        r = self.cli("paper", "bind", "--title", "Retry three times", sid="later")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("2 owned", self.cli("paper", "status").stdout)

    def test_overview_of_all_papers(self):
        self.make_paper()
        self.assertIn("paper status --all", self.ctx(self.prompt("/elenchus:paper all")))
        out = self.cli("paper", "status", "--all").stdout
        self.assertIn("in progress 0/3 owned", out)
        self.assertIn("main.typ", out)

    def test_paper_cards_export(self):
        p = self.make_paper()
        p.write_text(p.read_text(encoding="utf-8").replace("\n= Limits", '\n#card("Why >= at tau?", "Equality archives.")\n\n= Limits'), encoding="utf-8")
        self.assertIn("1 cards", self.cli("paper", "cards").stdout)
        tsv = next((self.cwd / ".elenchus" / "anki").glob("paper-*.tsv")).read_text(encoding="utf-8")
        self.assertIn("Why &gt;= at tau?\tEquality archives.", tsv)

    def test_setup_asks_about_employer_material(self):
        self.assertIn("employer or client", self.ctx(self.prompt("/elenchus:paper")))

    @unittest.skipUnless(have_typst(), "Typst not installed")
    def test_build_makes_a_pdf_and_catches_broken_references(self):
        p = self.make_paper()
        t = p.read_text(encoding="utf-8").replace(', formal: <eq-missing>)', ')')
        p.write_text(t, encoding="utf-8")
        r = self.cli("paper", "build")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(p.with_suffix(".pdf").read_bytes().startswith(b"%PDF"))
        p.write_text(t.replace("<eq-gate>, <alg-triage>", "<eq-gone>"), encoding="utf-8")
        self.assertNotEqual(self.cli("paper", "build").returncode, 0)

    def test_paper_module_identical_in_both_engines(self):
        self.assertEqual((HERE.parent / "scripts" / "paper.py").read_bytes(), (VIBE.parent / "paper.py").read_bytes())


class VibePaper(unittest.TestCase):
    def setUp(self):
        import os
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cwd = Path(self.tmp.name)
        self.env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "ELENCHUS_DIR")}
        self.env["ELENCHUS_DIR"] = str(self.cwd / ".elenchus")
        self.env["ELENCHUS_PAPERS"] = str(self.cwd / "papers.json")

    def run_(self, args, payload=None):
        return subprocess.run([sys.executable, str(VIBE), *args], input=json.dumps(payload) if payload else "",
                              capture_output=True, text=True, encoding="utf-8", env=self.env, cwd=self.cwd)

    def test_own_flow_and_refusal(self):
        cli = lambda *a: self.run_(["--session", "v", *a])
        say = lambda text: self.run_(["hook-prompt"], {"cwd": str(self.cwd), "session_id": "v", "prompt": text})
        self.assertEqual(cli("paper", "init", "--path", "docs/paper", "--name", "demo").returncode, 0)
        fill(self.cwd / "docs" / "paper" / "main.typ")
        say("/elenchus:own Retry three times")
        self.assertIn("NOT READY TO OWN", cli("status").stdout)
        say(f"/elenchus:own {TITLE}")
        self.assertIn("OWN GATE", cli("status").stdout)
        say("Archive only when confident.")
        for _ in range(2):
            self.assertEqual(cli("challenge", "--text", "What at p = tau?").returncode, 0)
            say("Equality archives.")
        self.assertEqual(cli("verdict", "--note", "defended").returncode, 0)
        say("reflect: >= puts the boundary on the archive side.")
        r = cli("assess", "--result", "accept", "--mechanism", "boundary", "--transfer", "hard tier",
                "--limit", "calibration", "--note", "sound")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("1 owned", cli("paper", "status").stdout)


if __name__ == "__main__":
    unittest.main()
