---
name: lessons
description: Audit the corrections lesson-kit has saved. List every lesson, show which are global and which belong to one project, and remove the ones that are wrong or outdated. Use when the user asks what the AI learned, wants to check saved lessons, or wants to delete one.
disable-model-invocation: true
---

# Audit saved lessons

lesson-kit saves a lesson when the user corrects the AI, and loads the relevant lessons at the start of every session. This skill is the audit: show what is saved, and remove what should not stay.

Run through the plugin's script: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lesson_kit.py"`.

## Steps

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lesson_kit.py" list`. If it prints nothing, say "no lessons saved yet" and stop.
2. Show the lessons grouped by scope: global first, then per project. Give each one its id, kind, and rule.
3. Flag lessons that contradict each other, or that look too specific to be global.
4. Ask which ones to remove. For each id the user names, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lesson_kit.py" remove <id>`.
5. Report how many lessons remain.

## Rules

- Never remove a lesson the user did not name.
- Never add or edit a lesson from this skill. Lessons are only created from a user correction during a session.
- Lessons live in one file, `lessons.json`, inside the plugin's data directory. Do not edit it by hand.
