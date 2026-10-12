#!/usr/bin/env python3
"""Cross-OS, launcher and anti-leak tests for Elenchus.

Windows behaviour is simulated on any OS with ELENCHUS_FORCE_WIN=1 and Windows-style
payloads (C:\\ paths, backslashes, Git Bash /c/ paths). The real thing still needs one
run on a Windows machine, see the README.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN / "scripts" / "elenchus.py"
RUNSH = PLUGIN / "scripts" / "run.sh"
failures = []
CLEAN = ("CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_ROOT", "ELENCHUS_DIR", "ELENCHUS_FORCE_WIN", "PYTHONIOENCODING")


def env_with(**extra):
    e = {k: v for k, v in os.environ.items() if k not in CLEAN}
    e.update(extra)
    return e


def run(args, stdin="", cwd=None, win=False, edir=None, cmd=None, **envx):
    e = env_with(**envx)
    if win:
        e["ELENCHUS_FORCE_WIN"] = "1"
    if edir:
        e["ELENCHUS_DIR"] = str(edir)
    base = cmd or [sys.executable, str(SCRIPT)]
    return subprocess.run([*base, *args], input=stdin, env=e, capture_output=True,
                          text=True, encoding="utf-8", cwd=cwd)


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


W25 = " ".join(["word"] * 30)
W12 = " ".join(["agree"] * 14)


class Proj:
    """A throwaway project dir with a fixed state dir, so Windows-style cwd strings can be
    used in payloads without touching the real filesystem."""

    def __init__(self, win=False):
        self.dir = Path(tempfile.mkdtemp())
        self.edir = self.dir / ".elenchus"
        self.win = win

    def prompt(self, text, cwd=None):
        return run(["hook-prompt"], json.dumps({"prompt": text, "cwd": cwd or str(self.dir)}),
                   cwd=self.dir, win=self.win, edir=self.edir).stdout

    def tool(self, name, cwd=None, **inp):
        r = run(["hook-pretool"], json.dumps({"tool_name": name, "tool_input": inp,
                                              "cwd": cwd or str(self.dir)}),
                cwd=self.dir, win=self.win, edir=self.edir)
        return '"deny"' in r.stdout

    def stop(self, text=None, active=False, lam=True):
        payload = {"cwd": str(self.dir), "stop_hook_active": active}
        if text is not None and lam:
            payload["last_assistant_message"] = text
        elif text is not None:
            tp = self.dir / "t.jsonl"
            tp.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant",
                          "content": [{"type": "text", "text": text}]}}) + "\n")
            payload["transcript_path"] = str(tp)
        r = run(["hook-stop"], json.dumps(payload), cwd=self.dir, win=self.win, edir=self.edir)
        return r.stdout

    def session(self):
        return run(["hook-session"], json.dumps({"cwd": str(self.dir)}), cwd=self.dir,
                   win=self.win, edir=self.edir).stdout

    def cli(self, *args):
        r = run(list(args), cwd=self.dir, win=self.win, edir=self.edir)
        return r.returncode == 0, r.stdout

    def state(self):
        return json.loads((self.edir / "state.json").read_text(encoding="utf-8"))


def to_open(p, topic="x"):
    p.prompt(f"/elenchus:learn explain {topic}")
    p.prompt(W25)
    p.cli("challenge", "--text", "q")
    p.prompt(W25)
    p.cli("verdict", "--note", "n")
    p.prompt("agree: " + W12)
    p.cli("assess", "--result", "accept", "--mechanism", "Learner explained the mechanism.",
          "--transfer", "Learner applied it to a new case.", "--limit", "Learner named a limitation.", "--note", "Understanding checked.")


# ---------------------------------------------------------------- leak detection

def scenario_leaks():
    p = Proj()
    check("session hook silent when inactive", p.session() == "")
    p.prompt("/elenchus:learn explain TLS")
    s = p.session()
    check("session hook injects iron rules when active", "ELENCHUS IRON RULES" in s and "phase=await_attempt" in s)
    check("stop blocks code fence while locked", '"block"' in p.stop("Try this:\n```py\nx=1\n```\nWhy?"))
    check("stop blocks headings while locked", '"block"' in p.stop("# TLS\nIt works. Why?"))
    check("stop blocks 4+ list items while locked", '"block"' in p.stop("- a\n- b\n- c\n- d\nWhich one?"))
    check("stop allows 3 list items", '"block"' not in p.stop("- a\n- b\n- c\nWhich one?"))
    check("stop blocks long reply", '"block"' in p.stop(("word " * 300) + "?"))
    check("stop allows short question", '"block"' not in p.stop("What does the client verify first?"))
    check("uses last_assistant_message not stale transcript", '"block"' in p.stop("No question here.", lam=True))
    check("transcript fallback still works", '"block"' in p.stop("No question here.", lam=False))
    # idle phase: no gate, long answers are blocked
    to_open(p, "dns")
    p.stop("done")
    check("phase idle after open turn", p.state()["phase"] == "idle")
    check("idle: long answer blocked", '"block"' in p.stop("word " * 300))
    check("idle: code block blocked", '"block"' in p.stop("Here you go:\n```\nls\n```"))
    check("idle: short reply allowed", '"block"' not in p.stop("Port 53. Want to learn how it works?"))
    # violation accountability: Claude ignores the block (stop_hook_active=True)
    out = p.stop("word " * 300, active=True)
    check("ignored block warns the user", '"systemMessage"' in out and "ignored a rule" in out)
    check("violation counted", p.state()["violations"] == 1)
    brief = p.prompt("hello there")
    check("Claude is told about its violation once", "VIOLATION ON RECORD" in brief)
    check("violation note not repeated", "VIOLATION ON RECORD" not in p.prompt("hello again"))
    # predict mode extras
    q = Proj()
    q.prompt("/elenchus:learn predict slicing")
    (q.dir / "demo.py").write_text("print([1,2][1:])\n", encoding="utf-8")
    q.cli("prepare", "--runtime", "python", "--file", "demo.py", "--question", "What is printed, and why?")
    check("predict: stop blocked without predict: request", '"block"' in q.stop("Here is the code, it prints a list."))
    check("predict: code allowed in reply", '"block"' not in q.stop("```py\nprint([1,2][1:])\n```\nReply predict: what happens when this runs?"))
    # reconcile phase
    q.prompt("predict: " + W25)
    q.cli("run")
    q.stop("Output was [2]. Reply agree: what differed and why.")
    check("await_reconcile: statement without ask blocked", '"block"' in q.stop("The slice starts at index one."))
    check("await_reconcile: question allowed", '"block"' not in q.stop("Why did you expect index 0 to be included?"))


# ---------------------------------------------------------------- command markers

def scenario_markers():
    p = Proj()
    p.prompt("ELENCHUS-COMMAND learn explain Bayes theorem\n\nElenchus is starting. Load the skill.")
    check("expanded command body activates (marker form)", p.state()["active"] and p.state()["topic"] == "Bayes theorem")
    check("mode parsed from marker form", p.state()["mode"] == "explain")
    p.prompt("ELENCHUS-COMMAND off\n\nThe user turned Elenchus off.")
    check("expanded off body deactivates", not p.state()["active"])
    p.prompt("elenchus learn propose a plugin idea")
    check("plain text form still works", p.state()["active"] and p.state()["mode"] == "propose")
    for f in ("learn", "off", "status"):
        body = (PLUGIN / "commands" / f"{f}.md").read_text(encoding="utf-8")
        check(f"commands/{f}.md carries the marker", f"ELENCHUS-COMMAND {f}" in body)


# ---------------------------------------------------------------- windows paths

def scenario_windows():
    p = Proj(win=True)
    cwd = r"C:\Users\herin\Documents\proj"
    p.prompt("/elenchus:learn explain x", cwd=cwd)
    check("win: locked Write denied", p.tool("Write", cwd=cwd, file_path=cwd + r"\src\a.py"))
    to_open(p)
    check("win: open Write to normal file allowed", not p.tool("Write", cwd=cwd, file_path=cwd + r"\src\a.py"))
    check("win: open Write forward slashes allowed", not p.tool("Write", cwd=cwd, file_path="C:/Users/herin/Documents/proj/src/a.py"))
    check("win: .elenchus backslash denied", p.tool("Write", cwd=cwd, file_path=cwd + r"\.elenchus\state.json"))
    check("win: .elenchus forward slash denied", p.tool("Edit", cwd=cwd, file_path="C:/Users/herin/Documents/proj/.elenchus/state.json"))
    check("win: .elenchus odd case denied", p.tool("Edit", cwd=cwd, file_path=r"c:\USERS\herin\Documents\proj\.ELENCHUS\state.json"))
    check("win: Git Bash /c/ spelling denied", p.tool("Edit", cwd=cwd, file_path="/c/Users/herin/Documents/proj/.elenchus/state.json"))
    check("win: relative backslash path denied", p.tool("Write", cwd=cwd, file_path=r".elenchus\state.json"))
    check("win: dot-dot traversal denied", p.tool("Write", cwd=cwd, file_path=r"src\..\.elenchus\state.json"))
    check("win: .claude settings denied", p.tool("Write", cwd=cwd, file_path=r"C:\Users\herin\Documents\proj\.claude\settings.local.json"))
    check("win: plugin script denied", p.tool("Edit", cwd=cwd, file_path=str(SCRIPT).replace("/", "\\")))
    check("win: shell poke with backslashes denied", p.tool("Bash", cwd=cwd, command=r"type C:\Users\herin\Documents\proj\.elenchus\state.json"))
    check("win: shell poke PowerShell denied", p.tool("PowerShell", cwd=cwd, command=r"Set-Content .\.elenchus\state.json '{}'"))
    check("win: normal shell command allowed when open", not p.tool("Bash", cwd=cwd, command="git status"))


# ---------------------------------------------------------------- CLI allowlist forms

def scenario_cli_forms():
    p = Proj()
    p.prompt("/elenchus:learn explain x")
    sc = str(SCRIPT)
    ok = {
        "python3 plain": f'python3 "{sc}" status',
        "python plain": f'python "{sc}" status',
        "quoted exe path": f'"C:/Program Files/Python313/python.exe" "{sc}" status',
        "py launcher": f'py -3 "{sc}" status',
        "single quotes": f"python3 '{sc}' status",
        "args with quotes": f'python3 "{sc}" challenge --text "what if the cert is expired?"',
        "plugin root var": 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/elenchus.py" status',
    }
    for name, c in ok.items():
        check(f"cli allowed: {name}", not p.tool("Bash", command=c))
    check("cli allowed: PowerShell call operator", not p.tool("PowerShell", command=f'& python "{sc}" status'))
    bad = {
        "chain semicolon": f'python3 "{sc}" status; id',
        "chain and": f'python3 "{sc}" status && id',
        "pipe": f'python3 "{sc}" status | sh',
        "redirect": f'python3 "{sc}" status > /tmp/x',
        "subshell": f'python3 "{sc}" status $(id)',
        "backtick": f'python3 "{sc}" status `id`',
        "var in dq": f'python3 "{sc}" challenge --text "$HOME"',
        "newline": f'python3 "{sc}" status\nid',
        "escaped quote trick": f'python3 "{sc}" status "a\\" ; id ; echo "b"',
        "wrong script": 'python3 /tmp/other.py status',
        "wrong subcommand": f'python3 "{sc}" hook-pretool',
        "python -c": f'python3 -c "print(1)" "{sc}" status',
        "unquoted backslash": f'python3 {sc}\\x status',
    }
    for name, c in bad.items():
        check(f"cli denied: {name}", p.tool("Bash", command=c))
    check("cli denied: PowerShell trailing &", p.tool("PowerShell", command=f'python "{sc}" status & whoami'))
    check("cli denied: PowerShell dollar var", p.tool("PowerShell", command=f'& python "{sc}" status "$env:USERPROFILE"'))


# ---------------------------------------------------------------- encoding

def scenario_encoding():
    p = Proj()
    e = env_with(PYTHONIOENCODING="cp1252", ELENCHUS_DIR=str(p.edir))
    text = "/elenchus:learn explain Verst\u00e4ndnis \u00fcberpr\u00fcfen \u00df \U0001F642"
    r = subprocess.run([sys.executable, str(SCRIPT), "hook-prompt"], input=json.dumps({"prompt": text, "cwd": str(p.dir)}),
                       env=e, capture_output=True, text=True, encoding="utf-8", cwd=p.dir)
    check("umlauts and emoji survive a cp1252 console", r.returncode == 0 and "Verst" in p.state()["topic"])
    check("topic stored intact", p.state()["topic"] == "Verst\u00e4ndnis \u00fcberpr\u00fcfen \u00df \U0001F642")
    out = json.loads(r.stdout)
    check("hook output is valid JSON", "additionalContext" in out["hookSpecificOutput"])
    bom = subprocess.run([sys.executable, str(SCRIPT), "hook-prompt"], input="\ufeff" + json.dumps({"prompt": W25, "cwd": str(p.dir)}),
                         env=e, capture_output=True, text=True, encoding="utf-8", cwd=p.dir)
    check("UTF-8 BOM on stdin tolerated", bom.returncode == 0 and "ELENCHUS" in bom.stdout)
    # cards: German text, LF line endings
    to_open(p, "Datenschutz")
    ok, _ = p.cli("cards", "add", "--front", "Was bedeutet Gew\u00e4hrleistung?", "--back", "Zusicherung \u00fcber Eigenschaften")
    raw = (p.edir / "anki" / "basic.tsv").read_bytes()
    check("anki file written with LF only", ok and b"\r\n" not in raw)
    check("anki file is UTF-8", "Gew\u00e4hrleistung".encode("utf-8") in raw)
    check("state dir gitignored", (p.edir / ".gitignore").read_text() == "*\n")


# ---------------------------------------------------------------- launcher

def make_plugin_copy():
    d = Path(tempfile.mkdtemp()) / "plugin"
    shutil.copytree(PLUGIN, d, ignore=shutil.ignore_patterns(".git", "__pycache__", "tests"))
    return d


def sh_run(plugin, args, stdin="", path=None, **envx):
    e = env_with(**envx)
    if path is not None:
        e["PATH"] = path
    return subprocess.run(["/bin/sh", str(plugin / "scripts" / "run.sh"), *args], input=stdin, env=e,
                          capture_output=True, text=True, encoding="utf-8")


def active_project():
    p = Proj()
    p.prompt("/elenchus:learn explain x")
    return p


def scenario_launcher():
    if not Path("/bin/sh").exists():
        print("SKIP launcher tests (no /bin/sh)")
        return
    plug = make_plugin_copy()
    p = active_project()
    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "x"}, "cwd": str(p.dir)})
    r = sh_run(plug, ["hook-pretool"], payload, ELENCHUS_DIR=str(p.edir))
    check("run.sh passes a deny through", r.returncode == 0 and '"deny"' in r.stdout)
    r = sh_run(plug, ["hook-pretool"], payload, ELENCHUS_DIR=str(p.edir), CLAUDE_PLUGIN_ROOT=str(plug))
    check("run.sh honours CLAUDE_PLUGIN_ROOT", r.returncode == 0 and '"deny"' in r.stdout)
    wp = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "C:\\Users\\a\\x.py"}, "cwd": "C:\\Users\\a"})
    r = sh_run(plug, ["hook-pretool"], wp, ELENCHUS_DIR=str(p.edir))
    check("run.sh survives backslashes in payload", r.returncode == 0 and '"deny"' in r.stdout)

    bins = Path(tempfile.mkdtemp())
    stub = bins / "python3"
    stub.write_text("#!/bin/sh\nexit 9\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    os.symlink(sys.executable, bins / "python")
    base = os.environ.get("PATH", "/usr/bin:/bin")
    r = sh_run(plug, ["hook-pretool"], payload, path=f"{bins}:{base}", ELENCHUS_DIR=str(p.edir))
    check("run.sh skips a broken python3 stub and uses python", r.returncode == 0 and '"deny"' in r.stdout)

    nopy = Path(tempfile.mkdtemp())
    for tool_name in ("sed", "dirname", "grep"):
        w = shutil.which(tool_name)
        if w:
            os.symlink(w, nopy / tool_name)
    r = sh_run(plug, ["hook-pretool"], payload, path=str(nopy), CLAUDE_PROJECT_DIR=str(p.dir))
    check("no python + active gate: pretool fails closed (exit 2)", r.returncode == 2 and "no working Python" in r.stderr)
    r = sh_run(plug, ["hook-prompt"], payload, path=str(nopy), CLAUDE_PROJECT_DIR=str(p.dir))
    check("no python: other hooks exit 1 (non-blocking, visible)", r.returncode == 1)
    idle = Proj()
    (idle.edir).mkdir(parents=True)
    (idle.edir / "state.json").write_text(json.dumps({"active": False}, indent=2))
    r = sh_run(plug, ["hook-pretool"], payload, path=str(nopy), CLAUDE_PROJECT_DIR=str(idle.dir))
    check("no python + inactive gate: pretool does not block", r.returncode == 1)
    r = sh_run(plug, ["hook-pretool"], payload, path=str(nopy), CLAUDE_PROJECT_DIR=str(Path(tempfile.mkdtemp())))
    check("no python + never started: pretool does not block", r.returncode == 1)

    (plug / "scripts" / "elenchus.py").write_text("import sys\nsys.exit(1)\n")
    r = sh_run(plug, ["hook-pretool"], payload, CLAUDE_PROJECT_DIR=str(p.dir))
    check("engine crash + active gate: pretool fails closed", r.returncode == 2 and "exited with code 1" in r.stderr)
    r = sh_run(plug, ["hook-stop"], payload, CLAUDE_PROJECT_DIR=str(p.dir))
    check("engine crash: stop hook exits 1, not 2", r.returncode == 1)


# ---------------------------------------------------------------- packaging

def scenario_packaging():
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    check("hooks.json covers 4 events", set(hooks) == {"SessionStart", "UserPromptSubmit", "PreToolUse", "Stop"})
    cmds = [h["command"] for ev in hooks.values() for g in ev for h in g["hooks"]]
    check("every hook goes through run.sh", all(c.startswith('sh "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" hook-') for c in cmds))
    for f in ("scripts/run.sh", "scripts/elenchus.py", "hooks/hooks.json"):
        check(f"{f} has LF line endings", b"\r" not in (PLUGIN / f).read_bytes())
    check(".gitattributes forces LF for sh and py", "*.sh text eol=lf" in (PLUGIN.parent / ".gitattributes").read_text())
    skill = (PLUGIN / "skills" / "socratic" / "SKILL.md").read_text(encoding="utf-8")
    check("skill has pre-flight check and rationalization table", "Pre-flight check" in skill and "Rationalizations" in skill)
    allfiles = [p for p in PLUGIN.rglob("*") if p.is_file() and ".git" not in p.parts and p.suffix in (".py", ".md", ".sh", ".json")]
    check("no em-dashes anywhere", not [p for p in allfiles if "\u2014" in p.read_text(encoding="utf-8")])


def scenario_nudges():
    """The mid-flow stop-hook line: tagged, short, no double question after imperative asks."""
    p = Proj()
    p.prompt("/elenchus:learn explain tls")
    first = "Good topic. Name one thing you already believe about how a TLS handshake starts."
    check("imperative ask is not blocked", '"block"' not in p.stop(first))
    check("question mark ask is not blocked", '"block"' not in p.stop("What do you think a handshake is for?"))
    for t in ("Say it in one sentence.", "Intro text here. Now explain it from scratch.",
              "Some context.\nPredict what you think happens."):
        check("imperative variant accepted: " + t[:28].replace("\n", " "), '"block"' not in p.stop(t))
    lecture = "A TLS handshake negotiates keys between client and server and then both sides encrypt traffic."
    out = p.stop(lecture)
    check("lecture without an ask is blocked", '"block"' in out)
    check("lecture is blocked for the missing ask", "no ask for the user" in out)
    check("block reason carries the [+] tag", "[+] Elenchus:" in out)
    check("block reason tells Claude not to repeat", "Do not repeat" in out)
    check("far-away demand word is not accepted",
          '"block"' in p.stop("Name it. " + ("The handshake negotiates keys and ciphers. " * 20)))
    check("mid-sentence demand word is not accepted",
          '"block"' in p.stop("The server will name the cipher and then encrypt everything that follows afterwards."))
    short = "That waits until this gate is done. What does the client send first, and why?"
    check("short clean reply passes", '"block"' not in p.stop(short))
    check("reply over 80 words is blocked", '"block"' in p.stop("Context. " * 90 + "What is it?"))
    out2 = p.stop(lecture, active=True)
    check("ignored block warns with [+] tag", "[+] Elenchus warning:" in out2)
    check("warning has no doubled tag", "[+] Elenchus: " not in out2)


for fn in (scenario_leaks, scenario_markers, scenario_windows, scenario_cli_forms,
           scenario_encoding, scenario_launcher, scenario_packaging, scenario_nudges):
    fn()

print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
