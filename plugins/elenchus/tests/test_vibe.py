#!/usr/bin/env python3
"""Mistral Vibe against the shared engine.

Vibe has no prompt hook: the user's words reach the engine through the session journal,
which Vibe 3 keeps under <session root>/journal/*.jsonl and names by transcript_path.
Tools arrive qualified (file_system.bash), denials are {"decision": "deny"}, and
post_agent replaces Stop. These tests replay that shape, with records copied from a real
Vibe 3.1 journal; they do not replace a live Vibe session."""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gates import Gates, SCRIPT  # noqa: E402
from test_paper import TITLE, fill  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent


class Vibe(Gates):
    def setUp(self):
        super().setUp()
        self.env.pop("CLAUDE_PLUGIN_ROOT", None)
        self.env["PLUGIN_ROOT"] = str(PLUGIN)
        self.env["ELENCHUS_PAPERS"] = str(self.cwd / "papers.json")
        self.root = self.cwd / "vibe-session"
        (self.root / "journal").mkdir(parents=True)
        self.ts = 1793961109000

    def record(self, *objs):
        with (self.root / "journal" / "0000000000000001.jsonl").open("a", encoding="utf-8") as f:
            f.writelines(json.dumps(o) + "\n" for o in objs)

    def say(self, text, source="turn_start"):
        """The user types: Vibe journals the input and its projection, same turn, same time."""
        self.ts += 1000
        turn, content = f"turn-{self.ts}", [{"type": "text", "text": text}]
        self.record(
            {"type": "core_input", "payload": {"input": {"determinism": {"time_unix_ms": self.ts}, "command": {
                "type": "user_message", "turn_id": turn, "content": content}}}},
            {"type": "projection_delta", "payload": {"delta": [{"op": "append_entry", "entry": {
                "type": "message", "role": "user", "source": source, "turnId": turn, "createdAt": self.ts,
                "id": f"rs-{self.ts}", "content": content}}]}})

    def reply(self, text):
        """Vibe projects the reply only after post_agent ran: at hook time it is a completion."""
        self.ts += 1000
        self.record({"type": "core_input", "payload": {"input": {"determinism": {"time_unix_ms": self.ts}, "command": {
            "type": "completion_succeeded", "result": {"finish_reason": "stop", "parts": [
                {"type": "reasoning", "content": [{"type": "text", "text": "thinking"}]},
                {"type": "text", "text": text}]}}}}})

    def vhook(self, name, **data):
        r = self.hook(name, "v", transcript_path=str(self.root), **data)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout else {}

    def tool(self, tool, **input):
        return self.vhook("pretool", hook_event_name="pre_tool", tool_name=tool, tool_input=input)

    def blocked(self, tool, **input):
        return self.tool(tool, **input).get("decision") == "deny"

    # The inherited Gates tests also run here, in Vibe's environment and dialect.
    def denied(self, tool, sid="one", **input):
        return '"decision": "deny"' in self.hook("pretool", sid, tool_name=tool, tool_input=input).stdout

    def test_typed_words_move_the_gate_and_qualified_tools_follow(self):
        self.assertFalse(self.blocked("file_system.write_file", file_path="a.txt"))  # never started: no lock
        self.say("/elenchus:learn explain TLS")
        self.assertTrue(self.blocked("file_system.write_file", file_path="a.txt"))
        self.assertTrue(self.blocked("vibe.cron", action="schedule", prompt="/elenchus:off"))
        self.assertTrue(self.blocked("file_system.bash", command="echo hi"))
        for read in ("file_system.read_file", "skill.read", "process.list", "vibe.todo"):
            self.assertFalse(self.blocked(read), read)
        prefix = f'"{sys.executable}" "{SCRIPT}" --session "v"'
        self.assertFalse(self.blocked("file_system.bash", command=prefix + " status"))
        self.say("A certificate binds identity to a key.")
        self.say("and the issuer signs it", source="turn_steer")
        self.tool("file_system.read_file")
        self.tool("file_system.read_file")  # a second tool call must not record the turn again
        s = self.state("v")
        self.assertEqual((s["phase"], s["turn"]), ("attempted", 3))
        self.assertIn("issuer signs", s["attempt"]["text"])

    def test_pass_opens_work_and_off_ends_it(self):
        self.say("/elenchus:learn explain TLS")
        self.say("A certificate binds identity to a key.")
        self.tool("file_system.read_file")
        self.assertEqual(self.cli("challenge", "--text", "What breaks that guarantee?", sid="v").returncode, 0)
        self.say("An untrusted issuer.")
        self.tool("file_system.read_file")
        self.assertEqual(self.cli("verdict", "--note", "ok", sid="v").returncode, 0)
        self.say("reflect: Trust moves to the issuer.")
        self.vhook("stop", hook_event_name="post_agent")  # a turn without tool calls is recorded too
        self.assertEqual(self.state("v")["phase"], "review")
        self.assertEqual(self.accept("v").returncode, 0)
        self.assertFalse(self.blocked("file_system.write_file", file_path="a.txt"))
        self.reply("word " * 300)
        self.assertEqual(self.vhook("stop", hook_event_name="post_agent"), {})
        self.say("great, now build it")
        self.assertFalse(self.blocked("file_system.bash", command="make"))
        self.say("/elenchus:learn explain DNS")
        self.assertTrue(self.blocked("file_system.bash", command="make"))
        self.say("/elenchus:off")
        self.assertFalse(self.blocked("file_system.bash", command="make"))
        self.assertFalse(self.state("v")["active"])

    def test_reply_review_retries_once_then_warns(self):
        self.say("/elenchus:learn explain TLS")
        self.reply("# TLS\n" + "word " * 200)
        first = self.vhook("stop", hook_event_name="post_agent")
        self.assertEqual(first.get("decision"), "deny")
        self.assertIn("[+] Elenchus:", first["reason"])
        second = self.vhook("stop", hook_event_name="post_agent")
        self.assertIn("ignored a rule", second["system_message"])
        self.assertNotIn("decision", second)
        self.assertEqual(self.state("v")["violations"], 1)
        self.say("[+] Elenchus: no ask for the user.")  # a retry message is not the learner
        self.say("ELENCHUS-COMMAND learn $ARGUMENTS")   # nor is a skill body
        self.tool("file_system.read_file")
        self.assertEqual((self.state("v")["turn"], self.state("v")["topic"]), (1, "TLS"))

    def test_status_delivers_the_briefing_without_a_session_id(self):
        self.say("/elenchus:learn explain TLS")
        self.tool("file_system.read_file")
        out = self.invoke(["status"]).stdout
        self.assertIn("ELENCHUS IRON RULES", out)
        self.assertIn('--session "v"', out)
        self.assertNotIn("ELENCHUS IRON RULES", self.invoke(["status"]).stdout)  # delivered once

    def test_ordinary_tool_result_supplies_context_once_per_turn(self):
        self.say("/elenchus:learn explain TLS")
        self.tool("file_system.read_file")
        data = {"tool_name": "file_system.read_file", "tool_input": {"path": "notes.md"}}
        context = self.vhook("posttool", **data)["hook_specific_output"]["additional_context"]
        self.assertIn("phase=await_attempt", context)
        self.assertIn('--session "v"', context)
        self.assertEqual(self.vhook("posttool", **data), {})
        self.say("The issuer signs the key.")
        self.reply("What breaks if the issuer is compromised?")
        self.assertEqual(self.vhook("stop"), {})
        self.assertEqual((self.state("v")["phase"], self.state("v")["rounds"]), ("challenging", 1))
        self.assertEqual(self.state("v")["notice"], "")
        self.say("A forged identity can pass verification.")
        command = f'"{sys.executable}" "{SCRIPT}" --session "v" verdict --note "Sound"'
        self.assertFalse(self.blocked("file_system.bash", command=command))
        self.assertEqual(self.cli("verdict", "--note", "Sound", sid="v").returncode, 0)
        # A command already returned the current state; do not append the old attempted briefing.
        self.assertEqual(self.vhook("posttool", tool_name="file_system.bash", tool_input={"command": command}), {})
        self.tool("file_system.read_file")
        context = self.vhook("posttool", **data)["hook_specific_output"]["additional_context"]
        self.assertIn("phase=verdict_ok", context)
        self.assertNotIn("phase=attempted", context)
        self.say("/elenchus:off")
        self.tool("file_system.read_file")
        self.assertIn("ELENCHUS OFF", self.vhook("posttool", **data)["hook_specific_output"]["additional_context"])

    def test_own_through_the_journal(self):
        self.assertEqual(self.cli("paper", "init", "--path", "docs/paper", "--name", "demo", sid="v").returncode, 0)
        fill(self.cwd / "docs" / "paper" / "main.typ")
        self.say("/elenchus:own Retry three times")
        self.tool("file_system.read_file")
        self.assertIn("not ready to own", self.cli("status", sid="v").stdout)
        self.say(f"/elenchus:own {TITLE}")
        self.tool("file_system.read_file")
        self.assertIn("OWN GATE", self.cli("status", sid="v").stdout)

    def test_an_idle_project_is_left_alone(self):
        self.say("just a normal task")
        self.assertEqual(self.tool("file_system.bash", command="make"), {})
        self.assertFalse((self.cwd / ".elenchus" / "sessions" / ("s-" + b"v".hex()) / "state.json").exists())


class Packaging(unittest.TestCase):
    def test_skill_names_survive_yaml(self):
        # `name: off` is the YAML boolean false: Vibe then refuses the skill, and off never works
        for f in PLUGIN.glob("skills/*/SKILL.md"):
            name = re.search(r'^name: (.+)$', f.read_text(encoding="utf-8"), re.M).group(1)
            self.assertEqual(name.strip('"'), f.parent.name)
            if name.lower() in ("off", "on", "yes", "no", "true", "false", "y", "n"):
                self.fail(f"{f}: quote the name")
            # `[a|b] <topic>` unquoted is invalid YAML: Claude Code shrugs, Vibe drops the skill
            for hint in re.findall(r'^argument-hint: (.+)$', f.read_text(encoding="utf-8"), re.M):
                self.assertRegex(hint, r'^".*"$', f)
        self.assertFalse((PLUGIN / "commands").exists(), "commands moved to skills, shared with Vibe")

    def test_vibe_manifest_and_hooks(self):
        manifest = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["$schema"].startswith("https://agent-plugins.org/schemas/1."))
        versions = {json.loads((PLUGIN / d / "plugin.json").read_text(encoding="utf-8"))["version"]
                    for d in (".", ".claude-plugin", ".codex-plugin")}
        self.assertEqual(len(versions), 1, versions)
        self.assertRegex(next(iter(versions)), r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
        hooks = (PLUGIN / "ai.mistral.vibe" / "hooks.toml").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'^command = "(.+)"$', hooks, re.M),
                         ["sh scripts/run.sh hook-pretool", "sh scripts/run.sh hook-posttool", "sh scripts/run.sh hook-stop"])
        self.assertEqual(len(re.findall(r"^strict = true$", hooks, re.M)), 1)


if __name__ == "__main__":
    unittest.main()
