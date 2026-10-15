#!/usr/bin/env python3
"""Elenchus gate engine for Mistral Vibe (cross-platform: Linux, macOS, Windows via Git Bash).

Hook handlers: hook-pretool, hook-postagent, and hook-prompt (the prompt core,
kept as a direct entry point for tests and future Vibe hook events).
CLI: gate, challenge, verdict, assess, prepare, run, question, status, cards.

Vibe offers only pre_tool and post_agent hooks, so the engine reads the user's
typed words from the session transcript. The first tool call of a turn records
attempts, predictions and reflections before the reply is written, and
post_agent reviews the finished reply. Gate state lives in
.elenchus/sessions/<session-key>/state.json. Only recorded user text can move
a gate. The agent registers its own moves and assesses a recorded reflection.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import os
import posixpath
import re
import sys
import time
import tempfile
import subprocess
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parent.parent
WIN = os.name == "nt" or os.environ.get("ELENCHUS_FORCE_WIN") == "1"

MODES = ("explain", "predict", "propose")
MIN_ROUNDS = {"explain": 1, "propose": 2}
MAX_WORDS = int(os.environ.get("ELENCHUS_MAX_WORDS", "80"))
CLI_CMDS = ("gate", "challenge", "verdict", "assess", "prepare", "run", "question", "status", "cards")


# ---------------------------------------------------------------- paths

def fwd(p: str, base: str = "") -> str:
    """Normalize any path spelling to one comparable form: forward slashes, lower case,
    no dot segments. Understands C:\\x, C:/x and (on Windows) Git Bash /c/x."""
    p = (p or "").replace("\\", "/")
    if WIN:
        m = re.match(r"^/([A-Za-z])(/.*)?$", p)
        if m:
            p = f"{m.group(1)}:{m.group(2) or '/'}"
    if not (re.match(r"^[A-Za-z]:/", p) or p.startswith("/")):
        b = (base or os.getcwd()).replace("\\", "/")
        p = b.rstrip("/") + "/" + p
    return posixpath.normpath(p).lower()


def slashes(p: str) -> str:
    return str(p).replace("\\", "/")


ROOT_RAW = slashes(ROOT)
ROOT_F = fwd(str(ROOT))
_m = re.match(r"^([a-z]):(/.*)$", ROOT_F)
ROOT_M = f"/{_m.group(1)}{_m.group(2)}" if _m else ""  # Git Bash spelling of the plugin dir
SCRIPT_F = fwd(str(SCRIPT))
CLI = f'"{slashes(sys.executable) or "python3"}" "{slashes(SCRIPT)}"'

# ---------------------------------------------------------------- policy

READ_TOOLS = {
    "read", "read_file", "grep", "glob", "ls", "web_search", "web_fetch", "skill",
    "todo", "ask_user_question", "search_tool_functions", "tool_search",
    "unified_harness_scratchpad", "self.sleep",
    "process.output", "process.list",
    "bash_output", "bash_sessions", "bash_log_file",
    "git_bash_output", "git_bash_sessions", "git_bash_log_file",
    "powershell_output", "powershell_sessions", "powershell_log_file",
}
WRITE_TOOLS = {"write_file", "edit", "run_typescript"}
SHELL_TOOLS = {"bash", "git_bash", "powershell"}
MCP_READ = re.compile(r"(search|read|fetch|get|list|query)", re.I)
MCP_WRITE = re.compile(
    r"(create|update|delete|write|send|move|upload|share|trash|copy|spawn|stop|"
    r"restore|duplicate|convert|insert|post|publish|commit|stage|bash|exec|run)", re.I)

CTRL_RE = re.compile(
    r"^\s*(?:/elenchus:|elenchus[:\s]+|ELENCHUS-COMMAND\s+)(learn|off|status|focus|cards)\b([^\n]*)", re.I)
AGREE_RE = re.compile(r"^\s*agree\s*:\s*(.+)$", re.I | re.S)
REFLECT_RE = re.compile(r"^\s*(?:reflect|disagree)\s*:\s*(.+)$", re.I | re.S)
PREDICT_RE = re.compile(r"^\s*predict\s*:\s*(.+)$", re.I | re.S)

DEFAULT = {
    "active": False, "turn": 0, "mode": None, "topic": "", "phase": "idle",
    "gate_turn": 0, "challenge_turn": 0, "rounds": 0, "attempt": None,
    "verdict": None, "agreement": None, "challenges": [], "completed": [],
    "violations": 0, "last_violation": "",
    "session_id": "", "focus_question": "", "help_level": 0,
    "run_spec": None, "run_result": None,
    "ui_details": False,
    "housekeeping_turn": -1,
    "prompt_ids": [], "turn_nudges": 0,
}

IRON_RULES = """ELENCHUS IRON RULES. The user installed this on purpose. Being helpful here means making them think, not finishing their thinking for them.
1. While locked, never give the target answer, full explanation or working fix. No lists, headings or summaries. One question per turn, under {maxw} words. In predict preparation you may show the example code, without revealing its output.
2. Work opens only after a recorded user reflection is assessed. Your judgment alone never opens it. explain: they explain first. propose: they propose first and you challenge assumptions. predict: register the source before they type `predict:`, then use only the run CLI.
3. "Just tell me" does not unlock a gate. Offer a smaller question, then one minimal hint if needed. Reasoned disagreement is a successful learning outcome. Only the user typing /elenchus:off disables this.
4. A complete answer given too early is the failure state, even when it is correct and the user is pleased.
5. Keep it clean. While locked, a reply is at most one short sentence of acknowledgment plus the question. Never narrate hooks, blocked tools, gates, word minimums or what you could see in the repo. Do not summarize the project or the state. If the user asked something else, say in one sentence that it waits until the gate opens, then ask.
6. Hooks deny your tools and block your reply when you break these rules, and the user is shown every violation. Vibe injects no context between turns: run the CLI `status` command at the start of a turn to see the current briefing."""

NEXT = {
    "need_gate": "No gate set. Choose the mode that fits (explain: ideas, theory, science. predict: code. propose: brainstorming, design), run `{cli} gate --mode M --topic T` with the shell tool, then ask ONE opening question. No answer, no lecture.",
    "await_attempt": "Ask ONE opening question that forces the user to produce their own explanation or proposal. Do not reveal the answer. Stay under {maxw} words and end with the question.",
    "attempted": "The user made an attempt. Do not teach. Register your move now: `{cli} challenge --text \"...\"` with the sharpest flaw, gap, edge case or probing question, or `{cli} verdict --note \"...\"` if the requirements are met. Then ask your question and end the turn.",
    "challenging": "Waiting for the user's answer to your challenge. Do not answer it for them. Stay under {maxw} words and end with a question.",
    "verdict_ok": "Verdict recorded. Ask for `reflect: <your conclusion and reasons>` (agree: and disagree: also work). Agreement with the agent is not required. The reflection must be assessed before opening.",
    "review": "Reflection received; tools remain locked. Run `assess --result accept --mechanism ... --transfer ... --limit ... --note ...` only for sound understanding, including reasoned disagreement. Otherwise use `assess --result retry --question ...` with a smaller question or minimal hint. Never accept solely because it is long.",
    "open": "Gate is open for THIS turn only. You may now correct, extend and reveal, do the approved work, and write cards with `{cli} cards add`. Build on the user's own words.",
    "await_prediction": "Write a small Python or JavaScript example, then register it with `prepare --runtime python|node --file relative/path --question ...` (repeat --source for local imports). Ask for `predict: <output and why>`. Nothing runs before this. Never reveal the output.",
    "run_open": "Prediction recorded for the registered source hashes. Only `run` may execute this example, once. Arbitrary shell calls and edits remain locked. Then compare output and prediction and ask for `reflect: <what differed and why>`.",
    "await_reconcile": "Waiting for the user's reflection (reflect:, agree:, disagree: or plain reasoning). Keep runs and edits locked. Ask one question. The reflection will be assessed before completion.",
    "idle": "No open gate. Any new question or task needs `{cli} gate --mode M --topic T` first. Do not answer at length without it.",
}


# ---------------------------------------------------------------- state

def words(text: str) -> int:
    return len(text.split())


def session_key(session_id: str) -> str:
    if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", session_id):
        raise ValueError("Invalid session id")
    return "s-" + session_id.encode("utf-8").hex()


def project_dir(d: Path) -> Path:
    return d.parent.parent if d.parent.name == "sessions" else d


def state_dir(cwd, session_id="") -> Path:
    env = os.environ.get("ELENCHUS_DIR")
    if env:
        base_dir = Path(env)
        return base_dir / "sessions" / session_key(session_id) if session_id else base_dir
    base = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("VIBE_PROJECT_DIR") or cwd or os.getcwd())
    try:
        start = base.resolve()
    except OSError:
        start = base
    for d in (start, *start.parents):
        if (d / ".elenchus").is_dir():
            base_dir = d / ".elenchus"
            break
    else:
        base_dir = start / ".elenchus"
    return base_dir / "sessions" / session_key(session_id) if session_id else base_dir


@contextmanager
def locked(d: Path):
    """OS advisory lock, released even after a crash. One transaction per session."""
    d.mkdir(parents=True, exist_ok=True)
    gi = project_dir(d) / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n", encoding="utf-8")
    with (d / ".lock").open("a+b") as f:
        if os.name == "nt":
            import msvcrt
            # Reading the byte before acquiring it fails when another Windows
            # process owns the lock. Inspect length without touching that byte.
            f.seek(0, os.SEEK_END)
            if f.tell() == 0:
                f.write(b"0")
                f.flush()
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


def history(d: Path):
    entries = []
    root = project_dir(d)
    legacy = root / "state.json"
    try:
        entries.extend(json.loads(legacy.read_text(encoding="utf-8")).get("completed", []))
    except (OSError, ValueError, AttributeError):
        pass
    for path in (root / "history").glob("*.json"):
        try:
            entries.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    unique = {c.get("id", json.dumps(c, sort_keys=True)): c for c in entries if isinstance(c, dict)}
    return sorted(unique.values(), key=lambda c: c.get("created", 0))[-200:]


def load(d: Path) -> dict:
    s = copy.deepcopy(DEFAULT)
    f = d / "state.json"
    if f.exists():
        try:
            value = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not isinstance(value.get("active", False), bool):
                raise ValueError("Invalid state schema")
            if value.get("phase", "idle") not in NEXT:
                raise ValueError("Unknown phase")
            s.update(value)
        except (ValueError, OSError):
            s.update(active=True, phase="idle", mode=None)  # corrupt state fails closed
    if d.parent.name == "sessions":
        s["completed"] = history(d)
    return s


def save(d: Path, s: dict) -> None:
    d.mkdir(parents=True, exist_ok=True)
    gi = project_dir(d) / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n", encoding="utf-8")
    tmp = d / ("state." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
    for i in range(6):  # Windows: antivirus or indexers can hold the file for a moment
        try:
            os.replace(tmp, d / "state.json")
            return
        except PermissionError:
            time.sleep(0.05 * (i + 1))
    os.replace(tmp, d / "state.json")


def reset_gate(s: dict) -> None:
    s.update(rounds=0, attempt=None, verdict=None, agreement=None, challenges=[], challenge_turn=0)
    s.update(focus_question="", help_level=0, run_spec=None, run_result=None)


def complete(d: Path, s: dict, how: str) -> None:
    v, a = s["verdict"] or {}, s["agreement"] or {}
    record = {
        "id": uuid.uuid4().hex, "created": time.time(), "session_id": s["session_id"],
        "topic": s["topic"], "mode": s["mode"], "rounds": s["rounds"], "how": how,
        "turn": s["turn"], "note": v.get("note", ""), "missed": v.get("missed", ""),
        "own_words": a.get("text", ""),
        "evidence": v.get("evidence", {}), "prediction": (s["attempt"] or {}).get("text", ""),
    }
    dest = project_dir(d) / "history"
    dest.mkdir(parents=True, exist_ok=True)
    tmp = dest / (record["id"] + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, dest / (record["id"] + ".json"))
    s["completed"].append(record)
    s["completed"] = s["completed"][-200:]


def cli_prefix(s):
    return CLI + (f' --session "{s["session_id"]}"' if s["session_id"] else "")


def latest_session(base: Path) -> str:
    """The most recently written session id under a project's .elenchus directory.
    Vibe has no prompt hook to tell the model its session id, so a bare `status`
    adopts the newest session and its briefing prints the exact CLI prefix."""
    sessions = base / "sessions"
    if not sessions.is_dir():
        return ""
    best, best_mtime = "", -1.0
    for d in sessions.iterdir():
        try:
            if d.is_dir() and d.name.startswith("s-"):
                m = (d / "state.json").stat().st_mtime
                if m > best_mtime:
                    best, best_mtime = d.name[2:], m
        except OSError:
            continue
    try:
        return bytes.fromhex(best).decode("utf-8", "replace") if best else ""
    except ValueError:
        return ""


def fmt(key: str, s=None) -> str:
    return NEXT[key].format(cli=cli_prefix(s) if s else CLI, maxw=MAX_WORDS)


def briefing(s: dict, note: str = "") -> str:
    mode = s["mode"]
    lines = [
        f"ELENCHUS | mode={mode or 'unset'} | topic={s['topic']!r} | phase={s['phase']} | "
        f"rounds={s['rounds']}/{MIN_ROUNDS.get(mode, 0)}",
        f"CLI (run it with the shell tool, exactly this prefix): {cli_prefix(s)}",
    ]
    if note:
        lines.append(f"Hook note: {note}")
    if s.get("last_violation"):
        lines.append(f"VIOLATION ON RECORD: last turn you broke a rule ({s['last_violation']}). The user was shown a warning. Do not repeat it.")
    lines.append(f"Next: {fmt(s['phase'], s)}")
    if s["focus_question"]:
        lines.append(f"Pinned question: {s['focus_question']}")
    lines.append("A concise answer counts. Judge mechanism, transfer and limits, never length. Accept reasoned disagreement. Register questions with `question --text ...`; hints progress from a smaller question to one minimal hint.")
    lines.append(f"Reminder: while locked, no target answers, no lists or headings, one question, under {MAX_WORDS} words. Example code is allowed during predict preparation. "
                 "A blocked tool means you owe the user a question, not a workaround. Vibe injects no context between turns, so run `status` when a turn starts.")
    return "\n".join(lines)


# ---------------------------------------------------------------- output

def out(obj) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


def deny(reason: str) -> None:
    out({"decision": "deny", "reason": reason})


# ---------------------------------------------------------------- transcript

def transcript_entries(path):
    """Read chat entries from a Vibe session journal (JSONL with
    projection_delta and core_input records) or a Claude-style transcript.
    Returns [{"id", "role", "source", "text"}] in conversation order, entries
    with no text omitted. Vibe journals rotate through numbered files, so a
    directory is read as a whole."""
    if not path:
        return []
    p = Path(path)
    files = sorted(p.glob("*.jsonl")) if p.is_dir() else [p]
    entries, core = [], []
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict):
                continue
            if o.get("type") == "projection_delta":
                for d in (o.get("payload") or {}).get("delta") or []:
                    e = d.get("entry") or {}
                    if not isinstance(e, dict):
                        continue
                    text = "\n".join(c.get("text", "") for c in e.get("content") or []
                                     if isinstance(c, dict) and c.get("type") == "text")
                    if text.strip():
                        entries.append({"id": e.get("id") or "", "role": e.get("role"),
                                        "source": e.get("source") or "", "text": text})
            elif o.get("type") == "core_input":
                cmd = ((o.get("payload") or {}).get("input") or {}).get("command") or {}
                if cmd.get("type") == "user_message":
                    text = "\n".join(c.get("text", "") for c in cmd.get("content") or []
                                     if isinstance(c, dict) and c.get("type") == "text")
                    if text.strip():
                        core.append({"id": cmd.get("turn_id") or "", "role": "user",
                                     "source": "core_input", "text": text})
            else:
                msg = o.get("message")
                if isinstance(msg, dict) and msg.get("role") in ("user", "assistant"):
                    c = msg.get("content")
                    if isinstance(c, str):
                        text = c
                    elif isinstance(c, list):
                        text = "\n".join(b.get("text", "") for b in c
                                         if isinstance(b, dict) and b.get("type") == "text")
                    else:
                        text = ""
                    if text.strip():
                        entries.append({"id": "", "role": msg["role"], "source": "", "text": text})
    if not any(e["role"] == "user" for e in entries):
        entries.extend(core)  # older journals record input only, no projection
    return entries


def last_assistant(path):
    for e in reversed(transcript_entries(path)):
        if e["role"] == "assistant":
            return e["text"]
    return None


# ---------------------------------------------------------------- prompt core

def start(s: dict, rest: str) -> None:
    toks = rest.strip().split(None, 1)
    mode, topic = None, rest.strip()
    if toks and toks[0].lower() in MODES:
        mode = toks[0].lower()
        topic = toks[1].strip() if len(toks) > 1 else ""
    elif toks and toks[0].lower() == "auto":
        topic = toks[1].strip() if len(toks) > 1 else ""
    reset_gate(s)
    s.update(active=True, mode=mode, topic=topic or "(open)", gate_turn=s["turn"], last_violation="")
    s["phase"] = "need_gate" if mode is None else ("await_prediction" if mode == "predict" else "await_attempt")


def on_agree(s: dict, text: str) -> str:
    if s["phase"] not in ("verdict_ok", "await_reconcile", "review"):
        return f"Reflection ignored in phase {s['phase']}."
    if not meaningful(text):
        return "No reasoning yet. Ask one smaller question; do not demand extra words."
    s["agreement"] = {"turn": s["turn"], "text": text[:4000]}
    s["phase"] = "review"
    return "Reflection RECORDED, not accepted. Assess its reasoning; disagreement is welcome."


def meaningful(text):
    return bool(re.search(r"\w", text)) and text.strip().lower().rstrip(".! ") not in {
        "yes", "no", "ok", "okay", "ja", "nein", "sure", "agree", "thanks", "danke",
    }


def on_predict(s: dict, text: str) -> str:
    if s["phase"] != "await_prediction":
        return f"predict: IGNORED in phase {s['phase']}."
    if not meaningful(text):
        return "Prediction needs a reason, not a word minimum. Running stays blocked."
    if not s["run_spec"]:
        return "Register the code with prepare first, then ask the user to predict that exact example."
    s["attempt"] = {"turn": s["turn"], "text": text[:1500]}
    s["phase"] = "run_open"
    return "predict: RECORDED. Only the registered example may run once, through the run CLI."


def on_text(s: dict, text: str) -> str:
    ph, mode = s["phase"], s["mode"]
    if mode in ("explain", "propose") and ph in ("await_attempt", "challenging", "attempted"):
        if not meaningful(text):
            return "No attempt yet. Offer a smaller question."
        s["attempt"] = {"turn": s["turn"], "text": text[:1500]}
        s["phase"] = "attempted"
        return "User attempt RECORDED. Evaluate its reasoning, regardless of length."
    if ph == "verdict_ok":
        if meaningful(text):
            s["phase"] = "attempted"
            s["verdict"] = None
            s["attempt"] = {"turn": s["turn"], "text": text[:1500]}
            return "The user pushed back instead of agreeing. Verdict withdrawn. Answer the objection, then challenge or accept again."
        return "Ask for the user's own conclusion; agreement is not required."
    if ph in ("await_reconcile", "review"):
        return on_agree(s, text)
    return ""


def handle_prompt_text(s: dict, prompt: str) -> str:
    """The UserPromptSubmit core: only the user's own typed words move a gate.
    Returns a hook note. Vibe has no prompt hook, so callers feed transcript
    text through here instead."""
    prompt = (prompt or "").strip()
    s["turn_nudges"] = 0
    m = CTRL_RE.match(prompt)
    if m:
        verb, rest = m.group(1).lower(), m.group(2)
        s["turn"] += 1
        if verb == "off":
            s.update(active=False, phase="idle", last_violation="")
            return "off"
        if verb == "learn":
            start(s, rest)
        if verb == "focus":
            if rest.strip().lower() in ("full", "compact"):
                s["ui_details"] = rest.strip().lower() == "full"
        if verb in ("status", "focus", "cards"):
            s["housekeeping_turn"] = s["turn"]
        return verb
    if not s["active"]:
        return ""
    s["turn"] += 1
    am, pm = AGREE_RE.match(prompt) or REFLECT_RE.match(prompt), PREDICT_RE.match(prompt)
    if am:
        note = on_agree(s, am.group(1).strip())
    elif pm:
        note = on_predict(s, pm.group(1).strip())
    else:
        note = on_text(s, prompt)
    s["last_violation"] = ""  # shown to the agent once
    return note


def process_user_entries(p: dict, s: dict) -> bool:
    """Record unseen user messages and return whether anything changed. A
    'prompt' payload key overrides the transcript, so tests and future Vibe
    hook events can drive the engine directly."""
    if isinstance(p.get("prompt"), str) and p["prompt"].strip():
        handle_prompt_text(s, p["prompt"])
        return True
    seen = list(s.get("prompt_ids") or [])
    known = set(seen)
    fresh = False
    for e in transcript_entries(p.get("transcript_path")):
        if e["role"] != "user" or e["source"] in ("harness", "system", "tool"):
            continue
        text = e["text"].strip()
        if text.startswith(TAG) or re.match(r"^ELENCHUS[\s:]", text):
            continue  # hook-injected retries are not learner words
        key = e["id"] or "h" + hashlib.sha256(text[:400].encode("utf-8")).hexdigest()[:32]
        if key in known:
            continue
        handle_prompt_text(s, text)
        seen.append(key)
        known.add(key)
        fresh = True
    s["prompt_ids"] = seen[-64:]
    return fresh


def hook_prompt(p: dict) -> None:
    d = state_dir(p.get("cwd"), p.get("session_id", ""))
    s = load(d)
    s["session_id"] = p.get("session_id", "")
    if process_user_entries(p, s):
        save(d, s)


# ---------------------------------------------------------------- tool hook

def is_python(tok: str) -> bool:
    b = re.sub(r"\.exe$", "", posixpath.basename(slashes(tok)).lower())
    return re.fullmatch(r"python(3(\.\d+)?)?|py", b) is not None


def tokenize(cmd: str, ps: bool = False):
    """Split a command line into tokens, or return None when it contains anything that
    could chain, redirect, substitute or expand. Quotes are honoured without escape
    processing so Windows paths with backslashes survive."""
    toks, cur, started = [], [], False
    i, n = 0, len(cmd)
    while i < n:
        ch = cmd[i]
        if ch == "'":
            j = cmd.find("'", i + 1)
            if j < 0:
                return None
            cur.append(cmd[i + 1:j])
            started = True
            i = j + 1
            continue
        if ch == '"':
            j = i + 1
            while j < n and cmd[j] != '"':
                if cmd[j] in "$`\r\n":
                    return None
                if cmd[j] == "\\" and j + 1 < n and cmd[j + 1] == '"':
                    return None
                j += 1
            if j >= n:
                return None
            cur.append(cmd[i + 1:j])
            started = True
            i = j + 1
            continue
        if ch in " \t":
            if started:
                toks.append("".join(cur))
                cur, started = [], False
            i += 1
            continue
        if ch == "&" and ps and not toks and not started:
            toks.append("&")
            i += 1
            continue
        if ch in "\r\n;|&<>()`${}" or (ch == "\\" and not ps):
            return None
        cur.append(ch)
        started = True
        i += 1
    if started:
        toks.append("".join(cur))
    return toks


def is_cli(cmd: str, ps: bool = False, cwd: str = "", session_id: str = "") -> bool:
    c = (cmd.replace("${CLAUDE_PLUGIN_ROOT}", ROOT_RAW).replace("$CLAUDE_PLUGIN_ROOT", ROOT_RAW)
            .replace("${PLUGIN_ROOT}", ROOT_RAW).replace("$PLUGIN_ROOT", ROOT_RAW))
    toks = tokenize(c, ps)
    if not toks:
        return False
    if toks[0] == "&":
        toks = toks[1:]
    if len(toks) < 3 or not is_python(toks[0]):
        return False
    base = re.sub(r"\.exe$", "", posixpath.basename(slashes(toks[0])).lower())
    i = 2 if (base == "py" and toks[1].startswith("-")) else 1
    if len(toks) <= i + 1:
        return False
    if fwd(toks[i], cwd) != SCRIPT_F:
        return False
    tail = toks[i + 1:]
    if tail[:1] == ["--session"]:
        if len(tail) < 3 or tail[1] != session_id:
            return False
        tail = tail[2:]
    elif session_id:
        return False
    return bool(tail) and tail[0] in CLI_CMDS and "--session" not in tail[1:]


def protected(path: str, cwd: str) -> bool:
    f = fwd(path, cwd)
    if "/.elenchus/" in f + "/":
        return True
    if f == ROOT_F or f.startswith(ROOT_F + "/"):
        return True
    return ("/.claude/settings" in f or "/.vibe/" in f + "/"
            or f.endswith("/hooks.json") or f.endswith("/hooks.toml"))


def touches_machinery(cmd: str) -> bool:
    lc = slashes(cmd).lower()
    return (".elenchus" in lc or ".claude/settings" in lc or "/.vibe/" in lc.replace("\\", "/") + "/"
            or "hooks.json" in lc or "hooks.toml" in lc or ROOT_F in lc or bool(ROOT_M and ROOT_M in lc))


def mcp_read_only(tool: str) -> bool:
    if not (tool.startswith("mcp__") or tool.startswith("connector_")):
        return False
    return bool(MCP_READ.search(tool)) and not MCP_WRITE.search(tool)


def hook_pretool(p: dict) -> None:
    d = state_dir(p.get("cwd"), p.get("session_id", ""))
    s = load(d)
    changed = s["session_id"] != p.get("session_id", "")
    s["session_id"] = p.get("session_id", "")
    if process_user_entries(p, s) or changed:
        save(d, s)
    if not s["active"]:
        return
    tool, ti, cwd = p.get("tool_name", ""), p.get("tool_input") or {}, p.get("cwd", "")
    for k in ("file_path", "notebook_path", "path"):
        v = ti.get(k)
        if isinstance(v, str) and v and protected(v, cwd):
            return deny("ELENCHUS: the gate machinery (.elenchus, the plugin, hook and settings files) is off limits. Use the CLI.")
    if tool in SHELL_TOOLS:
        cmd = ti.get("command", "") or ""
        if is_cli(cmd, tool == "powershell", cwd, s["session_id"]):
            return
        if touches_machinery(cmd):
            return deny("ELENCHUS: touching the gate machinery from the shell is not allowed. Use the CLI commands only.")
    ph, mode = s["phase"], s["mode"]
    if tool in READ_TOOLS or tool.startswith("self.") or mcp_read_only(tool):
        return
    if ph == "open":
        return
    if mode == "predict":
        if ph == "await_prediction" and tool in WRITE_TOOLS:
            return
    deny(f"ELENCHUS LOCKED ({mode or 'unset'}/{ph}). {tool} is blocked until the user has done their part. {fmt(ph, s)} "
         f"Run `{cli_prefix(s)} status` with the shell tool for the full briefing.")


# ---------------------------------------------------------------- reply review

def leaks(text: str):
    """Heuristic: does this reply look like a lecture instead of a question?"""
    if "```" in text:
        return "a code block"
    if re.search(r"(?m)^\s{0,3}#{1,6}\s", text):
        return "markdown headings"
    if len(re.findall(r"(?m)^\s*(?:[-*\u2022]|\d+[.)])\s+\S", text)) >= 4:
        return "a list"
    n = words(text)
    if n > MAX_WORDS:
        return f"{n} words"
    return None


TAG = "[+] Elenchus:"
NOREPEAT = "Your last message stays visible. Do not repeat or rephrase it, add only the missing part."

# An ask does not need a question mark: "Name one thing the client must verify." is a
# perfectly good Socratic prompt. A sentence that opens with one of these verbs counts.
DEMAND = re.compile(
    r"(?:[.!:;]\s+|\n)\s*(?:and\s+|then\s+|now\s+|first,?\s+)?"
    r"(?:name|explain|describe|predict|say|tell me|walk me through|give me|give|list|state|justify|"
    r"defend|argue|propose|write|sketch|compare|decide|choose|pick|show|try|restate|rewrite|"
    r"rephrase|finish|complete|work out|figure out)\b", re.I)


def asks(text: str) -> bool:
    """Does the reply end by handing the user something to answer?"""
    t = text.strip()
    if "?" in t:
        return True
    if len(t) > 400:
        t = t[-400:]  # a sliced tail starts mid-sentence, so it gets no sentence-start anchor
    else:
        t = "\n" + t
    return DEMAND.search(t) is not None


def teeth(s: dict, text):
    if text is None:
        return None
    if s["housekeeping_turn"] == s["turn"]:
        return f"{TAG} show only the current question and next step." if leaks(text) else None
    ph, low = s["phase"], text.lower()
    if ph in ("await_attempt", "challenging", "verdict_ok", "await_reconcile", "review"):
        lk = leaks(text)
        if lk:
            return f"{TAG} {lk} while the gate is locked. Reply with one short question under {MAX_WORDS} words, no recap."
    if ph in ("await_attempt", "challenging") and not asks(text):
        return f"{TAG} no ask for the user. Add one closing sentence they must answer in their own words. {NOREPEAT}"
    if ph == "attempted":
        return (f"{TAG} register your move first: `{CLI} challenge --text ...` or `{CLI} verdict --note ...`, "
                f"then end the turn. {NOREPEAT}")
    if ph == "review":
        return f"{TAG} assess the reflection before ending; accept sound reasoning or register a retry question."
    if ph == "verdict_ok" and not any(x in low for x in ("agree:", "reflect:", "disagree:")):
        return f"{TAG} ask for `reflect: <your conclusion and reasons>`. Disagreement is welcome. {NOREPEAT}"
    if ph == "await_prediction" and "predict:" not in low:
        return f"{TAG} ask for `predict: <what happens when this runs>` before anything runs, without saying the output. {NOREPEAT}"
    if ph == "await_reconcile" and not any(x in low for x in ("agree:", "reflect:", "disagree:")) and not asks(text):
        return f"{TAG} still waiting for `agree: <what differed and why>`. Ask for it or challenge their reasoning. {NOREPEAT}"
    if ph == "run_open":
        return f"{TAG} execute the registered example with the run CLI or ask the user to restart this prediction gate. Never claim an output without a run."
    if ph == "need_gate":
        return f"{TAG} run `{CLI} gate --mode ... --topic ...` first, then ask your opening question."
    if ph == "idle":
        lk = leaks(text)
        if lk:
            return (f"{TAG} no gate is open ({lk}). For a learning request run `{CLI} gate --mode ... --topic ...` "
                    "and ask your opening question.")
    return None


def hook_postagent(p: dict) -> None:
    d = state_dir(p.get("cwd"), p.get("session_id", ""))
    s = load(d)
    changed = s["session_id"] != p.get("session_id", "")
    s["session_id"] = p.get("session_id", "")
    fresh = process_user_entries(p, s)
    if not s["active"]:
        if fresh or changed:
            save(d, s)
        return
    text = p.get("last_assistant_message")
    if not isinstance(text, str) or not text.strip():
        text = last_assistant(p.get("transcript_path"))
    reason = teeth(s, text)
    resp = {}
    if reason:
        if s["turn_nudges"] == 0:
            # The deny reason is injected as a retry message: the agent can fix
            # the reply within this same user turn.
            s["turn_nudges"] = 1
            resp = {"decision": "deny", "reason": reason}
        else:
            s["violations"] += 1
            s["last_violation"] = reason[:160]
            resp = {"decision": "deny", "reason": reason,
                    "system_message": "Elenchus warning: the agent ignored a rule and ended its turn anyway. "
                                      + reason.replace(TAG, "").strip()[:160]}
    if s["phase"] == "open":
        s["phase"] = "idle"
        reset_gate(s)
    elif text and asks(text) and s["phase"] in ("await_attempt", "challenging", "await_prediction", "verdict_ok", "await_reconcile") and reason is None:
        # Keep the last valid ask as the pinned question, even without explicit question CLI.
        # Prediction replies may include the code being shown. Only pin the ask.
        s["focus_question"] = re.sub(r"```.*?```", "", text, flags=re.S).strip()[-1500:]
    save(d, s)
    if resp:
        out(resp)


# ---------------------------------------------------------------- CLI

def die(msg: str):
    print(msg)
    sys.exit(1)


def need_active(s: dict) -> None:
    if not s["active"]:
        die("Elenchus is not active. Only the user can start it, with /elenchus:learn.")


def cmd_gate(d, s, a):
    need_active(s)
    if s["phase"] not in ("need_gate", "idle"):
        die(f"A gate is already in progress (mode={s['mode']}, phase={s['phase']}). Finish it first.")
    reset_gate(s)
    s.update(mode=a.mode, topic=a.topic, gate_turn=s["turn"])
    s["phase"] = "await_prediction" if a.mode == "predict" else "await_attempt"
    save(d, s)
    print("Gate ready. Register one opening question.")


def cmd_question(d, s, a):
    need_active(s)
    if s["phase"] not in ("await_attempt", "challenging", "await_prediction", "verdict_ok", "await_reconcile"):
        die("A question belongs to a phase waiting for the learner.")
    if words(a.text) > MAX_WORDS or not asks(a.text) or leaks(a.text):
        die("Use one short question or imperative, without headings or a lecture.")
    levels = {"question": 0, "smaller": 1, "hint": 2}
    level = levels[a.support]
    if level == 2 and s["help_level"] < 1:
        die("Try a smaller question before a minimal hint.")
    s["help_level"] = max(s["help_level"], level)
    s["focus_question"] = a.text
    save(d, s)
    print("Question pinned.")


def cmd_challenge(d, s, a):
    need_active(s)
    if s["mode"] not in ("explain", "propose"):
        die("challenge applies to explain and propose gates only.")
    if s["phase"] != "attempted":
        die(f"Cannot challenge in phase {s['phase']}. The user has to make an attempt first.")
    s["rounds"] += 1
    s["challenge_turn"] = s["turn"]
    s["challenges"].append(a.text[:500])
    s["focus_question"] = a.text[:1500]
    s["help_level"] = 0
    s["phase"] = "challenging"
    save(d, s)
    print(f"Challenge {s['rounds']} registered. Ask it now, briefly, and end the turn.")


def cmd_verdict(d, s, a):
    need_active(s)
    if s["mode"] not in ("explain", "propose"):
        die("verdict applies to explain and propose gates only.")
    if s["phase"] != "attempted":
        die(f"Cannot accept in phase {s['phase']}. The user must have answered your latest challenge first.")
    need = MIN_ROUNDS[s["mode"]]
    if s["rounds"] < need:
        die(f"{s['rounds']}/{need} challenge rounds done. Challenge again; the user must answer each one.")
    if s["attempt"]["turn"] <= s["challenge_turn"]:
        die("The user has not answered your latest challenge yet.")
    s["verdict"] = {"turn": s["turn"], "note": a.note[:500], "missed": a.missed[:500]}
    s["phase"] = "verdict_ok"
    s["focus_question"] = "What is your conclusion, and what reasons support it? Disagreement is welcome."
    save(d, s)
    print("Verdict recorded. Ask for reflect: their conclusion and reasons, including disagreement.")


def cmd_assess(d, s, a):
    need_active(s)
    if s["phase"] != "review" or not s["agreement"]:
        die("Only a user reflection can be assessed.")
    if a.result == "retry":
        if not a.question or words(a.question) > MAX_WORDS or not asks(a.question) or leaks(a.question):
            die("A retry needs one short question.")
        s["phase"] = "await_reconcile" if s["mode"] == "predict" else "verdict_ok"
        s["focus_question"] = a.question
        s["agreement"] = None
        save(d, s)
        print("Reflection needs another step. Question pinned; tools stay locked.")
        return
    evidence = {k: getattr(a, k) for k in ("mechanism", "transfer", "limit")}
    if not all(meaningful(v) for v in evidence.values()) or not a.note:
        die("Acceptance needs evidence of mechanism, transfer to a new case, a limit, and a note. Quote or paraphrase the learner; do not invent evidence.")
    if s["mode"] == "predict" and not s["run_result"]:
        die("A prediction gate needs a recorded execution before acceptance.")
    verdict = s["verdict"] or {}
    verdict.update(note=a.note[:1500], evidence=evidence, missed=a.missed or verdict.get("missed", ""))
    s["verdict"] = verdict
    complete(d, s, "reconcile" if s["mode"] == "predict" else "reflection")
    s["phase"] = "open"
    s["focus_question"] = ""
    save(d, s)
    print("Understanding accepted. One turn of work is open.")


def source_path(name, cwd):
    base = Path(cwd).resolve()
    path = (base / name).resolve()
    try:
        rel = path.relative_to(base)
    except ValueError:
        die("Prediction sources must stay inside the project.")
    if protected(str(path), str(base)) or not path.is_file() or path.stat().st_size > 100000:
        die("Use an ordinary project source file smaller than 100 KB.")
    return path, rel.as_posix()


def cmd_prepare(d, s, a):
    need_active(s)
    if s["mode"] != "predict" or s["phase"] != "await_prediction":
        die("Prepare code only before the user's prediction.")
    if not a.question or words(a.question) > MAX_WORDS or not asks(a.question) or leaks(a.question):
        die("Prepare needs one short prediction question, without the output.")
    cwd = str(Path.cwd())
    entry, rel = source_path(a.file, cwd)
    if entry.suffix.lower() not in ({".py"} if a.runtime == "python" else {".js", ".mjs", ".cjs"}):
        die("Runtime and source extension do not match.")
    sources = {}
    for name in [a.file] + a.source:
        path, relative = source_path(name, cwd)
        sources[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    if len(sources) > 20:
        die("Keep prediction examples small: at most 20 source files.")
    s["run_spec"] = {"cwd": cwd, "entry": rel, "runtime": a.runtime, "sources": sources, "used": False}
    s["run_result"] = None
    s["focus_question"] = a.question
    save(d, s)
    print(f"Registered {rel} ({len(sources)} source files). Ask predict: output and reasoning.")


def cmd_run(d, s, a):
    need_active(s)
    spec = s["run_spec"]
    if s["phase"] != "run_open" or not spec or spec["used"]:
        die("A user prediction grants one registered run.")
    snapshots = {}
    for name, digest in spec["sources"].items():
        path, relative = source_path(name, spec["cwd"])
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            s["phase"] = "await_prediction"
            s["run_spec"] = None
            s["attempt"] = None
            save(d, s)
            die("Source changed. Register the new code and request a fresh prediction.")
        snapshots[relative] = content
    runtime = sys.executable if spec["runtime"] == "python" else shutil.which("node")
    if not runtime:
        die("Node.js is missing. Install it or restart with a Python example.")
    spec["used"] = True
    s["phase"] = "await_reconcile"
    s["focus_question"] = "What differed from your prediction, and why? What change would alter the result?"
    save(d, s)  # Consume before starting, so interruption cannot replay the run.
    with tempfile.TemporaryDirectory(prefix="elenchus-run-") as tmp:
        for name, content in snapshots.items():
            path = Path(tmp) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        entry = str(Path(tmp) / spec["entry"])
        bootstrap = "import sys,runpy,pathlib; sys.path.insert(0,str(pathlib.Path(sys.argv[1]).parent)); runpy.run_path(sys.argv[1],run_name='__main__')"
        cmd = [runtime, "-I", "-B", "-c", bootstrap, entry] if spec["runtime"] == "python" else [runtime, entry]
        env = {k: v for k, v in os.environ.items() if k.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL",
        }}
        # Spool output to disk so a noisy example cannot fill the engine's RAM.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            error = ""
            try:
                result = subprocess.run(cmd, cwd=tmp, env=env, stdin=subprocess.DEVNULL,
                                        stdout=stdout, stderr=stderr, timeout=10)
                exit_code = result.returncode
            except subprocess.TimeoutExpired:
                error, exit_code = "Example exceeded 10 seconds.", None
            except OSError as exc:
                error, exit_code = str(exc), None
            stdout.seek(0)
            stderr.seek(0)
            output = {"stdout": stdout.read(12000).decode("utf-8", errors="replace").replace("\r\n", "\n"),
                      "stderr": stderr.read(12000).decode("utf-8", errors="replace").replace("\r\n", "\n") + error,
                      "exit_code": exit_code}
    s["run_result"] = output
    save(d, s)
    print(json.dumps({"prediction": s["attempt"]["text"], "actual": output}, ensure_ascii=False))


def slug(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-") or "topic"


def cmd_cards(d, s, a):
    d = project_dir(d)
    if a.sub == "list":
        for f in sorted((d / "anki").glob("*.tsv")) if (d / "anki").exists() else []:
            n = len([l for l in f.read_text(encoding="utf-8").splitlines() if not l.startswith("#")])
            print(f"{f}: {n} cards")
        return
    need_active(s)
    topics = [c["topic"] for c in s["completed"]]
    if not topics:
        die("No topic has passed its gate yet. Cards come only from completed gates.")
    topic = a.topic or topics[-1]
    if topic not in topics:
        die(f"Topic {topic!r} has not passed a gate. Completed: {topics[-5:]}")
    mode = next(c["mode"] for c in reversed(s["completed"]) if c["topic"] == topic)
    if a.cloze and "{{c" not in a.front:
        die("A cloze card needs {{c1::...}} markup in --front.")
    esc = lambda x: html.escape(x).replace("\t", " ").replace("\r", "").replace("\n", "<br>")
    back = esc(a.back)
    if a.connects:
        back += f"<div class='el-connects'><b>Connects to:</b> {esc(a.connects)}</div>"
    if a.mistake:
        back += f"<div class='el-mistake'><b>I got this wrong before:</b> {esc(a.mistake)}</div>"
    tags = " ".join(["elenchus", slug(topic), mode] + [slug(t) for t in a.tags.split(",") if t.strip()])
    kind = "cloze" if a.cloze else "basic"
    path = d / "anki" / f"{kind}.tsv"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", encoding="utf-8", newline="\n") as f:
            f.write("#separator:tab\n#html:true\n"
                    f"#notetype:{'Cloze' if a.cloze else 'Basic'}\n#deck:Elenchus\n#tags column:3\n")
    front = esc(a.front)
    existing = path.read_text(encoding="utf-8").splitlines()
    if any(l.startswith(front + "\t") for l in existing if not l.startswith("#")):
        die("Duplicate card, skipped.")
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(f"{front}\t{back}\t{tags}\n")
    total = len([l for l in existing if not l.startswith("#")]) + 1
    print(f"Card added to {path.name} ({total} total).")


def cmd_status(d, s, a):
    if not s["active"]:
        print("Elenchus is inactive. The user starts it with /elenchus:learn.")
        return
    print(briefing(s))
    print(f"Completed gates: {len(s['completed'])} | rule violations on record: {s['violations']}")
    print("Earlier topics (use only a genuinely relevant connection):")
    for c in s["completed"][-10:]:
        print(json.dumps({k: c.get(k, "") for k in ("topic", "mode", "own_words", "missed", "evidence")}, ensure_ascii=False))
    if not s["completed"]:
        print("None yet. Do not invent a connection card.")


def cli_main(argv):
    ap = argparse.ArgumentParser(prog="elenchus.py")
    ap.add_argument("--session", default="")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate")
    g.add_argument("--mode", required=True, choices=MODES)
    g.add_argument("--topic", required=True)
    c = sub.add_parser("challenge")
    c.add_argument("--text", required=True)
    v = sub.add_parser("verdict")
    v.add_argument("--note", required=True)
    v.add_argument("--missed", default="")
    q = sub.add_parser("question")
    q.add_argument("--text", required=True)
    q.add_argument("--support", choices=("question", "smaller", "hint"), default="question")
    review = sub.add_parser("assess")
    review.add_argument("--result", choices=("accept", "retry"), required=True)
    for key in ("mechanism", "transfer", "limit", "note", "missed", "question"):
        review.add_argument("--" + key, default="")
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--runtime", choices=("python", "node"), required=True)
    prepare.add_argument("--file", required=True)
    prepare.add_argument("--source", action="append", default=[])
    prepare.add_argument("--question", required=True)
    sub.add_parser("run")
    sub.add_parser("status")
    k = sub.add_parser("cards")
    ks = k.add_subparsers(dest="sub", required=True)
    ad = ks.add_parser("add")
    ad.add_argument("--front", required=True)
    ad.add_argument("--back", required=True)
    ad.add_argument("--topic")
    ad.add_argument("--connects", default="")
    ad.add_argument("--mistake", default="")
    ad.add_argument("--tags", default="")
    ad.add_argument("--cloze", action="store_true")
    ks.add_parser("list")
    a = ap.parse_args(argv)
    if not a.session and a.cmd == "status":
        a.session = latest_session(state_dir(None, ""))
    d = state_dir(None, a.session)
    with locked(d):
        s = load(d)
        s["session_id"] = a.session
        handler = {"gate": cmd_gate, "challenge": cmd_challenge, "verdict": cmd_verdict,
                   "assess": cmd_assess, "prepare": cmd_prepare, "run": cmd_run,
                   "question": cmd_question, "status": cmd_status, "cards": cmd_cards}[a.cmd]
        if a.cmd == "cards":
            with locked(project_dir(d) / "anki"):
                handler(d, s, a)
        else:
            handler(d, s, a)


HOOKS = {"hook-prompt": hook_prompt, "hook-pretool": hook_pretool,
         "hook-postagent": hook_postagent}


def main() -> None:
    for st in (sys.stdin, sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    argv = sys.argv[1:]
    if argv and argv[0] in HOOKS:
        try:
            payload = json.loads(sys.stdin.read().lstrip("\ufeff") or "{}")
        except ValueError:
            payload = {}
        try:
            if not isinstance(payload, dict):
                raise ValueError("Expected a hook object")
            d = state_dir(payload.get("cwd"), payload.get("session_id", ""))
            with locked(d):
                HOOKS[argv[0]](payload)
        except Exception as e:  # never let a hook crash open the gate
            if argv[0] == "hook-pretool":
                deny(f"ELENCHUS internal error, failing closed: {e}")
            else:
                sys.stderr.write(f"elenchus {argv[0]} error: {e}\n")
        return
    cli_main(argv)


if __name__ == "__main__":
    main()
