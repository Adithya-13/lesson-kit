# lesson-kit

Correct your AI once. Claude Code notes the correction and applies it in your next sessions.

## The problem it solves

You fix a mistake in one session. You open a fresh session and the AI makes the same mistake again, because it starts from zero every time. The usual fix is writing the rule into a `CLAUDE.md` yourself, and that only happens if you remember and have the time.

lesson-kit does the noting for you:

1. You correct the AI the way you normally would.
2. It saves the correction as a short rule and tells you in one line: `Learned [ui, global]: ...`
3. At the start of every later session, the rules that apply are loaded back in.

```
you:     bukan button, harusnya native segmented control
claude:  (fixes it) Learned [ui, global]: Use a native segmented control for switching views, not custom buttons.
```

**Status: early but real.** Capture, save, and reload work today. It has not been used long enough to know how it behaves after months of lessons.

---

## Read this before installing

**It writes instructions that load into every future session.** A wrong lesson follows you around until you remove it. Look at what it saved from time to time with `/lesson-kit:lessons`, and delete anything you disagree with.

**It does not make the model learn.** No training happens. It is notes that get read again at the start of each session.

**Capture is not guaranteed.** The AI itself decides whether your message was a real correction. And it is only asked to decide when your message contains a correction word, such as `no,` `wrong` `instead` `should be` `bukan` `salah` `harusnya`. The full list is `CORRECTION_MARKERS` in `scripts/lesson_kit.py`. A correction with none of those words is not captured.

**Lessons have limits.** At most 30 are kept, ranked by how often they came up and how recently. A lesson not seen for 120 days expires. Two lessons that say nearly the same thing are merged.

**Scope matters.** A lesson is either global (loads everywhere) or project (loads only in that git repository). The AI picks the scope when it saves. If a lesson lands in the wrong one, remove it and correct the AI again with a clearer statement, for example "in every project".

**It costs a little context.** Saved lessons are added to each new session. The instruction to save a lesson is added only to messages that contain a correction word.

**macOS and Linux only.** The store uses file locking that Windows does not have.

**One Claude Code version is verified.** Claude Code 2.1.278. Hooks are a young feature, so a different version may behave differently.

---

## Which Claude app do I use?

**Claude Code**, in any of its forms: the terminal CLI, the Code tab in the Claude desktop app, or the VS Code and JetBrains extensions. It needs hooks, which run on your machine.

---

## Requirements

| Thing | Why |
|---|---|
| Claude Code | hooks and plugins |
| Python 3.9+ | runs the hook script (`python3` must be on your PATH) |

Nothing else to install.

---

## Install

```
/plugin marketplace add Adithya-13/lesson-kit
/plugin install lesson-kit@lesson-kit
```

Start a new session so the hooks are picked up.

## Use

Work as you normally do. When the AI gets something wrong, correct it in plain words. When it saves a lesson you will see one line, `Learned [kind, scope]: ...`.

To see or remove what it saved:

```
/lesson-kit:lessons
```

## Where lessons are stored

One file: `~/.claude/lesson-kit/lessons.json`. It is plain JSON. Set `LESSON_KIT_DIR` to keep it somewhere else. It is never sent anywhere except into your own AI conversation as context.

## Uninstall

```
/plugin uninstall lesson-kit@lesson-kit
```

Then delete `~/.claude/lesson-kit` if you also want the saved lessons gone.

## How it works

Two hooks, one script, one file.

- `UserPromptSubmit`: if your message contains a correction word, it adds a short instruction asking the AI to decide whether to save a lesson, and how.
- `SessionStart`: it loads the lessons that apply, global ones plus the ones for the current git repository.
- `scripts/lesson_kit.py add | list | remove`: the AI calls `add` to save. `/lesson-kit:lessons` calls `list` and `remove`.

## Privacy

- Lessons stay in one local file on your machine.
- Nothing here contacts any server. Saved lessons reach the AI only as conversation context, like anything else in a session.
- A lesson is only created from something you wrote in your own message, never from file contents or tool output.

## Tests

```bash
pip install pytest
pytest tests -q
```

## License

MIT. See `LICENSE`.
