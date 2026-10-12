#!/usr/bin/env python3
"""Exercise the real sh launcher, including Git Bash on Windows."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SH = shutil.which("sh")
if not SH and os.name == "nt":
    candidate = Path("C:/Program Files/Git/usr/bin/sh.exe")
    SH = str(candidate) if candidate.exists() else None


def posix(path):
    p = str(path).replace("\\", "/")
    return "/" + p[0].lower() + p[2:] if len(p) > 2 and p[1] == ":" else p


@unittest.skipUnless(SH, "sh is unavailable")
class Launcher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("ELENCHUS_TEST_TMP"))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / ".elenchus" / "sessions" / "s-6c61756e6368" / "state.json"
        self.state.parent.mkdir(parents=True)
        self.seed(True)
        self.payload = json.dumps({"cwd": str(self.root), "session_id": "launch", "tool_name": "Write",
                                   "tool_input": {"file_path": str(self.root / "a.py")}})
        self.env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PLUGIN_ROOT", "CLAUDE_PROJECT_DIR", "ELENCHUS_DIR")}
        self.env["ELENCHUS_DIR"] = str(self.root / ".elenchus")

    def seed(self, active):
        self.state.write_text(json.dumps({"active": active, "phase": "await_attempt", "mode": "explain"}), encoding="utf-8")

    def run_launcher(self, path, event="hook-pretool", plugin=None):
        env = {**self.env, "PATH": path}
        if plugin:
            env["CLAUDE_PLUGIN_ROOT"] = str(plugin)
        return subprocess.run([SH, str(ROOT / "scripts" / "run.sh"), event], input=self.payload,
                              capture_output=True, text=True, encoding="utf-8", env=env, cwd=self.root)

    def python_path(self):
        return posix(Path(sys.executable).parent) + ":/usr/bin:/bin" if os.name == "nt" else str(Path(sys.executable).parent) + ":/usr/bin:/bin"

    def test_real_python_passes_session_denial_through(self):
        result = self.run_launcher(self.python_path())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"deny"', result.stdout)

    def test_broken_store_style_stub_falls_back_to_python(self):
        bins = self.root / "bin"
        bins.mkdir()
        stub = bins / "python3"
        stub.write_bytes(b"#!/bin/sh\nexit 9\n")
        stub.chmod(0o755)
        result = self.run_launcher(posix(bins) + ":" + self.python_path())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"deny"', result.stdout)

    def test_missing_python_blocks_active_session_and_corrupt_state(self):
        # Git Bash ships shell utilities, but no Python. On POSIX use a tiny
        # utility-only PATH populated with links, excluding every Python launcher.
        if os.name == "nt":
            path = "/usr/bin:/bin"
        else:
            bins = self.root / "utilities"
            bins.mkdir()
            for name in ("cat", "sed", "dirname", "grep"):
                os.symlink(shutil.which(name), bins / name)
            path = str(bins)
        result = self.run_launcher(path)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("no working Python", result.stderr)
        self.state.write_text("{broken")
        self.assertEqual(self.run_launcher(path).returncode, 2)
        self.seed(False)
        self.assertEqual(self.run_launcher(path).returncode, 1)

    def test_engine_crash_blocks_active_session(self):
        plugin = self.root / "plugin"
        (plugin / "scripts").mkdir(parents=True)
        (plugin / "scripts" / "elenchus.py").write_text("import sys\nsys.exit(9)\n")
        result = self.run_launcher(self.python_path(), plugin=plugin)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("engine exited with code 9", result.stderr)
        self.assertEqual(self.run_launcher(self.python_path(), event="hook-stop", plugin=plugin).returncode, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
