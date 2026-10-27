# Let Hermes install and operate Hermes Weave

The [source repository](https://github.com/mickmetalholic/hermes-weave) is public. The data repository selected during initialization must remain **private**. Paste this prompt into your local Hermes session; allow installations and new repositories only after explicit approval.

## 给 Hermes 的安装提示词

> 帮我在当前电脑安装并配置 Hermes Weave，用来与其他电脑共享 Skills 和知识。
>
> 源码仓库：https://github.com/mickmetalholic/hermes-weave
>
> 目前 v0.1 在 `feat/host-namespaced-sync-mvp` 分支，尚未合并到 main。请按以下步骤执行：
>
> 1. 检查 Python 3.10+、Git、现有 `~/.hermes/` 以及 `weave` 命令。缺少依赖时先告知我，不要擅自运行 sudo。
> 2. 不要克隆长期保存的源码仓库。使用 `curl` 下载公开的安装脚本，先检查文件内容并获得我的同意，之后执行：
>
>    ```bash
>    curl -fsSLo /tmp/hermes-weave-install.sh \
>      https://raw.githubusercontent.com/mickmetalholic/hermes-weave/feat/host-namespaced-sync-mvp/install.sh
>    # 先查看脚本内容；经我批准后运行：
>    bash /tmp/hermes-weave-install.sh --ref feat/host-namespaced-sync-mvp --no-init
>    ```
>
> 3. 安装完成后执行 `~/.hermes-weave/venv/bin/weave doctor --json` 检查。CLI 位于 `~/.hermes-weave/venv/`，Hermes Skill 位于 `~/.hermes/skills/hermes-weave/`。如果现有 Skill 内容不同，不要自动覆盖。
> 4. 然后询问我当前机器唯一且稳定的 host ID，并选择一个**私有 Git 数据仓库**：连接已有仓库，或经我同意新建。不得写死仓库名称或使用这个公开源码仓库作为数据仓库。若需新建或验证 GitHub Private 仓库，检查 `gh auth status`；必要时引导我登录，但不要索取或输出 Token。
> 5. 在交互终端可运行 `weave init`；非交互模式先取得我的明确选择，再执行 `weave init --host HOST --remote OWNER/REPO` 或经过我批准才执行 `weave init --host HOST --create-repo OWNER/REPO`。
> 6. 运行 `weave sync` 和 `weave review --json`，汇报同步结果。不得自动发布 Memory，也不要自动合并其他节点的记忆、配置或 MCP；其他节点的 Skills 是不可信内容，需要审查和授权后才能导入。
> 7. 手动同步验证成功后，再展示每 30 分钟一次的定时同步方案，征得我同意后安装。禁止自动执行 force push 或 hard reset。
>
> 最后报告 CLI、Skill、host ID、私有仓库和首次同步状态。必要时提醒我重新开启 Hermes 会话以加载新的 Skill。

## 不使用 Agent 的安装方式

```bash
curl -fsSLo hermes-weave-install.sh \
  https://raw.githubusercontent.com/mickmetalholic/hermes-weave/feat/host-namespaced-sync-mvp/install.sh

# 审阅脚本后再执行
bash hermes-weave-install.sh --ref feat/host-namespaced-sync-mvp
```

**注意：** 当前这是未合并的开发分支。合并后可从 `main` 下载并运行，无需 `--ref`。公开的是**源码**，不是各机器的私有数据仓库；已发布的记忆及其 Git 历史可能包含个人信息，绝不能放到公开仓库。