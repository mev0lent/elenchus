#!/usr/bin/env python3
"""Elenchus gate engine for Claude Code, Cowork, Codex and Mistral Vibe
(Linux, macOS, Windows via Git Bash). One engine, three hosts.

Codex speaks Claude Code's hook protocol (event names, JSON fields, permissionDecision,
Stop decision block); it differs in tool names (apply_patch, update_plan) and shell input.
Vibe 3.1 reads user turns from its journal; post_tool carries the briefing without
requiring a separate status call on every turn.

Hook handlers: hook-session, hook-prompt, hook-pretool, hook-posttool, hook-stop.
CLI: gate, challenge, verdict, assess, prepare, run, question, status, cards, paper, graph, choice.

Gate state lives in .elenchus/sessions/<session-key>/state.json. Only the user's own typed
words record attempts, predictions and reflections. The agent registers its own moves and
assesses a recorded reflection. Every passed gate also becomes a note in the user's
knowledge graph, shared by all projects.
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paper  # noqa: E402  (owner's paper, shared with the other engine)

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parent.parent
WIN = os.name == "nt" or os.environ.get("ELENCHUS_FORCE_WIN") == "1"

MODES = ("explain", "predict", "propose", "decide")
MIN_ROUNDS = {"explain": 1, "propose": 2, "decide": 1}
MAX_WORDS = int(os.environ.get("ELENCHUS_MAX_WORDS", "80"))
CLI_CMDS = ("gate", "challenge", "verdict", "assess", "prepare", "run", "question", "status", "cards", "paper", "graph", "choice")


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
# Hooks only: Vibe sets PLUGIN_ROOT, Codex PLUGIN_ROOT and CLAUDE_PLUGIN_ROOT, Claude Code the latter.
_PR, _CPR = os.environ.get("PLUGIN_ROOT"), os.environ.get("CLAUDE_PLUGIN_ROOT")
HOST = "Vibe" if _PR and not _CPR else "Codex" if _PR else "Claude"
VIBE = HOST == "Vibe"
SHELL_NAME = "Bash" if HOST == "Claude" else "shell"

# ---------------------------------------------------------------- policy

READ_TOOLS = {
    "Read", "Glob", "Grep", "LS", "WebSearch", "WebFetch", "ToolSearch", "Skill",
    "TaskCreate", "TaskUpdate", "TaskGet", "TaskList", "TodoWrite", "BashOutput",
    "AskUserQuestion", "SendUserMessage", "ListSkills", "SearchSkills",
    "ListMcpResourcesTool", "ReadMcpResourceTool", "ReadMcpResourceDirTool",
    # Codex local function tools that neither write nor execute
    "update_plan", "view_image",
    # Vibe, matched on the part after the group: file_system.read_file, skill.read, process.list
    "read_file", "read", "grep", "glob", "ls", "web_search", "web_fetch", "skill", "todo",
    "ask_user_question", "search_tool_functions", "tool_search", "unified_harness_scratchpad",
    "sleep", "wait", "output", "list",
}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch",
               "write_file", "edit", "search_replace", "run_typescript"}
SHELL_TOOLS = {"Bash", "PowerShell", "bash", "git_bash", "powershell"}
MCP_READ = re.compile(r"(search|read|fetch|get|list|query)", re.I)
MCP_WRITE = re.compile(
    r"(create|update|delete|write|send|move|upload|share|trash|copy|spawn|stop|"
    r"restore|duplicate|convert|insert|post|publish|commit|stage|bash|exec|run)", re.I)

CTRL_RE = re.compile(
    r"^\s*(/elenchus:|[$@]elenchus[:\s-]+|ELENCHUS-COMMAND\s+|elenchus[:\s-]+)(learn|own|paper|off|status|focus|cards|recall|always)\b([^\n]*)", re.I)


def command(prompt: str):
    """(verb, rest) when the user typed an Elenchus command, else None. The bare form
    `elenchus off` is for hosts without slash commands; a sentence that merely starts
    with those words ("elenchus off does not work") is not a command."""
    m = CTRL_RE.match(prompt)
    if not m:
        return None
    verb, rest = m.group(2).lower(), m.group(3)
    bare = m.group(1)[0] not in "/$@" and not m.group(1).upper().startswith("ELENCHUS-COMMAND")
    if bare and verb in ("off", "status", "focus", "cards") and rest.strip().lower() not in ("", "full", "compact"):
        return None
    return verb, rest


AGREE_RE = re.compile(r"^\s*agree\s*:\s*(.+)$", re.I | re.S)
REFLECT_RE = re.compile(r"^\s*(?:reflect|disagree)\s*:\s*(.+)$", re.I | re.S)
PREDICT_RE = re.compile(r"^\s*predict\s*:\s*(.+)$", re.I | re.S)
DELEGATE_RE = re.compile(r"^\s*delegate\s*:\s*(.*)$", re.I | re.S)

DEFAULT = {
    "active": False, "turn": 0, "mode": None, "topic": "", "phase": "idle",
    "gate_turn": 0, "challenge_turn": 0, "rounds": 0, "attempt": None,
    "verdict": None, "agreement": None, "challenges": [], "completed": [],
    "violations": 0, "last_violation": "",
    "session_id": "", "focus_question": "", "help_level": 0,
    "run_spec": None, "run_result": None,
    "ui_details": False,
    "housekeeping_turn": -1,
    "own": "",
    "own_brief": "",    # extra briefing of an own gate or a recall gate
    "recall": False,    # this gate re-tests a note of the knowledge graph
    "notice": "",       # Vibe: prompt briefing, delivered by a tool result or status
    "prompt_ts": 0,     # Vibe: journal timestamp of the last user message already recorded
    "turn_nudges": 0,   # Vibe: reply corrections asked for in this turn
    "briefed_turn": -1, # Vibe: ordinary tool results carry the briefing once per user turn
}

IRON_RULES = """ELENCHUS IRON RULES. The user thinks first; you probe and assess.
1. While locked: at most one short acknowledgment plus one question, under {maxw} words. No target answer, lecture, headings, or lists. Predict preparation may show code without output.
2. Only the user's typed words record an attempt, prediction, reflection, delegation, or off command. Assess sound reasoning, including disagreement; never invent evidence or accept by length.
3. Required answered challenges: explain 1, propose 2, decide 1. Explain/propose also need a user reflection and assessment. Decide ends with assess, without verdict/reflect. Predict uses one registered run, then reflection and assessment.
4. Only the user can disable this. Mention delegate: only if they ask you to choose; own gates cannot be delegated. Blocked tools mean ask, never bypass.
5. Follow Next with at most one bookkeeping call per ordinary turn. Its result is the verification. Do not repeat status, skill reads, or question after challenge/prepare. Stop pins closing questions. Cards wait until requested.
6. Retry text follows a reply already visible to the user: add only the missing question, without repeating yourself."""

NEXT = {
    "need_gate": "Choose explain, predict, propose, or decide with `gate --mode M --topic T --question Q`. Ask Q and end the turn. Predict uses prepare instead.",
    "await_attempt": "Ask one opening question. End the turn; no tool call is needed to pin it.",
    "attempted": "Ask one probing question and end the turn; Stop records the challenge. Use verdict after the required answered challenges.",
    "challenging": "Wait for the user's answer. Do not answer your own challenge or register it again.",
    "verdict_ok": "Ask for the user's conclusion and reasons, then wait. Plain reasoning is a reflection; reflect:, agree:, and disagree: also work.",
    "review": "Assess the recorded reflection: `assess --result accept --mechanism M --transfer T --limit L --note N`, or `assess --result retry --question Q`. Judge reasoning, never length.",
    "open": "Work normally until the next gate. You build; the user decides real trade-offs. Use `gate --mode decide --topic T --question Q` for those. Routine implementation choices are yours. Cards are optional, on request.",
    "await_prediction": "Prepare one small example with `prepare --runtime python|node --file F --question Q` (repeat --source for imports). Ask for `predict: output and why`. Do not run or reveal output.",
    "run_open": "Run the registered example once with `run`. Compare with the user's prediction, ask for reflect: what differed and why, and end the turn.",
    "await_reconcile": "Ask for the user's reflection on the result. No more runs or edits. Assess only after they answer.",
    "idle": "State is unreadable: tools stay locked. Start `gate --mode M --topic T`; only the user can disable Elenchus.",
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
    base = Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd or os.getcwd())
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


def home() -> Path:
    """Where everything that spans projects lives: the knowledge graph and the always-on flag."""
    base = os.environ.get("ELENCHUS_DIR")
    return Path(base) if base else Path.home() / ".config" / "elenchus"


def always_flag() -> Path:
    return Path(os.environ.get("ELENCHUS_ALWAYS") or home() / "always-on")


@contextmanager
def maybe_locked(d: Path):
    """Lock a project that has a .elenchus folder; never create one just to look."""
    if project_dir(d).is_dir():
        with locked(d):
            yield
    else:
        # shortcut: no lock before the folder exists, so two first commands in the same
        # instant could both write; add a lock on the project's parent if that is ever seen.
        yield


@contextmanager
def locked(d: Path):
    """OS advisory lock, released even after a crash. One transaction per session."""
    d.mkdir(parents=True, exist_ok=True)
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
    elif d.parent.name == "sessions" and always_flag().exists():
        s.update(active=True, phase="open")  # always-on: a session starts in open work, until the user types off
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


def complete(d: Path, s: dict, how: str, links: str = "") -> str:
    v, a = s["verdict"] or {}, s["agreement"] or {}
    record = {
        "id": uuid.uuid4().hex, "created": time.time(), "session_id": s["session_id"],
        "topic": s["topic"], "mode": s["mode"], "rounds": s["rounds"], "how": how,
        "turn": s["turn"], "note": v.get("note", ""), "missed": v.get("missed", ""),
        "own_words": a.get("text", ""),
        "evidence": v.get("evidence", {}),
        "prediction": (s["attempt"] or {}).get("text", "") if s["mode"] == "predict" else "",
    }
    dest = project_dir(d) / "history"
    dest.mkdir(parents=True, exist_ok=True)
    tmp = dest / (record["id"] + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, dest / (record["id"] + ".json"))
    s["completed"].append(record)
    s["completed"] = s["completed"][-200:]
    try:
        return f"Saved to the user's knowledge graph: {graph_add(record, project_dir(d).parent.name, links)}"
    except OSError as e:  # the gate record above is already safe
        return f"Knowledge graph not written ({e})."


# ---------------------------------------------------------------- knowledge graph

STOP = {"the", "and", "for", "with", "how", "why", "what", "does", "der", "die", "das", "und", "wie", "was", "ein", "eine"}


def graph_dir() -> Path:
    """One folder of Markdown notes for all projects. [[wikilinks]] are the edges, so
    Obsidian, Logseq or Foam open it as a graph without any conversion."""
    return Path(os.environ.get("ELENCHUS_GRAPH") or home() / "graph")


def node(name: str) -> str:
    """A note name that is a valid file name and a valid [[wikilink]] target."""
    return " ".join(re.sub(r'[\\/:*?"<>|#^\[\]]+', " ", name).split()).strip(". ")[:80] or "topic"


def graph_add(rec: dict, project: str, links: str) -> Path:
    """Append one passed gate to the note of its topic: the user's own words, the assessed
    evidence, and edges to the project and to related notes."""
    g = graph_dir()
    g.mkdir(parents=True, exist_ok=True)
    note = g / (node(rec["topic"]) + ".md")
    ev = rec.get("evidence") or {}
    day = time.strftime("%Y-%m-%d", time.localtime(rec["created"]))
    kind = rec["how"] if rec["how"] in ("recall", "delegated") else rec["mode"]
    lines = ["", f"## {day} · {kind} · gate {rec['id'][:8]}", ""]
    if kind == "delegated":
        lines.append("- **Left to the agent.** I did not decide this myself.")
    for label, value in (("Decided", rec.get("note") if kind == "decide" else ""),
                         ("My remark" if kind == "delegated" else "In my words", rec.get("own_words")),
                         ("My prediction", rec.get("prediction")),
                         ("How it works", ev.get("mechanism")), ("Applies to", ev.get("transfer")),
                         ("Limit", ev.get("limit")), ("I missed", rec.get("missed"))):
        if value:
            lines.append(f"- **{label}:** {' '.join(value.split())}")
    edges = dict.fromkeys(node(x) for x in [project] + links.split(",") if x.strip())
    lines.append("- **Connects to:** " + ", ".join(f"[[{e}]]" for e in edges))
    with locked(g):
        with note.open("a", encoding="utf-8", newline="\n") as f:
            if f.tell() == 0:
                f.write(f"# {rec['topic']}\n")
            f.write("\n".join(lines) + "\n")
    return note


def graph_find(query: str, limit: int | None = 5) -> list:
    """Notes that share words with the query, best first, as (title, latest entry)."""
    want = set(re.findall(r"\w{3,}", query.lower())) - STOP
    g, hits = graph_dir(), []
    for f in g.glob("*.md") if g.is_dir() else []:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        low, title = text.lower(), f.stem.lower()
        score = sum(3 if w in title else 1 for w in want if w in low)
        if score:
            hits.append((score, f.stem, text.rsplit("\n## ", 1)[-1].strip()))
    return [(t, body) for _, t, body in sorted(hits, reverse=True)[:limit]]


def graph_due(words: str):
    """The note to recall as (title, latest entry): the best match for the words, else the
    one untouched longest. Decisions the user delegated are not theirs to recall."""
    g = graph_dir()
    if words.strip():
        found = graph_find(words, None)
    else:
        found = [(f.stem, f.read_text(encoding="utf-8").rsplit("\n## ", 1)[-1].strip())
                 for f in sorted(g.glob("*.md"), key=lambda f: f.stat().st_mtime)] if g.is_dir() else []
    return next((hit for hit in found if "· delegated ·" not in hit[1].split("\n", 1)[0]), None)


def graph_note(cli: str) -> str:
    g = graph_dir()
    notes = list(g.glob("*.md")) if g.is_dir() else []
    n = len(notes)
    if not n:
        return ""
    stale = sum(1 for f in notes if time.time() - f.stat().st_mtime > 30 * 86400)
    return (f"ELENCHUS KNOWLEDGE GRAPH: the user keeps what they have learned and decided, in their own words, "
            f"in {slashes(g)} ({n} notes, all projects). Before you explain a concept or settle a design question for them, "
            f"run `{cli} graph <words>`. If they have been there before, remind them of their own conclusion and build on it "
            "instead of redoing the thinking for them."
            + (f" {stale} of the notes have not been revisited for a month: at a natural pause, offer `/elenchus:recall` once." if stale else ""))


def cmd_graph(d, s, a):
    g = graph_dir()
    if not a.words:
        notes = sorted(g.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True) if g.is_dir() else []
        print(f"Knowledge graph: {g} ({len(notes)} notes). Search with `graph <words>`.")
        for f in notes[:30]:
            print(f"- {f.stem}")
        return
    hits = graph_find(" ".join(a.words))
    if not hits:
        print("Nothing in the knowledge graph on this yet.")
    for title, body in hits:
        print(f"[[{title}]] ({slashes(g / (title + '.md'))})\n## {body}\n")


def cli_prefix(s):
    return CLI + (f' --session "{s["session_id"]}"' if s["session_id"] else "")


def fmt(key: str, s=None) -> str:
    if key == "attempted" and s:
        answered = s["rounds"] >= MIN_ROUNDS.get(s["mode"], 1) and (s["attempt"] or {}).get("turn", 0) > s["challenge_turn"]
        if s["mode"] == "decide" and answered:
            return "One challenge answered. Accept sound reasoning with `assess --result accept --note N`; otherwise challenge again. No verdict or reflection step."
        if answered:
            return "Required challenges answered. If sound, run `verdict --note N`, then ask for the user's reflection and end the turn. Otherwise challenge again."
        return "Ask one probing question and end the turn. Stop records the challenge; no CLI or status call is needed."
    return NEXT[key]


def step(s: dict) -> str:
    return (f"ELENCHUS | mode={s['mode'] or 'unset'} | phase={s['phase']} | rounds={s['rounds']}/{MIN_ROUNDS.get(s['mode'], 0)}\n"
            f"Next: {fmt(s['phase'], s)}")


def briefing(s: dict, note: str = "") -> str:
    mode = s["mode"]
    lines = [
        f"ELENCHUS | mode={mode or 'unset'} | topic={s['topic']!r} | phase={s['phase']} | "
        f"rounds={s['rounds']}/{MIN_ROUNDS.get(mode, 0)}",
        f"CLI (run it with the {SHELL_NAME} tool, exactly this prefix): {cli_prefix(s)}",
    ]
    if note:
        lines.append(f"Hook note: {note}")
    if s.get("last_violation"):
        lines.append(f"VIOLATION ON RECORD: last turn you broke a rule ({s['last_violation']}). The user was shown a warning. Do not repeat it.")
    if s.get("own_brief") and s["active"]:
        lines.append(s["own_brief"])
    known = graph_find(s["topic"], 3) if s["phase"] in ("need_gate", "await_attempt", "await_prediction") and not s["recall"] else []
    if known:
        lines.append("ALREADY IN THE USER'S KNOWLEDGE GRAPH (do not re-teach; ask them to recall it, build on their words, "
                     "and name the related notes in `assess --links`): "
                     + " | ".join(f"[[{t}]] {' '.join(body.split())[:300]}" for t, body in known))
    lines.append(f"Next: {fmt(s['phase'], s)}")
    if s["phase"] == "open":
        return "\n".join(lines)
    if s["focus_question"]:
        lines.append(f"Pinned question: {s['focus_question']}")
    lines.append("A concise answer counts. Judge mechanism, transfer and limits, never length. Accept reasoned disagreement. The reply pins its question automatically; `question` is only needed for explicit smaller/hint support.")
    lines.append(f"Reminder: while locked, no target answers, no lists or headings, one question, under {MAX_WORDS} words. Example code is allowed during predict preparation. "
                 "A blocked tool means you owe the user a question, not a workaround.")
    return "\n".join(lines)


# ---------------------------------------------------------------- output

def out(obj) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


def emit_ctx(event: str, text: str) -> None:
    out({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})


def deny(reason: str) -> None:
    if VIBE:
        return out({"decision": "deny", "reason": reason})
    out({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                "permissionDecision": "deny",
                                "permissionDecisionReason": reason}})


# ---------------------------------------------------------------- session hook

def hook_session(p: dict) -> None:
    d = state_dir(p.get("cwd"), p.get("session_id", ""))
    s = load(d)
    s["session_id"] = p.get("session_id", "")
    pp = paper_of(d)
    note = "\n\n".join(x for x in (paper.session_note(pp, cli_prefix(s)) if pp else "", graph_note(cli_prefix(s))) if x)
    if not s["active"]:
        return emit_ctx("SessionStart", note) if note else None
    rules = "" if s["phase"] == "open" else IRON_RULES.format(maxw=MAX_WORDS) + "\n\n"
    emit_ctx("SessionStart", rules + briefing(s) + ("\n\n" + note if note else ""))


# ---------------------------------------------------------------- prompt hook

def start(s: dict, rest: str) -> None:
    toks = rest.strip().split(None, 1)
    mode, topic = None, rest.strip()
    if toks and toks[0].lower() in MODES:
        mode = toks[0].lower()
        topic = toks[1].strip() if len(toks) > 1 else ""
    elif toks and toks[0].lower() == "auto":
        topic = toks[1].strip() if len(toks) > 1 else ""
    reset_gate(s)
    s.update(active=True, mode=mode, topic=topic or "(open)", gate_turn=s["turn"], last_violation="", recall=False)
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
    if mode in ("explain", "propose", "decide") and ph in ("await_attempt", "challenging", "attempted"):
        if not meaningful(text):
            return "No attempt yet. Offer a smaller question."
        s["attempt"] = {"turn": s["turn"], "text": text[:1500]}
        s["phase"] = "attempted"
        return "User attempt RECORDED. Evaluate its reasoning, regardless of length."
    if ph == "verdict_ok":
        return on_agree(s, text)  # conclusions and reasoned objections both deserve assessment
    if ph in ("await_reconcile", "review"):
        return on_agree(s, text)
    return ""


def on_prompt(d: Path, s: dict, prompt: str) -> str:
    """Only the user's own typed words move a gate. Returns the briefing for the agent."""
    m = command(prompt)
    if m:
        verb, rest = m
        s["turn"] += 1
        if verb == "off":
            s.update(active=False, phase="idle", last_violation="", own="", own_brief="", recall=False)
            save(d, s)
            return "ELENCHUS OFF. Gates are disabled until the user types /elenchus:learn again. Confirm in one short sentence."
        if verb == "paper":
            save(d, s)
            if rest.strip().lower() == "all":
                return "ELENCHUS PAPER. Run `{cli} paper status --all` and report the overview as it is, briefly.".format(cli=cli_prefix(s))
            key = PAPER_SHOW if paper_of(d) else PAPER_SETUP
            return "ELENCHUS PAPER. " + key.format(cli=cli_prefix(s))
        if verb == "own":
            title = rest.strip().strip('"')
            pp = paper_of(d)
            if not title or not pp:
                save(d, s)
                why = "This project has no owner's paper yet." if title else "Usage: /elenchus:own <decision title>."
                return f"ELENCHUS: {why} Tell the user in one sentence; /elenchus:paper starts one."
            dec, problem = paper.readiness(pp, title)
            if problem:
                save(d, s)
                return ("ELENCHUS: not ready to own. " + problem +
                        " Tell the user exactly this in one or two sentences. Do not write the formal statement for them.")
            start(s, "propose " + dec["title"])
            s["own"], s["own_brief"] = dec["title"], paper.gate_brief(pp, dec["title"])
        if verb == "learn":
            start(s, rest)
            s["own"] = s["own_brief"] = ""
        if verb == "recall":
            due = graph_due(rest)
            if not due:
                return "ELENCHUS: the knowledge graph has no note to recall for this yet. Tell the user in one sentence."
            start(s, "explain " + due[0])
            s["own"], s["recall"] = "", True
            s["own_brief"] = ("RECALL GATE. The user passed this before. Their latest entry, which they must not see yet: <<"
                              + " ".join(due[1].split())[:1500] + ">> Ask them to reproduce from memory what they concluded and why. "
                              "Do not show or paraphrase the old entry until they have answered. Then probe what faded or changed, "
                              "and say plainly what held.")
        if verb == "always":
            if rest.strip().lower() not in ("on", "off"):
                return "ELENCHUS: Usage: /elenchus:always on|off. Nothing changed."
            flag, on = always_flag(), rest.strip().lower() == "on"
            if on:
                flag.parent.mkdir(parents=True, exist_ok=True)
                flag.touch()
                if not s["active"]:
                    s.update(active=True, phase="open")
            elif flag.exists():
                flag.unlink()
            if (d / "state.json").exists() or (not on and s["active"]):
                save(d, s)
            if not on:
                return "ELENCHUS ALWAYS OFF. New sessions start without Elenchus again; this session is unchanged. Confirm in one sentence."
            return ("ELENCHUS ALWAYS ON. Every new session, in every project, now starts in open work: nothing is locked, and "
                    "decisions that shape the result go to the user as decide gates. /elenchus:off ends it for one session, "
                    "/elenchus:always off for all. Confirm in one sentence.\n\n" + briefing(s))
        if verb == "focus":
            if rest.strip().lower() in ("full", "compact"):
                s["ui_details"] = rest.strip().lower() == "full"
        if verb in ("status", "focus", "cards"):
            s["housekeeping_turn"] = s["turn"]
        save(d, s)
        if not s["active"]:
            return "Elenchus is not active. The user starts it with /elenchus:learn."
        context = IRON_RULES.format(maxw=MAX_WORDS) + "\n\n" + briefing(s)
        if verb in ("status", "focus", "cards"):
            context += "\nThis is a housekeeping command. Show only the current question and next step; do not register a challenge or assess an answer."
        return context
    if not s["active"]:
        return ""
    if s["phase"] == "open":
        return briefing(s)  # nothing to record, so open work never writes to the project
    s["turn"] += 1
    am = AGREE_RE.match(prompt) or REFLECT_RE.match(prompt)
    pm = PREDICT_RE.match(prompt)
    dm = DELEGATE_RE.match(prompt)
    if dm and s["mode"] in ("decide", "propose") and not s["own"] and s["phase"] != "need_gate":
        # "you pick" is a legitimate answer; it is recorded as exactly that
        s["agreement"], s["verdict"] = {"turn": s["turn"], "text": dm.group(1).strip()[:1500]}, None
        saved = complete(d, s, "delegated")
        s.update(phase="open", focus_question="")
        note = (f"The user DELEGATED this decision to you. {saved} Decide it now, tell them in one sentence what you chose "
                f"and why, record it with `{cli_prefix(s)} choice --note \"<what you chose and why>\"`, "
                "and log it in the owner's paper as inherited if there is one. Do not ask again.")
    elif am:
        note = on_agree(s, am.group(1).strip())
    elif pm:
        note = on_predict(s, pm.group(1).strip())
    else:
        note = on_text(s, prompt)
    text = briefing(s, note)
    s["last_violation"] = ""  # shown to the agent once
    save(d, s)
    return text


def hook_prompt(p: dict) -> None:
    d = state_dir(p.get("cwd"), p.get("session_id", ""))
    s = load(d)
    s["session_id"] = p.get("session_id", "")
    text = on_prompt(d, s, (p.get("prompt") or "").strip())
    if text:
        emit_ctx("UserPromptSubmit", text)


# ---------------------------------------------------------------- Vibe journal

def journal(path) -> list:
    """Messages of a Vibe session, oldest first: [{"role", "ts", "text"}]. Vibe passes the
    session's storage root as transcript_path; the journal is the JSONL files under it."""
    root, found = Path(path or ""), {}
    for f in sorted([*root.glob("*.jsonl"), *root.glob("journal/*.jsonl")] if path and root.is_dir() else []):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                o = json.loads(line)
                payload = o["payload"] if o.get("type") in ("projection_delta", "core_input") else None
            except (ValueError, KeyError, AttributeError, TypeError):
                continue
            if not isinstance(payload, dict):
                continue
            entries, blocks = [], lambda content: "\n".join(
                b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
            if o["type"] == "projection_delta":
                for delta in payload.get("delta") or []:
                    e = delta.get("entry") if isinstance(delta, dict) else None
                    if isinstance(e, dict) and e.get("type") == "message" and e.get("role") in ("user", "assistant") \
                            and not (e["role"] == "user" and e.get("source") in ("harness", "system", "tool")):
                        entries.append((e["role"], e.get("turnId"), e.get("createdAt"), blocks(e.get("content"))))
            else:
                inp = payload.get("input") or {}
                c, ts = inp.get("command") or {}, (inp.get("determinism") or {}).get("time_unix_ms")
                if c.get("type") == "user_message":
                    entries.append(("user", c.get("turn_id"), ts, blocks(c.get("content"))))
                elif c.get("type") == "completion_succeeded":
                    # the reply is projected only after post_agent ran; the completion has it in time
                    entries.append(("assistant", None, ts, blocks((c.get("result") or {}).get("parts"))))
            for role, turn, ts, text in entries:
                if text.strip() and isinstance(ts, (int, float)):
                    # a message appears as input and as projection: keep one per turn and text
                    found[(role, turn, text)] = {"role": role, "ts": ts, "text": text}
    return sorted(found.values(), key=lambda e: e["ts"])


def read_turns(p: dict, d: Path, s: dict) -> list:
    """Vibe has no prompt hook: record the user messages the journal holds and this
    session has not seen yet, exactly as a prompt hook would."""
    turns = journal(p.get("transcript_path"))
    for e in turns:
        text = e["text"].strip()
        if e["role"] != "user" or e["ts"] <= s["prompt_ts"]:
            continue
        s["prompt_ts"] = e["ts"]
        if text.startswith(TAG) or re.match(r"ELENCHUS(-COMMAND|[\s:|])", text):
            continue  # hook retries and skill bodies are not the user's words
        was_active = s["active"]
        s["turn_nudges"] = 0
        note = on_prompt(d, s, text)
        if (d / "state.json").exists() and (note or was_active):
            s["notice"] = note
            save(d, s)  # a session without state stays off disk; its old messages replay as no-ops
    return turns




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


def same_engine(path: str, cwd: str) -> bool:
    """Vibe runs hooks from a pinned copy of the plugin while the agent may call the
    installed one. A byte-identical copy of this file is this engine."""
    try:
        f = Path(path) if os.path.isabs(path) else Path(cwd or ".") / path
        return f.name == SCRIPT.name and f.read_bytes() == SCRIPT.read_bytes()
    except OSError:
        return False


def is_cli(cmd: str, ps: bool = False, cwd: str = "", session_id: str = "") -> str:
    """The engine subcommand when cmd is exactly one call of this engine for this session, else ''."""
    c = cmd
    for var in ("CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT"):
        c = c.replace("${" + var + "}", ROOT_RAW).replace("$" + var, ROOT_RAW)
    toks = tokenize(c, ps)
    if not toks:
        return ""
    if toks[0] == "&":
        toks = toks[1:]
    if len(toks) < 3 or not is_python(toks[0]):
        return ""
    base = re.sub(r"\.exe$", "", posixpath.basename(slashes(toks[0])).lower())
    i = 2 if (base == "py" and toks[1].startswith("-")) else 1
    if len(toks) <= i + 1:
        return ""
    if fwd(toks[i], cwd) != SCRIPT_F and not same_engine(toks[i], cwd):
        return ""
    tail = toks[i + 1:]
    if tail[:1] == ["--session"]:
        if len(tail) < 3 or tail[1] != session_id:
            return ""
        tail = tail[2:]
    elif session_id:
        return ""
    return tail[0] if tail and tail[0] in CLI_CMDS and "--session" not in tail[1:] else ""


def protected(path: str, cwd: str) -> bool:
    f = fwd(path, cwd)
    if "/.elenchus/" in f + "/":
        return True
    if f == ROOT_F or f.startswith(ROOT_F + "/"):
        return True
    return ("/.claude/settings" in f or "/.codex/config" in f or "/.vibe/plugins" in f or "/.vibe/config" in f
            or "/.config/elenchus" in f + "/"
            or f.endswith(("/hooks.json", "/hooks.toml")))


def touches_machinery(cmd: str) -> bool:
    lc = slashes(cmd).lower()
    return (".elenchus" in lc or ".config/elenchus" in lc or ".claude/settings" in lc or ".codex/config" in lc or ".vibe/plugins" in lc
            or ".vibe/config" in lc or "hooks.json" in lc or "hooks.toml" in lc or ROOT_F in lc or bool(ROOT_M and ROOT_M in lc))


PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$", re.M)


def patch_paths(tool: str, ti: dict) -> list:
    """Codex edits files with apply_patch; its targets live in the patch text, not in file_path."""
    if tool != "apply_patch":
        return []
    text = ti.get("command") or ti.get("input") or ti.get("patch") or ""
    if isinstance(text, list):
        text = "\n".join(str(x) for x in text)
    return [a or b for a, b in PATCH_FILE.findall(str(text))]


def shell_command(ti: dict) -> str:
    """Claude Code sends a command string. Codex may send a string, an argv list, or cmd."""
    cmd = ti.get("command") if ti.get("command") is not None else ti.get("cmd", "")
    if isinstance(cmd, list):
        # ["bash", "-lc", "<script>"] carries the script last; anything else is plain argv
        if len(cmd) >= 3 and str(cmd[-2]) in ("-c", "-lc"):
            return str(cmd[-1])
        return " ".join(str(x) for x in cmd)
    return cmd if isinstance(cmd, str) else ""


def mcp_read_only(tool: str) -> bool:
    if not tool.startswith(("mcp__", "connector_")):
        return False
    last = tool.split("__")[-1]
    return bool(MCP_READ.search(last)) and not MCP_WRITE.search(last)


def hook_pretool(p: dict) -> None:
    d = state_dir(p.get("cwd"), p.get("session_id", ""))
    s = load(d)
    s["session_id"] = p.get("session_id", "")
    if VIBE:
        read_turns(p, d, s)  # the first tool call of a turn records what the user typed
    tool, ti, cwd = p.get("tool_name", ""), p.get("tool_input") or {}, p.get("cwd", "")
    if not isinstance(ti, dict):
        ti = {}
    names = {tool, tool.rsplit(".", 1)[-1]}  # Vibe qualifies its tools: file_system.bash
    sub = is_cli(shell_command(ti), bool(names & {"PowerShell", "powershell"}), cwd, s["session_id"]) if names & SHELL_TOOLS else ""
    if s["active"] and sub in ("verdict", "assess"):
        problem = verdict_problem(s) if sub == "verdict" else assessment_problem(s)
        if problem:
            return deny(f"{problem}\n{step(s)}")  # reject impossible moves before asking for permission
    if sub and sub != "run" and HOST == "Claude":
        # The engine's own bookkeeping needs no permission prompt. `run` executes code and keeps it.
        # shortcut: Claude Code only; Codex and Vibe cannot be told to approve from a hook, revisit when they can.
        return out({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                           "permissionDecisionReason": "Elenchus bookkeeping"}})
    if not s["active"]:
        return
    for v in [ti.get(k) for k in ("file_path", "notebook_path", "path")] + patch_paths(tool, ti):
        if isinstance(v, str) and v and protected(v, cwd):
            return deny("ELENCHUS: the gate machinery (.elenchus, the plugin, hook and settings files) is off limits. Use the CLI.")
    if names & SHELL_TOOLS:
        cmd = shell_command(ti)
        if sub:
            return
        if touches_machinery(cmd):
            return deny("ELENCHUS: touching the gate machinery from the shell is not allowed. Use the CLI commands only.")
    ph, mode = s["phase"], s["mode"]
    if names & READ_TOOLS or mcp_read_only(tool):
        return
    if ph == "open":
        return
    if mode == "predict":
        if ph == "await_prediction" and names & WRITE_TOOLS:
            return
    deny(f"ELENCHUS LOCKED ({mode or 'unset'}/{ph}). {tool} is blocked until the user has done their part. {fmt(ph, s)}"
         + (f" Run `{cli_prefix(s)} status` for the full briefing." if VIBE else ""))


def hook_posttool(p: dict) -> None:
    """Vibe 3.1 can append context to tool results, even without a prompt hook."""
    if not VIBE:
        return
    d = state_dir(p.get("cwd"), p.get("session_id", ""))
    s = load(d)
    s["session_id"] = p.get("session_id", "")
    tool, ti = p.get("tool_name", ""), p.get("tool_input") or {}
    if not isinstance(ti, dict):
        ti = {}
    names = {tool, tool.rsplit(".", 1)[-1]}
    # CLI transitions already return their new state. Never append a stale prompt notice.
    if names & SHELL_TOOLS and is_cli(shell_command(ti), bool(names & {"PowerShell", "powershell"}), p.get("cwd", ""), s["session_id"]):
        return
    if s["briefed_turn"] == s["turn"] or (not s["notice"] and (not s["active"] or s["phase"] == "open")):
        return
    context = s["notice"] or briefing(s)
    s.update(notice="", briefed_turn=s["turn"])
    if (d / "state.json").exists():
        save(d, s)
    out({"hook_specific_output": {"additional_context": context}})


# ---------------------------------------------------------------- stop hook

def last_text(path):
    if not path or not os.path.exists(path):
        return None
    last = None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                msg = o.get("message") if isinstance(o, dict) else None
                if not isinstance(msg, dict) or (o.get("type") or msg.get("role")) != "assistant":
                    continue
                c = msg.get("content")
                if isinstance(c, str):
                    t = c
                elif isinstance(c, list):
                    t = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
                else:
                    continue
                if t.strip():
                    last = t
    except OSError:
        return None
    return last


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
        return (f"{TAG} ask one short probing question, or record a verdict (decide gate: assess), "
                f"then end the turn. {NOREPEAT}")
    if ph == "review":
        return f"{TAG} assess the reflection before ending; accept sound reasoning or register a retry question."
    if ph == "verdict_ok" and not asks(text) and not any(x in low for x in ("agree:", "reflect:", "disagree:")):
        return f"{TAG} ask for the user's conclusion and reasons. Disagreement is welcome. {NOREPEAT}"
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


def hook_stop(p: dict) -> None:
    d = state_dir(p.get("cwd"), p.get("session_id", ""))
    s = load(d)
    if VIBE:
        s["session_id"] = p.get("session_id", "")
        turns = read_turns(p, d, s)  # covers turns without a tool call
    if not s["active"]:
        return
    text = p.get("last_assistant_message")
    if not isinstance(text, str) or not text.strip():
        text = (next((e["text"] for e in reversed(turns) if e["role"] == "assistant"), None)
                if VIBE else last_text(p.get("transcript_path")))
    if (s["phase"] == "attempted" and s["mode"] in MIN_ROUNDS and s["housekeeping_turn"] != s["turn"]
            and text and asks(text) and not leaks(text)):
        register_challenge(s, text)  # record the actual closing question without a model/tool round trip
    reason = teeth(s, text)
    warn = None
    if reason:
        if VIBE and not s["turn_nudges"]:
            s["turn_nudges"] = 1
            save(d, s)
            return out({"decision": "deny", "reason": reason})  # Vibe hands the reason back as a retry
        if not VIBE and not p.get("stop_hook_active"):
            return out({"decision": "block", "reason": reason})
        s["violations"] += 1
        s["last_violation"] = reason[:160]
        warn = f"[+] Elenchus warning: {HOST} ignored a rule and ended its turn anyway. {reason.replace(TAG, '').strip()[:160]}"
    if text and asks(text) and s["phase"] in ("await_attempt", "challenging", "await_prediction", "verdict_ok", "await_reconcile") and reason is None:
        # Keep the last valid ask beside the input, even without explicit question CLI.
        # Prediction replies may include the code being shown. Only pin the ask.
        s["focus_question"] = re.sub(r"```.*?```", "", text, flags=re.S).strip()[-1500:]
        s["notice"] = ""  # the reply has advanced or pinned this state; discard the old prompt snapshot
    elif warn is None:
        return
    save(d, s)
    if warn:
        out({"system_message" if VIBE else "systemMessage": warn})


# ---------------------------------------------------------------- CLI

def die(msg: str):
    print(msg)
    sys.exit(1)


def need_active(s: dict) -> None:
    if not s["active"]:
        die("Elenchus is not active. Only the user can start it, with /elenchus:learn.")


def cmd_gate(d, s, a):
    need_active(s)
    if s["phase"] not in ("need_gate", "idle", "open"):
        die(f"A gate is already in progress (mode={s['mode']}, phase={s['phase']}). Finish it first.")
    if a.question and (a.mode == "predict" or words(a.question) > MAX_WORDS or not asks(a.question) or leaks(a.question)):
        die("Use one short opening question; predict registers its question with prepare.")
    reset_gate(s)
    s.update(mode=a.mode, topic=a.topic, gate_turn=s["turn"])
    s["phase"] = "await_prediction" if a.mode == "predict" else "await_attempt"
    s["focus_question"] = a.question
    save(d, s)
    print("Gate ready. Ask the opening question and end the turn; it is pinned automatically.")


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


def register_challenge(s, text):
    if s["mode"] == "decide" and not s["agreement"]:
        s["agreement"] = {"turn": s["turn"], "text": s["attempt"]["text"]}  # the choice as first stated
    s["rounds"] += 1
    s["challenge_turn"] = s["turn"]
    s["challenges"].append(text[:500])
    s["focus_question"] = text[:1500]
    s["help_level"] = 0
    s["phase"] = "challenging"


def cmd_challenge(d, s, a):
    need_active(s)
    if s["mode"] not in ("explain", "propose", "decide"):
        die("challenge applies to explain, propose and decide gates only.")
    if s["phase"] != "attempted":
        die(f"Cannot challenge in phase {s['phase']}. The user has to make an attempt first.")
    register_challenge(s, a.text)
    save(d, s)
    print(f"Challenge {s['rounds']} registered. Ask it now, briefly, and end the turn.")


def verdict_problem(s):
    if s["mode"] not in ("explain", "propose"):
        return "verdict applies to explain and propose gates only. A decide gate ends with assess."
    if s["phase"] != "attempted":
        return f"Cannot accept in phase {s['phase']}. The user must have answered your latest challenge first."
    need = MIN_ROUNDS[s["mode"]]
    if s["rounds"] < need:
        return f"{s['rounds']}/{need} challenge rounds done. Ask a probe, then wait for the user's answer."
    if s["attempt"]["turn"] <= s["challenge_turn"]:
        return "The user has not answered your latest challenge yet."
    return ""


def cmd_verdict(d, s, a):
    need_active(s)
    problem = verdict_problem(s)
    if problem:
        die(problem)
    s["verdict"] = {"turn": s["turn"], "note": a.note[:500], "missed": a.missed[:500]}
    s["phase"] = "verdict_ok"
    s["focus_question"] = "What is your conclusion, and what reasons support it? Disagreement is welcome."
    save(d, s)
    print("Verdict recorded. Ask for their conclusion and reasons, including disagreement. Plain reasoning or reflect: both work.")


def assessment_problem(s):
    if s["mode"] == "decide":
        if s["phase"] != "attempted" or s["rounds"] < 1 or s["attempt"]["turn"] <= s["challenge_turn"]:
            return "A decide gate needs the user's choice, one challenge and their answer before it can be accepted."
    elif s["phase"] != "review" or not s["agreement"]:
        return "Only a user reflection can be assessed."
    return ""


def cmd_assess(d, s, a):
    need_active(s)
    problem = assessment_problem(s)
    if problem:
        die(problem)
    decide = s["mode"] == "decide"
    if decide:
        if a.result == "retry":
            die("In a decide gate, challenge again instead of retrying.")
        first = (s["agreement"] or {}).get("text", "")
        s["agreement"] = {"turn": s["turn"], "text": f"{first} | Challenged, I answered: {s['attempt']['text']}"}
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
    if decide:
        evidence = {k: v for k, v in evidence.items() if v}
        if not a.note:
            die("Acceptance needs --note: the decision and its reason, in the user's words.")
    elif not all(meaningful(v) for v in evidence.values()) or not a.note:
        die("Acceptance needs evidence of mechanism, transfer to a new case, a limit, and a note. Quote or paraphrase the learner; do not invent evidence.")
    if s["mode"] == "predict" and not s["run_result"]:
        die("A prediction gate needs a recorded execution before acceptance.")
    verdict = s["verdict"] or {}
    verdict.update(note=a.note[:1500], evidence=evidence, missed=a.missed or verdict.get("missed", ""))
    s["verdict"] = verdict
    saved = complete(d, s, "recall" if s["recall"] else "reconcile" if s["mode"] == "predict" else "reflection", a.links)
    owned = ""
    if s.get("own"):
        p = paper_of(d)
        owned = paper.bind(p, s["own"], s["completed"][-1]) if p else "No paper found; run `paper bind` after /elenchus:paper."
    s.update(own="", own_brief="", recall=False, last_violation="", phase="open", focus_question="")
    save(d, s)
    print("Understanding accepted. Work is open until the next gate starts." + (f" {owned}." if owned else "") + f" {saved}")


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
    print(json.dumps({"prediction": s["attempt"]["text"], "actual": output, "next": fmt(s["phase"], s)}, ensure_ascii=False))


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
    passed = [c for c in s["completed"] if c.get("how") != "delegated"]
    topics = [c["topic"] for c in passed]
    if not topics:
        die("No topic has passed its gate yet. Cards come only from completed gates.")
    topic = a.topic or topics[-1]
    if topic not in topics:
        die(f"Topic {topic!r} has not passed a gate. Completed: {topics[-5:]}")
    mode = next(c["mode"] for c in reversed(passed) if c["topic"] == topic)
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


def paper_of(d: Path):
    edir = project_dir(d)
    return paper.find(edir.parent, edir)


def cmd_choice(d, s, a):
    """Append the agent's choice to this session's latest delegation, never user words."""
    need_active(s)
    rec = next((c for c in reversed(s["completed"]) if c.get("session_id") == s["session_id"]), None)
    if s["phase"] != "open" or not rec or rec.get("how") != "delegated":
        die("Only this session's latest delegated decision can receive an agent choice, in open work.")
    note = " ".join(a.note.split())
    if not note or len(note) > 1500:
        die("A choice needs --note with 1 to 1500 characters.")
    if rec.get("agent_choice") and rec["agent_choice"] != note:
        die("The agent's choice is already recorded; it cannot be replaced.")
    rec["agent_choice"] = note
    dest = project_dir(d) / "history" / (rec["id"] + ".json")
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, dest)
    save(d, s)
    path = graph_dir() / (node(rec["topic"]) + ".md")
    try:
        with locked(graph_dir()):
            text = path.read_text(encoding="utf-8")
            entries = text.split("\n## ")
            entry = next(i for i, body in enumerate(entries[1:], 1)
                         if body.split("\n", 1)[0].endswith("· delegated · gate " + rec["id"][:8]))
            line = f"- **The agent chose:** {note}\n"
            if line not in entries[entry].splitlines(keepends=True):
                entries[entry] = entries[entry].rstrip("\n") + "\n" + line
                tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
                tmp.write_text("\n## ".join(entries), encoding="utf-8")
                os.replace(tmp, path)
    except (OSError, StopIteration) as exc:
        die(f"Choice saved in project history; graph update failed ({exc}). Retry the same choice after fixing the graph.")
    print(f"Agent choice recorded: {path}")


PAPER_SETUP = ("The user wants an owner's paper for this project. Ask once where it should live: inside this repository "
               "(docs/paper, only if the repository is private and theirs) or in their own notes folder (public repositories, "
               "code they do not own). For employer or client work, first ask whether they may keep notes outside those "
               "systems; without a clear yes, do not create the paper. Then run `{cli} paper init --path <folder> --name <project>`. Offer a recall check "
               "before anything else: they write recall.md next to the paper from memory, without the code and without you. "
               "When they are ready, add every decision you find in the code as one line under '== Decisions': "
               '#decision("what was decided", origin: "inherited", where: "file:line"). What and where, never why. '
               "Finish with `{cli} paper status`.")
PAPER_SHOW = ("Run `{cli} paper status` and `{cli} paper build`, and report both briefly: the state, the PDF path, "
              "or the Typst error to fix. If the paper has #card lines, also run `{cli} paper cards`. "
              "Suggest the next decision to formalize or own, foundations first. "
              "Decisions marked [not formalized] need a labeled equation, invariant, definition or algorithm, "
              "written by the user, before /elenchus:own accepts them.")


def cmd_paper(d, s, a):
    if a.sub == "init":
        edir = project_dir(d)
        p = paper.init(edir.parent, edir, a.path, a.name)
        print(f"Paper ready: {p}")
        return
    if a.sub == "status" and a.all:
        print(paper.status_all())
        return
    p = paper_of(d)
    if not p:
        die("No owner's paper in this project yet. The user starts one with /elenchus:paper.")
    if a.sub == "cards":
        print(paper.cards(p, project_dir(d) / "anki"))
        return
    if a.sub == "status":
        print(paper.status(p))
        return
    if a.sub == "build":
        try:
            print(f"PDF: {paper.build(p)}")
        except RuntimeError as e:
            die(f"Typst could not build the paper:\n{e}")
        return
    if a.sub == "check":
        _, problem = paper.readiness(p, a.title)
        print(problem or "Ready: the decision is formalized and every label resolves. The user can start /elenchus:own.")
        return
    # bind: one passed gate of this project (any session) to a formalized decision,
    # e.g. a gate that covered several closely related decisions
    _, problem = paper.readiness(p, a.title)
    if problem:
        die(problem)
    recs = []
    for f in (project_dir(d) / "history").glob("*.json"):
        try:
            recs.append(json.loads(f.read_text(encoding="utf-8")))
        except ValueError:
            continue
    recs = sorted((r for r in recs if r.get("how") != "delegated" and (not a.gate or r.get("id") == a.gate)),
                  key=lambda r: r.get("created", 0))
    if not recs:
        die("No passed gate in this project." if not a.gate else f"Gate {a.gate} not found in this project.")
    print(paper.bind(p, a.title, recs[-1]))


def cmd_status(d, s, a):
    if a.brief and s["active"]:
        print(s["notice"] or briefing(s))
        if s["notice"]:
            s["notice"] = ""
            save(d, s)
        return
    if not s["active"]:
        print(s["notice"] or "Elenchus is inactive. The user starts it with /elenchus:learn.")
        return
    print(s["notice"] or briefing(s))
    if s["notice"]:  # Vibe: what the user's last message produced, delivered once
        s["notice"] = ""
        save(d, s)
    print(f"Completed gates: {len(s['completed'])} | rule violations on record: {s['violations']}")
    print("Earlier topics (use only a genuinely relevant connection):")
    for c in s["completed"][-10:]:
        print(json.dumps({k: c.get(k, "") for k in ("topic", "mode", "own_words", "missed", "evidence")}, ensure_ascii=False))
    if not s["completed"]:
        print("None yet. Do not invent a connection card.")
    pp = paper_of(d)  # Vibe has no session hook, so status carries the session notes
    for note in (paper.session_note(pp, cli_prefix(s)) if pp else "", graph_note(cli_prefix(s))):
        if note:
            print("\n" + note)


def cli_main(argv):
    ap = argparse.ArgumentParser(prog="elenchus.py")
    ap.add_argument("--session", default="")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate")
    g.add_argument("--mode", required=True, choices=MODES)
    g.add_argument("--topic", required=True)
    g.add_argument("--question", default="")
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
    for key in ("mechanism", "transfer", "limit", "note", "missed", "question", "links"):
        review.add_argument("--" + key, default="")
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--runtime", choices=("python", "node"), required=True)
    prepare.add_argument("--file", required=True)
    prepare.add_argument("--source", action="append", default=[])
    prepare.add_argument("--question", required=True)
    sub.add_parser("run")
    sub.add_parser("status").add_argument("--brief", action="store_true")
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
    pp = sub.add_parser("paper")
    ps = pp.add_subparsers(dest="sub", required=True)
    pi = ps.add_parser("init")
    pi.add_argument("--path", required=True)
    pi.add_argument("--name", required=True)
    pst = ps.add_parser("status")
    pst.add_argument("--all", action="store_true")
    ps.add_parser("build")
    ps.add_parser("cards")
    pc = ps.add_parser("check")
    pc.add_argument("--title", required=True)
    pb = ps.add_parser("bind")
    pb.add_argument("--title", required=True)
    pb.add_argument("--gate", default="")
    sub.add_parser("graph").add_argument("words", nargs="*")
    sub.add_parser("choice").add_argument("--note", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "graph":  # reads only what spans projects: no project state, no folder
        return cmd_graph(None, None, a)
    if a.cmd == "paper" and a.sub == "status" and a.all:
        return print(paper.status_all())
    if not a.session and a.cmd == "status":
        # Vibe cannot tell the agent its session id: a bare status adopts the newest
        # session here, and its briefing prints the exact prefix for everything else.
        states = list((state_dir(None, "") / "sessions").glob("s-*/state.json"))
        if states:
            a.session = bytes.fromhex(max(states, key=lambda f: f.stat().st_mtime).parent.name[2:]).decode("utf-8", "replace")
    d = state_dir(None, a.session)
    with maybe_locked(d):
        s = load(d)
        s["session_id"] = a.session
        handler = {"gate": cmd_gate, "challenge": cmd_challenge, "verdict": cmd_verdict,
                   "assess": cmd_assess, "prepare": cmd_prepare, "run": cmd_run,
                   "question": cmd_question, "status": cmd_status, "cards": cmd_cards,
                   "paper": cmd_paper, "graph": cmd_graph, "choice": cmd_choice}[a.cmd]
        moving = a.cmd in ("gate", "question", "challenge", "verdict", "assess", "prepare", "run", "choice")
        if moving:
            s["notice"] = ""
        try:
            if a.cmd == "cards" and (a.sub == "add" or (project_dir(d) / "anki").is_dir()):
                with locked(project_dir(d) / "anki"):
                    handler(d, s, a)
            else:
                handler(d, s, a)
        except SystemExit as exc:
            if exc.code and s["active"]:
                print(step(s))  # recover in this result instead of another status/model round trip
            raise
        if moving and a.cmd != "run":
            print(step(s))



HOOKS = {"hook-session": hook_session, "hook-prompt": hook_prompt,
         "hook-pretool": hook_pretool, "hook-stop": hook_stop, "hook-posttool": hook_posttool}


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
            with maybe_locked(d):
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
