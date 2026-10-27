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

## AI-first installation (recommended)

Want Hermes to install and operate Weave for you? Copy the prompt in [docs/ai-setup.md](docs/ai-setup.md) into a **trusted local Hermes session**. With your approval, Hermes can check prerequisites, clone this source checkout, review and run `scripts/bootstrap.sh`, install the bundled `hermes-weave` Skill, create/inspect a second private GitHub data repository with the `gh` CLI, register this machine with `weave init`, and run the first sync. No need to manually paste several shell commands or let an LLM write its own Git synchronization script.

The bootstrap script uses `~/.hermes-weave/source` for the source checkout and `~/.hermes-weave/venv` for an **isolated virtualenv**, puts the CLI at `~/.local/bin/weave` (when that path is free), and installs the bundled Skill at `~/.hermes/skills/hermes-weave/SKILL.md`. It will not overwrite an existing different Skill without explicit `weave skill install --replace`. **Start a new Hermes session after installation** to load it.

When using the v0.1 PR instead of merged `main`, clone with `--branch feat/host-namespaced-sync-mvp` (shown in the AI setup guide). Inspect scripts before execution. Never run remote `curl | bash` installers.

## Getting started (macOS / Linux / WSL2)

1. Plan for a **second, private Git repository**, separate from the Weave source. `weave init` can prompt you to connect an existing Git repo or create a new PRIVATE GitHub repo using an authenticated `gh` CLI. There is no built-in owner or data repository name. **GitHub remotes require `gh` to verify privacy**, even if the repository already exists; other Git servers require manual privacy verification. Each computer needs Git read/write access; never use a public repository for personal data.
2. On each computer, install Python >=3.10, Git, and Hermes, then install Weave:

   ```bash
   git clone https://github.com/mickmetalholic/hermes-weave.git ~/.hermes-weave/source
   cd ~/.hermes-weave/source
   # Inspect scripts/bootstrap.sh, then run it with approval:
   bash scripts/bootstrap.sh
   ```

3. On computer A, run the **interactive wizard** in a terminal:

   ```bash
   weave init       # asks for unique host ID and private data repo (existing or create)
   weave sync
   weave review
   ```

   On computer B, run `weave init` again with a **different host ID** and select the SAME private data repository. For a non-interactive Agent that has obtained your approval, use `weave init --host HOST --remote URL` (existing remote) or `weave init --host HOST --create-repo OWNER/REPO` (create new private GitHub repo).

4. After reading a peer's `SKILL.md`, explicitly import a new skill:

   ```bash
   weave apply macbook code-review
   # If the name is already used locally:
   weave apply macbook code-review --as code-review-macbook
   # For a later update, back up and replace explicitly:
   weave apply macbook code-review --replace
   ```

Imported skills are tracked in a local provenance ledger and **never republished as new originals**. If you intentionally want to develop and publish an imported skill as your own, run `weave promote code-review` first.

## Filesystem layout

```text
~/.hermes-weave/
├── source/          # CLI source checkout
├── venv/            # isolated Python environment
├── data/            # private Git DATA clone (created by init)
├── config.json      # local node config
├── state.json       # import/provenance ledger
├── sync.lock        # local synchronization lock
└── logs/            # scheduled-task logs
```

Hermes keeps its own Skills under `~/.hermes/skills/` including the installed `hermes-weave` operator Skill. The optional `weave` executable symlink is at `~/.local/bin/weave`. Paths can be customized using `HERMES_WEAVE_HOME` for the CLI data location and bootstrap installation, or via CLI init flags.

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

`~/.hermes-weave/logs/` is created by the bootstrap script; use the **absolute path** to `weave` (`command -v weave`), and verify Git SSH authentication works non-interactively. On macOS prefer `launchd` or Hermes's no-agent cron script, depending on your local setup. Avoid scheduling overlapping syncs: Weave holds an exclusive local lock.

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