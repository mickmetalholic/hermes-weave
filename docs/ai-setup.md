# Let Hermes install and operate Hermes Weave (native Plugin)

The recommended route is **Hermes native plugin installation**; `install.sh` remains a legacy CLI installer. Hermes already knows how to clone, enable and update native plugins. You should not need to clone the source or install a second Python CLI.

## 给 Hermes 的提示词（直接复制）

> 请帮我把 Hermes Weave 安装成当前 Hermes 的原生插件，用于多台电脑的 Skills 与知识共享。
>
> 开源地址：https://github.com/mickmetalholic/hermes-weave
>
> 1. 检查 Hermes 版本及插件命令是否可用，确认 Git 存在。先告诉我本机状态。
> 2. 经我同意后执行 `hermes plugins install mickmetalholic/hermes-weave --enable`，然后运行 `hermes plugins doctor hermes-weave --ci` 检查插件注册。不要再运行旧的 install.sh，也不要把源码克隆到 ~/.hermes-weave/source。
> 3. 插件启用后，使用 `weave_status` 工具检查是否已初始化。如果没有，向我询问**当前机器专属的唯一 host ID**，以及准备使用哪个**独立的私有 Git 数据仓库**。不能把公开源码仓库当作数据仓库，也不能擅自创建一个固定名称的仓库。
> 4. 若我选择新建 GitHub 私有仓库，先检查 `gh auth status`，由我批准具体的 OWNER/REPO 后再调用 `weave_init`；若选择已有仓库，先验证它是 Private。API Key、Token、OAuth、SSH 私钥不得复制到 Git 仓库。
> 5. 完成初始化后，获得我的同意才运行 `weave_sync`；然后运行 `weave_review` 查看其他机器的新 Skills、记忆或配置快照。发布 Memory 默认关闭，不自动导入或执行外部 Skill。
> 6. 要安装来自其他机器的 Skill 时，先阅读其实际文件，报告用途、依赖、安全风险和冲突情况，再征得我同意后调用 `weave_apply`。覆盖本机 Skill 必须额外征得明确同意。
> 7. 如需每 30 分钟自动同步，先给出系统 Cron/Launchd 或 Hermes Cron 方案，经我批准后再配置，不要从会话 Hook 自动 Git Push。
>
> 完成后汇报本机 host ID、私有数据仓库、插件状态、首次同步结果和待审核 Skills。若插件工具没有出现，提示我重新打开 Hermes 会话。

## 手动安装

```bash
hermes plugins install mickmetalholic/hermes-weave --enable
hermes plugins doctor hermes-weave --ci
hermes weave init
hermes weave sync
hermes weave review --json
```

The bundled Skill is namespaced as `hermes-weave:hermes-weave` and can be loaded with `skill_view("hermes-weave:hermes-weave")`. The plugin uses the existing `src/hermes_weave` implementation and stores mutable data in `~/.hermes-weave/`. Installing the plugin does not create a background scheduler, silently share memory, or import any peer Skill.

**Important:** `--enable` explicitly enables the plugin code on this machine. Trust and review third-party code before installation. The source repo is public; the separate data repo must remain private. Git history retains private snapshots even after a later file deletion. Run `hermes plugins doctor` on your local Hermes to verify actual compatibility; the repository CI also runs contract tests without loading a full Hermes instance.
