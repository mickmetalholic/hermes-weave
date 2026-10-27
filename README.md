# Hermes Weave

**Different machines. Shared intelligence.**

Hermes Weave is a Git-backed, multi-host knowledge exchange for independently running [Hermes Agent](https://github.com/NousResearch/hermes-agent) installations. Each host publishes to **its own directory** in a **separate private data repository**. Peers can review changes and deliberately import skills without losing local skills or copying another computer's runtime database.

> **Status:** v0.1 experimental MVP. Supports publishing safe text-based skills, optional memory snapshots, optional curated config snapshots, and manual skill imports. It **does not** semantically merge memory/config or automatically install peer skills. Review imported content before use.

## Architecture

```text
Public/private SOURCE repo:  hermes-weave/         (the Python application)
Separate PRIVATE DATA repo:  (chosen by user during weave init)/
  hosts/
    macbook/
      skills/<skill>/SKILL.md
      memory/MEMORY.md              # opt-in
      memory/USER.md                # opt-in
      config/shared.yaml            # opt-in curated file, not Hermes config.yaml
      manifest.json
    desktop/
      skills/<skill>/SKILL.md
      manifest.json
```

One Git remote, one clone per device; only `hosts/<this-host>/` is written by that node. The remote is an ordinary Git repository (GitHub private repo, Gitea, or SSH bare Git). **Do not use the source-code repository as the data repository.**

## One-script installation (macOS / Linux / WSL2)

No source checkout needed. **Use a separately reviewed local installer**; it downloads a temporary GitHub source archive, installs the CLI in an isolated Python virtual environment, registers the bundled Hermes Skill, and then offers \`weave init\`. The source archive is removed after installation. It does **not** choose or create your private data repository without asking.

The source repository is currently **private**, so authenticate \`gh\` with access to the source repo first:

\`\`\`bash
gh auth login
gh auth status

# Download the installer from the current testing branch (do not pipe to bash).
gh api -H 'Accept: application/vnd.github.raw+json' \
  'repos/mickmetalholic/hermes-weave/contents/install.sh?ref=feat%2Fhost-namespaced-sync-mvp' \
  > hermes-weave-install.sh

# Read the downloaded script before running it.
less hermes-weave-install.sh
bash hermes-weave-install.sh --ref feat/host-namespaced-sync-mvp
\`\`\`

When this PR is merged, omit \`--ref\` and fetch \`install.sh\` from \`main\`. Requirements: Python 3.10+, Git, an authenticated GitHub CLI (\`gh\`, while source is private), and an existing Hermes installation at \`~/.hermes\`. Never run a downloaded script without inspecting it. Installation does **not** need \`git clone\` or a persistent \`source/\` directory.

If Hermes itself is guiding setup and cannot answer terminal prompts, use \`bash hermes-weave-install.sh --ref feat/host-namespaced-sync-mvp --no-init\` and then let it ask you for approved \`weave init\` parameters. The install script doesn't silently overwrite another \`weave\` executable or an existing different Hermes Skill. For a planned Skill upgrade, inspect the changes first and explicitly run \`weave skill install --replace\` to back up and replace it.

To let Hermes guide the process, paste [docs/ai-setup.md](docs/ai-setup.md) into a local session.

## Getting started

Run \`weave init\` in a terminal (the installer can offer it automatically). It asks for a **unique stable host ID** and for your choice of **an existing private Git data repo or a new private GitHub repo**. Nothing about the data repository is hardcoded. All computers must use the **same** private data repository and a **different** host ID.

\`\`\`bash
weave init
weave sync
weave review --json

# After approving and reviewing a Skill from another host:
weave apply macbook code-review
# Resolve a conflicting name with --as; replace requires opt-in backup.
weave apply macbook code-review --as code-review-macbook
\`\`\`

For a non-interactive agent that has already obtained your approval, use \`weave init --host HOST --remote OWNER/PRIVATE-REPO\` or \`weave init --host HOST --create-repo OWNER/PRIVATE-REPO\`. Data stays in \`~/.hermes-weave/data\`. Memory publication remains **off** until explicitly enabled.

## Filesystem layout

```text
~/.hermes-weave/
├── venv/            # isolated Python environment
├── data/            # private Git DATA clone (created by init)
├── config.json      # local node config
├── state.json       # import/provenance ledger
├── sync.lock        # local synchronization lock
└── logs/            # scheduled-task logs
```

Hermes keeps its own Skills under `~/.hermes/skills/` including the installed `hermes-weave` operator Skill. The optional `weave` executable symlink is at `~/.local/bin/weave`. Paths can be customized using `HERMES_WEAVE_HOME` for the CLI data location and installer, or via CLI init flags.

## Commands

| Command | Effect |
| --- | --- |
| `weave doctor --json` | Read-only local health and configuration check |
| `weave skill install [--replace]` | Install bundled Hermes operator Skill; refuse silent overwrite |
| `weave repo inspect OWNER/REPO` | Verify a GitHub data repository is private (requires `gh`) |
| `weave repo create OWNER/REPO` | Explicitly create a private GitHub data repository (requires `gh` and authorization) |
| `weave init` | Interactive host registration + private repo connect/create wizard; non-interactive flags available |
| `weave pull` | Fetch remote data only; does **not** change Hermes |
| `weave publish` | Fetch then publish current host snapshot; includes safeguards |
| `weave sync` | Pull, publish, summarize peer changes; **no auto-import** |
| `weave review [--json]` | List new/updated/conflicting peer skills plus memory/config snapshots |
| `weave apply HOST SKILL [--as NAME] [--replace]` | Explicit skill import; replaces only with opt-in backup |
| `weave promote SKILL` | Deliberately fork an imported skill for republishing |

For memory snapshot publication, opt in **at initialization** with `--share-memory`. This publishes both `~/.hermes/memories/MEMORY.md` and `USER.md` to the private data repo; treat them as sensitive personal data, including all historical Git commits. **No peer memory is ever written into another host's Hermes automatically.**

For a deliberately curated **non-secret** config file, pass `--shared-config ~/weave-share.yaml` to `weave init`. This publishes only that file as `config/shared.yaml`, **not** the whole Hermes `config.yaml`, `.env`, `auth.json`, connection tokens, or credentials. It is never applied automatically. For example, a manually reviewed YAML file containing a list of recommended MCP server names is reasonable; credentials are not.

## Scheduling

Each host runs the same CLI on its own schedule. In system crontab on Linux:

```cron
*/30 * * * * /full/path/to/weave sync >> "$HOME/.hermes-weave/logs/cron.log" 2>&1
```

`~/.hermes-weave/logs/` is created by the installer; use the **absolute path** to `weave` (`command -v weave`), and verify Git SSH authentication works non-interactively. On macOS prefer `launchd` or Hermes's no-agent cron script, depending on your local setup. Avoid scheduling overlapping syncs: Weave holds an exclusive local lock.

## Trust and safety

- This is **knowledge exchange, not complete profile replication**. `.env`, OAuth tokens, `auth.json`, state databases, running sessions, and local machine paths are **not** synced.
- Publishing text-based skills rejects symlinks, secret-like content, known credential files, binary content and large files. These are *best-effort guards*, **not** guaranteed secret detection. Inspect what you publish, including prior Git history.
- Imported skills can contain instructions or scripts and must be treated as **untrusted code/content**, even if received from your own other machines. Import is never automatic. Do not execute copied scripts without checking them.
- Never connect two active installs with the same `--host` ID: each host namespace has exactly one writer. Git push retries handle separate host directories, not duplicate-writer conflicts.
- Peers must be mutually trusted: a shared Git repository does **not** enforce per-directory permissions or make untrusted repository content safe. Git host identities are advisory, not cryptographically authenticated.
- If a Git operation fails or reports conflicts, Weave does **not** use force-push or delete the other host's data. Inspect the data worktree and `git status` before retrying.
- The data repo's entire history contains any snapshots that were pushed, even after you remove files in a later commit.

Read [docs/protocol.md](docs/protocol.md) for repository layout and future roadmap.

## Development

```bash
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
```

## Roadmap

- v0.1: Safe multi-host snapshot publishing, explicit skill import, provenance ledger, and regression tests.
- v0.2: Agent-generated proposals for memory consolidation, source-diff review, conflict resolution queue (approval required).
- v0.3: Structured allowlisted configuration/MCP diffs, dry-run previews, richer secret scanning, and schedule management.

MIT License.