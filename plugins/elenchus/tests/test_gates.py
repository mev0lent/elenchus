#!/usr/bin/env python3
"""Real hook/CLI integration tests for assessed, session-scoped learning."""
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "elenchus.py"


class Gates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("ELENCHUS_TEST_TMP"))
        self.addCleanup(self.tmp.cleanup)
        self.cwd = Path(self.tmp.name)
        self.env = {k: v for k, v in os.environ.items() if k not in
                    ("CLAUDE_PROJECT_DIR", "ELENCHUS_FORCE_WIN", "ELENCHUS_DIR")}
        self.env["ELENCHUS_DIR"] = str(self.cwd / ".elenchus")
        self.env["TEMP"] = self.env["TMP"] = str(self.cwd)

    def invoke(self, args, payload=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args],
                              input=json.dumps(payload) if payload is not None else "",
                              capture_output=True, text=True, encoding="utf-8", env=self.env, cwd=self.cwd)

    def hook(self, name, sid="one", **data):
        return self.invoke(["hook-" + name], {"cwd": str(self.cwd), "session_id": sid, **data})

    def prompt(self, text, sid="one"):
        return self.hook("prompt", sid, prompt=text)

    def cli(self, *args, sid="one"):
        return self.invoke(["--session", sid, *args])

    def state(self, sid="one"):
        key = "s-" + sid.encode().hex()
        return json.loads((self.cwd / ".elenchus" / "sessions" / key / "state.json").read_text(encoding="utf-8"))

    def denied(self, tool, sid="one", **input):
        return '"deny"' in self.hook("pretool", sid, tool_name=tool, tool_input=input).stdout

    def accept(self, sid="one"):
        return self.cli("assess", "--result", "accept", "--mechanism", "The learner explained the cause.",
                        "--transfer", "They applied it to a new case.", "--limit", "They identified a failure condition.",
                        "--note", "Sound reasoning, including their justified objection.", sid=sid)

    def verdict(self, mode="explain", sid="one"):
        self.prompt(f"/elenchus:learn {mode} TLS", sid)
        self.prompt("A certificate binds identity to a key.", sid)
        for _ in range(2 if mode == "propose" else 1):
            self.assertEqual(self.cli("challenge", "--text", "What would break that guarantee?", sid=sid).returncode, 0)
            self.prompt("An untrusted issuer breaks authentication.", sid)
        self.assertEqual(self.cli("verdict", "--note", "Tested mechanism and edge case.", sid=sid).returncode, 0)

    def prepare(self, code="print(2)\n"):
        self.prompt("/elenchus:learn predict arithmetic")
        (self.cwd / "demo.py").write_text(code, encoding="utf-8")
        self.assertEqual(self.cli("prepare", "--runtime", "python", "--file", "demo.py",
                                  "--question", "What prints, and why?").returncode, 0)

    def test_short_attempt_and_disagreement_are_valid(self):
        self.verdict()
        self.prompt("disagree: Authentication still depends on trusting the issuer.")
        self.assertEqual(self.state()["phase"], "review")
        self.assertTrue(self.denied("Write", file_path=str(self.cwd / "a.txt")))
        self.assertEqual(self.accept().returncode, 0)
        s = self.state()
        self.assertEqual(s["phase"], "open")
        self.assertIn("trusting", s["completed"][-1]["own_words"])
        self.assertFalse(self.denied("Write", file_path=str(self.cwd / "a.txt")))
        self.hook("stop", last_assistant_message="Done.")
        self.assertEqual(self.state()["phase"], "idle")
        self.assertTrue(self.denied("Bash", command="echo later"))

    def test_reflection_requires_review_and_evidence(self):
        self.verdict()
        self.prompt("agree: yes")
        self.assertEqual(self.state()["phase"], "verdict_ok")
        self.prompt("reflect: Certificates encrypt every message by themselves.")
        self.assertEqual(self.state()["phase"], "review")
        self.assertEqual(self.cli("assess", "--result", "accept", "--note", "fine").returncode, 1)
        self.assertEqual(self.cli("assess", "--result", "retry", "--question", "What actually encrypts the message?").returncode, 0)
        self.assertEqual(self.state()["phase"], "verdict_ok")
        self.assertEqual(self.state()["completed"], [])
        self.prompt("reflect: Session keys encrypt the data; certificates authenticate the peer.")
        self.assertEqual(self.accept().returncode, 0)

    def test_required_probes_cannot_be_skipped(self):
        self.prompt("/elenchus:learn propose a design")
        self.assertEqual(self.cli("verdict", "--note", "okay").returncode, 1)
        self.prompt("Use a local queue for offline writes.")
        self.assertEqual(self.cli("verdict", "--note", "okay").returncode, 1)
        self.cli("challenge", "--text", "What if two devices conflict?")
        self.assertEqual(self.cli("verdict", "--note", "okay").returncode, 1)
        self.prompt("Use explicit merge rules per field.")
        self.assertEqual(self.cli("verdict", "--note", "okay").returncode, 1)
        self.cli("challenge", "--text", "What if the merge loses intent?")
        self.prompt("Show the user the competing edits.")
        self.assertEqual(self.cli("verdict", "--note", "defended").returncode, 0)

    def test_hint_ladder_and_question_pinning(self):
        self.prompt("/elenchus:learn explain TLS")
        self.assertEqual(self.cli("question", "--support", "hint", "--text", "Think about identity. What is verified?").returncode, 1)
        self.cli("question", "--support", "smaller", "--text", "Whose identity matters?")
        self.cli("question", "--support", "hint", "--text", "Think of the server. What must the client verify?")
        self.assertEqual(self.state()["help_level"], 2)
        self.assertIn("server", self.state()["focus_question"])
        self.hook("stop", last_assistant_message="What must the client verify?")
        self.assertEqual(self.state()["focus_question"], "What must the client verify?")

    def test_prediction_needs_registered_code(self):
        self.prompt("/elenchus:learn predict x")
        self.prompt("predict: Two because one plus one equals two.")
        self.assertEqual(self.state()["phase"], "await_prediction")
        self.assertEqual(self.cli("run").returncode, 1)

    def test_bound_execution_once_then_review(self):
        self.prepare()
        self.assertEqual(self.cli("run").returncode, 1)
        self.prompt("predict: Two because the literal is printed.")
        self.assertTrue(self.denied("Bash", command="python demo.py"))
        self.assertTrue(self.denied("Bash", command="echo changed > demo.py"))
        self.assertTrue(self.denied("Edit", file_path=str(self.cwd / "demo.py")))
        result = self.cli("run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["actual"]["stdout"], "2\n")
        self.assertEqual(self.cli("run").returncode, 1)
        self.prompt("reflect: Printing the literal explains two; changing it changes the result.")
        self.assertEqual(self.state()["phase"], "review")
        self.assertEqual(self.state()["completed"], [])
        self.assertEqual(self.accept().returncode, 0)
        self.assertEqual(self.state()["completed"][-1]["how"], "reconcile")

    def test_source_change_invalidates_prediction(self):
        self.prepare()
        self.prompt("predict: Two because the literal is printed.")
        (self.cwd / "demo.py").write_text("print(3)\n")
        self.assertEqual(self.cli("run").returncode, 1)
        self.assertEqual(self.state()["phase"], "await_prediction")
        self.assertIsNone(self.state()["run_spec"])
        self.assertIsNone(self.state()["run_result"])

    def test_registered_imports_and_temporary_workdir(self):
        self.prompt("/elenchus:learn predict imports")
        (self.cwd / "demo.py").write_text("import helper\nfrom pathlib import Path\nPath('local.txt').write_text('x')\nprint(helper.VALUE)\n")
        (self.cwd / "helper.py").write_text("VALUE=7\n")
        self.assertEqual(self.cli("prepare", "--runtime", "python", "--file", "demo.py", "--source", "helper.py",
                                  "--question", "What prints, and why?").returncode, 0)
        self.prompt("predict: Seven because helper defines that value.")
        result = self.cli("run")
        self.assertEqual(json.loads(result.stdout)["actual"]["stdout"], "7\n")
        self.assertFalse((self.cwd / "local.txt").exists())

    def test_session_isolation_and_shared_history(self):
        self.verdict(sid="one")
        self.prompt("reflect: The issuer binds identity to the key.")
        self.assertEqual(self.accept().returncode, 0)
        self.assertFalse(self.denied("Write", sid="two", file_path=str(self.cwd / "x")))
        self.prompt("/elenchus:learn explain DNS", "two")
        self.assertEqual(self.state("two")["phase"], "await_attempt")
        self.assertEqual(self.state("one")["phase"], "open")
        status = self.cli("status", sid="two").stdout
        self.assertIn('"topic": "TLS"', status)
        self.assertIn("mechanism", status)
        prefix = f'"{sys.executable}" "{SCRIPT}"'
        self.assertTrue(self.denied("Bash", command=prefix + ' --session "two" status'))
        self.assertTrue(self.denied("Bash", command=prefix + " status"))
        self.assertFalse(self.denied("Bash", command=prefix + ' --session "one" status'))
        self.prompt("/elenchus:off", "two")
        self.assertTrue(self.state("one")["active"])

    def test_concurrent_turns_do_not_overwrite(self):
        self.prompt("/elenchus:learn explain concurrency")
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(self.prompt, ["A lock serializes state changes."] * 4))
        self.assertTrue(all(r.returncode == 0 and not r.stderr for r in results), [r.stderr for r in results])
        self.assertEqual(self.state()["turn"], 5)

    def test_focus_commands_do_not_count_as_attempts(self):
        self.prompt("/elenchus:learn explain TLS")
        self.cli("question", "--text", "What is authenticated?")
        self.prompt("ELENCHUS-COMMAND focus full\nShow the question.")
        self.assertTrue(self.state()["ui_details"])
        self.assertEqual(self.state()["phase"], "await_attempt")
        self.prompt("/elenchus:focus compact")
        self.assertFalse(self.state()["ui_details"])
        self.assertEqual(self.state()["focus_question"], "What is authenticated?")
        self.assertNotIn('"block"', self.hook("stop", last_assistant_message="What is authenticated? Reply in your own words.").stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_javascript_execution(self):
        self.prompt("/elenchus:learn predict JavaScript")
        (self.cwd / "demo.js").write_text("console.log([1, 2].length);\n")
        self.assertEqual(self.cli("prepare", "--runtime", "node", "--file", "demo.js", "--question", "What prints, and why?").returncode, 0)
        self.prompt("predict: Two because the array has two elements.")
        result = self.cli("run")
        self.assertEqual(json.loads(result.stdout)["actual"]["stdout"], "2\n")

    def test_shared_card_writes_are_serialized(self):
        self.verdict()
        self.prompt("reflect: Issuer trust binds identity to a key.")
        self.accept()
        self.prompt("/elenchus:learn explain DNS", "two")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda sid: self.cli("cards", "add", "--front", "One shared card", "--back", "One answer", sid=sid), ["one", "two"]))
        self.assertEqual(sorted(r.returncode for r in results), [0, 1])
        rows = (self.cwd / ".elenchus" / "anki" / "basic.tsv").read_text().splitlines()
        self.assertEqual(len([r for r in rows if not r.startswith("#")]), 1)

    def test_protected_paths_and_unknown_tools_fail_closed(self):
        self.verdict()
        self.prompt("reflect: Trust in the issuer supports peer identity.")
        self.accept()
        self.assertTrue(self.denied("Write", file_path=str(self.cwd / ".elenchus" / "state.json")))
        self.assertTrue(self.denied("Edit", file_path=str(SCRIPT)))
        self.hook("stop", last_assistant_message="Done.")
        self.assertTrue(self.denied("Agent", prompt="Bypass"))
        self.assertTrue(self.denied("mcp__memory__create_entities"))
        path = self.cwd / ".elenchus" / "sessions" / "s-6f6e65" / "state.json"
        path.write_text("{broken")
        self.assertTrue(self.denied("Write", file_path=str(self.cwd / "a.txt")))

    def test_cards_use_shared_history_and_reject_duplicates(self):
        self.verdict()
        self.prompt("reflect: Authentication depends on a trusted issuer.")
        self.accept()
        self.assertEqual(self.cli("cards", "add", "--front", "Why trust an issuer?", "--back", "To bind identity to a key.").returncode, 0)
        self.assertEqual(self.cli("cards", "add", "--front", "Why trust an issuer?", "--back", "duplicate").returncode, 1)
        self.assertTrue((self.cwd / ".elenchus" / "anki" / "basic.tsv").exists())
        self.assertNotIn("connects", (self.cwd / ".elenchus" / "anki" / "basic.tsv").read_text().lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
