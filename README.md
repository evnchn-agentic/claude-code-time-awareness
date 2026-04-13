# claude-code-time-awareness

**Time awareness for autonomous Claude Code agents.**

Claude Code agents don't know what time it is during autonomous work. The system prompt date is set once at session start and goes stale immediately. Existing solutions only fire on user messages — useless when the agent is working autonomously for hours.

This hook injects the current time into the agent's context after every Bash command and Playwright browser interaction, so long-running autonomous sessions can pace themselves, stop at deadlines, and log accurate timestamps.

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
| **This project** | **`PostToolUse:Bash` + `PostToolUse:mcp__playwright__`** | **Works** | **Works** |

The key insight: `UserPromptSubmit` fires when a human sends a message. During autonomous work, there are no human messages — but there are plenty of Bash commands and browser interactions. `PostToolUse` fires consistently during both interactive and autonomous sessions.

## The Solution

A `PostToolUse` hook that injects the current time (with seconds) as `additionalContext` after every Bash call and Playwright interaction:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "echo '{\"hookSpecificOutput\":{\"hookEventName\":\"PostToolUse\",\"additionalContext\":\"Current time: '$(date \"+%H:%M:%S %Z %A\")'\"}}'"
          }
        ]
      },
      {
        "matcher": "mcp__playwright__",
        "hooks": [
          {
            "type": "command",
            "command": "echo '{\"hookSpecificOutput\":{\"hookEventName\":\"PostToolUse\",\"additionalContext\":\"Current time: '$(date \"+%H:%M:%S %Z %A\")'\"}}'"
          }
        ]
      }
    ]
  }
}
```

Add this to `~/.claude/settings.json` (global) or `.claude/settings.json` (project).

## Why Seconds?

Seconds matter for time-sensitive operations:
- **Hardware interactions** — GPIO, serial, IPKVM, sensor reads where sub-minute timing matters for debugging
- **Playwright browser testing** — correlating with network logs, debugging timeouts, animation timing
- **Negligible cost** — only 2 extra characters per injection (~1 token)

## How It Works

1. Agent runs a Bash command or Playwright action (happens constantly during autonomous work)
2. Hook fires, outputs JSON with `additionalContext` containing the current time
3. Claude Code injects the time string into the agent's context
4. Agent sees `Current time: 19:31:42 HKT Tuesday` and can act on it

The agent sees this as a system reminder after each call:
```
PostToolUse:Bash hook additional context: Current time: 19:31:42 HKT Tuesday
```

## Installation

Add to `~/.claude/settings.json`. If you already have `PostToolUse` hooks, merge into the existing array — don't replace it.

## Customization

### Different time format
```bash
# ISO 8601
date "+%Y-%m-%dT%H:%M:%S%z"

# 12-hour with AM/PM
date "+%I:%M:%S %p %Z"

# Unix timestamp
date "+%s"
```

### Additional matchers
You can add time awareness to any tool by adding another matcher entry:
```json
{
  "matcher": "mcp__docker__",
  "hooks": [{
    "type": "command",
    "command": "echo '{\"hookSpecificOutput\":{\"hookEventName\":\"PostToolUse\",\"additionalContext\":\"Current time: '$(date \"+%H:%M:%S %Z %A\")'\"}}'"
  }]
}
```

## FAQ

**Does this add overhead?**
Negligible. The `date` command takes <1ms. The injected context is ~15 tokens per call.

**Will the agent always obey the time?**
No — the time is informational, not a hard stop. The agent sees the time and can choose to wind down, but nothing forces it. This is by design: a binding time limit would be dangerous (can't stop on errors, runaway loops).

**Does this work with subagents?**
Yes — subagents spawn their own Bash calls, so they inherit time awareness from the global settings.

## Pairs Well With

- [claude-code-stop-gate](https://github.com/evnchn-agentic/claude-code-stop-gate) — nonce-based confirmation prevents accidental session termination. Time awareness is informational; stop gate is enforcement.

## License

MIT
