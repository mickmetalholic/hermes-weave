# AI-first installation of Hermes Weave

Paste the following into a **local Hermes Agent session**. Ask the Agent to explain and get permission before installing software, creating a repository, publishing private data, or enabling automation.

## 给 Hermes 的提示词

> 帮我在当前电脑安装并配置 Hermes Weave（https://github.com/mickmetalholic/hermes-weave），用于多台 Hermes 之间共享 Skills 和知识。当前测试版本是 `feat/host-namespaced-sync-mvp`；合并到 `main` 后再改用正式版本。
>
> 1. 检查本机是否已装 Python 3.10+、Git、Hermes，以及 GitHub CLI `gh`。本项目当前为 Private，确认 `gh auth status` 可访问源码仓库。缺少软件时先告诉我，不使用 sudo 或擅自安装全局工具。
> 2. 不要手动克隆源码，也不要创建 `~/.hermes-weave/source`。使用 `gh api` 将仓库的 `install.sh` 下载为本地文件，先检查内容、向我说明它会安装什么，并获得我明确同意后运行（带 `--no-init`）： 
>
>    ```bash
>    gh api -H 'Accept: application/vnd.github.raw+json' \
>      'repos/mickmetalholic/hermes-weave/contents/install.sh?ref=feat%2Fhost-namespaced-sync-mvp' \
>      > /tmp/hermes-weave-install.sh
>    # 经我批准后才执行：
>    bash /tmp/hermes-weave-install.sh --ref feat/host-namespaced-sync-mvp --no-init
>    ```
>
> 3. 安装程序应将 CLI 放在 `~/.hermes-weave/venv`、将快捷命令放在 `~/.local/bin/weave`，并安装 `~/.hermes/skills/hermes-weave/SKILL.md`。执行 `~/.hermes-weave/venv/bin/weave doctor --json` 检查。已有不同版本的 Skill 时不要自行覆盖，先询问我是否备份替换。
> 4. 私有**数据仓库**没有固定仓库名。让我选择已有仓库或者创建新的 Private GitHub 仓库，并确认本机唯一、稳定的 host ID。交互式终端可运行 `weave init`；没有交互终端，先问我所选仓库和 host ID，然后执行 `weave init --host HOST --remote OWNER/REPO`，或者仅在我同意创建时执行 `weave init --host HOST --create-repo OWNER/REPO`。不要把源码仓库当数据仓库。
> 5. 初始化完成后运行 `weave sync`、`weave review --json`，总结其他机器新发布的 Skills 和记忆/配置快照。Memory 发布默认关闭，不要自行打开。不自动应用别的主机配置、记忆、MCP、Token，不执行来自 Git 的陌生脚本。
> 6. 先手工确认同步成功，再提出每 30 分钟运行一次 `weave sync` 的定时任务方案，展示命令并取得我的同意。发生 Git 冲突不要擅自 force push 或 hard reset。
>
> 最后报告 CLI 路径、Skill 安装状态、本机 host ID、私有数据仓库位置和本次同步结果。新安装的 Skill 可能需要重开 Hermes 会话才能被发现。

## Manual install (private source repository)

```bash
gh auth login
gh api -H 'Accept: application/vnd.github.raw+json' \
  'repos/mickmetalholic/hermes-weave/contents/install.sh?ref=feat%2Fhost-namespaced-sync-mvp' \
  > hermes-weave-install.sh
# Inspect before execution
less hermes-weave-install.sh
bash hermes-weave-install.sh --ref feat/host-namespaced-sync-mvp
```

The installer offers to run `weave init` when executed in an interactive terminal. Data is kept in a separate private repo selected by the user at initialization, not in the source repo. Re-running the installer is possible; changing an existing custom Skill requires explicit replacement.

**Security:** Git history retains previously published snapshots. Scrub source files and never publish credentials or secrets. The source archive is temporarily downloaded and installed; no persistent source checkout is created.