import json
import os
import subprocess
import sys
from datetime import date, timedelta

import lesson_kit as lk

TODAY = date(2026, 9, 21)
SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "lesson_kit.py")


def candidate(**overrides):
    base = {
        "kind": "ui",
        "scope": "global",
        "project": "",
        "rule": "Use the native iOS segmented control when a toggle between views is requested.",
        "why": "Built two buttons instead of a segmented control.",
        "apply": "Any tab or toggle request in an iOS app.",
        "origin": "session-1",
    }
    return {**base, **overrides}


def entry(**overrides):
    merged, _ = lk.merge([], candidate(**overrides), TODAY)
    return merged[0]


def test_data_dir_is_the_same_for_hooks_and_shell_commands():
    hook_env = {"CLAUDE_PLUGIN_DATA": "/somewhere/plugin-data"}
    shell_env = {}
    assert lk.data_dir(hook_env) == lk.data_dir(shell_env)


def test_data_dir_honors_the_explicit_override():
    assert lk.data_dir({"LESSON_KIT_DIR": "/custom"}) == "/custom"


def test_validate_accepts_a_complete_candidate():
    assert lk.validate(candidate()) == ""


def test_validate_rejects_unknown_kind():
    assert "kind must be" in lk.validate(candidate(kind="vibes"))


def test_validate_rejects_short_rule():
    assert "rule must be" in lk.validate(candidate(rule="too short"))


def test_validate_rejects_missing_why():
    assert "why is required" in lk.validate(candidate(why=""))


def test_validate_requires_project_for_project_scope():
    assert "needs --project" in lk.validate(candidate(scope="project", project=""))


def test_merge_adds_a_new_entry_with_incrementing_id():
    first, message = lk.merge([], candidate(), TODAY)
    second, _ = lk.merge(first, candidate(rule="Run the linter before every commit, no exceptions."), TODAY)
    assert message == "OK L0921-1"
    assert [e["id"] for e in second] == ["L0921-1", "L0921-2"]


def test_merge_bumps_a_similar_rule_instead_of_duplicating():
    first, _ = lk.merge([], candidate(), TODAY)
    again, message = lk.merge(first, candidate(rule="Use native iOS segmented control when a toggle between views is requested."), TODAY)
    assert message == "SEEN-AGAIN L0921-1"
    assert len(again) == 1 and again[0]["seen"] == 2


def test_merge_keeps_similar_rules_apart_across_projects():
    a = candidate(scope="project", project="/work/a")
    b = candidate(scope="project", project="/work/b")
    first, _ = lk.merge([], a, TODAY)
    both, message = lk.merge(first, b, TODAY)
    assert message.startswith("OK") and len(both) == 2


def test_prune_drops_expired_entries():
    old = {**entry(), "last_seen": (TODAY - timedelta(days=lk.EXPIRY_DAYS + 1)).isoformat()}
    assert lk.prune([old, entry()], TODAY) == [entry()]


def test_prune_caps_the_store_and_keeps_the_most_seen():
    entries = [{**entry(), "id": "L0921-%d" % n, "seen": n} for n in range(1, lk.MAX_ENTRIES + 6)]
    kept = lk.prune(entries, TODAY)
    assert len(kept) == lk.MAX_ENTRIES
    assert max(e["seen"] for e in kept) == lk.MAX_ENTRIES + 5


def test_visible_to_shows_global_everywhere_and_project_only_at_home():
    assert lk.visible_to(entry(), "/anywhere")
    project_entry = entry(scope="project", project="/work/a")
    assert lk.visible_to(project_entry, "/work/a")
    assert not lk.visible_to(project_entry, "/work/b")


def test_render_context_is_empty_without_visible_lessons():
    assert lk.render_context([entry(scope="project", project="/work/a")], "/work/b") == ""


def test_render_context_lists_global_and_current_project_lessons():
    entries = [entry(), {**entry(scope="project", project="/work/a"), "id": "L0921-2", "rule": "Run make test before pushing changes."}]
    text = lk.render_context(entries, "/work/a")
    assert "segmented control" in text and "make test" in text
    assert "make test" not in lk.render_context(entries, "/work/b")


def test_capture_payload_fires_only_on_correction_words():
    silent = lk.capture_payload({"prompt": "please add a settings screen"}, SCRIPT, "/work/a")
    loud = lk.capture_payload({"prompt": "no, that's not what I asked", "session_id": "s1"}, SCRIPT, "/work/a")
    assert silent is None
    assert loud["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "s1" in loud["hookSpecificOutput"]["additionalContext"]


def test_capture_markers_cover_indonesian_corrections():
    assert lk.capture_payload({"prompt": "bukan button, harusnya segmented control"}, SCRIPT, "/w")


def test_load_payload_is_none_when_store_is_empty():
    assert lk.load_payload([], "/work/a") is None


def test_load_payload_targets_session_start():
    payload = lk.load_payload([entry()], "/work/a")
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_find_project_root_walks_up_to_the_git_directory(tmp_path):
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src" / "deep"
    nested.mkdir(parents=True)
    assert lk.find_project_root(str(nested)) == os.path.realpath(str(tmp_path))


def run_cli(args, data_dir, stdin=""):
    env = {**os.environ, "LESSON_KIT_DIR": str(data_dir)}
    return subprocess.run(
        [sys.executable, SCRIPT, *args], input=stdin, capture_output=True, text=True, env=env, cwd=str(data_dir)
    ).stdout


def test_cli_add_list_remove_round_trip(tmp_path):
    added = run_cli(
        ["add", "--kind", "ui", "--scope", "global", "--rule", candidate()["rule"],
         "--why", "because", "--apply", "always", "--origin", "s1"], tmp_path)
    assert added.startswith("OK ")
    listed = run_cli(["list"], tmp_path)
    assert "segmented control" in listed
    entry_id = listed.split()[0]
    assert "0 lesson(s) remain" in run_cli(["remove", entry_id], tmp_path)


def test_cli_add_reports_rejection_without_writing(tmp_path):
    out = run_cli(["add", "--kind", "nope", "--rule", "x"], tmp_path)
    assert out.startswith("REJECT")
    assert run_cli(["list"], tmp_path) == ""


def test_hook_load_emits_saved_lessons_as_json(tmp_path):
    run_cli(["add", "--kind", "ui", "--scope", "global", "--rule", candidate()["rule"],
             "--why", "because", "--apply", "always"], tmp_path)
    out = run_cli(["hook", "load"], tmp_path, stdin=json.dumps({"cwd": str(tmp_path)}))
    assert "segmented control" in json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_hook_never_raises_on_garbage_input(tmp_path):
    assert run_cli(["hook", "capture"], tmp_path, stdin="not json") == ""
