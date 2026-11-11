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
        for key, name in (("GRAPH", ".elenchus/graph"), ("ALWAYS", ".elenchus/always-on"), ("PAPERS", "papers.json")):
            self.env["ELENCHUS_" + key] = str(self.cwd / name)
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
        # a passed gate stays open across turns, until the next gate starts
        self.hook("stop", last_assistant_message="Done.")
        self.prompt("now build it")
        self.assertNotIn('"block"', self.hook("stop", last_assistant_message="word " * 300).stdout)
        self.assertEqual(self.state()["phase"], "open")
        self.assertFalse(self.denied("Bash", command="echo later"))
        self.assertEqual(self.cli("gate", "--mode", "propose", "--topic", "cache key").returncode, 0)
        self.assertTrue(self.denied("Bash", command="echo later"))

    def test_fast_gates_record_challenges_without_cli_round_trips(self):
        for mode, rounds in (("explain", 1), ("propose", 2), ("decide", 1)):
            with self.subTest(mode=mode):
                self.prompt(f"/elenchus:learn {mode} TLS", mode)
                self.hook("stop", mode, last_assistant_message="What would you do, and why?")
                self.assertIn("What would", self.state(mode)["focus_question"])
                self.prompt("Trust the issuer because it signs the key.", mode)
                for n in range(rounds):
                    result = self.hook("stop", mode, last_assistant_message="What if the issuer is compromised?")
                    self.assertNotIn('"block"', result.stdout)
                    self.assertNotIn('"deny"', result.stdout)
                    self.assertEqual((self.state(mode)["phase"], self.state(mode)["rounds"]), ("challenging", n + 1))
                    self.assertTrue(self.denied("Write", sid=mode, file_path="answer.txt"))
                    self.hook("stop", mode, last_assistant_message="What if the issuer is compromised?")
                    self.assertEqual(self.state(mode)["rounds"], n + 1)
                    self.prompt("Then a forged identity can pass verification.", mode)
                if mode == "decide":
                    result = self.cli("assess", "--result", "accept", "--note", "Trust a controlled issuer.", sid=mode)
                else:
                    result = self.cli("verdict", "--note", "Sound reasoning.", sid=mode)
                    self.assertEqual(result.returncode, 0, result.stdout)
                    self.assertIn("phase=verdict_ok", result.stdout)
                    result = self.hook("stop", mode, last_assistant_message="What is your conclusion, and what reasons support it?")
                    self.assertNotIn('"block"', result.stdout)
                    self.assertNotIn('"deny"', result.stdout)
                    self.prompt("my takeaway is that trust depends on the issuer's signing key.", mode)
                    self.assertEqual(self.state(mode)["phase"], "review")
                    result = self.accept(mode)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn("phase=open", result.stdout)

    def test_automatic_challenges_reject_lectures_and_ignore_housekeeping(self):
        self.prompt("/elenchus:learn explain TLS")
        self.prompt("The issuer signs the key.")
        self.hook("stop", last_assistant_message="word " * 90 + "What breaks it?")
        self.assertEqual((self.state()["phase"], self.state()["rounds"]), ("attempted", 0))
        self.prompt("/elenchus:focus")
        self.hook("stop", last_assistant_message="What breaks it?")
        self.assertEqual((self.state()["phase"], self.state()["rounds"]), ("attempted", 0))

    def test_transition_errors_and_brief_status_supply_the_next_move(self):
        self.prompt("/elenchus:learn explain TLS")
        self.prompt("The issuer signs the key.")
        result = self.cli("assess", "--result", "accept", "--note", "Too soon")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("phase=attempted", result.stdout)
        self.assertIn("Next:", result.stdout)
        self.assertEqual(self.state()["phase"], "attempted")
        result = self.cli("status", "--brief")
        self.assertIn("Next:", result.stdout)
        self.assertNotIn("Earlier topics", result.stdout)

    def test_ordinary_prompt_context_stays_within_the_fast_path_budget(self):
        def context(result):
            return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertLess(len(context(self.prompt("/elenchus:learn explain TLS"))), 2500)
        self.assertLess(len(context(self.prompt("The issuer signs the key."))), 1300)
        skill = SCRIPT.parent.parent / "skills" / "socratic" / "SKILL.md"
        self.assertLess(len(skill.read_text(encoding="utf-8")), 9000)

    def test_gate_pins_its_question_in_one_call(self):
        self.passed()
        before = self.state()
        self.assertNotEqual(self.cli("gate", "--mode", "decide", "--topic", "key", "--question", "no question").returncode, 0)
        self.assertEqual(self.state(), before)
        result = self.cli("gate", "--mode", "decide", "--topic", "key", "--question", "What key would you use, and why?")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.state()["focus_question"], "What key would you use, and why?")

    def test_natural_reflection_records_objections_without_unlocking_or_repeating(self):
        self.prompt("/elenchus:learn explain TLS")
        self.prompt("my takeaway is that the issuer signs the key.")
        self.assertEqual(self.state()["phase"], "attempted")
        self.verdict()
        self.prompt("yes")
        self.assertEqual(self.state()["phase"], "verdict_ok")
        self.prompt("But the issuer itself could be compromised.")
        self.assertEqual(self.state()["phase"], "review")
        self.assertIsNotNone(self.state()["verdict"])
        self.assertIn("compromised", self.state()["agreement"]["text"])
        self.assertTrue(self.denied("Write", file_path="answer.txt"))
        self.assertNotEqual(self.cli("assess", "--result", "accept", "--note", "insufficient evidence").returncode, 0)

    def test_prose_is_not_a_command(self):
        self.prompt("/elenchus:learn explain TLS")
        self.prompt("elenchus off does not work for me")
        self.assertTrue(self.state()["active"])
        self.prompt("elenchus off")
        self.assertFalse(self.state()["active"])
        self.prompt("/elenchus:learn explain TLS")
        self.prompt("/elenchus:off please")
        self.assertFalse(self.state()["active"])

    def test_passed_gate_lands_in_the_knowledge_graph(self):
        self.verdict()
        self.prompt("reflect: The issuer vouches for the key, so trust moves to the issuer.")
        r = self.cli("assess", "--result", "accept", "--mechanism", "Issuer signs the key.", "--transfer", "SSH host keys.",
                     "--limit", "A compromised issuer.", "--note", "Sound.", "--links", "PKI, Certificates")
        self.assertIn("knowledge graph", r.stdout)
        note = (self.cwd / ".elenchus" / "graph" / "TLS.md").read_text(encoding="utf-8")
        for part in ("# TLS", "trust moves to the issuer", "[[PKI]]", "[[Certificates]]", f"[[{self.cwd.name}]]"):
            self.assertIn(part, note)
        self.assertIn("trust moves to the issuer", self.cli("graph", "tls").stdout)
        self.assertIn("Nothing", self.cli("graph", "kubernetes").stdout)
        # three months later, another session, a neighbouring topic: the agent is told
        self.assertIn("KNOWLEDGE GRAPH", self.hook("session", "later").stdout)
        self.assertIn("[[TLS]]", self.prompt("/elenchus:learn explain TLS session resumption", "later").stdout)

    def passed(self, sid="one"):
        self.verdict(sid=sid)
        self.prompt("reflect: The issuer vouches for the key, so trust moves to the issuer.", sid)
        self.assertEqual(self.accept(sid).returncode, 0)

    def note(self, title):
        return (self.cwd / ".elenchus" / "graph" / f"{title}.md").read_text(encoding="utf-8")

    def test_recall_retests_the_oldest_note(self):
        self.assertIn("no note to recall", self.prompt("/elenchus:recall").stdout)
        self.passed()
        old = self.cwd / ".elenchus" / "graph" / "TLS.md"
        os.utime(old, (1, 1))
        self.assertIn("not been revisited for a month", self.hook("session", "later").stdout)
        brief = self.prompt("/elenchus:recall", "later").stdout
        self.assertIn("RECALL GATE", brief)
        self.assertIn("trust moves to the issuer", brief)
        s = self.state("later")
        self.assertEqual((s["topic"], s["mode"], s["phase"]), ("TLS", "explain", "await_attempt"))
        self.assertTrue(self.denied("Write", sid="later", file_path=str(self.cwd / "a.txt")))
        self.prompt("The issuer signs the key.", "later")
        self.cli("challenge", "--text", "What breaks it?", sid="later")
        self.prompt("A compromised issuer.", "later")
        self.cli("verdict", "--note", "held", sid="later")
        self.prompt("reflect: Trust still moves to the issuer.", "later")
        self.assertEqual(self.accept("later").returncode, 0)
        self.assertEqual(self.note("TLS").count("\n## "), 2)
        self.assertIn("· recall ·", self.note("TLS"))
        self.assertGreater(old.stat().st_mtime, 1)

    def test_decide_gate_is_one_round(self):
        self.passed()
        self.assertEqual(self.cli("gate", "--mode", "decide", "--topic", "cache key").returncode, 0)
        self.assertTrue(self.denied("Bash", command="echo x"))
        self.prompt("Key on the user id, it is stable.")
        self.assertNotEqual(self.cli("verdict", "--note", "x").returncode, 0)
        self.assertNotEqual(self.cli("assess", "--result", "accept", "--note", "x").returncode, 0)  # unchallenged
        self.assertEqual(self.cli("challenge", "--text", "What about shared accounts?").returncode, 0)
        self.assertNotEqual(self.cli("assess", "--result", "accept", "--note", "x").returncode, 0)  # unanswered
        self.prompt("Then the tenant id joins the key.")
        r = self.cli("assess", "--result", "accept", "--note", "Key on tenant and user id.")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.state()["phase"], "open")
        self.assertFalse(self.denied("Bash", command="echo x"))
        for part in ("· decide ·", "Decided:** Key on tenant and user id.", "it is stable. | Challenged, I answered: Then the tenant"):
            self.assertIn(part, self.note("cache key"))
        self.assertNotIn("My prediction", self.note("cache key") + self.note("TLS"))

    def test_recall_search_skips_delegations_before_limiting_matches(self):
        self.passed()
        for i in range(6):
            self.prompt(f"/elenchus:learn decide TLS z{i}")
            self.prompt("delegate: choose this")
        self.prompt("/elenchus:recall TLS")
        self.assertEqual(self.state()["topic"], "TLS")
        self.assertTrue(self.state()["recall"])

    def test_delegated_decision_is_recorded_as_such(self):
        self.prompt("/elenchus:learn explain TLS")
        self.prompt("delegate: you explain it")  # only decisions can be handed over
        self.assertEqual(self.state()["phase"], "attempted")
        self.prompt("/elenchus:learn decide log format")
        out = self.prompt("delegate: no opinion on this").stdout
        self.assertIn("DELEGATED", out)
        self.assertEqual(self.state()["phase"], "open")
        self.assertFalse(self.denied("Bash", command="echo x"))
        for part in ("· delegated ·", "Left to the agent", "no opinion on this"):
            self.assertIn(part, self.note("log format"))
        self.assertIn("log format", self.cli("graph", "delegated").stdout)
        self.assertIn("no note to recall", self.prompt("/elenchus:recall", "later").stdout)

    def test_always_on_starts_sessions_in_open_work(self):
        self.assertEqual(self.prompt("hello", "zero").stdout, "")
        self.assertIn("ALWAYS ON", self.prompt("/elenchus:always on").stdout)
        self.assertIn("phase=open", self.prompt("hello", "two").stdout)
        self.assertNotIn("IRON RULES", self.hook("session", "two").stdout)
        self.assertFalse(self.denied("Write", sid="two", file_path=str(self.cwd / "a.txt")))
        self.assertTrue(self.denied("Write", sid="two", file_path=str(Path.home() / ".config" / "elenchus" / "always-on")))
        self.hook("stop", "two", last_assistant_message="word " * 300)
        self.assertFalse((self.cwd / ".elenchus" / "sessions" / ("s-" + b"two".hex()) / "state.json").exists())  # no state written
        self.assertEqual(self.cli("gate", "--mode", "decide", "--topic", "schema", sid="two").returncode, 0)
        self.assertTrue(self.denied("Write", sid="two", file_path=str(self.cwd / "a.txt")))
        self.prompt("/elenchus:off", "two")
        self.assertEqual(self.prompt("hello", "two").stdout, "")
        self.prompt("/elenchus:always off", "two")
        self.assertEqual(self.prompt("hello", "three").stdout, "")

    def test_always_requires_an_explicit_switch_and_off_clears_recall(self):
        for text in ("/elenchus:always", "/elenchus:always typo"):
            self.assertIn("Nothing changed", self.prompt(text).stdout)
            self.assertFalse(Path(self.env["ELENCHUS_ALWAYS"]).exists())
        self.prompt("/elenchus:always on", "implicit")
        self.prompt("/elenchus:always off", "implicit")
        self.assertIn("phase=open", self.prompt("still working", "implicit").stdout)
        self.assertEqual(self.prompt("fresh session", "new").stdout, "")
        self.passed()
        self.prompt("/elenchus:recall")
        self.assertTrue(self.state()["recall"])
        self.prompt("/elenchus:off")
        self.assertFalse(self.state()["recall"])

    def test_agent_choice_only_appends_to_its_own_delegation(self):
        self.assertNotEqual(self.cli("choice", "--note", "JSON").returncode, 0)
        self.prompt("/elenchus:learn decide log format")
        self.assertNotEqual(self.cli("choice", "--note", "JSON").returncode, 0)
        self.prompt("delegate: no opinion")
        original = self.state()["completed"][-1].copy()
        self.assertNotEqual(self.cli("choice", "--note", "JSON", sid="other").returncode, 0)
        # A newer entry in the same note belongs to another session.
        self.prompt("/elenchus:learn decide log format", "other")
        self.prompt("delegate: another remark", "other")
        for note in (" ", "x" * 1501):
            self.assertNotEqual(self.cli("choice", "--note", note).returncode, 0)
        note = "JSON, because our log collector already parses it."
        for _ in range(2):
            r = self.cli("choice", "--note", note)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotEqual(self.cli("choice", "--note", "Replace it").returncode, 0)
        rec = next(c for c in self.state()["completed"] if c["id"] == original["id"])
        self.assertEqual({k: v for k, v in rec.items() if k != "agent_choice"}, original)
        self.assertEqual(rec["agent_choice"], note)
        text = self.note("log format")
        self.assertEqual(text.count("The agent chose"), 1)
        self.assertIn(note, text.split("\n## ")[1])
        self.assertNotIn(note, text.split("\n## ")[2])
        path = self.cwd / ".elenchus" / "graph" / "log format.md"
        backup = path.with_suffix(".backup")
        path.rename(backup)
        self.assertIn("Choice saved in project history", self.cli("choice", "--note", note).stdout)
        backup.rename(path)
        self.assertEqual(self.cli("choice", "--note", note).returncode, 0)
        self.assertEqual(self.note("log format").count("The agent chose"), 1)
        self.assertFalse((path.parent / ".gitignore").exists())
        self.assertIn("no note to recall", self.prompt("/elenchus:recall", "third").stdout)
        self.assertNotEqual(self.cli("cards", "add", "--front", "Choice?", "--back", note).returncode, 0)

    def test_untouched_folders_stay_clean(self):
        del self.env["ELENCHUS_DIR"]
        for key in ("GRAPH", "ALWAYS", "PAPERS"):
            self.env["ELENCHUS_" + key] = str(self.cwd / ("x-" + key.lower()))
        self.prompt("just a normal task")
        self.hook("session")
        self.denied("Bash", command="make")
        self.hook("stop", last_assistant_message="done")
        self.invoke(["graph", "tls"])
        self.cli("status")
        self.assertFalse((self.cwd / ".elenchus").exists())
        self.prompt("/elenchus:learn explain TLS")
        self.assertTrue(self.denied("Bash", command="make"))
        self.assertTrue((self.cwd / ".elenchus" / ".gitignore").exists())

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
        # the engine's own bookkeeping is approved without a prompt (Claude Code); code execution is not
        allowed = lambda sub: '"allow"' in self.hook("pretool", "one", tool_name="Bash", tool_input={"command": f'{prefix} --session "one" {sub}'}).stdout
        if "PLUGIN_ROOT" not in self.env:
            self.assertTrue(allowed("status"))
            self.assertTrue(allowed("graph tls"))
        self.assertFalse(allowed("run"))
        self.assertFalse(allowed("status; rm -rf x"))
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
        self.prompt("/elenchus:learn explain DNS")
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
