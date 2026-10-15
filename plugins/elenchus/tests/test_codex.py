#!/usr/bin/env python3
"""Codex hook payloads against the shared engine.

Codex uses Claude Code's hook protocol but its own tool names: shell commands arrive as
tool "Bash" with a string, an argv list or a cmd field; file edits arrive as "apply_patch"
with the targets inside the patch text. Codex sets PLUGIN_ROOT, which switches the wording.
These tests replay that shape; they do not replace a live Codex session."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gates import Gates  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent


def patch(*paths):
    body = "".join(f"*** Update File: {p}\n@@\n-a\n+b\n" for p in paths)
    return "*** Begin Patch\n" + body + "*** End Patch\n"


class Codex(Gates):
    def setUp(self):
        super().setUp()
        self.env["PLUGIN_ROOT"] = self.env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN)

    # The inherited Gates tests also run here, now with Codex's environment.

    def open_gate(self):
        self.verdict()
        self.prompt("reflect: Session keys encrypt the data; certificates authenticate the peer.")
        self.assertEqual(self.accept().returncode, 0)
        self.assertEqual(self.state()["phase"], "open")

    def test_apply_patch_is_locked_until_assessed(self):
        self.prompt("elenchus learn explain TLS")
        self.assertTrue(self.denied("apply_patch", command=patch("notes.md")))
        self.open_gate()
        self.assertFalse(self.denied("apply_patch", command=patch("notes.md")))

    def test_apply_patch_cannot_touch_machinery_even_when_open(self):
        self.open_gate()
        self.assertTrue(self.denied("apply_patch", command=patch("notes.md", ".elenchus/sessions/x/state.json")))
        self.assertTrue(self.denied("apply_patch", command=patch(".codex/config.toml")))
        moved = "*** Begin Patch\n*** Update File: a.md\n*** Move to: .elenchus/state.json\n*** End Patch\n"
        self.assertTrue(self.denied("apply_patch", command=moved))

    def test_shell_input_shapes(self):
        self.prompt("elenchus learn explain TLS")
        self.assertTrue(self.denied("Bash", command="echo hi"))
        self.assertTrue(self.denied("Bash", command=["bash", "-lc", "echo hi"]))
        self.assertTrue(self.denied("Bash", cmd="echo hi"))
        self.open_gate()
        self.assertFalse(self.denied("Bash", command=["bash", "-lc", "echo hi"]))
        self.assertTrue(self.denied("Bash", command=["bash", "-lc", "cat .elenchus/state.json"]))
        self.assertTrue(self.denied("Bash", cmd="rm -rf .elenchus"))

    def test_read_only_codex_tools_stay_available(self):
        self.prompt("elenchus learn explain TLS")
        self.assertFalse(self.denied("update_plan", plan=[]))
        self.assertFalse(self.denied("view_image", path="diagram.png"))
        self.assertTrue(self.denied("spawn_agent", message="explain TLS"))

    def test_skill_mention_prefixes_start_a_gate(self):
        for i, text in enumerate(("$elenchus-learn explain TLS", "$elenchus:learn explain TLS", "elenchus learn explain TLS")):
            sid = f"p{i}"
            self.prompt(text, sid)
            s = self.state(sid)
            self.assertTrue(s["active"], text)
            self.assertEqual(s["mode"], "explain", text)

    def test_wording_names_codex(self):
        self.prompt("elenchus learn explain TLS")
        out = self.hook("session", source="startup").stdout + self.prompt("hello").stdout
        self.assertIn("shell tool", out)
        self.assertNotIn("Bash tool", out)

    def test_stop_output_is_json(self):
        self.prompt("elenchus learn explain TLS")
        r = self.hook("stop", last_assistant_message="# Lecture\n" + "word " * 200, stop_hook_active=False)
        self.assertEqual(json.loads(r.stdout)["decision"], "block")


if __name__ == "__main__":
    unittest.main()
