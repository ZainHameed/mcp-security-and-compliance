# MCP Security and Compliance

Cursor and Claude Code plugin that gates MCP servers and plugins. Install it once in each IDE. Do not copy the rule, skill, or hook into each repo.

Author: Zain Hameed. License: MIT.

Each project still has its own allowlist, `.cursor/mcp-allowlist.yaml`, because the approved servers differ by repo. The plugin does not contain that file, and it does not ship an MCP server or secret variables.

## What the plugin provides

The plugin installs a skill, a Cursor rule, and hooks. The skill holds the policy. The rule and the hooks make that policy apply on the first prompt, before any MCP call.

### Skill

`skills/mcp-security-and-compliance/SKILL.md` is the full policy. The agent opens it when a task needs the detail: which operations are allowed, how to treat tickets, email, databases, cloud changes, secrets, and untrusted text from other systems.

The blank form beside it, `mcp-allowlist.template.yaml`, is copied into the open project only after a person confirms the server list. The skill tells the agent to stop when approval, data classification, or scope is unclear, and to ask before high-risk work. Silence is not approval.

### Rule

`rules/mcp-security-preflight.mdc` is Cursor-only. Cursor injects it into every chat in a project where this plugin is enabled. It tells the agent, before the first MCP call and before every later one:

1. Read `.cursor/mcp-allowlist.yaml` in the open project.
2. If that file is missing, or the server is not approved, stop and ask. Write the file only after the person confirms the full list.
3. If a hook denies a call, do not retry it with the shell, curl, or a CLI.
4. If the hook allows a server, that is not approval for the operation. Open the skill before a write, delete, production change, credential change, or external send.
5. Do not print secrets.

Claude Code does not load this rule file. The Claude hook repeats the same preflight at the start of a session.

### Hooks

Both IDEs call `hooks/mcp-allowlist-gate.py`. They use different config files because the hook events are different.

`hooks/cursor-hooks.json` runs before every MCP call and every shell command in Cursor.

`hooks/hooks.json` runs at the start of a Claude Code session, and before MCP tools and Bash.

The script reads the allowlist from the open project, not from the plugin folder.

- No allowlist, an unknown server, or a server that is not `approved`: the call is denied.
- `DROP`, `TRUNCATE`, or `DELETE` without `WHERE`: the person is asked first.
- `rm -rf`, `git push --force`, and `git push --force-with-lease`: the person is asked first.
- An approved server, and none of the above: the call is allowed.

An allow means the server is approved. It does not approve a destructive change, a production change, a credential change, or sending confidential data. Those still follow the skill. If the script fails, the call is blocked.

## Install in Cursor

`.cursor-plugin/marketplace.json` lists this plugin with `source: "."`, so an admin can import the Git repository as a Team Marketplace.

1. Open **Dashboard → Plugins → Team Marketplaces**.
2. Click **Add Marketplace** / **Import from Repo** and paste this repository URL.
3. Confirm Cursor lists **MCP Security and Compliance**, then save access and install mode.
4. In Cursor, open **Customize**, install the plugin, and prefer project scope when asked.
5. Start a new agent chat.

There is nothing to set under **Plugins → Configure**.

For a local check before the repo is published, copy this folder to `~/.cursor/plugins/local/mcp-security-and-compliance/` and run **Developer: Reload Window**.

## Install in Claude Code

`.claude-plugin/marketplace.json` lists this plugin with `source: "./"`.

```bash
claude plugin marketplace add /path/to/this/repo
claude plugin install mcp-security-and-compliance@mcp-security-marketplace
```

Or test a local checkout without installing:

```bash
claude --plugin-dir /path/to/this/repo
```

Claude Code checks the same `.cursor/mcp-allowlist.yaml`. In Claude, the allowlist `name` is the server key in `mcp__<server>__<tool>`.

## First use in a project

The first MCP call is denied until `.cursor/mcp-allowlist.yaml` exists in that project. The agent lists server names, asks which ones are approved, and writes the file only after an explicit yes. In Cursor, names must match `mcp_server_name`. In Claude Code, names must match the server key in `mcp__<server>__<tool>`. Commit that file. Do not copy it from another project, and do not put secrets in it.
