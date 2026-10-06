# Changelog

## 1.0.0

Initial release of the MCP Security and Compliance plugin for Cursor and Claude Code.

- Always-on Cursor rule that stops an agent before an unapproved MCP or plugin call.
- Shared skill with the security, privacy, and approval policy.
- Cursor hook that denies an MCP call when the open project's allowlist is missing or the server is not approved, and asks before destructive SQL or destructive shell commands.
- Claude Code hook that injects the same preflight at session start and checks the same allowlist before MCP and Bash tools.
- Per-project allowlist template. The approved server list stays in the app repo at `.cursor/mcp-allowlist.yaml`.
