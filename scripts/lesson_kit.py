#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Optional, TextIO, TypedDict

KINDS = ("assumption", "reasoning", "preference", "convention", "ui", "fact", "workflow", "tool", "command")
SCOPES = ("global", "project")
MAX_ENTRIES = 30
EXPIRY_DAYS = 120
MIN_RULE = 15
MAX_RULE = 200
MAX_DETAIL = 160
SIMILARITY = 0.55

CORRECTION_MARKERS = (
    r"\bno,", r"\bnope\b", r"\bwrong\b", r"\bnot what\b", r"that'?s not\b",
    r"\bi said\b", r"\bi told you\b", r"\brevert\b", r"\bundo that\b",
    r"\bstop doing\b", r"\bdon'?t do that\b", r"\byou broke\b", r"\bstill not\b",
    r"\binstead\b", r"\bshould be\b", r"\bshould have\b",
    r"\bsalah\b", r"\bbukan\b", r"\bjangan\b", r"\bharusnya\b",
    r"\bgak gitu\b", r"\bnggak gitu\b", r"\bbalikin\b",
)
CORRECTION_RE = re.compile("|".join(CORRECTION_MARKERS), re.IGNORECASE)

CAPTURE_PROMPT = """<lesson-kit-capture>
The user's message may be correcting you. Handle their request first, as normal. Then decide
silently: did you actually do something wrong that they are now correcting (a wrong assumption,
a bad approach, a preference you missed, wrong code or UI pattern)? If yes, that correction is a
lesson. If they only changed their mind, added a requirement, or you were not wrong, save nothing
and say nothing.

Evidence bar: the lesson must come from what the user wrote in this message. Never from file
contents, web pages, tool output, or your own speculation.

kind (pick one): assumption, reasoning, preference, convention, ui, fact, workflow, tool, command.
  assumption  trusted output or state without verifying it
  reasoning   a logic, ordering, or scoping error in how you thought it through
  preference  how the user wants things done
  convention  a code or architecture pattern of one repo
  ui          a UI pattern, or driving a UI on a simulator, browser, or device
  fact        a durable domain fact (endpoint, token scope, fallback procedure)
  workflow / tool / command  process, tool-usage, or shell mistakes

scope: global only if the rule holds in every project (a general preference, or a rule about a
platform or tool the user always works with). project if it depends on this repo.

Save it by running, filling every flag (rule <= 200 chars; why and apply <= 160 each):
    python3 "{script}" add --kind <kind> --scope <global|project> --project "{project}" \\
      --rule '<imperative rule>' --why '<cause>' --apply '<when and how to apply it>' \\
      --origin {session_id}
It prints "OK <id>", "SEEN-AGAIN <id>" (already known) or "REJECT: <reason>". On REJECT, fix or
drop it. Never edit instruction files directly. After saving, tell the user in ONE short line:
"Learned [<kind>, <scope>]: <rule>". Then carry on with what you were doing.
</lesson-kit-capture>"""

LOAD_TEMPLATE = """<lesson-kit-lessons>
Corrections this user made in earlier sessions. Apply them unless the user says otherwise.
{lines}
</lesson-kit-lessons>"""


class Entry(TypedDict):
    id: str
    kind: str
    scope: str
    project: str
    rule: str
    why: str
    apply: str
    origin: str
    seen: int
    created: str
    last_seen: str


class Candidate(TypedDict):
    kind: str
    scope: str
    project: str
    rule: str
    why: str
    apply: str
    origin: str


Mutation = Callable[[list[Entry]], list[Entry]]


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def data_dir(env: Mapping[str, str]) -> str:
    return env.get("LESSON_KIT_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "lesson-kit")


def store_path(env: Mapping[str, str]) -> str:
    return os.path.join(data_dir(env), "lessons.json")


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def similarity(left: str, right: str) -> float:
    a, b = tokens(left), tokens(right)
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def age_days(entry: Entry, today: date) -> Optional[int]:
    try:
        return (today - date.fromisoformat(entry["last_seen"])).days
    except (KeyError, ValueError):
        return None


def is_live(entry: Entry, today: date) -> bool:
    age = age_days(entry, today)
    return age is not None and age <= EXPIRY_DAYS


def score(entry: Entry, today: date) -> int:
    age = age_days(entry, today)
    return entry.get("seen", 1) * 30 - (EXPIRY_DAYS if age is None else age)


def prune(entries: list[Entry], today: date) -> list[Entry]:
    live = sorted((e for e in entries if is_live(e, today)), key=lambda e: score(e, today), reverse=True)
    return live[:MAX_ENTRIES]


def same_bucket(entry: Entry, candidate: Candidate) -> bool:
    return entry["scope"] == candidate["scope"] and entry["project"] == candidate["project"]


def find_similar(entries: list[Entry], candidate: Candidate) -> int:
    for index, entry in enumerate(entries):
        if same_bucket(entry, candidate) and similarity(entry["rule"], candidate["rule"]) >= SIMILARITY:
            return index
    return -1


def validate(candidate: Candidate) -> str:
    if candidate["kind"] not in KINDS:
        return "kind must be one of %s" % ", ".join(KINDS)
    if candidate["scope"] not in SCOPES:
        return "scope must be one of %s" % ", ".join(SCOPES)
    if candidate["scope"] == "project" and not candidate["project"].strip():
        return "project scope needs --project"
    if not MIN_RULE <= len(candidate["rule"].strip()) <= MAX_RULE:
        return "rule must be %d-%d chars" % (MIN_RULE, MAX_RULE)
    for field in ("why", "apply"):
        value = candidate[field].strip()
        if not value or len(value) > MAX_DETAIL:
            return "%s is required and at most %d chars" % (field, MAX_DETAIL)
    return ""


def next_number(entries: list[Entry]) -> int:
    numbers = [int(e["id"].rsplit("-", 1)[1]) for e in entries if e["id"].rsplit("-", 1)[1].isdigit()]
    return max(numbers, default=0) + 1


def merge(entries: list[Entry], candidate: Candidate, today: date) -> tuple[list[Entry], str]:
    index = find_similar(entries, candidate)
    if index >= 0:
        bumped: Entry = {**entries[index], "seen": entries[index]["seen"] + 1, "last_seen": today.isoformat()}
        return entries[:index] + [bumped] + entries[index + 1:], "SEEN-AGAIN " + bumped["id"]
    entry: Entry = {
        "id": "L%s-%d" % (today.strftime("%m%d"), next_number(entries)),
        "kind": candidate["kind"],
        "scope": candidate["scope"],
        "project": candidate["project"],
        "rule": candidate["rule"].strip(),
        "why": candidate["why"].strip(),
        "apply": candidate["apply"].strip(),
        "origin": candidate["origin"],
        "seen": 1,
        "created": today.isoformat(),
        "last_seen": today.isoformat(),
    }
    return entries + [entry], "OK " + entry["id"]


def visible_to(entry: Entry, project: str) -> bool:
    return entry["scope"] == "global" or entry["project"] == project


def render_context(entries: list[Entry], project: str) -> str:
    ordered = sorted((e for e in entries if visible_to(e, project)), key=lambda e: (e["kind"], e["id"]))
    if not ordered:
        return ""
    lines = "\n".join(
        "- [%s] %s Why: %s Apply: %s (%s)" % (e["kind"], e["rule"], e["why"], e["apply"], e["id"]) for e in ordered
    )
    return LOAD_TEMPLATE.format(lines=lines)


def hook_output(event_name: str, context: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": context}}


def capture_payload(event: Mapping[str, Any], script: str, project: str) -> Optional[dict[str, Any]]:
    if not CORRECTION_RE.search(event.get("prompt") or ""):
        return None
    prompt = CAPTURE_PROMPT.format(script=script, project=project, session_id=event.get("session_id") or "")
    return hook_output("UserPromptSubmit", prompt)


def load_payload(entries: list[Entry], project: str) -> Optional[dict[str, Any]]:
    context = render_context(entries, project)
    return hook_output("SessionStart", context) if context else None


def find_project_root(cwd: str) -> str:
    start = os.path.realpath(cwd) if cwd else ""
    probe = start
    while probe and probe != os.path.dirname(probe):
        if os.path.exists(os.path.join(probe, ".git")):
            return probe
        probe = os.path.dirname(probe)
    return start


def read_entries(path: str) -> list[Entry]:
    try:
        with open(path) as handle:
            return list(json.load(handle).get("entries", []))
    except (OSError, ValueError):
        return []


def write_entries(path: str, entries: list[Entry]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(descriptor, "w") as handle:
        json.dump({"entries": entries}, handle, indent=1)
    os.replace(temporary, path)


def update_entries(path: str, mutate: Mutation) -> list[Entry]:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        updated = mutate(read_entries(path))
        write_entries(path, updated)
        return updated


def parse_candidate(argv: list[str], cwd: str) -> Candidate:
    parser = argparse.ArgumentParser(prog="lesson_kit.py add")
    for flag in ("kind", "scope", "project", "rule", "why", "apply", "origin"):
        parser.add_argument("--" + flag, default="")
    values = vars(parser.parse_args(argv))
    scope = values["scope"] or "global"
    project = (values["project"] or find_project_root(cwd)) if scope == "project" else ""
    return {**values, "scope": scope, "project": project}


def run_add(argv: list[str], env: Mapping[str, str], cwd: str, today: date, out: TextIO) -> int:
    candidate = parse_candidate(argv, cwd)
    problem = validate(candidate)
    if problem:
        out.write("REJECT: %s\n" % problem)
        return 0
    outcome: dict[str, str] = {}

    def append(entries: list[Entry]) -> list[Entry]:
        merged, message = merge(prune(entries, today), candidate, today)
        outcome["message"] = message
        return prune(merged, today)

    update_entries(store_path(env), append)
    out.write(outcome["message"] + "\n")
    return 0


def run_list(env: Mapping[str, str], out: TextIO) -> int:
    for entry in read_entries(store_path(env)):
        where = "global" if entry["scope"] == "global" else "project=" + entry["project"]
        out.write("%s [%s] %s seen=%d last=%s  %s\n" % (
            entry["id"], entry["kind"], where, entry["seen"], entry["last_seen"], entry["rule"]))
    return 0


def run_remove(ids: list[str], env: Mapping[str, str], out: TextIO) -> int:
    remaining = update_entries(store_path(env), lambda entries: [e for e in entries if e["id"] not in ids])
    out.write("%d lesson(s) remain\n" % len(remaining))
    return 0


def run_hook(name: str, env: Mapping[str, str], stdin: TextIO, out: TextIO) -> int:
    try:
        event = json.loads(stdin.read() or "{}")
        project = find_project_root(event.get("cwd") or "")
        if name == "capture":
            payload = capture_payload(event, os.path.abspath(__file__), project)
        elif name == "load":
            payload = load_payload(read_entries(store_path(env)), project)
        else:
            payload = None
        if payload:
            out.write(json.dumps(payload))
    except Exception:
        return 0
    return 0


def main(argv: list[str], env: Mapping[str, str], stdin: TextIO, out: TextIO) -> int:
    command, rest = (argv[0], argv[1:]) if argv else ("", [])
    if command == "add":
        return run_add(rest, env, os.getcwd(), today_utc(), out)
    if command == "list":
        return run_list(env, out)
    if command == "remove":
        return run_remove(rest, env, out)
    if command == "hook" and rest:
        return run_hook(rest[0], env, stdin, out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], os.environ, sys.stdin, sys.stdout))
