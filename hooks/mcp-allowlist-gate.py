#!/usr/bin/env python3
"""Project gate for MCP allowlist checks and destructive shell commands.

The hook only locks calls. It does not decide policy. A missing or unapproved
server is denied. Destructive SQL and destructive shell commands ask the human.
Everything else on an approved server is allowed, and the always-on rule still
requires the agent to follow SKILL.md.
"""

import json
import re
import sys
from pathlib import Path

CURRENT_EVENT = ""

PREFLIGHT = (
    "MCP security preflight: before any MCP call, read .cursor/mcp-allowlist.yaml in the open project. "
    "If it is missing or the server is not approval_status approved, stop and ask. "
    "Write that file only after the human confirms the full list. "
    "Open the mcp-security-and-compliance skill for the policy. "
    "A hook deny must not be retried through the shell, curl, or a CLI. "
    "An approved server is not approval for writes, deletes, production changes, credentials, or external sends. "
    "Do not print secrets or api_key values. "
    "Cursor allowlist names are mcp_server_name. Claude Code names are the server key in mcp__<server>__<tool>."
)


def emit(payload):
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")


def decision(permission, user_message="", agent_message=""):
    if CURRENT_EVENT == "PreToolUse":
        specific = {
            "hookEventName": "PreToolUse",
            "permissionDecision": permission,
        }
        reason = agent_message or user_message
        if reason:
            specific["permissionDecisionReason"] = reason
        if permission == "allow" and agent_message:
            specific["additionalContext"] = agent_message
        emit({"hookSpecificOutput": specific})
        return 0

    payload = {"permission": permission}
    if user_message:
        payload["user_message"] = user_message
    if agent_message:
        payload["agent_message"] = agent_message
    emit(payload)
    return 0


def deny(user_message, agent_message):
    return decision("deny", user_message, agent_message)


def ask(user_message, agent_message):
    return decision("ask", user_message, agent_message)


def allow(agent_message=""):
    return decision("allow", agent_message=agent_message)


def unquote(value):
    value = value.split("#", 1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value.strip("'\"")


def approved_servers(text):
    """Read only real list entries. Ignore comments and block scalars."""
    approved = set()
    name = None
    status = None
    block_floor = None

    def flush():
        nonlocal name, status
        if name and status == "approved":
            approved.add(name)
        name = None
        status = None

    for raw in text.splitlines():
        if block_floor is not None:
            indent = len(raw) - len(raw.lstrip(" "))
            if raw.strip() and indent <= block_floor:
                block_floor = None
            else:
                continue

        stripped = raw.split("#", 1)[0].rstrip()
        if not stripped.strip():
            continue
        if re.search(r":\s*[|>][+-]?\s*$", stripped):
            block_floor = len(raw) - len(raw.lstrip(" "))
            continue

        name_match = re.match(r"^\s*-\s+name:\s*(.+)$", stripped)
        status_match = re.match(r"^\s*approval_status:\s*(.+)$", stripped)
        if name_match:
            if name is not None or status is not None:
                flush()
            name = unquote(name_match.group(1))
            continue
        if status_match and name is not None:
            status = unquote(status_match.group(1))
            flush()
    flush()
    return approved


def server_name(payload):
    named = str(payload.get("mcp_server_name") or "").strip()
    if named:
        return named
    command = str(payload.get("command") or "").strip()
    if command and re.fullmatch(r"[A-Za-z0-9._:+-]+", command):
        return command
    return ""


def is_plugin_install(path):
    """True when a path is the plugin checkout or Cursor's plugin cache, not the app repo."""
    parts = path.parts
    if ".cursor-plugin" in parts:
        return True
    for index, part in enumerate(parts[:-1]):
        if part == ".cursor" and parts[index + 1] == "plugins":
            return True
    return False


def workspace_roots(payload):
    roots = payload.get("workspace_roots") or []
    if isinstance(roots, str):
        roots = [roots]
    resolved = []
    for root in roots:
        try:
            candidate = Path(root).resolve()
        except OSError:
            continue
        if not is_plugin_install(candidate):
            resolved.append(candidate)
    return resolved


def containing_root(path, roots):
    matches = [root for root in roots if path == root or root in path.parents]
    if not matches:
        return None
    return max(matches, key=lambda item: len(item.parts))


def project_root(payload):
    """Resolve the open app repo. Plugin install paths are never the allowlist root."""
    roots = workspace_roots(payload)
    hints = []
    payload_cwd = payload.get("cwd")
    if payload_cwd:
        try:
            hints.append(Path(payload_cwd).resolve())
        except OSError:
            pass
    try:
        hints.append(Path.cwd().resolve())
    except OSError:
        pass

    for hint in hints:
        if is_plugin_install(hint):
            continue
        match = containing_root(hint, roots)
        if match is not None:
            return match
        if (hint / ".cursor").is_dir():
            return hint

    if len(roots) == 1:
        return roots[0]
    return None


def tool_input_text(payload):
    raw = payload.get("tool_input")
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    try:
        return json.dumps(raw)
    except TypeError:
        return str(raw)


def destructive_sql(text):
    if re.search(r"(?i)\b(drop|truncate)\b", text):
        return True
    if re.search(r"(?i)\bdelete\s+from\b", text) and not re.search(r"(?i)\bwhere\b", text):
        return True
    return False


def destructive_shell(command):
    patterns = (
        r"(?:^|[;&|]\s*)rm\s+(?:-[^\s]*[rR][^\s]*[fF]|-[^\s]*[fF][^\s]*[rR]|--recursive\b[^\n]*-f|--force\b[^\n]*-r)",
        r"\bgit\s+push\b[^\n]*--force\b",
        r"\bgit\s+push\b[^\n]*(?:^|\s)-f(?:\s|$)",
        r"\bmkfs(?:\.[a-z0-9]+)?\b",
    )
    return any(re.search(pattern, command) for pattern in patterns)


def shell_gate(payload):
    command = str(payload.get("command") or "")
    if destructive_shell(command):
        return ask(
            "Destructive shell command. Approve only if you intend this exact action.",
            "Stop until the human approves this shell command. Do not weaken it or rerun it another way. State what will change, what may be lost, and whether it is reversible.",
        )
    return allow()


def mcp_gate(payload):
    root = project_root(payload)
    if root is None:
        return deny(
            "MCP blocked: the project root for the allowlist was ambiguous.",
            "Stop. Do not call any MCP or plugin, and do not substitute a shell command or CLI.",
        )

    allowlist = root / ".cursor" / "mcp-allowlist.yaml"
    if not allowlist.is_file():
        return deny(
            "MCP blocked: this project has no .cursor/mcp-allowlist.yaml.",
            "Stop. Do not call any MCP or plugin, and do not substitute curl, a CLI, or the shell. Open the mcp-security-and-compliance skill. List server names only, with no URLs or secrets, and ask the human to approve the full allowlist before writing .cursor/mcp-allowlist.yaml in the open project. Each name must be the exact mcp_server_name.",
        )
    try:
        approved = approved_servers(allowlist.read_text(encoding="utf-8"))
    except OSError:
        return deny(
            "MCP blocked: the project allowlist could not be read.",
            "Stop. Do not call MCP. Ask the human to fix .cursor/mcp-allowlist.yaml.",
        )

    server = server_name(payload)
    if not server:
        return deny(
            "MCP blocked: the MCP server name was missing.",
            "Stop. Do not call MCP. The hook did not receive a server name. Ask the human before retrying.",
        )
    if server not in approved:
        return deny(
            "MCP blocked: %s is not approved in this project's allowlist." % server,
            "Stop. Do not call %s and do not substitute a shell command or CLI. It is missing, pending, or denied in .cursor/mcp-allowlist.yaml. Ask the human, and update that file only after they confirm. The name must match mcp_server_name exactly."
            % server,
        )
    if destructive_sql(tool_input_text(payload)):
        return ask(
            "This MCP call looks like DROP, TRUNCATE, or DELETE without WHERE. Approve only if you intend it.",
            "The server is approved. This call is still destructive. Wait for the human to approve it. Do not rewrite it to avoid this check.",
        )
    return allow(
        "Allowlist approved this server only. Open the mcp-security-and-compliance skill before any write, delete, production change, credential change, or external send. Do not print secrets."
    )


def tool_input_object(payload):
    raw = payload.get("tool_input")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def claude_pre_tool(payload):
    tool = str(payload.get("tool_name") or "")
    tool_input = tool_input_object(payload)
    if tool == "Bash":
        adapted = dict(payload)
        adapted["command"] = str(tool_input.get("command") or "")
        return shell_gate(adapted)
    if tool.startswith("mcp__"):
        server, separator, inner = tool[5:].partition("__")
        if not separator or not server:
            return deny(
                "MCP blocked: the Claude MCP tool name did not include a server.",
                "Stop. Do not call MCP. Ask the human before retrying.",
            )
        adapted = dict(payload)
        adapted["mcp_server_name"] = server
        adapted["tool_name"] = inner
        if "tool_input" not in adapted:
            adapted["tool_input"] = tool_input
        return mcp_gate(adapted)
    return allow()


def main():
    global CURRENT_EVENT
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return deny(
            "Blocked: the security hook received invalid input.",
            "Stop. Do not call any MCP or plugin.",
        )
    if not isinstance(payload, dict):
        return deny(
            "Blocked: the security hook received invalid input.",
            "Stop. Do not call any MCP or plugin.",
        )

    event = str(payload.get("hook_event_name") or "")
    CURRENT_EVENT = event
    if event == "SessionStart":
        emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": PREFLIGHT,
                }
            }
        )
        return 0
    if event == "PreToolUse":
        return claude_pre_tool(payload)
    if event == "beforeShellExecution":
        return shell_gate(payload)
    if event == "beforeMCPExecution" or payload.get("mcp_server_name"):
        return mcp_gate(payload)
    if "command" in payload:
        return shell_gate(payload)
    return deny(
        "Blocked: the security hook could not tell which action this was.",
        "Stop. Do not call any MCP or plugin.",
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        deny(
            "Blocked: the security hook failed.",
            "Stop. Do not call any MCP or plugin.",
        )
        sys.exit(0)
