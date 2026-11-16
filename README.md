# claude-code-time-awareness

**Time awareness for autonomous Claude Code agents.**

Claude Code agents don't know what time it is during autonomous work. The system prompt date is set once at session start and goes stale immediately. Existing solutions only fire on user messages — useless when the agent is working autonomously for hours.

This hook injects the current time into the agent's context when a prompt arrives and, during autonomous work, after a Bash command or Playwright browser interaction at most once every 10 minutes. Long-running sessions can pace themselves, stop at deadlines, and log accurate timestamps, without a clock line after every single tool call.

## The Problem

Claude Code has no clock. The [system prompt date is set once at session start and never updates](https://github.com/anthropics/claude-code/issues/24182). This isn't hypothetical — the [issue has been raised](https://github.com/anthropics/claude-code/issues/24182) and [written about](https://dev.to/tadmstr/claude-code-doesnt-know-youve-been-gone-heres-the-fix-17ko), but existing solutions only work for interactive sessions.

Anyone running agents autonomously hits this:

- **"Work until 9pm"** — the agent has no way to know when 9pm arrives. It either asks you (defeats autonomy), guesses wrong (stale time), or ignores time entirely.
- **Shared machines** — you need the agent to stop before you take the laptop out, but you're away from it.
- **Overnight/multi-day jobs** — timestamps in logs, commits, and journals are wrong or missing. The agent doesn't know if it's been 5 minutes or 5 hours since the last message.
- **Cost control** — agent runs indefinitely instead of stopping after a reasonable work period.

## Prior Art & Why They Don't Work

| Approach | Mechanism | Interactive | Autonomous |
|---|---|---|---|
| [Issue #24182](https://github.com/anthropics/claude-code/issues/24182) | Inject timestamp into user messages | Would work (unimplemented) | No — no user messages |
| [DEV Community fix](https://dev.to/tadmstr/claude-code-doesnt-know-youve-been-gone-heres-the-fix-17ko) | `UserPromptSubmit` hook | Works | **No** — hook never fires |
| `SessionStart` hook | Inject time once at start | Stale in minutes | Stale in minutes |
| **This project** | **`UserPromptSubmit` + throttled `PostToolUse` (Bash, Playwright)** | **Works** | **Works** |

The key insight: `UserPromptSubmit` fires when a human sends a message. During autonomous work, there are no human messages — but there are plenty of Bash commands and browser interactions. `PostToolUse` fires consistently during both interactive and autonomous sessions.

## The Solution

[`time-stamp.py`](time-stamp.py), one small hook script (stdlib only), wired to two events:

- **`UserPromptSubmit`**: always stamps, so every human message arrives with the time.
- **`PostToolUse`** on `Bash|mcp__playwright__`: stamps only if this agent's last stamp is 10 or more minutes old.

The throttle is kept per agent: one empty state file per session, and a separate one per subagent (hook input carries `agent_id` only inside a subagent, and a subagent has its own context).

## Why throttle?

The first version of this repo stamped after every Bash and Playwright call. Measured on one machine running agents most of the day:

| | Bash calls | `PostToolUse` stamps | clock age when a Bash call ran |
|---|---|---|---|
| per-call echo (15–30 Oct 2026) | 19,677 | 19,111 | ~0 |
| throttled, 10 min (2–16 Nov 2026) | 20,783 | 80 | p50 0.4 min · p99 9.2 min · max 14.2 min |

Each stamp is small, but it was one more process and one more line of context on almost every call. The throttle removes 99.6% of them, and no Bash call ran with a clock more than about a quarter of an hour old.

**Why per agent, not per session:** keyed on `session_id` alone, a subagent shares its parent's throttle but not its context. On the same machine that left 178 of 200 subagents that ran 5+ Bash calls without a single stamp. The per-call echo had left none without one (0 of 262).

## Why Seconds?

Seconds matter for time-sensitive operations:
- **Hardware interactions** — GPIO, serial, IPKVM, sensor reads where sub-minute timing matters for debugging
- **Playwright browser testing** — correlating with network logs, debugging timeouts, animation timing
- **Negligible cost** — only 2 extra characters per injection (~1 token)

## How It Works

1. A prompt arrives, or the agent runs a Bash command or Playwright action
2. The hook reads this agent's state file. After a tool call with a stamp under 10 minutes old, it prints nothing
3. Otherwise it prints `additionalContext` with the current time and touches the state file
4. The agent sees the time as a system reminder:
```
PostToolUse:Bash hook additional context: Current time: 19:31:42 HKT Tuesday
```

## Installation

1. Copy the script: `mkdir -p ~/.claude/hooks && cp time-stamp.py ~/.claude/hooks/`
2. Check it: `python3 ~/.claude/hooks/time-stamp.py --self-test`
3. Merge [`settings-snippet.json`](settings-snippet.json) into `~/.claude/settings.json`. If you already have `PostToolUse` or `UserPromptSubmit` hooks, add to the existing arrays; don't replace them.

The interval is `THROTTLE` at the top of the script (600 s). State lives in `~/.claude/hooks/state` (override with `TIME_STAMP_STATE_DIR`); it is one empty file per session or subagent, never pruned, so clear it whenever you like. The hook fails open: on any error it prints nothing and exits 0.

## Customization

### Different time format
Edit `fmt()` in `time-stamp.py`; the `strftime` codes are the same as `date`'s:
```python
"%Y-%m-%dT%H:%M:%S%z"   # ISO 8601
"%I:%M:%S %p %Z"        # 12-hour with AM/PM
```

### Additional matchers
Extend the `PostToolUse` matcher regex, e.g. `"Bash|mcp__playwright__|mcp__docker__"`. All tools share the agent's one throttle.

### Unthrottled one-liner
The original per-call version, if you want a stamp after every Bash call and no script file:
```json
{
  "matcher": "Bash",
  "hooks": [{
    "type": "command",
    "command": "echo '{\"hookSpecificOutput\":{\"hookEventName\":\"PostToolUse\",\"additionalContext\":\"Current time: '$(date \"+%H:%M:%S %Z %A\")'\"}}'"
  }]
}
```

## FAQ

**Does this add overhead?**
A Python start-up per Bash/Playwright call (tens of milliseconds), and about 15 tokens of context per stamp — at most one stamp per agent per 10 minutes, plus one per prompt.

**Will the agent always obey the time?**
No — the time is informational, not a hard stop. The agent sees the time and can choose to wind down, but nothing forces it. This is by design: a binding time limit would be dangerous (can't stop on errors, runaway loops).

**Does this work with subagents?**
Yes. Subagents run the same global hooks, and each subagent has its own throttle (keyed on `agent_id`), so its first Bash call is stamped even if the parent was stamped a minute ago.

## Pairs Well With

- [claude-code-stop-gate](https://github.com/evnchn-agentic/claude-code-stop-gate) — nonce-based confirmation prevents accidental session termination. Time awareness is informational; stop gate is enforcement.

## License

MIT
