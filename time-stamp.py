#!/usr/bin/env python3
"""Time-awareness hook for Claude Code, throttled.

  * UserPromptSubmit: always stamp.
  * PostToolUse: stamp only if this agent's last stamp is >= THROTTLE seconds old.

"This agent" is the session, or the subagent inside it: hook input carries
`agent_id` only when the hook fires inside a subagent, and a subagent has its own
context, so it gets its own throttle. Keyed on session_id alone, a subagent would
never see a stamp while its parent had been stamped recently.

State: mtime of <STATE_DIR>/time-stamp-<session_id>[-<agent_id>], one empty file
per agent. Fails open: any error -> silent exit 0.

Self-check: python3 time-stamp.py --self-test
"""
import sys, os, json, time, tempfile

THROTTLE = 600  # seconds
STATE_DIR = os.environ.get("TIME_STAMP_STATE_DIR",
                           os.path.expanduser("~/.claude/hooks/state"))


def fmt(now):
    return time.strftime("%H:%M:%S %Z %A", time.localtime(now))


def run(payload, state_dir, now, throttle=THROTTLE):
    """Return the hook JSON to print, or None to stay silent."""
    event = payload.get("hook_event_name", "")
    if event not in ("UserPromptSubmit", "PostToolUse"):
        return None
    key = "-".join(str(payload[k]) for k in ("session_id", "agent_id") if payload.get(k)) or "nosid"
    path = os.path.join(state_dir, "time-stamp-" + key)
    if event == "PostToolUse":
        try:
            if now - os.path.getmtime(path) < throttle:
                return None
        except OSError:
            pass
    os.makedirs(state_dir, exist_ok=True)
    with open(path, "a"):
        pass
    os.utime(path, (now, now))
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": event,
        "additionalContext": "Current time: " + fmt(now)}})


def self_test():
    d = tempfile.mkdtemp(prefix="ts-selftest-")
    t0 = 1_800_000_000.0
    post = {"hook_event_name": "PostToolUse", "session_id": "s1"}
    prompt = {"hook_event_name": "UserPromptSubmit", "session_id": "s1"}
    sub = {"hook_event_name": "PostToolUse", "session_id": "s1", "agent_id": "a1"}
    checks = [
        ("first PostToolUse prints", run(post, d, t0) is not None),
        ("PostToolUse 1 min later is silent", run(post, d, t0 + 60) is None),
        ("PostToolUse at 9m59s is silent", run(post, d, t0 + 599) is None),
        ("PostToolUse at 10m prints", run(post, d, t0 + 600) is not None),
        ("UserPromptSubmit always prints", run(prompt, d, t0 + 601) is not None),
        ("PostToolUse 1 min after a prompt is silent", run(post, d, t0 + 660) is None),
        ("subagent gets its own stamp while the parent is throttled", run(sub, d, t0 + 661) is not None),
        ("subagent is throttled on its own clock", run(sub, d, t0 + 700) is None),
        ("parent stays throttled after the subagent stamps", run(post, d, t0 + 701) is None),
        ("other sessions are independent",
         run({"hook_event_name": "PostToolUse", "session_id": "s2"}, d, t0 + 702) is not None),
        ("unknown event is silent", run({"hook_event_name": "Stop", "session_id": "s1"}, d, t0) is None),
    ]
    out = run(prompt, d, t0 + 800)
    checks.append(("event name echoed back", bool(out) and
                   json.loads(out)["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"))
    for name, ok in checks:
        print(("PASS " if ok else "FAIL ") + name)
    ok = all(c[1] for c in checks)
    print("SELF-TEST " + ("OK" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    try:
        out = run(json.load(sys.stdin), STATE_DIR, time.time())
        if out:
            print(out)
    except Exception:
        pass  # fail open: a broken clock must never break a tool call
    sys.exit(0)


if __name__ == "__main__":
    main()
