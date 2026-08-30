# TVBoxOS-Mobile Fork Android 14 — 事实记录

> **文档角色**：事实与证据的唯一记录（基线快照 + 追加式执行记录）。维护状态与决策见《Maintenance-Update》，对 GPT 评估的回应见《Assessment-Response》。
> 追加规则：后续实施结果只追加，不删改历史内容。
> 所属目录：`TVBoxOS-Mobile Fork`（Drive）

## 1. 任务与目标

对 fork `slashinchi/TVBoxOS-Mobile` 执行 Phase A（Android 14 / targetSdk 34 最小兼容修复 + 同源空指针防护），
并恢复 fork GitHub Actions CI，供网页版复核。

- 方案文档：《TVBoxOS-Mobile Fork 维护与 Android 14 修复方案（执行最终版）》（同目录 Google Docs）
- 完整实施计划：`Oneplus/docs/plans/2026-08-15--tvboxos-mobile-fork-android14-phase-a.md`（本地路径，执行机可读）

## 2. 实施前基线（2026-08-15 核验）

| 项目 | 值 |
|---|---|
| fork | `slashinchi/TVBoxOS-Mobile`（AGPL-3.0） |
| 上游 | `kukuqi666/TVBoxOS-Mobile` |
| 默认分支 | `main`（仅此一个分支） |
| main / origin/main / upstream/main | `6aabea8`（= `6aabea8965a45df9a126d0436404ae8afccfe96f`，2026-07-29） |
| main 与上游关系 | 完全一致，可快进同步（main 为纯镜像，无本地提交） |
| 仓库权限 | 认证账号 `slashinchi` 为 fork ADMIN；main 无分支保护、无 ruleset |
| fork Actions | workflow 文件 `.github/workflows/build.yml` 存在但 **GitHub 未索引**（fork 安全策略默认禁用，`total_count=0`，从未运行） |
| 本机编译环境 | macOS：`openjdk@17`（Homebrew）已装；**无 Android SDK**，本轮不安装、不以本地 `assembleDebug` 为门禁 |

## 3. 已核实的代码缺口（实施前）

### Phase A 指定修复（方案文档 4 文件）
- `app/src/main/java/com/github/tvbox/osc/ui/activity/DetailActivity.java`
  - 无 `androidx.core` import（`androidx.core:core-ktx:1.13.1` 依赖已存在）
  - Home 键 Receiver：旧式 `registerReceiver`（L293），未用 `RECEIVER_NOT_EXPORTED`
  - `openBackgroundPlay`：缺 `playFragment != null`（L288-289）
  - PIP/后台播放 Receiver：旧式注册（L945），无防重前置；注销路径已置空字段（L947-950）
  - PIP PendingIntent：`getBroadcast(..., 0)` 无 `setPackage`、无 `FLAG_IMMUTABLE`（L907-920）
- `app/src/main/java/com/github/tvbox/osc/service/PlayService.java`
  - `getPendingIntent`：有 `setPackage`，缺 `FLAG_IMMUTABLE`（L116-117）
- `app/src/main/java/com/github/catvod/crawler/JarLoader.java`
  - 加载与下载均无只读 DCL 策略（L49 加载 / L98-107 下载）
- `app/src/main/java/com/github/catvod/crawler/JsLoader.java`
  - 同上（L46 加载 / L86 下载）

### 同源残余空指针（DetailActivity，showPreview=false 可达）
按修复归属分两批：
- 由 `336cbe1`（Android 14 指定修复）一并处理：HomeKey 回调 `openBackgroundPlay` 判空(L288)、注销路径 `isPlaying()` 判空(L938)
- 由 `20307f4`（同源空指针提交）处理，共 8 处：`jumpToPlay`(L419)、`toggleFullPreview`→`changedLandscape`(L791)、`use1DMDownload`→`getFinalUrl`(L814)、`enterPip` getPlayer 链(L862-899)、Receiver `getController()`(L918)、`playServerSwitch`→`PlayService.start`(L956)、onBackPressed `hideAllDialogSuccess()`(L752)、截图回调(L1010)

### 明确不修改（方案原文）
- `AndroidManifest.xml`（前台媒体播放服务声明已满足）
- `LocalPlayActivity.java` / `PlayerTitleView.java`（`ACTION_BATTERY_CHANGED` 例外）
- Phase B 全部：签名、版本号、`AboutDialog` 更新源、Release 写回、`update.json`

## 4. 执行方式

- 分支策略：`main` 保持上游镜像；所有自维护提交只进新建 `patched` 分支
- 提交拆分：CI 引导（build.yml push 分支）→ Phase A 指定修复 → 同源空指针
- 每次提交后依赖 GitHub Actions `assembleDebug` 作为编译验证（本机不编译）
- 真机冒烟（OnePlus Android 14）不在本轮完成，见 §6

## 5. 执行记录（追加）

### 5.1 执行结果（2026-08-16 CST）

| 项目 | 值 |
|---|---|
| `patched` 分支 | 已创建并推送（基于 `main` = `6aabea8`） |
| 提交 1 | `485dcb5` `ci: run debug builds on patched`（build.yml push 分支 → `[main, patched]`） |
| 提交 2 | `336cbe1` `fix: harden Android 14 receivers and dynamic loaders`（4 文件，44+/7-） |
| 提交 3 | `20307f4` `fix: guard remaining DetailActivity playFragment NPEs`（DetailActivity，10+/5-） |
| CI run 1 | `31894673818` → **success**（assembleDebug，首次触发） |
| CI run 2 | `31895070560` → **success** |
| CI run 3 | `31895308760` → **success** |
| APK artifact | `TVBox-Mobile`（26,029,024 字节，debug APK，retention 14 天） |
| fork Actions | 已启用（用户点击 "I understand my workflows, go ahead and enable them"），`build.yml` `state=active` |
| main 镜像 | `origin/main` = `upstream/main` = `6aabea8`，未被污染 |

### 5.2 实际改动清单

- `DetailActivity.java`：
  - import `androidx.core.content.ContextCompat`
  - Home 键 Receiver → `ContextCompat.registerReceiver(..., RECEIVER_NOT_EXPORTED)`
  - `openBackgroundPlay` 增加 `playFragment != null` 前置判空
  - PIP PendingIntent → `setPackage(getPackageName())` + `FLAG_UPDATE_CURRENT | FLAG_IMMUTABLE`
  - RemoteAction Receiver → ContextCompat 注册 + 防重注册（`isRegister=true` 分支开头判空）+ 注销判空
  - 同源空指针：`jumpToPlay`/`onBackPressed`/`toggleFullPreview`/`use1DMDownload`/`enterPip`/Receiver `onReceive`/`playServerSwitch`/截图回调 8 处最小判空
- `PlayService.java`：`getPendingIntent` 增加 `FLAG_IMMUTABLE`
- `JarLoader.java` / `JsLoader.java`：Android 14+ 加载前 `setReadOnly()`（失败 return false）；下载时先删旧只读缓存（失败终止）→ 打开流后立刻 `setReadOnly()`（失败终止）→ 写完再加载

### 5.3 明确未做（Phase B，留待下一轮）

- 自有签名（keystore Secrets）、版本号规则（`2.1.26.1/23601`）、`AboutDialog` 更新源指向 fork、`assembleRelease`、Release 写回 `patched`、`update.json`
- Android SDK 本地安装 / 本地出包
- 真机冒烟（见 §6，未执行）

### 5.4 Drive 上传记录

- 实施前快照上传：文件 ID `1iCCsAJMExqzHr9omR1rP7Wc8Jmpha22u`（parent `1Spyk3STrJMxfX1YofVlyYMwHPjgYoR9s`），回读正文一致（4357 字节）
- 实施后更新（已确认）：本文件已两次覆盖更新——首次含 §5.1-§5.4 执行记录（6686 字节），本轮含 §5.5 残余修复（8048 字节），均回读验证一致

### 5.5 残余风险修复（2026-08-16 追加）

GPT 评估（Drive 文件 `1aqSOc26DbeHHZ71OaMiXnWouTz-sH7Zb`）提出的 P0/P1 处理结果：

| 条目 | 分类 | 处理 |
|---|---|---|
| `showPreview=false` 静默 no-op | P0 | **已修复**：`jumpToPlay()` 懒创建 `PlayFragment` + `executePendingTransactions()` 同步初始化后 `setData`，恢复"点集数即播"原设计语义；`showPreview` 仍从 Hawk 读（默认 true），不写死 |
| Receiver `getAction()` 空值 NPE | P1 | **已修复**：两处改为常量前置 `equals`（RemoteAction `IntentKey.BROADCAST_ACTION.equals(...)`、Home `Intent.ACTION_CLOSE_SYSTEM_DIALOGS.equals(...)`） |
| Actions debug APK 不能当长期基线 | P0 | 未做（属 Phase B1：签名/版本/signed RC，下一轮） |
| Release tag 必须来自 patched / Secrets fail-fast / 密钥灾备 / 制品身份验证 / Phase B2 / 数据迁移 / 真机清单 | P1 | 未做（下一轮/真机阶段执行） |

- 提交：`28bd5d0` `fix: restore playback when showPreview is disabled`（含 receiver 常量前置）
- CI：run `31897227678` → **success**
- 上下文确认：仓库无独立 PlayActivity；upstream 原设计即 `!showPreview` 时走 `jumpToPlay`（无条件 `setData`，会 NPE）；`mController` 在 fragment `onViewCreated→init()` 创建，故懒创建需同步事务后调用 `setData`

## 2026-08-16 01:50 — Milestone 0+1：AGENTS.md 契约 + no-preview 全屏闭环

- Before: `patched=28bd5d0`，`main=6aabea8`（upstream mirror）；工作区干净；仓库根无 AGENTS.md
- Changes:
  - `147736f` `docs: add patched AGENTS.md handoff contract`（按 Handoff Protocol §5 的 9 条稳定契约，只含长期规则）
  - `acfc354` `fix: fullscreen on-demand play when preview is disabled`（DetailActivity）：
    1. 懒创建改为 `findFragmentById(R.id.previewPlayer)` 先复用，防 Activity 重建后重复 add
    2. `setData()` 后 `!showPreview && !fullWindows` 时显示容器并 `toggleFullPreview()` 直接进全屏
    3. `toggleFullPreview()` 退出全屏（`fullWindows` 变 false）后 `!showPreview` 时隐藏 `previewPlayer`，恢复无预览语义
    4. `enterPip()` 在 no-preview 时先显示容器
- Verification: CI run `31898954538` → `assembleDebug` **success**
- Artifact: `TVBox-Mobile` debug APK（retention 14 天）
- Device verification: **not run**
- Remaining unknowns: 真机 no-preview 行为、方向切换、PIP 组合、duplicate fragment 实机确认
- 环境发现：本地 clone 的 `remote.origin.fetch` refspec 仅含 main（clone 时仓库只有 main）；已改为 `+refs/heads/*:refs/remotes/origin/*` 并补建 `origin/patched` ref（纯本地配置，无仓库内容变更）

## 2026-08-16 02:20 — Milestone 1b：no-preview 隐藏音频 + Fragment 恢复 reconcile

- Before: `patched=acfc354`，`main=6aabea8`；工作区干净
- Changes（提交 2 个，仅 patched，均 DetailActivity.java）：
  - `38c83ab` `fix: reconcile no-preview player lifecycle`：
    1. 新增 `ensurePlayFragment()` helper（成员 → `findFragmentById(R.id.previewPlayer)` 复用 → 不存在才 `new+add` + `executePendingTransactions`）
    2. `initView()`：`showPreview=true` 复用 restored fragment 并 show；`showPreview=false` 隐藏 restored fragment（fragment `hide()`，BaseLazyFragment 不派发 init）、容器 GONE
    3. `jumpToPlay()`：hidden fragment 先 show + pending transactions 再 `setData`
    4. no-preview 退出全屏：`isPlaying()` 时 `getPlayer().pause()` 后隐藏容器
  - `898340a` `fix: ignore delayed PIP callbacks after exit`：PIP 300ms 横竖屏/400ms 自动播放回调增加 `isInPictureInPictureMode()` 守卫
- Verification: CI run `31900147924` → `assembleDebug` **success**
- Artifact: `TVBox-Mobile` debug APK（retention 14 天）
- Device verification: **not run**
- Remaining unknowns: 真机行为（两态 preview、旋转、PIP 组合）、doikki `getPlayer()` 创建时序、VodController 内部实现
- ChatGPT static review 提出的 P0（隐藏音频）与 P1（initView 未 reconcile）均在本批次闭环

## 2026-08-16 02:50 — Phase B1a：版本 + signed-RC workflow 脚手架

- Before: `patched=898340a`，`main=6aabea8`；工作区干净；GitHub Signing Secrets 为空；DECISIONS D-002/D-003/D-004 Accepted 无 supersede
- Changes（提交 3 个，仅 patched）：
  - `9393ab4` `chore: set first fork RC version and harden signing fail-fast`：`versionName '2.1.26.1'` / `versionCode 23601`（D-003）；删除 alias/password 明文默认回退；keystore 存在但任一 env 缺失时 `GradleException` fail-fast
  - `4ac166a` `ci: add patched signed RC validation`：`build.yml` 新增 `build-signed-rc` job（仅 workflow_dispatch；首步验证 `refs/heads/patched` 否则 exit 1；5 项配置 fail-fast（4 secrets + `TVBOX_SIGNER_SHA256` 变量）；`assembleRelease`；`apksigner verify --print-certs` 比对 signer SHA-256 + `aapt2 dump badging` 比对 package/versionCode/versionName；仅 success 上传 RC APK 与 identity report；`always()` 清理 keystore；不建 tag/Release/update.json）；`build-apk` 排除 workflow_dispatch
  - `7448f8d` `ci: guard RC failure reporter when log is absent`：`Report Gradle failure` 步骤 tail/grep 加 `|| true` 防护
- Verification:
  - push CI run `31901234667`（4ac166a）→ **success**；run `31901595264`（7448f8d）→ **success**
  - dispatch fail-fast 验证 run `31901495795`：`build-signed-rc` → **failure**（步骤 `Verify signing configuration fail-fast`，错误仅列出缺失变量名 `TVBOX_KEYSTORE_BASE64 TVBOX_KEY_ALIAS TVBOX_KEY_PASSWORD TVBOX_STORE_PASSWORD TVBOX_SIGNER_SHA256`，无值泄露）；`build-apk`/`publish-github-release` → skipped；artifacts = **0**
- Artifact: 无（预期，secrets 未配置）
- Device verification: **not run**
- Remaining unknowns: 正式 keystore 生成/导入与 Secrets 配置（B1b 人工门）；`TVBOX_SIGNER_SHA256` fingerprint 值；真实 signed RC 构建与 apksigner 校验结果；DECISIONS 读取曾失败后已重试成功
- 约束确认（官方文档）：`workflow_dispatch` 文件必须存在于默认分支；`main` 保持镜像，故 RC 复用 `build.yml` 并以 `gh workflow run build.yml --ref patched` 触发

## 2026-08-16 03:20 — B1a.1：fingerprint 规范化 + identity report 增强 + 无材料 fail-fast 复验

- Before: `patched=9141daa` 之前为 `7448f8d`；`main=6aabea8`；Secrets/Variables 仍为空；工作区干净
- Changes（提交 1 个，仅 patched）：
  - `9141daa` `ci: normalize signer fingerprint and enrich RC identity report`（build.yml）：
    1. `Verify APK identity`：expected/actual SHA-256 统一 normalize（小写、去冒号/空白），并要求 `^[0-9a-f]{64}$`，杜绝 keytool 大写冒号格式与 apksigner 小写无冒号格式的误判
    2. `rc-identity.txt` 扩为 6 行：`signer_sha256` / `apk_sha256`（sha256sum）/ `package` / `versionCode` / `versionName` / `commit`（GITHUB_SHA），无 secret
    3. `Restore signing key`：解码后 `[ -s TVBoxOSC.jks ]` 校验非空
- Verification:
  - push CI run `31903222230`（9141daa）→ **success**
  - 无材料 dispatch run `31903329115`：`build-signed-rc` → **failure，唯一业务失败步骤 = `Verify signing configuration fail-fast`**（错误仅列缺失变量名，无值泄露；reporter 无二次失败）；`build-apk`/`publish-github-release` → skipped；artifacts = **0**
- Artifact: 无（预期）
- Device verification: **not run**
- Remaining unknowns: 真实 signed RC（B1b，待用户 keystore + Secrets）；灾备载体选择
- B1a 全链验收完成：版本 2.1.26.1/23601、signed-RC workflow、缺材料 fail-fast、fingerprint 规范化、identity report 完整

## 2026-08-16 03:30 — B1b 首次真实 signed RC：失败（KEY/STORE PASSWORD 为空值）

- Before: `patched=9141daa`，`main=6aabea8`；4 Secrets + `TVBOX_SIGNER_SHA256` 名称全部存在（03:02Z/03:07Z 创建）
- Action: `gh workflow run build.yml --ref patched` → run `31924206986`
- Result: `build-signed-rc` **failure**，失败步骤 = `Verify signing configuration fail-fast`
- Evidence（run 日志 env 段）：`TVBOX_KEYSTORE_BASE64: ***`、`TVBOX_KEY_ALIAS: ***`（有值）；**`TVBOX_KEY_PASSWORD: `（空）`TVBOX_STORE_PASSWORD: `（空）**；`TVBOX_SIGNER_SHA256: 11eca313...7d010`（正常）
- 结论：两个密码 Secret 名存在但值为空字符串（`gh secret list` 不显示值，无法通过 CLI 区分；GitHub UI 设置时值不允许为空，CLI stdin 空输入可写入空值）
- 根因推断：设置时密码变量未赋值或 stdin 为空文件（如 zsh `read -s "pw?..."` 未生效），待用户确认
- 处置：**等待用户重新设置 `TVBOX_KEY_PASSWORD` / `TVBOX_STORE_PASSWORD`**（值与 keystore 一致），设置后重跑 dispatch；不修改代码
- Device verification: not run；无 artifact

## 2026-08-16 03:35 — B1b 真实 signed RC 成功 ✅（Phase B1 CI 验收关闭）

- Before: 用户重设 `TVBOX_KEY_PASSWORD` / `TVBOX_STORE_PASSWORD`（zsh `read -s "pw?..."` 成功，gh 确认 Set Actions secret）→ 重新 dispatch
- Action: `gh workflow run build.yml --ref patched` → run `31924444067`
- Result: `build-signed-rc` **success**；`build-apk` / `publish-github-release` skipped
- Artifact: `TVBox-Mobile-RC-v2.1.26.1.apk`（42,430,037 字节，retention 30 天）+ `TVBox-Mobile-RC-identity`
- Identity report（全部通过，与 GitHub Variable 一致）：
  - `signer_sha256=11eca31346835da4a0a5ab295647b14070f4c07533f08358679188941ae7d010`（= `TVBOX_SIGNER_SHA256`）
  - `apk_sha256=d85c3aec43ef72492c26ca708372bd2d524cfc212c9a298f60607bffbd7407a5`（本地 `shasum -a 256` 复核一致）
  - `package=com.github.tvbox.osc`、`versionCode=23601`、`versionName=2.1.26.1`、`commit=9141daa7d46dd3ca170ac54af4b6c34721abfa33`（= patched HEAD）
- 未做：不建 tag/Release、不写 update.json/README/main；cleanup 步骤执行（keystore 不落盘）
- 残余风险（用户已接受暂缓，非阻塞）：
  - NAS 上存有裸 `TVBoxOSC.jks.bak`（非加密 DMG 副本）；独立加密灾备未落地，延期处理
  - `.envrc` 明文含密码环境变量并注入 shell 环境（direnv），建议后续移除/改用临时输入
- Device verification: **not run**（下一步真机迁移与 smoke）

## 6. 真机未验证项（待网页版复核后执行）

1. 详情页 `showPreview=true/false` 两种状态下进入不抛 SecurityException / NPE
2. Home 键 / 返回键（含全屏态）无崩溃
3. PIP：上一集 / 播放暂停 / 下一集三键正常
4. 后台播放通知栏按钮正常
5. PIP + 后台播放组合：无重复 Receiver、无 unregister 异常
6. 至少一个远程 JAR 源可加载
7. 至少一个 JSAPI / JsLoader 源可加载
8. 旧只读缓存版本变化后：删除、重建、重新加载成功

## 7. 敏感信息说明

本文档不含任何密钥、token、凭据。

## 2026-08-16 04:30 — Milestone 3：OnePlus Android 14 一次性换签迁移 + runtime smoke

- Before: `patched=9141daa`，`main=6aabea8`；设备 PHK110（Android 14）装有 upstream-signed `2.1.26/236`（signer 前缀 e7df0eca，2024-11-02 安装）
- Migration:
  1. 应用内备份：`/sdcard/tvbox_backup/2026-08-16-115344/`（sqlite 258,048 B + hawk 16,286 B）→ adb pull 到本机 tmp（非 repo，迁移后删除）
  2. 卸载 upstream → 安装 run `31924444067` 的 RC `TVBox-Mobile-v2.1.26.1.apk`（42,430,037 B，SHA-256=d85c3aec...7407a5）
  3. 设备身份：versionCode=23601 / versionName=2.1.26.1；signer 闭环（设备 base.apk SHA == 下载 APK SHA == CI identity apk_sha256）
  4. 应用内恢复备份 `2026-08-16-115344` → 再次「立即备份」得 `2026-08-16-120438` 对比
- Data baseline compare: vodRecord 70=70（全量差集 0）、vodCollect 0=0、cache 577→578（+1 可解释）、hawk 键集 21=21（密文差异为 Hawk2 加密随机性，非内容差异）
- Runtime smoke（用户手工 + adb logcat 监控，全程无 SecurityException/NPE/FATAL/duplicate fragment/ISE）：
  - showPreview=true：预览/全屏/Back ✅
  - Home/Back、方向横竖屏 ×2 ✅
  - PIP：enter/exit 正常，PictureInPictureParams hasSetActions=true，快速进出无 delayed-callback 回归 ✅
  - 通知栏：开启后台播放（BACKGROUND_PLAY_TYPE=1）+ 系统通知权限后，上一集/播放暂停/下一集正常 ✅
  - JAR 源 csp_Duopan 播放正常（JarLoader 只读加载路径）✅
  - 只读缓存：加载路径正常；缓存替换路径无 UI 触发器，静态覆盖
- Gaps（交 ChatGPT 决策）：
  1. `showPreview=false` 无 UI 入口（HawkConfig.n 孤儿配置，全库无写入点；release 非 debuggable，run-as 不可用）→ M3 验收清单该项无法 runtime 触发；静态修复已覆盖（acfc354/38c83ab）
  2. JSAPI 源未单独实测（当前源列表仅见 jar 源）
- Artifact: RC 保留 GitHub artifact（run 31924444067，retention 30 天）；迁移备份临时副本已删
- Device verification: **PASS**（上述两项 gap 除外）；残余：D-008 灾备 Deferred 仍有效

## 2026-08-16 13:35 CST — JSAPI/JsLoader runtime gate 真机验证 PASS（M3 最后一项 gap 关闭）

- 背景：HANDOFF gap #2（JSAPI 源未实测）在本轮通过真机 fixture 验证；未改任何应用代码，无 commit。
- Fixture（本机 tmp，不落仓库）：
  - 官方 Build Tools 34.0.0 d8 构建 V1/V2 两个含 classes.dex 的 jar；唯一类 `com.github.catvod.js.Method`（构造器 `Method(QuickJSContext)`、`marker()` 带 RuntimeVisible `@Function` 注解）；dexdump 确认 `VISIBILITY_RUNTIME com/whl/quickjs/wrapper/Function`、无内部类/lambda；V1 md5=80b42749...、V2 md5=84903c6c...（SHA-256 不同）
  - JS 模块 `jsapi-fixture.js`：`home()` 返回 `vod_name: jsapi.marker()`；config-v1/v2 为独立 URL（api 同 `http://127.0.0.1:18080/jsapi-fixture.js`，jar 同 URL `.../jsapi-fixture.jar;md5;<不同值>`）；adb reverse tcp:18080
- Gate A（下载+只读加载）：首次应用 config-v1 → server 收到 jar GET → logcat `自定义jsapi加载成功!` + `JSAPI-FIXTURE-V1 constructor called` + `JSAPI-FIXTURE-V1 marker() invoked`（进程 27473）→ 首页 UI 显示 `JSAPI-FIXTURE-V1`（jsapi.marker() 返回值）✅
- Gate B（只读缓存命中）：force-stop + relaunch → 仅 GET config（无 jar GET）→ 新进程 5525 从 filesDir 只读缓存 `fba8e6bb...jar`（-r--------, 1174B）DCL 加载 → UI 仍 `JSAPI-FIXTURE-V1` ✅
- Gate C（同 URL 替换）：服务端同路径 jar 替换为 V2（md5 不匹配）→ 应用 config-v2 → 13:31:13 新 jar GET（旧只读缓存 delete+重建，文件 1174B→1176B）→ 进程内静态 classs map 仍返回 V1（Activity 重启不清静态 map，符合代码语义）→ force-stop 清 map 后 relaunch → `JSAPI-FIXTURE-V2 constructor called` + `marker() invoked`（进程 7393）→ UI 显示 `JSAPI-FIXTURE-V2`，此后无二次 jar GET（V2 缓存命中）✅
- 异常排除：全程 logcat 无 SecurityException / VerifyError / ClassNotFoundException / NoClassDefFoundError / QuJS 错误（仅 Oppo 系统 SchedAssist 噪声）✅
- 清理与恢复：
  - 测试前备份 `2026-08-16-131720`（sqlite SHA-256=236bca12... / hawk SHA-256=eb8e67b1...；vodRecord=70、vodCollect=0、cache=584、hawk 21 键）
  - pm clear → 应用内恢复备份 → 再备份 `2026-08-16-133528` 对比：vodRecord 70=70、vodCollect 0=0、cache 584=584、hawk 键集 21=21 无差异 ✅
  - 版本 2.1.26.1/23601、signer 13b8eeba 未变；原订阅列表恢复（tvbox 等，无 fixture 订阅残留）；filesDir 无 fixture jar 残留；POST_NOTIFICATIONS 被 pm clear 重置后 pm grant 恢复 granted=true
- 结论：**JSAPI/JsLoader runtime gate PASS；M3 Dynamic loaders 两项（JAR + JSAPI + Android14 只读缓存删除/重建/重载）全部真机验证完毕**；M3 仅剩 showPreview=false 无 UI 入口一项（孤儿配置，静态覆盖，待 ChatGPT 决策）

## 2026-08-16 14:40 CST — JAR 加固源启动闪退诊断与修复（commit 353aee2）

- 现象：13:40+ 用户使用后 app 启动即闪退；复现（14:11-14:12，三次 SIGABRT）logcat：
  - `Fatal signal 6 (SIGABRT)`，线程 pool-6-thread-1（okhttp 线程池，启动时 HomeFragment 历史查询触发）
  - `Abort message: 'JNI DETECTED ERROR IN APPLICATION: obj == null in call to CallObjectMethod from com.github.catvod.spider.DexNative.getSpider'`
  - Java 栈：`HomeFragment$queryHistory → RoomDataManger.getAllVodRecord → ApiConfig.getCSP:740 → JarLoader.getSpider:163 → csp.jar Init.getSpider → new DouDouGuard → BaseSpiderGuard.<init> → DexNative.getSpider(Native)`
- 证据链：
  - 触发源 = 全局 spider jar（当前配置 spider 字段 canyue.jar，下载缓存为 filesDir/csp.jar）
  - csp.jar 内容：classes.dex 仅 36KB（壳）+ assets/ftyguard_v7.so（81KB）/ ftyguard_v8.so（102KB）/ ftyshinidie.guard（993KB 加密 dex）；jar 打包时间 2026-08-16 02:37 UTC（10:37 CST）= **当日更新的新版加固 jar**
  - 每源一个 `*Guard` 包装类（DouDouGuard/AllliveGuard/AppYsV2Guard 等），构造链最终进 DexNative（ftguard JNI 守卫）
  - 关键时序：13:36-13:40（恢复备份后，旧 jar 只读加载）queryHistory 正常；13:47-13:52 用户操作触发 csp.jar 重新下载（新版加固）→ 14:11 起启动必崩 → **jar 版本更新是触发变量**；fork 的 Android 14 setReadOnly 与加固初始化冲突（只读 jar 下 ftguard 守卫返回 null → JNI 崩）
- 修复 `353aee2`（仅 JarLoader.java，+28/-5）：
  - `isHardenedJar()`：zip 条目含 ftyguard / *.guard 判定（ConcurrentHashMap 缓存）
  - 加载路径：加固 jar `setWritable(true)` 恢复可写；普通 jar 保持 setReadOnly（M3 Gate B/C 行为不变）
  - 下载路径：写完文件后仅非加固 jar setReadOnly
- 验证（run `31931510414` signed RC；identity：signer 11eca313...、APK SHA-256=f445ed922657d852263b3f278098a60094d979bea598dda1593a787c28884dd9、package/version 不变、commit=353aee2）：
  - 覆盖安装（fork→fork，数据保留）→ 启动/订阅管理/首页源加载/历史页（70 条）全部正常
  - 全程 0 次 Fatal signal / JNI DETECTED
- 残余：JsLoader 同款 setReadOnly 未改（js 源 jar 若加固会同类崩；当前无实例，YAGNI）；D-008 Deferred 不变

## 2026-08-18 CST — ChatGPT review follow-up 执行（d8f010e 验证 + showPreview B 收口）

- 背景：ChatGPT review follow-up 要求：①移除 JarLoader isHardenedJar() path-only 永久缓存（同路径内容替换后重新判定）②setWritable(true) 失败 fail-safe ③不扩大 DCL ④commit+signed RC+Android14 加固/同路径替换/普通 jar 回归验证 ⑤FACTS/HANDOFF/ACTIVE-PLAN 维护 + 修正 stale Baseline HEAD ⑥showPreview=false 按 B 收口（不新增 UI）⑦暂不进 B2。
- 代码（已存在，GitHub `d8f010e`，commit 时间 2026-08-17 21:53，仅 JarLoader.java +13/-14）：
  - 删除 `hardenedCache` 字段与 `computeIfAbsent`，`isHardenedJar` 每次打开 zip 重新扫描；
  - 加载路径 `if (!jarFile.setWritable(true)) return false;`（与 setReadOnly fail-safe 对齐）；
  - `ZipFile` 打开失败 catch → `return true`（保守按加固，避免误 setReadOnly 引入闪退风险）。
- CI：run `32037092556`（head=d8f010e）success；signed RC identity：signer_sha256=11eca313...、apk_sha256=1924f0c4...、package=com.github.tvbox.osc、version=2.1.26.1/23601、commit=d8f010e（已与本机下载 APK SHA 复核一致）。
- 真机验证（PHK110 Android 14，d8f010e RC 覆盖安装，root 直改文件系统，全程 0 Fatal signal / JNI DETECTED）：
  - a 加固分支：root 将缓存 jar `ef63d06c...jar` 同路径内容替换为含 `assets/ftyguard_dummy.so` 的 fake-加固 jar（md5=5d24aacd，先 chmod 444 模拟只读）→ 启动 → 权限 `r--r--r-- → rw-r--r--`（= setWritable(true) 生效，判定加固铁证）；md5 命中缓存 → server 无新 jar GET；0 崩溃。
  - b 同路径重新判定：同一缓存路径再由加固态恢复普通 jar（md5=10828d1b，chmod 444）→ 再启动 → 权限回 `r--`（= setReadOnly，判定非加固）+ 0 崩溃 + UI 显示 `JAR-REGRESSION-V2`（普通 jar 完整加载）。同一路径内容替换后两次判定均正确（配合 d8f010e 移除缓存的代码证据闭环）。
  - c 普通 JAR 回归：普通 fixture jar 只读加载 + 内容显示正常。
- 备注：当前设备真实全局 spider jar 为 FishGuard 加固（assets/FishGuard-v7/v8.so + .md5，3.7MB，8/16 22:03），不在 isHardenedJar 检测范围（ftyguard/.guard），但 FishGuard 对只读不敏感（8/16-8/18 一直只读加载正常），无碍；如需纳入检测需单独扩展（非本次范围）。
- 设备恢复：删除测试订阅（JARFIX/config-jar1）与测试缓存（ef63d06c.jar、d09113c0 config）；切回用户 tvbox 订阅；force-stop+relaunch 0 崩溃。
- 决策：showPreview=false 按 B 收口（DECISIONS D-009）；向下兼容 smoke（API 24 / API 31 或 33 / API 34）登记为 B2 正式公开 Release 前 gate（ACTIVE-PLAN M4）。

## 2026-08-18 CST — Milestone 4 / Phase B2：sustainable release chain 实施 + RC dry-run

- ChatGPT 批准启动 B2（先实施/验证发布链，不立即正式 tag/Release）。用户新增约束：当前无其他版本设备、暂不测 API24/33；不为 emulator 改正式 APK 的 arm64-v8a ABI。
- 实施 commit：
  - `83f7c83` feat: fork release chain（仅 4 文件）：
    - build.yml tag job：`assembleDebug` → `assembleRelease`；产物 `apk/debug/*` → `apk/release/*`；新增 `Verify tag ancestry on patched`（`git merge-base --is-ancestor $GITHUB_SHA origin/patched`）；新增 `Verify release APK identity`（复用 build-signed-rc 的 apksigner/aapt2 校验：signer_sha256=TVBOX_SIGNER_SHA256、package、versionCode、versionName=2.1.26.1）；「Publish update manifest」push 目标 `main` → **`patched`**（不再污染 main）。
    - scripts/sync_release_metadata.sh：默认仓库 `kukuqi666/TVBoxOS-Mobile` → `slashinchi/TVBoxOS-Mobile`。
    - AboutDialog.java `RAW_UPDATE_JSON` → `slashinchi/TVBoxOS-Mobile/patched/update.json`。
    - 根 update.json：version=2.1.26.1、apk_url 指向 fork v2.1.26.1（与 AboutDialog 同 commit 绑定，避免只改 URL 不配内容）。
  - `e75f76e` docs: README 下载链接 label 与 URL 改指向 fork（v2.1.26.1）。
- 验证（run `32136107526`，head=83f7c83，workflow_dispatch signed RC）：
  - `build-signed-rc` success；identity：signer_sha256=11eca313...、apk_sha256=284280c1...、package=com.github.tvbox.osc、version=2.1.26.1/23601、commit=83f7c83；本机下载 APK SHA 与 identity 一致。
  - 零副作用断言：`git ls-remote --tags` = 0（无 tag）；GitHub releases API = 0；patched head=83f7c83；**main head 保持 6aabea8（upstream mirror，未被写入）**。
- 发布脚本本地验证（不提交）：`sync_release_metadata.sh --skip-version-check v2.1.26.1` 生成的 update.json 与手写根 update.json 完全一致（version=2.1.26.1、fork apk_url）；README URL 替换正确；**发现并处理**：脚本会插入「v2.1.26.1 已发布」更新记录条目（正式 release 前不得提前提交，已丢弃生成物）；README 原 label 仍显示 kukuqi666（仅改 URL 不改 label 的上游行为），已手动修 label=slashinchi。
- 决策/延期：API24/33 向下兼容 smoke 登记 Deferred（DECISIONS D-010，见 ACTIVE-PLAN M4 段）；本批不创建正式 tag/Release、不 push main；ABI 保持 arm64-v8a 未动。

## 2026-08-18 CST — Minimal release-workflow hardening（a7c6bf0）

- ChatGPT 通过 B2 主体，暂不授权正式 tag/Release；要求最小 hardening 四项。commit `a7c6bf0`（仅 .github/workflows/build.yml，+39/-5）：
  ① publish job checkout 加 `fetch-depth: 0`（保证 tag ancestry gate 在 metadata commit / rerun 场景仍有共同祖先）；
  ② release identity 不再硬编码：`versionName`/`versionCode` 从 `app/build.gradle` 动态提取（sed，versionCode 无引号正则），与 APK badging 互证；`build-signed-rc` 的 identity 一并改同一套动态互证（消除两套版本规则）；
  ③ Release signing 对齐 signed-RC：新增 5 项 fail-fast（4 secrets + TVBOX_SIGNER_SHA256）、keystore decode 后 `chmod 600` + 非空 `-s` 检查、job 末尾 `if: always()` Cleanup signing key（rm -f TVBoxOSC.jks）；
  ④ 恢复语义：Release 成功但 metadata push 失败 → 只补 metadata（rerun Publish update manifest / 手动 `sync_release_metadata.sh --skip-version-check`），禁止删除已成功 tag/Release（记入 DECISIONS D-011）。
- 验证（run `32143069314`，head=a7c6bf0，workflow_dispatch signed RC）：identity 全过——signer_sha256=11eca313...、apk_sha256=569dcc46...（本机下载 SHA 一致）、package=com.github.tvbox.osc、versionCode=23601/versionName=2.1.26.1（动态提取成功）、commit=a7c6bf0；**0 tag / 0 Release / main 保持 6aabea8**。
- 边界：本次只跑到 build-signed-rc；tag job 的 fetch-depth/ancestry/metadata 恢复路径仅在正式授权 tag/Release 时验证（静态核对 + 文档记录）。

## 2026-08-18 CST — ChatGPT 授权 v2.1.26.1 首发；评审驳回 mkdir 缺口 → 修后新 HEAD 待重新授权

- **授权**：ChatGPT 完成 Phase B2 最终评审，正式授权在 `a7c6bf0a59ba9396cbdee4825504caf7e1489b31` 创建首个 lightweight tag `v2.1.26.1` + GitHub Release。约束：tag 前若 patched HEAD 变化立即停止；Release APK SHA 不要求等于 signed-RC 的 569dcc46（重新构建，可不同，需记录新值）。
- **评审发现阻塞缺口**：publish-github-release job 的「Verify release APK identity」在 `set -euo pipefail` 下 `tee build/apk-signature.txt`，但该 job 无 build-signed-rc 那侧的 `mkdir -p build`（build.yml:156 vs 无）。若缺目录：tee 失败 → job 失败 → 发生在 Release 创建前；rerun 仍 checkout 同一 commit，缺口复现不可自愈。
- **用户决策（评估挑刺）**：先修 mkdir 再交回重新授权，不在 a7c6bf0 打 tag。
- **修复**：`65c5e32`「ci: mkdir build before release identity checks」（仅 .github/workflows/build.yml +1），publish verify 步骤 `set -euo pipefail` 后加 `mkdir -p build`。
- **signed RC 验证（run `32157525327`，head=`65c5e32`，workflow_dispatch）**：conclusion=success，build-signed-rc success；build-apk/publish-github-release skipped（按设计）。identity 全过：signer_sha256=`11eca313...`（= vars）、apk_sha256=`5352c36c1013e1a0816a418337998f6b4dcb895a2171402ce4229ab5cac99065`（新值）、package=com.github.tvbox.osc、versionCode=23601、versionName=2.1.26.1、commit=65c5e32（动态互证一致）。
- **零副作用**：0 tag / 0 Release / main 保持 `6aabea8`；live ahead=18 / behind=0（旧文档 ahead 16 过时）。
- **边界**：tag `v2.1.26.1` 未创建（按规则 HEAD 已离开 a7c6bf0，未经授权的新 HEAD 不发布）；待 ChatGPT 对 `65c5e32` 重新授权后执行 tag workflow。

## 2026-08-18 CST（晚）— v2.1.26.1 tag 已建，tag workflow 被 aliyun 502 阻断，停等重试/决策

- **重新授权**：ChatGPT 对 `65c5e32f5eaabe31eb267cd1f418511688b15547` 独立重新评审通过，正式重新授权该 commit 为 v2.1.26.1 首发目标（APK SHA 不要求等于 RC 5352c36c，record 实际值）。
- **打 tag**：HEAD 门禁通过（local==origin/live==65c5e32、0 tag、main=6aabea8、worktree clean）→ `git tag v2.1.26.1 65c5e32...` + push。远程 `refs/tags/v2.1.26.1` 精确指向 `65c5e32`（type=commit，lightweight ✓）。
- **tag workflow 失败链（run `32160785347`，event=push，head=65c5e32）**：1 原跑 + 4 次 rerun，publish-github-release job 全在 **Build release artifact** 失败。所有 gate 均 PASS（ancestry ✓ / tag-version ✓ / signing fail-fast ✓ / keystore restore ✓），之后 `./gradlew :app:assembleRelease` 依赖解析失败：
  - 全部报 `Could not GET https://maven.aliyun.com/repository/{releases,public}/... Received status code 502`（依次 gradle-settings-api:8.5.2、androidx:drawerlayout:1.1.1、android-device-provider-gradle-proto:31.5.2 等）。
  - **根因定位：GitHub runner → maven.aliyun.com 路径故障**，非仓库顺序代码缺陷：本机同一 URL 20/20 探测健康（404=正常，Gradle 应继续下一个 repo），google() 同 artifact 200；仅 runner 出口持续 502。此前所有 signed RC（含 `65c5e32` 的 `32157525327`）在同一仓库顺序下成功。
  - **副作用零**：0 Release / 无 metadata commit / `patched` 仍 `65c5e32` / `main` 仍 `6aabea8` / tag 保持在授权 SHA。
- **停点（按授权边界）**：改为 build.gradle 仓库顺序 = 新 commit → HEAD 离开 `65c5e32` → 属计划外决定，未授权不擅改 → 停止重试并交回 ChatGPT/用户决策。
- **恢复路径（未执行，供决策）**：① 首选——等 aliyun 恢复后 `gh run rerun 32160785347`（tag 已在位，零改动可重试）；② 若 aliyun 长期不可用——在 tag workflow 用 init.d 覆盖仓库优先级或调整 build.gradle 顺序，需新 commit + 重新授权后重打 tag。

## 2026-08-19 CST — CI repository-resilience batch（b187b6f）＋ signed RC PASS，待重新授权正式 Release

- **背景**：ChatGPT 复核 tag `v2.1.26.1`@`65c5e32` 与失败 run `32160785347`，判定 aliyun 502 属外部故障，但 Aliyun 位于 google()/mavenCentral() 之前使外部 502 成为 Release dependency-resolution 单点；授权实施最小 CI repository-resilience batch（不删除 Aliyun、不迁移 dependency management、不改 app 功能/version/signing/ABI、不涉 P2 deprecation）；**尚未授权任何新 HEAD 正式 Release；旧 tag 暂不删除/移动**。
- **变更**：`b187b6f`「ci: prioritize official repos over aliyun on GITHUB_ACTIONS」，仅 `build.gradle`（+38/-14）。GITHUB_ACTIONS=="true" 时官方源优先：`gradlePluginPortal → google → mavenCentral → jitpack →（allprojects 含 4thline）→ Aliyun releases/public fallback`；普通本地/大陆环境保持 Aliyun 优先。`task clean` 保留。
- **脚本作用域坑（3 次修正，force-with-lease amend 至 b187b6f）**：① 顶层 `def onGitHubActions` 在 `allprojects{}` 闭包内不可见（MissingPropertyException）；② `ext.onGitHubActions` + `rootProject.ext` 仍失败——Gradle 先求值 `buildscript{}` 块（早于其余顶层代码），buildscript 访问时属性未赋值；③ 终版在 buildscript/allprojects 两处就地 `System.getenv("GITHUB_ACTIONS")=="true"` 判断，消除作用域与求值顺序问题。教训：buildscript 块内的条件不能用顶层共享变量。
- **验证（run `32202091955`，workflow_dispatch，head=`b187b6f`）**：conclusion=success，build-signed-rc success（build-apk / publish-github-release skipped 按设计）。identity：signer_sha256=`11eca313...`、apk_sha256=`aede78440dcd82d0a4e369b91977baebcdb85ab0e25b7ea3cb5323c19401a49b`（新值）、package=com.github.tvbox.osc、versionCode=23601、versionName=2.1.26.1、commit=b187b6f（动态互证一致）。**repository-resilience 生效证据：CI 官方源优先路径跑通**（若 aliyun 仍异常而 RC 成功，即为 fallback 证据；本次 502 未出现即算官方优先优先成功）。
- **零副作用**：tag `v2.1.26.1` 仍钉 `65c5e32`（本地+远程，未删未移）、0 Release、`main`=`6aabea8`、`patched`=`b187b6f`（live ahead 19 / behind 0）、worktree clean。
- **边界/待办**：正式 tag/Release 未执行——等待 ChatGPT 复核 exact diff + signed RC 后对 `b187b6f` **单独重新授权**；授权后才删除旧 `v2.1.26.1` tag、将同名 lightweight tag 重建到 `b187b6f`、跑正式 tag workflow。正式 tag workflow 跑通后还需补验（本批未执行）：publish `mkdir -p build` / APK identity gate（tag 侧）、GitHub Release asset（APK + update.json）、Release APK 实际 SHA、metadata 仅写 patched，然后才可关闭 M4。

## 2026-08-19 CST — 正式 Release v2.1.26.1（tag@b187b6f）发布成功，Milestone 4 关闭

- **重新授权**：ChatGPT 复核 `b187b6f` exact diff（仅 build.gradle，1 commit / 1 file）+ signed RC run `32202091955`，正式重新授权 `b187b6f` 作为 v2.1.26.1 首发目标。要求执行前 patched 仍==b187b6f，否则授权失效。
- **tag 迁移（授权后）**：门禁通过（origin/patched==local==live==`b187b6f`）→ 删除远程旧 tag + 本地旧 tag（曾钉 65c5e32）→ 重建 lightweight tag 精确钉 `b187b6f` → push。远程 `refs/tags/v2.1.26.1` 指向 `b187b6f`（type=commit）。
- **正式 tag workflow（run `32205623569`，event=push，head=`b187b6f`）conclusion=success**：publish-github-release 全部 15 step PASS——
  - ancestry gate ✓（tag commit ∈ origin/patched）；tag/version gate ✓；signing fail-fast（5 项 secret/vars）✓；keystore restore ✓；assembleRelease ✓；
  - **此前未实跑的 publish「Verify release APK identity」首次实跑 PASS**（含 `mkdir -p build` 路径，build.yml:333）：signer_sha256=`11eca313...`、apk_sha256=`df1760aa82a60c78da88655cdbbf2f2caec2e60c141cef3e78e1b63f314a57ce`、package=com.github.tvbox.osc、versionCode=23601、versionName=2.1.26.1、commit=b187b6f（动态互证一致）；
  - Create update manifest ✓；Publish GitHub Release ✓；Publish update manifest ✓（幂等写入 metadata commit 到 patched）；Cleanup ✓。build-apk/build-signed-rc skipped。
- **GitHub Release v2.1.26.1**：非 draft / 非 prerelease，created 2026-08-19T01:41:52Z，URL https://github.com/slashinchi/TVBoxOS-Mobile/releases/tag/v2.1.26.1 。资产：`TVBox-Mobile-v2.1.26.1.apk`（42,430,037 B）+ `update.json`（164 B）。
- **正式 Release APK SHA-256**：`df1760aa82a60c78da88655cdbbf2f2caec2e60c141cef3e78e1b63f314a57ce`（本机下载复核与 CI 记录一致；按授权不要求等于 RC 的 aede78440...）。Release 内 update.json 与 patched 上 update.json 内容一致（version=2.1.26.1，apk_url→fork Release）。
- **metadata 只写 patched**：`b72cbe9`「chore: sync release metadata for v2.1.26.1 [skip ci]」仅 README.md +4（更新记录新增 v2.1.26.1 条目）；update.json 因已在 patched 预同步无 diff。**main 保持 `6aabea8`（upstream mirror，fork/main==upstream/main）**。
- **最终状态**：tag=`b187b6f`、Release=1、patched=`b72cbe9`（metadata 后）、main=`6aabea8`、live ahead 20 / behind 0、worktree clean。
- **Milestone 4 CLOSED**（2026-08-19）。遗留：D-010（API24/33 smoke Deferred）、D-008（灾备 Deferred）、可选 P2。正式 Release 后扩展验证（覆盖升级真机等）待用户/后续批次。


## 2026-08-19 11:29 CST — ChatGPT post-release independent closeout PASS

- **独立 GitHub 复核**：正式 workflow run `32205623569` 为 `event=push`、`head_branch=v2.1.26.1`、`head_sha=b187b6ff8d89525da30e2543ed77e8e55bc58b2c`、`conclusion=success`；`publish-github-release` 全步骤 success，`build-apk` / `build-signed-rc` 按设计 skipped。
- **正式 publish path 实跑证据**：冷 Gradle cache；`assembleRelease` `148 actionable tasks: 148 executed`、BUILD SUCCESSFUL；`Verify release APK identity` 实际执行 `mkdir -p build` 并 PASS。identity：signer_sha256=`11eca31346835da4a0a5ab295647b14070f4c07533f08358679188941ae7d010`、apk_sha256=`df1760aa82a60c78da88655cdbbf2f2caec2e60c141cef3e78e1b63f314a57ce`、package=`com.github.tvbox.osc`、versionCode=`23601`、versionName=`2.1.26.1`、commit=`b187b6f`；v2 signature=true、1 signer、RSA4096。
- **Release 复核**：正式 job 明确创建 `v2.1.26.1` Release，并上传 `TVBox-Mobile-v2.1.26.1.apk` 与 `update.json`；随后 metadata writeback 成功。
- **tag / patched 拓扑复核**：GitHub compare `v2.1.26.1...b187b6f` = identical；`b187b6f...patched` = ahead 1 / behind 0，唯一 post-release commit 为 `b72cbe9`，由 `github-actions[bot]` 创建且仅 README.md +4。
- **main/upstream 镜像复核**：fork `main → patched` = ahead 20 / behind 0，base=`6aabea8`；独立查询 upstream `kukuqi666/TVBoxOS-Mobile/main` 仍=`6aabea8965a45df9a126d0436404ae8afccfe96f`，因此 fork/main==upstream/main 未被污染。
- **update manifest 复核**：`patched/update.json` version=`2.1.26.1`，apk_url 指向 fork 自身 `v2.1.26.1/TVBox-Mobile-v2.1.26.1.apk`。
- **结论**：Milestone 4 / 首个正式 Release **POST-RELEASE CLOSEOUT PASS / CLOSED**。不再为 `v2.1.26.1` 增加代码、RC 或发布门禁；覆盖安装正式 Release APK 属可选 confidence check。项目转入 **upstream maintenance**：仅在 upstream 新 commit、真实运行 bug 或明确维护需求出现时启动下一批。

## 2026-08-19 15:09 CST — Repository Identity / README Batch 获用户授权，handoff 给 OpenCode

- **用户决定**：在三轮方案评估/挑刺后确认总体计划无重大问题，授权把执行要求写入 GD 并 handoff 给 OC。该授权不重开 M4，不改变 `v2.1.26.1` 已关闭的 Release 结论。
- **ChatGPT 独立基线复核**：GitHub `patched=b72cbe9c5840d7ca77da2f5e449858f8153c369f`（release metadata commit，parent=b187b6f）；`main=6aabea8965a45df9a126d0436404ae8afccfe96f`；repository default branch 仍为 `main`。GitHub branch endpoint 显示 main / patched 均 `protected=false` / required status checks off。
- **已知未核项**：当前 ChatGPT connector 未能完整读取 repository rulesets，因此 default branch 切换前 OC 必须用 gh/API 或 GitHub Settings 补验 rulesets、branch protection、open PR base；存在冲突则先停止 settings mutation 并回 ChatGPT。
- **授权批次**：README fork identity 重构；新增 `docs/MIGRATION.md`；Release automation 与 README 解耦（update.json-only）；AGENTS branch-role 防误操作；验证后把 GitHub default branch 从 main 切到 patched；必要的 repository description 更新。
- **硬边界**：不改 app runtime/applicationId/version/signing/ABI，不改 update.json 下载加速策略，不删 inherited runtime/resources，不混入 P2 Actions deprecation，不新建/移动 tag/Release。
- **验证原则**：metadata script 必须 `bash -n` + clean/temp dry-run（README SHA 不变、update.json 正确、同版本幂等、错误版本 fail）+ patched 普通 CI；仅该授权范围不要求 signed RC / PHK110 runtime smoke。若实际 diff 触及 app/build/signing/artifact 行为，停止并回 ChatGPT 重新定验证级别。
- **长期决定**：新增 D-012（default/user-facing=`patched`，`main` 仍 upstream mirror，禁止 upstream 直 Sync patched）与 D-013（README human-facing；Releases version history；update.json machine-facing；Release automation 不写 README）。
- **执行后**：append FACTS、维护 ACTIVE-PLAN、整体重写 HANDOFF，然后停止并回 ChatGPT 做 post-batch review。

## 2026-08-19 CST — Repository Identity / README Batch 完成（`bea9706`）

- **Preflight / reconciliation**：Drive 最新 HANDOFF baseline=`b72cbe9`；`git pull --ff-only origin patched` 后起点一致；`main=upstream/main=6aabea8`；tag `v2.1.26.1`=`b187b6f`、Release 未动；误生成父目录临时 `download.bin` 已清理。
- **Repo diff**：commit `bea9706`「docs: establish fork repository identity」，仅 5 个授权文件：`README.md`、`docs/MIGRATION.md`、`scripts/sync_release_metadata.sh`、`.github/workflows/build.yml` metadata coupling、`AGENTS.md`。未改 app/runtime/version/signing/ABI/resources/tag/Release。
- **README**：相对 logo；fork 标题/中文定位；Build(patched)/Latest Release/License 三个 badge；upstream attribution；Why this fork；仅 Releases/latest 下载入口；迁移警告；`upstream/main → fork/main → fork/patched` 分支模型；AGPL/Credits/Disclaimer。删除上游个人化、宣传、R18、接口/短链/壁纸教程和长 changelog，未删除 inherited runtime/resources。
- **Migration**：新增 `docs/MIGRATION.md`，只写 `com.github.tvbox.osc` same applicationId/different signer、应用备份、OnePlus PHK110/Android 14 已验证环境、sources/subscriptions/favorites/history/settings 恢复边界、恢复提醒；不含 secret/keystore/用户备份。
- **D-013 解耦**：脚本只生成 `update.json`，保留 tag/version gate、`--skip-version-check`、gh.xxooo.cf URL；workflow `Publish update manifest` 只 diff/add `update.json`，不再读取/修改/stage README；build/signing/identity/version/tag ancestry 未动。
- **Metadata dry-run**（临时 clean worktree）：bash syntax、valid、同版本幂等、非法 tag、版本不匹配、`--skip-version-check` 全 PASS；README SHA `df3de1643b881c57c3f09938c6f47de06c0544b142664f4be275d038b4646aa8` 前后不变；update.json 内容正确；脚本无 README coupling。
- **Ordinary CI**：run `32251157073`（push，head=`bea9706`）success；`build-apk` success，publish/signed RC 按事件 skip。
- **GitHub settings preflight / mutation**：rulesets=[]；main/patched protection 均 disabled；open PR=[]；patched workflow push branches=`[main, patched]`；随后 default branch `main → patched` 成功，repository description 更新为 maintenance-fork 定位，topics 未动。
- **Post-switch verification**：default branch=`patched`；匿名临时 clone 默认 checkout `patched@bea9706`；GitHub raw README SHA 与本地一致；`main=upstream/main=6aabea8`；tag `v2.1.26.1` 仍=`b187b6f`；Release assets 仍 APK+update.json；patched update.json version/apk_url 正确；live ahead=21 / behind=0；worktree clean。
- **结论**：D-012/D-013 已落实，Repository Identity / README Batch **PASS / CLOSED**。后续交回 ChatGPT 做 post-batch review；M4、D-008、D-009、D-010 不重开。


## 2026-08-19 CST — ChatGPT Repository Identity post-batch review：核心 PASS，两个窄范围尾项待修

- **独立 GitHub 复核**：`b72cbe9...bea9706` = 1 commit / 5 个授权文件；commit `bea9706` 未触碰 app/runtime/version/signing/ABI/resources/tag/Release。`scripts/sync_release_metadata.sh` 只生成 update.json；workflow metadata writeback 只 diff/add update.json。
- **CI / branch / release 状态**：run `32251157073`（push，head=`bea9706`）success；default branch=`patched`；main=`6aabea8`=upstream/main；patched=`bea9706`；tag v2.1.26.1 仍=`b187b6f`；update.json 仍指 fork Release；open PR=[]；main/patched protection disabled。
- **核心结论**：README fork identity、MIGRATION、D-013 解耦、AGENTS branch role、default branch 切换与 description 更新均 **CORE PASS**。
- **F-001（identity tail）**：repository API 仍显示 `homepage=https://kukuqi666.github.io/TVBoxOS-Mobile/website`。该未标注 upstream Website 与新的 fork identity 不一致；要求改为 fork `/releases/latest` 或清空。
- **F-002（accuracy tail）**：README 写“Android 14+”，但运行证据只覆盖 OnePlus PHK110 / Android 14；build baseline 为 minSdk24、compile/target34、arm64-v8a，API24/API33 smoke 仍 D-010 Deferred。要求收紧文案并增加短 compatibility 边界说明。
- **验证级别**：仅 README + repository homepage setting；普通 CI 即可，不要求 signed RC、metadata dry-run 或设备 smoke。D-008/D-009/D-010/M4 不重开。
- **状态**：Repository Identity batch final closeout 暂缓；follow-up 已写入 HANDOFF/ACTIVE-PLAN，交回 OC。


## 2026-08-19 CST — 用户补充 post-batch follow-up：MIGRATION 必须加入中文

- **用户要求**：当前 `docs/MIGRATION.md` 全英文，不符合仓库中文主入口与主要使用场景；要求加入中文。
- **范围调整**：原 follow-up 的 F-001（repository Website）与 F-002（README compatibility）保留，并新增 F-003：`docs/MIGRATION.md` 改为**中文在前、英文在后**的双语文档。
- **内容边界**：中文必须忠实覆盖现有英文中的 same applicationId / different signer、不能直接覆盖、迁移前备份、OnePlus PHK110 / Android 14 已验证环境、已验证恢复项、未验证范围和恢复提醒；英文保留；两种语言不得出现语义冲突，不得扩张为全设备无损迁移保证。
- **验证级别**：授权 repo diff 从“仅 README”调整为“`README.md` + `docs/MIGRATION.md`”；另有 repository homepage settings-only 修改。普通 CI 即可，不要求 signed RC、metadata dry-run 或设备 smoke；main、tag、Release、update.json 均不得变化。
- **文档治理**：HANDOFF / ACTIVE-PLAN 已同步扩展为三个尾项；DECISIONS 不变，D-012/D-013 继续有效。

## 2026-08-19 CST — F-001/F-002/F-003 follow-up 完成（`3c6e376`）

- **Preflight**：`HEAD=origin/patched=bea9706`；`main=upstream/main=6aabea8`；worktree clean；tag `v2.1.26.1`=`b187b6f`、Release 和 update.json 未动；homepage 原为 upstream Pages。
- **F-002 README**：`Android 14+` 收紧为 `Android 14 / targetSdk 34`；新增兼容性段，准确披露 minSdk Android 7.0/API24、ABI arm64-v8a、compileSdk/targetSdk 34、OnePlus PHK110/Android 14 已实测、API24/API33 smoke 为 Deferred（D-010），不宣称所有旧系统/设备/ROM/后续 Android 已实测。
- **F-003 MIGRATION**：`docs/MIGRATION.md` 改为中文在前、英文在后；两部分逐项覆盖 same applicationId/different signer、备份核验、敏感信息禁止、OnePlus PHK110/Android14 边界、卸载/安装/恢复顺序、恢复项、人工复核项、原始备份保留与失败恢复；未扩张单设备结论，未删除英文。
- **Repo diff**：commit `3c6e376`「docs: clarify compatibility and migration」，精确仅 `README.md` + `docs/MIGRATION.md`；未改 app/runtime/version/signing/ABI、metadata/workflow、main、tag、Release、update.json。
- **普通 CI**：run `32260133419`（push，head=`3c6e376`）success；`build-apk` success，build-signed-rc/publish-github-release 按事件 skip。
- **F-001 homepage**：GitHub repository homepage 已设置为 `https://github.com/slashinchi/TVBoxOS-Mobile/releases/latest`；未修改 Pages/default/topics/description。
- **Post-check**：default=`patched`；默认 clone=`patched@3c6e376`；README compatibility 口径正确；中英 MIGRATION separator/order 与事实边界一致；`main=upstream/main=6aabea8`；tag=`b187b6f`；Release assets=`TVBox-Mobile-v2.1.26.1.apk, update.json`；update.json 正确；live ahead 22 / behind 0；worktree clean。
- **结论**：F-001/F-002/F-003 **PASS / CLOSED**；Repository Identity / README Batch post-batch follow-up 收口，交回 ChatGPT 做最终 closeout；M4、D-008、D-009、D-010 不重开。


## 2026-08-19 22:06 CST — ChatGPT final closeout：Repository Identity / README Batch PASS / CLOSED

- **GD reconciliation**：最新 HANDOFF / ACTIVE-PLAN / FACTS 均以 `patched=3c6e376ff9710fbeea0355c53827798bc204c50d`、`main/upstream=6aabea8965a45df9a126d0436404ae8afccfe96f`、default=`patched`、homepage=`https://github.com/slashinchi/TVBoxOS-Mobile/releases/latest` 为当前状态，无内部冲突。
- **GitHub exact diff**：独立 compare `bea9706...patched` = ahead 1 / behind 0 / total 1；仅 `README.md`（+8/-1）与 `docs/MIGRATION.md`（+42/-9），无授权外 repo 文件。
- **README 独立回读**：`Why this fork` 已使用 `Android 14 / targetSdk 34`；Compatibility 明确 Android 7.0/API24、`arm64-v8a`、compileSdk/targetSdk 34、OnePlus PHK110 / Android 14 已真机验证，以及 API24/API33 smoke 为 D-010 Deferred；未再使用 `Android 14+` 或全设备/后续系统兼容承诺。
- **MIGRATION 独立回读**：中文在前、英文在后；两种语言对 same applicationId / different signer、不可直接覆盖、迁移前备份、敏感信息限制、OnePlus PHK110 / Android 14 已验证边界、安装/恢复步骤、已验证恢复项、人工复核与失败恢复表达一致；没有扩张为所有 ROM/Android 无损迁移保证。
- **GitHub repository setting**：独立读取 repository metadata，default branch=`patched`；homepage=`https://github.com/slashinchi/TVBoxOS-Mobile/releases/latest`；description 为 maintenance-fork 定位；上游 Pages 不再作为 fork Website。
- **CI**：run `32260133419` 精确 head=`3c6e376ff9710fbeea0355c53827798bc204c50d`、event=`push`、conclusion=`success`；`build-apk` success，`build-signed-rc` 与 `publish-github-release` 按事件 skipped。
- **main/upstream**：独立读取 fork/main 与 upstream/main，二者均=`6aabea8965a45df9a126d0436404ae8afccfe96f`，main 未污染。
- **tag/update invariant**：GitHub compare `v2.1.26.1...b187b6f` = identical；`patched/update.json` 仍为 version=`2.1.26.1`，apk_url 仍指向 fork `v2.1.26.1/TVBox-Mobile-v2.1.26.1.apk`。
- **验证等级**：本 follow-up 仅文档 + repository homepage setting；没有 app/runtime/build/signing/version/artifact behavior 变化，因此不新增 signed RC、metadata dry-run 或 PHK110 smoke，不重开 M4。
- **最终结论**：F-001/F-002/F-003 与 Repository Identity / README Batch **FINAL PASS / CLOSED**。项目恢复 **Maintenance**；后续仅按 upstream 更新、真实 bug 或用户明确需求启动新批。D-008/D-009/D-010 继续 Deferred/accepted，P2 项不作为当前 blocker。


## 2026-08-19 23:40 CST — Upstream Maintenance Automation U1 获用户授权，handoff 给 OpenCode

- **用户决定**：同意将日常 upstream 维护自动化，采用修订后的方案 B，但分成 U1/U2 两批。当前只授权 U1；U2（auto signed RC / Deployment Approval / Release）必须等 U1 实施、真实 dry-run 与 ChatGPT closeout 后再单独授权。
- **调度锁定**：每隔两天，在 `Asia/Shanghai` 的 `12:22` / `22:22` 检查。实现不能用 day-of-month `*/2`；以 `2026-08-20` 为 anchor，用本地自然日差 parity gate，workflow 每天两次唤醒。保留 `workflow_dispatch force_check`。
- **用户通知偏好**：正常 actionable upstream update → PR Review Request 给 `slashinchi`；异常 → GitHub Issues；希望通过 Email + GitHub App 获知。用户已批准开启 Issues。PR Review 对用户的语义是“有一批上游改动待决定是否收进 fork”，Deployment Approval（U2）语义是“RC 已通过，是否正式发版”。
- **ChatGPT 最终挑刺后的安全修订**：
  - upstream candidate code 视为未审阅输入；执行 Gradle 的 candidate job 必须 read-only、无 signing secrets / repo write；write job 不执行 candidate code；
  - U1 不引入 PAT / classic token / 新 GitHub App secret；
  - GitHub 官方语义：`GITHUB_TOKEN` 触发的 push 不应被当作普通事件链；bot 创建/更新 PR 产生的 pull_request workflow 进入 approval-required 状态。U1 因此在 monitor 内先完成 candidate validation，不依赖 PR workflow，也不要求用户点击额外 Approve workflows；
  - GitHub 默认个人仓库通常禁止 Actions 创建/approve PR。U1 若需要，可以启用仓库 “Allow GitHub Actions to create and approve pull requests”，但 default workflow permissions 必须保持 read，automation 禁止 approving review / auto-merge，只有 U1 最小 write job显式申请 write scopes；
  - `main` 只允许 FF 到 upstream；candidate 从 patched 派生；U1 绝不自动 merge patched；一个 upstream SHA 一个 candidate，不静默替换已审阅 PR；
  - fork-owned auto-preserve 仅 README/update.json；build/release/runtime/unknown conflict 提高风险或 fail closed；
  - Issues 异常必须去重，恢复后可留言并 close；
  - 60 天 public repo inactivity 自动 disable scheduled workflow 属 residual risk，U1 只保留 manual dispatch fallback，不用假 commit 保活。
- **GitHub 独立授权基线**：`patched=3c6e376ff9710fbeea0355c53827798bc204c50d`；fork/main=`6aabea8965a45df9a126d0436404ae8afccfe96f`；upstream/main 同 SHA；default=`patched`；repository `has_issues=false`（待 U1 启用）；`v2.1.26.1` tag / Release 保持已关闭状态。
- **U1 授权 repo scope**：new `.github/workflows/upstream-monitor.yml`；必要时一个小 helper；AGENTS durable rules；Issues / 必要 Actions PR-create setting；GD docs。明确禁止 `build.yml`、app/runtime、version/signing/ABI、release/update chain、keystore/secrets、Environment、tag/Release、patched auto-merge。
- **执行后要求**：fixture tests + real no-change force-check + ordinary CI + settings/post-state evidence；append FACTS、维护 ACTIVE-PLAN、整体重写 HANDOFF，然后 STOP 返回 ChatGPT。未经授权不得进入 U2。

## 2026-08-20 00:51 CST — Upstream Maintenance Automation U1 implemented and verified

- **Implementation commits**：`01065034c54684e73699250062451152482f0b63`（新增 `.github/workflows/upstream-monitor.yml`、`scripts/upstream_monitor.py`、AGENTS U1 safety rules）；`822a8812002e6d9a030b57710c9a7edd93d33b93`（新 workflow 全部 `actions/checkout@v5`，消除 runner Node 20 deprecation warning）。
- **Exact repo diff from U1 authorization baseline `3c6e376ff9710fbeea0355c53827798bc204c50d`**：仅 `AGENTS.md`、`.github/workflows/upstream-monitor.yml`、`scripts/upstream_monitor.py`；未改 `.github/workflows/build.yml`、app/runtime、version/signing/ABI、release/update chain、tag/Release。
- **Workflow design**：`schedule` 每天 `12:22` / `22:22`，`timezone=Asia/Shanghai`；以 `2026-08-20` anchor 的本地日期 parity gate；保留 `workflow_dispatch force_check`；concurrency 防并发。
- **Fixture tests**：本地及 workflow job 均 `9/9 PASS`；覆盖 8/20、8/21、8/22、8/31→9/1、12/31→1/1、no-change、main fast-forward、main divergence、candidate clean merge/conflict、README/update fork-owned preserve、docs-only/runtime/build/unknown classification、open exact/stale PR policy、`base_ref=HEAD` diff regression、权限静态契约。
- **Permission evidence**：real U1 probe job `96150490205` 记录 `Contents: read`、`PullRequests: read`，输出 `Probe state: no-change`；candidate validation job定义 `contents: read`、build步骤清空 `GITHUB_TOKEN/GH_TOKEN`；write job仅显式 `contents: write` + `pull-requests: write`，不包含 Gradle、secrets 或 signing path。
- **Settings before/after**：before `has_issues=false`、`default_workflow_permissions=read`、`can_approve_pull_request_reviews=false`；after `has_issues=true`、`default_workflow_permissions=read`、`can_approve_pull_request_reviews=true`；default branch=`patched`、homepage=`https://github.com/slashinchi/TVBoxOS-Mobile/releases/latest`。
- **Ordinary CI**：run `32277445662`（head=`0106503`）success；run `32277903893`（head=`822a881`）success；两次 `build-apk` success，`build-signed-rc` / `publish-github-release` skipped by push event。
- **Real no-change force-check**：run `32277720757`（head=`0106503`）success，run `32278178069`（head=`822a881`）success；fixture/date/probe success，probe fetched upstream/main=`6aabea8965a45df9a126d0436404ae8afccfe96f` and returned `no-change`；candidate validation/write/notify skipped；no PR/Issue/ref mutation。
- **Post-check**：local and live `patched=822a8812002e6d9a030b57710c9a7edd93d33b93`；fork/main=upstream/main=`6aabea8965a45df9a126d0436404ae8afccfe96f`；tag `v2.1.26.1`=`b187b6ff8d89525da30e2543ed77e8e55bc58b2c`；Release assets unchanged；local/live `update.json` blob=`75e4a9c322e128a77927cf2dc9cef95a27291c4e`；open PR=[]、open Issue=[]；worktree clean。
- **Residual risks retained**：scheduled workflow may be delayed or auto-disabled after 60 days of public-repo inactivity；Email/GitHub Mobile delivery depends on account notification settings；bot-created PR `pull_request` workflow may show approval-required UX and is not a U1 gate；U2 signed RC/Environment/Deployment Approval/formal Release remains unimplemented and separately unauthorized.
- **Closeout state**：D-014/D-015/D-016 remain Accepted unchanged；U1 implementation and verification complete；stop and return to ChatGPT for post-batch review；do not enter U2.

## 2026-08-20 02:18 CST — U1 final recovery hardening and closeout verification

- **Independent review follow-up**：对 `2d6e822..e76cda5` 的终审提出 5 项 Important：`no-actionable-delta` write 门禁、candidate branch freshness、Issue recovery 误关闭、candidate diff stat 缺失、Drive 文档落后；均已在 `913c9d7943a37272bf0f77e1108f37b75144eb20` 收口。
- **Code changes**：write job 仅在 `PROBE_STATE != no-actionable-delta` 时要求 patched 包含 fork/main；probe 输出 candidate branch OID；repair job 校验 branch OID、patched ancestry 与确定性 candidate tree；Issue title 使用 `reason + upstream short SHA`，recover 只关闭匹配 key 的已知 automation reason；failure Issue 补充 candidate diff stat。未改 `build.yml`、app/runtime、version/signing/ABI、release/update chain、tag/Release。
- **Exact diff**：`e76cda5..913c9d7` 仅 `.github/workflows/upstream-monitor.yml` 与 `scripts/upstream_monitor.py`；`git diff --check` PASS，worktree clean。
- **Local verification**：fixture `12/12 PASS`；`python3 -m py_compile scripts/upstream_monitor.py` PASS；Ruby YAML parse PASS。完整本地 Gradle test 仍因本机无 Java Runtime 无法运行，GitHub CI 已提供构建证据。
- **Ordinary CI**：run `32286103311` 精确 head=`913c9d7943a37272bf0f77e1108f37b75144eb20`，success；`build-apk` success；`build-signed-rc` / `publish-github-release` skipped by push event。
- **Final real no-change force-check**：run `32286347837` 精确 head=`913c9d7943a37272bf0f77e1108f37b75144eb20`，success；fixture/date/probe/recover success，probe 明确输出 `no-change`；candidate validation、write、repair、notify skipped；无 ref、PR、Issue mutation。
- **Final settings/post-check**：default=`patched`；Issues enabled；`default_workflow_permissions=read`；`can_approve_pull_request_reviews=true`；open PR=[]；open Issue=[]；fork/main=`6aabea8965a45df9a126d0436404ae8afccfe96f` = upstream/main；tag `v2.1.26.1`=`b187b6ff8d89525da30e2543ed77e8e55bc58b2c`；Release assets unchanged；`patched/update.json` blob=`75e4a9c322e128a77927cf2dc9cef95a27291c4e`。
- **Closeout**：HANDOFF、ACTIVE-PLAN、FACTS 已同步到 `913c9d7` 与 final run evidence；D-014/D-015/D-016 语义保持 Accepted；U1 已停止交回 ChatGPT，U2 仍未授权。

## 2026-08-20 06:02 CST — U1 final HEAD verification and documentation closeout

- **Final implementation range**：`ed7905d`、`6154e64`、`19a0549`、`bd1a4aa`、`95deb52`、`371f75c`、`9f030ff`；只修改 `.github/workflows/upstream-monitor.yml` 与 `scripts/upstream_monitor.py`，未触碰 `build.yml`、app/runtime、version/signing/ABI、release/update chain、tag/Release。
- **Final hardening**：PR probe/write/repair 使用 REST full pagination；校验 `OPEN`、head repository、head branch、head OID、base=`patched`、candidate tree；补齐 main 已同步但 candidate branch 缺失恢复、PR create/view/list/close timeout/retry/cleanup、cancelled fail-closed；Issue 通知/恢复加入 title/body/comment marker reconciliation，避免 ambiguous timeout 重复评论/Issue。
- **Local verification**：fixture `12/12 PASS`；`python3 -m py_compile scripts/upstream_monitor.py` PASS；Ruby YAML parse PASS；全部 workflow `run` block `bash -n` PASS；`git diff --check` PASS；worktree clean。完整本地 Gradle test 仍因本机缺 Java Runtime 无法运行。
- **Ordinary CI**：run `32306535445` 精确 head=`9f030ff1d3482a516b16f8ae0984514b4c408b13`，success；`build-apk` success；`build-signed-rc` / `publish-github-release` skipped by push event。
- **Final real no-change force-check**：run `32306776877` 精确 head=`9f030ff1d3482a516b16f8ae0984514b4c408b13`，success；probe 日志明确 `Probe state: no-change`；fixture/date/probe/recover success；candidate validation、write、repair、notify skipped；无 ref、PR、Issue mutation。
- **Final settings/invariants**：default=`patched`；Issues enabled；`default_workflow_permissions=read`；`can_approve_pull_request_reviews=true`；open PR=[]；open Issue=[]；fork/main=`6aabea8965a45df9a126d0436404ae8afccfe96f` = upstream/main；patched=`9f030ff1d3482a516b16f8ae0984514b4c408b13`；tag `v2.1.26.1`=`b187b6ff8d89525da30e2543ed77e8e55bc58b2c`；Release assets unchanged；`patched/update.json` blob=`75e4a9c322e128a77927cf2dc9cef95a27291c4e`。
- **Coverage boundary**：当前 upstream 无 delta，真实 actionable candidate build、candidate branch push/repair、PR create/view/close、Issue create/comment/close、conflict/build-failure/cancelled path 未实际触发；仅有 fixture/static coverage。scheduled workflow 延迟/60-day auto-disable、账户通知设置、U2 未实现仍保留为 residual/unauthorized。
- **Closeout**：最终 review 无 Critical/Blocking；D-014/D-015/D-016 语义保持 Accepted；HANDOFF、ACTIVE-PLAN、FACTS 待本次上传后回读校验；U1 停止交回 ChatGPT，U2 仍未授权。

## 2026-08-20 07:29 CST — ChatGPT U1 post-batch independent review

- **GitHub exact diff**：`3c6e376...9f030ff` = 12 commits / 3 authorized files only：`.github/workflows/upstream-monitor.yml`（1276 lines）、`scripts/upstream_monitor.py`（512 lines）、`AGENTS.md`（+3 durable rules）；未改 build.yml/app/runtime/version/signing/ABI/release/update chain。
- **Independent CI evidence**：ordinary CI run `32306535445` exact head=`9f030ff1d3482a516b16f8ae0984514b4c408b13` success；build-apk success，signed RC/publish skipped。
- **Independent no-change evidence**：force-check run `32306776877` exact head=`9f030ff...` success；probe job token permissions=`Contents: read`, `PullRequests: read`；日志明确 `Probe state: no-change`；candidate validation/write/repair/notify skipped。
- **Current GitHub invariants**：fork/main=`6aabea8965a45df9a126d0436404ae8afccfe96f` = upstream/main；Issues enabled；default=`patched`；open PR=[]；open Issue=[]；tag `v2.1.26.1` 仍=`b187b6f...`；`update.json` blob/content未变。
- **PASS**：schedule timezone/anchor model、main FF-only、fork-owned README/update policy、candidate read-only build/no signing secrets、write separation、no auto-merge/sign/tag/release 均与 U1 授权一致。GitHub 官方当前文档确认 schedule 支持 IANA timezone并在 default branch 最新 commit 上运行。
- **U1a-01 Important**：candidate_validation 构建一次本地 merge，write job在另一 runner重新生成 candidate；当前只校验 base/upstream freshness、classification/candidate-needed和 write-side branch tree，未直接比较“validated build tree SHA == final PR branch tree SHA”。要求输出/比较 tree SHA，tree mismatch fail closed。
- **U1a-02 Non-blocking fix**：workflow dependency 当前 `fixture_tests → date_gate`，导致 off-day 仍每次跑完整 fixtures；调整为 date_gate先行，fixtures仅 active/force path，使非检查日真正轻量。
- **U1a-03 Residual hardening**：candidate branch/Issue key固定 upstream SHA 前7位；尚无真实 automation candidate/PR，现阶段统一提升到至少12位，降低长期命名碰撞/歧义风险。
- **Operational gate missing**：当前时间 07:29 CST，尚未出现首个真实 `event=schedule` run；U1 FINAL CLOSED 前至少观察一次 natural schedule（优先当日12:22或22:22，平台延迟可接受）。
- **Notification gate missing**：FACTS 明确真实 Issue create/comment/close 尚未触发；补一个 `[Automation Test] upstream-monitor notification channel` Issue 的 create/assign/mention/comment/close repo-side验证。不造假 upstream PR。账户级 GitHub Mobile/Email 投递仍需用户侧设置确认。
- **Maintainability**：workflow/helper 体积与重复 shell retry/reconcile 逻辑较大，记为 P2 debt；当前不大重构，待首次真实 actionable candidate/Issue 运行后再评估，避免为缩短文件破坏 fail-closed 状态机。
- **Conclusion**：U1 **CORE PASS / FINAL CLOSEOUT HOLD**；U1a 窄范围 follow-up 已写入 HANDOFF/ACTIVE-PLAN。U2 继续未授权。

## 2026-08-20 08:56 CST — ChatGPT second U1 review / U1a scope expanded

- 用户明确：3 个 U1 尾项由 ChatGPT 按专业判断直接决定；此前 P2 maintainability debt 也必须处理并 handoff OC。
- 复核结论保持：U1 CORE PASS / FINAL CLOSED HOLD；U2 未授权。
- 新增专业决策：candidate 内部身份升级为 full 40-char upstream SHA（人类显示 12 位）；validated candidate tree 必须与最终 PR branch tree deterministic equality；off-day date_gate-only。
- 新发现 functional gap：当前 `no-actionable-delta`（仅 README/update 等 fork-owned upstream 变化）会同步 main 后静默，违背“上游有更新就通知用户”；授权改为自动关闭 informational Issue 通知，不造空 PR。
- maintainability debt 从 P2 提升为本轮必做：保留现有 job/state machine，只把重复 PR/Issue pagination/timeout/retry/idempotency/reconcile 从约 1276 行 YAML 收敛到 trusted `scripts/upstream_monitor.py`；允许最多新增一个 stdlib unittest 文件；禁止为缩短行数做状态机重写。
- 最新 GitHub 官方文档再次核验：`on.schedule` 支持 IANA `timezone`；scheduled workflow运行 default branch latest commit；public repo 60 days no activity 会自动 disable scheduled workflows。
- 60-day risk 不能由 disabled workflow self-heal；继续禁止假 commit 保活。真正消除需 external watchdog，留给 ChatGPT 在 U1 final closeout 后单独处理，不授权 OC 引入外部 service/PAT/webhook。
- U1a operational gates：真实 Issue channel test + 完成 U1a 后 current HEAD 的至少一次自然 `event=schedule` active run + workflow indexing。
- D-017/D-018 已追加 DECISIONS；HANDOFF/ACTIVE-PLAN 已切到 U1a final hardening / maintainability / operational acceptance。

## 2026-08-20 13:00 CST — ChatGPT scheduler investigation after U1a handoff

- OC handoff states U1a implementation is at `cf16c14e514b21a5d53460110df98e8e8245630f`; ordinary CI `32326021904` PASS, force-check `32326201073` PASS, OA-02 Issue #1 create/assign/comment/close PASS, OA-03 workflow indexed/active PASS. OA-01 alone remains open because no natural `event=schedule` run was created at the 12:22 CST window.
- Independent GitHub commit evidence: `cf16c14` commit timestamp=`2026-08-20T02:49:28Z` = 10:49:28 CST, about 1h33 before 12:22; the miss is not explained by landing after the target window.
- Independent current workflow evidence at `cf16c14`: schedule stanza remains `22 12 * * *` and `22 22 * * *` with `timezone: Asia/Shanghai`; `workflow_dispatch` remains present; `date_gate` is first operational job.
- Official GitHub docs confirm: public-fork scheduled workflows are disabled by default; workflow states explicitly distinguish `ACTIVE`, `DISABLED_FORK`, `DISABLED_INACTIVITY`, and `DISABLED_MANUALLY`. Current OC/API evidence says this workflow is `active`, therefore the fork-default rule is **not a proven root cause**.
- Consequence: `gh workflow enable` on an already-active workflow is not accepted as a meaningful fix for an alleged hidden fork scheduler toggle. No separate documented fork-scheduler state was found beyond workflow state.
- Official docs also state scheduled workflows are best-effort and can be delayed or dropped under load. Recent GitHub Community reports in 2026 document repositories with correct default branch + active workflow + working manual dispatch but delayed/missing initial schedule events; treated as corroborating platform behavior, not primary authority.
- OA-01 acceptance refined: any natural `event=schedule` on current production workflow proves scheduler connectivity. If it occurs on an off-day, `date_gate.active=false` + all downstream operational jobs skipped is valid scheduler evidence when combined with the already-passed active `force_check`. A natural active-day run is no longer uniquely required.
- Authorized no-code remediation if the 2026-08-20 22:22 window (plus reasonable grace) is also silent: controlled workflow state cycle `active → disabled_manually → active` using supported `gh workflow disable/enable`; record before/after state; do not change cron/YAML or create fake commits.
- If 2026-08-21 12:22 and 22:22 also remain silent after that reset, classify OA-01 as likely GitHub scheduler backend/platform blocker, collect workflow/repo/default-branch/permissions/zero-run evidence, and stop changing U1 code. ChatGPT then decides Support escalation or external scheduler/watchdog fallback.
- U2 remains unauthorized; tag/Release/update chain remains outside this investigation.


## 2026-08-20 13:18 CST — ChatGPT third scheduler review：5-minute isolated probe replaces passive waiting

- 用户提出：GitHub 官方最短 schedule interval 为 5 分钟，当前目标是快速验证能否产生 `schedule` event，不应优先等待 22:22。ChatGPT 复盘后接受该意见。
- 官方文档再次核实：GitHub Actions `on.schedule` 最短间隔为 5 分钟；支持 IANA `timezone`；scheduled workflow 运行于 default branch latest commit；public fork 的 scheduled workflow 默认 disabled，且 workflow state 明确区分 `ACTIVE` / `DISABLED_FORK` / `DISABLED_MANUALLY` / `DISABLED_INACTIVITY`。
- 新验收模型拆为：A scheduler transport、B production trigger binding、C SOP business path。B 已有 workflow ID/state=active/default=patched/blob/stanza 证据；C 已有 `cf16c14` force-check/fixture/CI 证据；缺的是 A。
- 授权临时 `.github/workflows/scheduler-probe.yml`：`*/5 * * * *` + Asia/Shanghai，仅只读最小 job，不 checkout、不访问 upstream、不 Gradle、不 secrets、不写 repo。
- probe 若 `disabled_fork`，enable 后观察；若 active，观察连续 3 个 due windows；仍无 event 则只对 probe做一次 disable→enable，再观察。
- 任一真实 probe `event=schedule` → scheduler transport PASS，删除 probe；生产 12:22/22:22 首次自然 run 降为 non-blocking maintenance observation，不再阻塞 U1 closeout。
- probe reset 后连续多个 5-minute windows仍零 schedule event → classify GitHub scheduler/platform blocker，停止修改 production U1 code。
- 不允许把 production upstream-monitor 暂改为 5 分钟，因为会高频唤醒真实业务路径并扩大临时 diff。

## 2026-08-20 19:19 CST — Isolated scheduler probe execution and stop

- **Production schedule evidence discovered**：run `32333618052`，`event=schedule`，head=`cf16c14e514b21a5d53460110df98e8e8245630f`，created=`2026-08-20T04:54:57Z` (`12:54:57 CST`)，success；date gate、fixture、probe、recover success，probe=`no-change`；candidate validation/write/notify skipped；无 repo mutation。Production OA-01 scheduler evidence因此 PASS for the U1a implementation HEAD。
- **Probe add**：diagnostic commit `3e71d4db6fd4eefba84393ebbb445a30f43843be` (`18:29:07 CST`) 只新增 `.github/workflows/scheduler-probe.yml`；`*/5 * * * *` + `Asia/Shanghai`；单 job；`contents: read`；无 checkout/upstream/Gradle/secrets/write。
- **Probe indexing/state**：workflow ID=`338519099`，initial state=`active`；remote indexed successfully。
- **Initial observation**：45 次 × 30 秒轮询（约 22.5 分钟，覆盖至少 3 个 due windows），`event=schedule` 数量为 0。
- **Controlled reset**：仅对 probe 执行 `active → disabled_manually → active`；两个状态均通过 GitHub API/CLI 验证；production `upstream-monitor.yml` 未 disable/enable、未改 cron、未改代码。
- **Post-reset observation**：再次 45 次 × 30 秒轮询（约 22.5 分钟，覆盖至少 3 个 due windows），`event=schedule` 数量仍为 0。
- **Probe removal**：commit `f73bd44e9af5b73e2ae0f312a3ee8d7faba18c20` (`19:18:03 CST`) 删除 probe 并 push；remote probe file 404/absent；production workflow blob=`82d8171f2a052a8463ae854d9b87cb4230bfd706`、state=`active` 未变。
- **Stop classification**：满足 HANDOFF 规定的 active/no-event → one reset → active/no-event stop condition；isolated 5-minute probe 记录为 GitHub scheduler/platform blocker or scheduler-specific operational uncertainty，停止修改 production U1 code，交回 ChatGPT。不要把 public-fork `disabled_fork` 假设当作已证实根因，因为 production state=`active` 且已产生一次真实 schedule run。
- **Invariants after probe**：current `patched`=`f73bd44e9af5b73e2ae0f312a3ee8d7faba18c20`；`main/upstream`=`6aabea8965a45df9a126d0436404ae8afccfe96f`；default=`patched`；open PR/Issue=[]；tag/Release/update.json 未变；U2 未授权。


## 2026-08-20 19:54 CST — ChatGPT final closeout：U1 / U1a PASS / FINAL CLOSED

- 独立 GitHub 复核 production run `32333618052`：workflow=`Upstream Maintenance Monitor`，`event=schedule`，head=`cf16c14e514b21a5d53460110df98e8e8245630f`，created=`12:54:57 CST`，conclusion=`success`。jobs：date gate / fixtures / probe / recover success；candidate validation / write / repair / notify skipped；probe log=`Probe state: no-change`；无 repo mutation。
- 独立复核 ordinary CI `32326021904` 与 force-check `32326201073` 均 exact `cf16c14` success。
- GitHub compare `cf16c14...f73bd44`：ahead 2、files=[]；两笔 scheduler-probe add/remove diagnostic commit 最终净文件差异为零。`f73bd44` tree 与 `cf16c14` tree均=`4c9908c62320c28bd4df47eca8819952c8959796`。
- 当前 remote `.github/workflows/scheduler-probe.yml` absent；production upstream-monitor blob=`82d8171f2a052a8463ae854d9b87cb4230bfd706`，schedule仍为 Asia/Shanghai 12:22/22:22。
- fork/main=`6aabea8965a45df9a126d0436404ae8afccfe96f` = upstream/main；default=`patched`；open PR=[]；open Issue=[]；tag/Release/update.json 未变。
- 5-minute probe 初始/reset 后各约22.5分钟零 event 的旧“platform blocker” stop classification被 ChatGPT纠正：production 真实 schedule已成功，且 production 已观测到约32m35s delay；短 probe不足以否定 scheduler，最终仅作为 inconclusive diagnostic history保留。
- U1/U1a final verdict：**PASS / FINAL CLOSED**。D-014～D-018继续有效；新增 D-019 scheduler best-effort / health policy。U2 implementation仍未授权。
- 首次真实 actionable upstream update 仍为 live canary：candidate branch/write/PR Review Request及账户级 Push/Email实际投递未生产实测；该边界不阻塞U1，首次真实场景必须复核。
- 60-day inactivity auto-disable仍是平台残余风险；禁止假commit保活，后续需external watchdog核 workflow state + recent schedule，建立前manual `force_check`为fallback。


## 2026-08-20 20:05 CST — ChatGPT post-closeout critique：U1b maintenance follow-up opened

- 既有 U1/U1a production natural schedule / CI / force-check / OA-02 / OA-03 / exact-tree/security 证据继续有效，不撤销历史 FINAL CLOSED。
- 新发现 deterministic schedule edge：workflow date gate 当前按 runner 实际 Asia/Shanghai 日期做 parity；若 22:22 schedule 延迟跨午夜，会把 event 归到错误日期。要求按 `github.event.schedule` 计算最近应执行 cron occurrence date。
- 新发现 deterministic lineage edge：`no-actionable-delta` 会 FF main 但不改 patched；之后真正 upstream code 更新时，当前 `patched_contains_main=false → patched-behind-main` 分支会错误阻塞 candidate。要求把 policy-equivalent main-ahead 视为允许的暂态，并在下一次 actionable 更新时从 current patched + latest upstream 生成完整 validated candidate PR；不允许 bot auto-merge patched。
- `recover` job 当前只操作 Issue，却仍有 `contents: write` + persisted checkout credential；要求降至 contents:read / issues:write / persist-credentials:false。
- 以上组成独立 U1b Maintenance follow-up；U2 implementation 在其 closeout 前继续 NOT AUTHORIZED。


## 2026-08-20 21:03 CST — U1b implementation / verification / closeout

- U1b implementation committed and pushed as `e3f1bf20b60bb7aa63dc2ee4ecd0b049a2958201` (`ci: harden upstream monitor lineage gates`); only `.github/workflows/upstream-monitor.yml`, `scripts/upstream_monitor.py`, and `scripts/tests/test_upstream_monitor.py` changed. `build.yml`, app/runtime, signing/release chain, tag/Release, and `update.json` were not touched.
- U1b-01 implementation: schedule events pass `github.event.schedule` and an Asia/Shanghai runner timestamp to the helper; supported schedules are exactly `22 12 * * *` and `22 22 * * *`; the helper selects the latest occurrence not later than runner time, and empty/unknown schedules raise non-zero. Dispatch uses actual Asia/Shanghai date; `force_check` still overrides parity.
- U1b-02 implementation: probe classification moved into trusted `probe-state` helper and now distinguishes stable `no-change` after `fork_main == upstream` with an empty candidate from later `actionable-main-ahead` when main is an upstream ancestor and the current patched + latest upstream candidate is non-empty. Write path still rechecks origin SHA/tree and never ancestry-only merges patched.
- U1b-03 implementation: `recover` now has `contents: read`, `issues: write`, and checkout `persist-credentials: false`; its Issue recovery behavior is unchanged.
- Local verification: `python3 -m unittest scripts.tests.test_upstream_monitor` = 24/24 PASS; `python3 -m py_compile scripts/upstream_monitor.py` PASS; Ruby YAML parse and every workflow `run` block `bash -n` PASS; `git diff --check` PASS; reviewer re-review reported no findings.
- CLI edge checks: delayed `12:54` maps to `12:22` same day; next-day `00:05` maps to prior-day `22:22`; off-day/force dispatch results are correct; empty and unknown schedules fail closed.
- GitHub verification: ordinary build CI run `32371680652` success at head `e3f1bf2`; force-check monitor run `32371956449` success at head `e3f1bf2`, probe=`no-change`, candidate validation/write/repair/notify skipped; recover job log showed Contents read, Issues write, and `persist-credentials: false`.
- Current remote invariants: `origin/patched=e3f1bf20b60bb7aa63dc2ee4ecd0b049a2958201`; `origin/main=upstream/main=6aabea8965a45df9a126d0436404ae8afccfe96f`; tag `v2.1.26.1`, Release, `update.json`, and open PR/Issue state unchanged. No artificial upstream mutation was created.
- Remaining live-canary boundary: first real actionable upstream update must still be reviewed by ChatGPT for candidate tree/build, main fast-forward, PR identity/review request, and human Merge gate. U2 implementation remains unauthorized.


## 2026-08-20 23:32 CST — ChatGPT U1/U1a/U1b final closeout

- ChatGPT 独立复核 GD 与 GitHub，确认 `patched=e3f1bf20b60bb7aa63dc2ee4ecd0b049a2958201`。
- `f73bd44...e3f1bf2` exact diff 仅 3 个授权文件：`.github/workflows/upstream-monitor.yml`、`scripts/upstream_monitor.py`、`scripts/tests/test_upstream_monitor.py`。
- U1b-01：scheduled occurrence attribution 已实现，支持 production `22 12 * * *` / `22 22 * * *`，跨午夜按 intended occurrence 日期做 parity；未知 schedule fail closed。
- U1b-02：`actionable-main-ahead` 与 stable no-actionable/no-change state 已实现；不自动 merge patched，后续 actionable update 仍从 current patched + latest upstream 生成 exact-tree candidate PR。
- U1b-03：recover 实际权限为 `Contents: read / Issues: write`，checkout `persist-credentials=false`。
- ordinary CI `32371680652` exact `e3f1bf2` PASS；signed RC / formal publish skipped。
- force-check `32371956449` exact `e3f1bf2` PASS；24/24 fixtures PASS；probe=`no-change`；candidate/write/repair/notify 未产生 mutation。
- fork/main == upstream/main == `6aabea8965a45df9a126d0436404ae8afccfe96f`；default=`patched`；open PR/Issue=[]；`update.json` 仍为 `2.1.26.1` fork Release URL；既有 tag/Release 未移动。
- Final verdict：**U1 / U1a / U1b FINAL CLOSED**。当前进入 Maintenance；首次真实 actionable upstream PR 为 live canary。U2 仅允许 design/review，implementation 继续未授权。


## 2026-08-21 09:00 CST — ChatGPT reopens scheduler reliability gate as U1c

- 用户复核原始目标后指出：自动上游检测不能以“曾经有一次 production schedule run”为充分验收；5-minute isolated probe 没有产生 schedule event，也不能被简单忽略后进入下一阶段。
- ChatGPT 重新评估后接受该质疑：U1/U1a/U1b 的代码、CI、权限、状态机与单次 natural `schedule` 成功证据继续有效，但此前“整个 U1 FINAL CLOSED”的表述过强。
- GitHub 官方当前文档明确：`schedule` 最短 5 分钟，但 scheduled events 在高负载时可能 delay，足够高时甚至可能被 dropped；因此 native schedule 不提供每个窗口必达的可靠性保证。
- 5-minute probe 的两段约 22.5 分钟零事件仍属于 inconclusive diagnostic（短于已观测约 32m35s 的 production 延迟），但它同时证明“无法通过短时 probe 获得可重复的正向调度验收”；不能把这个负面结果抹掉。
- 当前真实缺口重新定义为 **Scheduler Reliability / Coverage**，不是 upstream comparison/state-machine 逻辑。
- 推荐 U1c：保留 GitHub schedule primary，增加 independent external watchdog；在 intended active window + grace 检查 workflow state + natural run/probe，缺失/失败时通过 `workflow_dispatch` 补跑。优先用单 repo fine-grained PAT 的 `Actions:write`；不用需要 `Contents:write` 的 repository_dispatch。
- U1c 必须有一次真实 external timer/cron → GitHub dispatch → real run ID → successful probe 的 end-to-end canary；完成前 U2 implementation BLOCKED。
- 本次只修正控制面与验收定义，不改 repo；当前 implementation HEAD 仍 `e3f1bf20b60bb7aa63dc2ee4ecd0b049a2958201`。
## 2026-08-21 12:22 CST — U1c third assessment: GitHub-only control repo v2 authorized

- Updated ASER was applied: assessment centered on the business goal “unattended upstream detection has verifiable coverage,” and only missing evidence was collected; prior U1a/U1b code evidence was not reopened without cause.
- Rejected prior D-022 implementation route: a target-scoped `Actions:write` PAT could dispatch `build.yml`; current `build.yml` runs `build-signed-rc` on `workflow_dispatch` and reads signing secrets, so the watchdog credential would have signing-trigger capability.
- User constraint: avoid an additional VPS. Reassessment found a GitHub-only practical-reliability design: private non-fork control repo + reconciliation schedule + target locked Issue comment control channel.
- Official GitHub evidence: public repository workflow/run/job/branch state can be read without auth; creating an issue comment requires fine-grained `Issues:write`; `issue_comment` executes default-branch workflow code; GITHUB_TOKEN-generated non-dispatch events do not recursively create workflow runs; private-repo hosted-runner jobs consume billable minutes rounded up per job.
- Security improvement: cross-repo PAT reduced to selected target repo + **Issues:write only**; no Actions:read/write, Contents, PR or Administration permission. All reads are unauthenticated public REST.
- Reliability improvement: control repo uses reconciliation rather than fire-once scheduling; production cadence every 3 hours at :37, calculating the latest intended active occurrence after a 60-minute grace. Future runs catch up missed control schedules.
- Deterministic coverage ledger added to design: target probe success writes `TVBOX_UPSTREAM_COVERED_V1` occurrence marker to locked control Issue using target GITHUB_TOKEN; watchdog requests use `TVBOX_UPSTREAM_WATCHDOG_V1 REQUEST`.
- Strict target pre-gate required before any existing date/probe/write job. Invalid issue comments stop after gate. Replay and stale/future/off-parity occurrences fail closed.
- Failure handling: max 3 request attempts per occurrence; target workflow disabled, token auth/expiry, API failure, or request exhaustion produce a single idempotent incident in private control repo. Disabled target is not auto-enabled; control directly compares public upstream/fork main SHAs and escalates if delta exists.
- Accepted residual risk: private control repo still uses GitHub Actions schedule, so a GitHub-wide scheduler outage is not an independent failure domain. Under the explicit no-VPS/GitHub-only constraint, this is accepted; catch-up must occur on the next reconciliation after service resumes.
- Acceptance hardened: 60-minute continuous private `*/5` natural-schedule canary; real REQUEST→issue_comment→probe→COVERED E2E; replay no-op; watchdog PAT negative test against `build.yml workflow_dispatch`; target regression CI/force-check; failure-path incident evidence.
- Decision: no new P0/P1 remains in the design after these changes. U1c implementation is AUTHORIZED within the locked scope. U2 remains BLOCKED until ChatGPT independently closes U1c.

## 2026-08-21 22:56 CST — U1c implementation and production E2E closeout

- TVBox U1c event gate/coverage changes were pushed to `patched=979c013313a4a37739be7ef782200f865ae04c42`; control production implementation/docs were pushed to `main=e93f2a6`.
- Human gate facts: target-selected fine-grained PAT secret `TVBOX_WATCHDOG_TOKEN` exists in the private control repo; only the non-sensitive expiry variable `TVBOX_WATCHDOG_TOKEN_EXPIRES_ON=2026-09-20` was read. Token value was never read, printed, or stored.
- Target Issue #2 is a normal open locked Issue and remains the request ingress. Because GitHub Actions `GITHUB_TOKEN` cannot comment on a locked conversation, a separate normal open unlocked Issue #3 was created as the coverage ledger. Target/control variables now set `TVBOX_AUTOMATION_CONTROL_ISSUE_NUMBER=2` and `TVBOX_AUTOMATION_COVERAGE_ISSUE_NUMBER=3`.
- Natural canary: private control schedule run `32491261550`, `event=schedule`, head=`fc4bced`, success; observed for more than 60 minutes without reset before production rollout.
- First production dispatch `32493232382` succeeded at the job level but returned `api-failure`; private incident Issue #2 recorded the incorrect Actions API path `.github/workflows/upstream-monitor.yml`. Root cause was confirmed by public API: the workflow endpoint requires filename `upstream-monitor.yml`; fixed by control commit `d1b0619`.
- Corrected control dispatch `32493423430` returned `{"status":"requested","occurrence":"2026-08-20T22:22:00+08:00"}` and created a request comment on target Issue #2. Target run `32493441165` passed event gate/date gate/fixtures/probe but failed coverage because the locked Issue rejects target `GITHUB_TOKEN` comments; this proved the lock/coverage conflict.
- Final split-ledger retry: target run `32494521332`, head=`979c013`, event=`issue_comment`, all event gate/date gate/fixture/probe/coverage jobs success. Coverage comment ID `5371505648` was written to Issue #3 by `github-actions[bot]` for occurrence `2026-08-20T22:22:00+08:00`, probe=`no-change`, upstream/fork main=`6aabea8965a45df9a126d0436404ae8afccfe96f`.
- Final control reconciliation `32494640540`, head=`349371ab60049bc406957e06383a9354e713912d`, returned `{"status":"covered","occurrence":"2026-08-20T22:22:00+08:00"}` with no new duplicate incident. The transient API-failure incident was closed after resolution; token-within-30d warning remains open for expiry tracking. Documentation-only commit `e93f2a6` followed afterward.
- Tests: control watchdog `19/19`, TVBox helper `29/29`; control `py_compile`, YAML parse and `git diff --check` passed. No build/signing/release/app/update/tag/Release paths were modified; U2 remains BLOCKED.

## 2026-08-21 23:03 CST — U1c PAT capability negative test

- A temporary control-repo diagnostic workflow used the configured `TVBOX_WATCHDOG_TOKEN` only to POST a negative `build.yml` `workflow_dispatch` request for `patched`; it never printed or persisted the token.
- Diagnostic run `32495457843` succeeded because the target API rejected the request with HTTP `403` (`build.yml workflow_dispatch rejected as expected`). No new target `build.yml` run appeared; latest target build run remained `32494456143`, a prior push event.
- The temporary diagnostic workflow was removed immediately. Control repo final HEAD is `c6f2145`; TVBox remains `979c013`. U1c acceptance item “PAT cannot dispatch build/signing workflow” is verified; U2 remains BLOCKED.


## 2026-08-22 08:00 CST — ChatGPT U1c independent review / closeout hold

- [CHATGPT-REVIEW] Public target current state independently verified: `patched=979c013313a4a37739be7ef782200f865ae04c42`; fork/main=`6aabea8965a45df9a126d0436404ae8afccfe96f` = upstream/main; open PR=[]。
- [CHATGPT-REVIEW] `e3f1bf2..979c013` = 3 commits; files are `.github/workflows/upstream-monitor.yml`, `scripts/upstream_monitor.py`, `scripts/tests/test_upstream_monitor.py`, `AGENTS.md`, and `.gitignore`. `.gitignore` only adds `.worktrees/`; classified as non-functional repo-hygiene scope drift, accepted without a revert commit.
- [CHATGPT-REVIEW] ordinary build run `32494456143` is exact head=`979c013`, event=`push`, conclusion=`success`.
- [CHATGPT-REVIEW] U1c target E2E run `32494521332` is exact head=`979c013`, event=`issue_comment`, conclusion=`success`; event gate/date gate/fixture/probe/coverage jobs all succeeded. Issue #3 contains `TVBOX_UPSTREAM_COVERED_V1:2026-08-20T22:22:00+08:00` written by `github-actions[bot]`, run_id=`32494521332`, probe=`no-change`.
- [CHATGPT-REVIEW] target Issue #2 is open+locked; Issue #3 is open+unlocked. Issue #2 title/body is stale after the split-ledger fix: it still describes itself as coverage ledger and says target may add COVERED markers. This does not break the variable-driven workflow but should be corrected before final closeout.
- [EVIDENCE-BOUNDARY] Current ChatGPT GitHub connector cannot read private `slashinchi/tvbox-automation-control`. Natural canary `32491261550`, production request `32493423430`, covered reconciliation `32494640540`, PAT negative run `32495457843`=403, and final control HEAD=`c6f2145` are therefore retained as OC/GD evidence rather than mislabeled as independent GitHub observations.
- [CHATGPT-REVIEW] Acceptance #6 explicitly requires target regression CI + `force_check no-change`. Current-head build and issue_comment E2E are PASS, but the latest recorded `force_check` is `32371956449` at U1b head `e3f1bf2`; no `force_check` run at `979c013` is recorded. U1c verdict is **CORE PASS / FINAL CLOSEOUT HOLD** pending one exact-head `workflow_dispatch force_check=true` with success/no-change/no unexpected mutation.
- [NEXT] Authorized closeout batch is limited to: (1) current-head force_check; (2) correct Issue #2 title/body to locked request-ingress semantics while keeping it locked; (3) update FACTS/PLAN/HANDOFF and stop. U2 implementation remains unauthorized.

## 2026-08-22 08:01 CST — U1c final closeout PASS

- [OC-EXECUTION] Current-head regression run `32538741581` was dispatched from `patched` with `force_check=true`; Actions checked out exact `979c013313a4a37739be7ef782200f865ae04c42` and concluded `success`.
- [OC-EXECUTION] The run log reported `Probe state: no-change`; U1 fixtures passed; candidate validation, branch/write, notify, and coverage jobs were skipped as expected for a no-change workflow-dispatch probe. No automation branch, PR, or Issue mutation was created; post-run refs remain `main=6aabea8` and `patched=979c013`.
- [OC-EXECUTION] Target Issue #2 was corrected in place while retaining `locked=true`: title is `[Automation Control] Locked watchdog request ingress`; body now describes exact request-only ingress, points successful coverage to unlocked Issue #3, and removes the old coverage-ledger / target-may-add-COVERED wording. Issue #3 remains open and unlocked.
- [OC-REVIEW] GitHub/Actions rechecked after both changes: run `32538741581` success, target refs unchanged, open PR list empty, and target open Issues remain #2/#3. U1c closeout acceptance is PASS; U1/U1a/U1b/U1c reliability is FINAL CLOSED. U2 implementation remains BLOCKED.

## 2026-08-22 08:05 CST — HANDOFF role repair / current-state reconciliation

- [OC-ENTRY] Drive file `1Q7ZvjsDKPpqEa1wfQSy8wcgZBfmEXCaEwZBWiTsgh_c` was exported and read as the authorized OpenCode entry prompt. It requires reading HANDOFF/ACTIVE-PLAN, reconciling GitHub, maintaining FACTS/PLAN/HANDOFF, and stopping before U2.
- [OC-REVIEW] HANDOFF revision history showed the latest two revisions at 2026-08-21 23:54 CST and 2026-08-22 08:03 CST were role-drifted `OpenCode Handoff Entrypoint` checklists. The preserved Current State document was used as the reconstruction base; the separate OC prompt remains the entrypoint.
- [OC-REVIEW] Current GitHub recheck: `patched=979c013313a4a37739be7ef782200f865ae04c42`; `main=upstream/main=6aabea8965a45df9a126d0436404ae8afccfe96f`; open PRs empty; Issue #2 open+locked with request-ingress title/body; Issue #3 open+unlocked.
- [OC-REVIEW] Latest natural schedule run `32494757828` used exact head `979c013`, concluded success on the off-day date gate, and skipped fixture/probe/coverage/candidate/write/notify/recovery jobs as expected; no mutation was observed. No U1c test was rerun.
- [OC-EXECUTION] `TVBoxOS-Mobile-Fork-HANDOFF.md` was restored to a durable `HANDOFF / Current State` document, with the latest U1c closeout, split #2/#3 ledger model, current refs, evidence boundary, and U2 block retained. ACTIVE-PLAN and HANDOFF were updated accordingly; U1c remains FINAL CLOSED and U2 implementation remains BLOCKED.

## 2026-08-22 13:55 CST — F1 execution paused at planned Environment approval gate

- [OC-PREFLIGHT] At F1 start, target `patched=979c013`; `main=upstream/main=6aabea8`; open PRs empty; Actions `default_workflow_permissions=read`; `can_approve_pull_request_reviews=true`; four repository signing secret names present; `release-signing` Environment absent. Secret values were never read.
- [OC-EXECUTION] F1-1 commit `d061958` adds exact/prefix fork-owned candidate preservation for `AGENTS.md`, `update.json`, signing metadata/helper/test paths, and all `.github/workflows/`; it binds only `build-signed-rc` and `publish-github-release` to `release-signing`; 31 helper tests passed with py_compile/YAML/diff checks.
- [OC-EXECUTION] `release-signing` was configured with required reviewer `slashinchi`, `prevent_self_review=false`, branch policy `patched`, tag policy `v*`. Environment secret names `TVBOX_KEYSTORE_BASE64`, `TVBOX_KEY_ALIAS`, `TVBOX_KEY_PASSWORD`, `TVBOX_STORE_PASSWORD` exist; repository-level rollback copies remain. No secret values were logged.
- [OC-EXECUTION] Corrected shadow canary run `32555459847` succeeded: candidate SHA `8b7bab50c9439c25f0b796d910ba5efba5d42a09`, PR #4 was created against a shadow patched ref, reviewer `slashinchi` was requested, second reconcile reused the same PR, pull_request run `32555474017` was `action_required` and not approved/executed, and all four shadow refs plus the PR were cleaned. Initial run `32555397842` failed before candidate preparation because the workflow was on real main without the helper; cleanup succeeded and commit `631c374` corrected the checkout.
- [OC-EXECUTION] Temporary canary workflow was removed in commit `f87d99d`; current final patched head is `f87d99d46dbff8e68c5f2d53b602c1f58cd9d5d6`.
- [OC-HUMAN-GATE] Final-head signed RC run `32555524779` is waiting for deployment approval under `release-signing`; expected approval is exact `refs/heads/patched` / `f87d99d`. OC must not approve it. After approval, verify signer/package/version/commit identity before deleting repository-level signing secret copies.
- [OC-STATE] HANDOFF and ACTIVE-PLAN are now `REVIEW_PENDING / HUMAN_ACTION_REQUIRED`; F1 remains open and Automation Foundation is not CLOSED. U2 remains BLOCKED.

## 2026-08-22 08:10 CST — U1c closed-state wording repair

- [OC-DOC-REPAIR] Removed current-state U1c execution language from HANDOFF / ACTIVE-PLAN: no `AUTHORIZED` U1c heading, no current `Authorized repo scope`, and no pending Human Gate remains. Historical scope is explicitly labeled closed/reference-only.
- [OC-DOC-REPAIR] PAT gate is recorded as completed history: selected target + Issues:write PAT secret exists, expiry is recorded, and negative-capability handling was already verified; no token value was read or written.
- [OC-DOC-REPAIR] Replay/idempotency semantics are explicit: control-side reconciliation deduplicates #2 REQUEST comments against the Issue #3 `TVBOX_UPSTREAM_COVERED_V1` ledger. The target event gate validates request shape/locked Issue/actor/occurrence only and does not query the coverage ledger.
- [OC-BOUNDARY] This was a GD-document-only repair. No GitHub repository code was modified and no U1c test or workflow was rerun.

## 2026-08-22 CST — ChatGPT G1 governance repair + F1 foundation replan
- Trigger: user required the Handoff framework to function as the real control plane: ChatGPT designs and persists the landing plan, OC executes it, then ChatGPT independently reviews. User also re-stated ASER closeout as goal-first: code/function/plan existence is not completion unless the actual need is solved.
- GitHub read-only baseline during assessment: `patched=979c013313a4a37739be7ef782200f865ae04c42`; fork/main=`6aabea8965a45df9a126d0436404ae8afccfe96f`; upstream/main same; existing U1/U1c technical evidence is not revoked.
- Assessment finding 1: prior workflow had drifted back to task-specific long OC prompts even though the fixed OC Entrypoint and Handoff Protocol already existed. This was process non-compliance, not lack of a basic protocol.
- Assessment finding 2: the higher-level Automation Foundation cannot be closed solely from current no-change/scheduler evidence because the actionable `GITHUB_TOKEN → candidate PR/reviewer` positive path has not been exercised in production shape.
- Assessment finding 3: signing credentials are repository-level while fork/main is an exact upstream mirror; candidate-only workflow preservation cannot fully isolate upstream workflow code from repository-wide secrets. F1 therefore uses protected Environment `release-signing` plus trusted fork-owned workflow/control-plane preservation.
- External verification: current GitHub docs state GITHUB_TOKEN-created/updated PRs generate approval-required pull_request runs; public repositories support Environment secrets/required reviewers/selected deployment branch/tag policies; same-name Environment secrets take precedence over repository secrets; repository workflow settings can allow GITHUB_TOKEN PR creation while default workflow permissions remain read.
- GD changes by ChatGPT: Handoff Protocol v2, fixed OC Entrypoint hardening, short current HANDOFF, decision-complete ACTIVE-PLAN, and DECISIONS D-025/D-026.
- Boundary: no GitHub repository code/settings/secrets/Environment/PR/branch/tag/Release were changed by ChatGPT in this planning batch. F1 implementation is handed to OC only after final GD read-back.

## 2026-08-22 14:07 CST — F1 execution completed; returned to ChatGPT review

- [OC-EXECUTION] Environment approval cleared for exact final `patched` head `f87d99d46dbff8e68c5f2d53b602c1f58cd9d5d6`. Signed RC run `32555524779` concluded success: Gradle release build, APK identity verification, RC APK upload, identity-report upload, and runner keystore cleanup all passed.
- [OC-IDENTITY] Downloaded identity report records signer fingerprint matching the repository `TVBOX_SIGNER_SHA256` variable, APK SHA-256 `542bb7f39aef0be2edf4696dab921871a4decd1bdcc327661599ef2beabc67b4`, package `com.github.tvbox.osc`, versionCode `23601`, versionName `2.1.26.1`, and commit `f87d99d46dbff8e68c5f2d53b602c1f58cd9d5d6`.
- [OC-SECURITY] Only after the signed RC PASS, repository-level secrets `TVBOX_KEYSTORE_BASE64`, `TVBOX_KEY_ALIAS`, `TVBOX_KEY_PASSWORD`, and `TVBOX_STORE_PASSWORD` were deleted. Post-check shows none at repository scope; all four same-name Environment secret names remain under `release-signing`. Secret values were never read or recorded.
- [OC-REGRESSION] Ordinary final-head push CI run `32555515469` concluded success; `build-apk` passed and signed/release jobs were skipped by their existing event guards.
- [OC-MONITOR] Forced read-only monitor run `32555955041` concluded success at exact final head. Event gate, date gate, U1 fixture tests, and probe passed; probe log states `Probe state: no-change`; coverage/candidate/write/notify/recovery jobs were skipped or no-op, with no mutation.
- [OC-INVARIANTS] Final GitHub checks: default branch `patched`; `main=upstream/main=6aabea8965a45df9a126d0436404ae8afccfe96f`; `patched=f87d99d`; tag `v2.1.26.1=b187b6ff8d89525da30e2543ed77e8e55bc58b2c`; `update.json` blob `75e4a9c322e128a77927cf2dc9cef95a27291c4e`; existing Release assets unchanged; open PRs and canary refs absent; workflow permissions `read`, PR approval capability `true`.
- [OC-STATE] F1 execution evidence is complete and returned as `REVIEW_PENDING` for independent ChatGPT goal-level review. Automation Foundation is not marked `CLOSED`; U2 remains `BLOCKED`.

## 2026-08-22 — ChatGPT independent F1 stage closeout review

- [GPT-REVIEW] Independently verified current GitHub `patched=f87d99d46dbff8e68c5f2d53b602c1f58cd9d5d6`; fork `main=6aabea8965a45df9a126d0436404ae8afccfe96f`; no open PRs and no `automation/foundation-canary-*` refs.
- [GPT-REVIEW] Real positive-path canary evidence PASS: workflow run `32555459847` succeeded with `Contents: write` + `PullRequests: write`; PR #4 was created by `github-actions[bot]`, targeted the shadow patched ref, requested reviewer `slashinchi`, second reconcile reused the same PR, the PR workflow was observed as `action_required`, and cleanup removed the PR/shadow refs without changing real maintenance refs.
- [GPT-REVIEW] Environment-gated signed RC evidence PASS: run `32555524779` succeeded on exact `f87d99d`; downloaded identity artifact records signer `11eca31346835da4a0a5ab295647b14070f4c07533f08358679188941ae7d010`, APK SHA-256 `542bb7f39aef0be2edf4696dab921871a4decd1bdcc327661599ef2beabc67b4`, package `com.github.tvbox.osc`, versionCode `23601`, versionName `2.1.26.1`, commit `f87d99d46dbff8e68c5f2d53b602c1f58cd9d5d6`. Job execution began only after the Environment approval wait and all signing/identity/cleanup steps passed.
- [GPT-REVIEW] Final ordinary CI run `32555515469` PASS (`build-apk` success; signed/release jobs skipped). Final force-check `32555955041` PASS; event/date/fixtures/probe passed and probe log explicitly states `Probe state: no-change`; candidate/write/notify paths were skipped/no-op.
- [GPT-REVIEW] Current invariants independently checked where connector-visible: tag `v2.1.26.1` compares identical to `b187b6ff8d89525da30e2543ed77e8e55bc58b2c`; `update.json` remains blob `75e4a9c322e128a77927cf2dc9cef95a27291c4e` with version `2.1.26.1`; no open PR/canary refs. GitHub connector does not expose repository/environment secret-list or Environment-policy read APIs, so the current secret-scope deletion/policy metadata remains supported by OC's recorded `gh` evidence plus the successful Environment-gated runtime, not by an independent connector settings read.
- [GPT-REVIEW] Closeout defect found: current repo `AGENTS.md` contains ChatGPT-only closeout and F1 security/canary rules, but omits two stable Protocol-v2 executor rules that the authorized plan explicitly required: repo/GitHub writes only under current `AUTHORIZED`, and material design/scope/permission mismatch => `NEEDS_REPLAN` rather than executor redesign.
- [GPT-DECISION] F1 core functional/security result is PASS, but overall Automation Foundation is **not CLOSED** yet. A minimal F1a Executor Contract Alignment batch is authorized; persistent GitHub diff must be AGENTS-only, followed by current-head ordinary CI + monitor force-check and invariant recheck. U2 remains BLOCKED.

## 2026-08-22 14:57 CST — F1a executor contract alignment completed

- [OC-PREFLIGHT] Reconciled the authorized F1a baseline: local/remote `patched=f87d99d` before the patch; `main=upstream/main=6aabea8965a45df9a126d0436404ae8afccfe96f`; no open PRs or foundation-canary refs; no unexpected tracked worktree changes.
- [OC-EXECUTION] Added two stable rules to root `AGENTS.md`: implementation writes require current GD HANDOFF=`AUTHORIZED`; material design/scope/permission mismatch returns `NEEDS_REPLAN`, and planned human gates return `REVIEW_PENDING / HUMAN_ACTION_REQUIRED`. Existing ChatGPT-only closeout semantics remain unchanged.
- [OC-BOUNDARY] Commit `9a124ee8b7883b8a8da606547d2b3bddb1e256cf` was pushed to `patched`; `f87d99d..9a124ee` changes exactly one file, `AGENTS.md`, with 2 insertions. No workflow, helper, app, build, Environment, secret, tag, Release, update, or U2 mutation occurred.
- [OC-REGRESSION] Ordinary push CI run `32558116597` passed on exact head `9a124ee`; `build-apk` passed and `build-signed-rc` / `publish-github-release` were skipped by existing event guards.
- [OC-MONITOR] Current-head force-check run `32558129690` passed event gate, date gate, U1 fixture tests, and probe; probe log states `Probe state: no-change`; coverage, candidate, write, notify and recovery paths were skipped or no-op.
- [OC-INVARIANTS] Final checks: `patched=9a124ee`; `main=upstream/main=6aabea8965a45df9a126d0436404ae8afccfe96f`; tag `v2.1.26.1=b187b6ff8d89525da30e2543ed77e8e55bc58b2c`; `update.json` blob unchanged; no open PRs or canary refs; release-signing Environment policy and secret names unchanged.
- [OC-STATE] F1a execution is complete and HANDOFF/ACTIVE-PLAN are returned to `REVIEW_PENDING`. Automation Foundation remains `CLOSEOUT HOLD` pending ChatGPT's independent review; U2 remains `BLOCKED`.

## 2026-08-22 15:09 CST — ChatGPT final Automation Foundation closeout review

- [GPT-REVIEW] F1a exact diff independently verified: `f87d99d46dbff8e68c5f2d53b602c1f58cd9d5d6..9a124ee8b7883b8a8da606547d2b3bddb1e256cf` is exactly one commit, one file (`AGENTS.md`), two insertions, with no workflow/helper/app/build/settings/signing/release change.
- [GPT-REVIEW] Final `AGENTS.md` independently verified to require current GD HANDOFF=`AUTHORIZED` before repo/GitHub implementation writes; DESIGNING/REVIEW_PENDING/NEEDS_REPLAN/CLOSED stop writes; material design/scope/permission mismatch returns `NEEDS_REPLAN`; planned human gates return `REVIEW_PENDING / HUMAN_ACTION_REQUIRED`; ChatGPT-only closeout semantics remain.
- [GPT-REVIEW] Final-head ordinary CI run `32558116597` independently verified on exact `9a124ee8b7883b8a8da606547d2b3bddb1e256cf`: workflow success, `build-apk` success, signed-RC and publish-release jobs skipped.
- [GPT-REVIEW] Final-head monitor run `32558129690` independently verified on exact `9a124ee8b7883b8a8da606547d2b3bddb1e256cf`: event/date/fixtures/probe PASS; probe log explicitly states `Probe state: no-change`; candidate/write/notify paths skipped/no-op.
- [GPT-REVIEW] Current invariants independently verified where connector-visible: `patched=9a124ee8b7883b8a8da606547d2b3bddb1e256cf`; fork `main=upstream/main=6aabea8965a45df9a126d0436404ae8afccfe96f`; tag `v2.1.26.1` is identical to `b187b6ff8d89525da30e2543ed77e8e55bc58b2c`; `update.json` remains blob `75e4a9c322e128a77927cf2dc9cef95a27291c4e`; no open PRs or `foundation-canary` refs.
- [GPT-REVIEW] Prior F1 core evidence remains valid because F1a changed only root governance text: real GITHUB_TOKEN candidate/reviewer/idempotency canary passed and cleaned; Environment-gated signed RC `32555524779` passed signer/package/version/commit identity; signing material migration evidence remains as previously recorded.
- [EVIDENCE-BOUNDARY] GitHub connector still cannot independently enumerate current repository/environment secret lists or Environment policy. Those configuration facts remain supported by OC's recorded authenticated `gh` evidence plus the successful Environment-gated runtime. This is explicit evidence-boundary residual risk, not a current blocker.
- [GPT-DECISION] **Automation Foundation FINAL CLOSED.** G1, F1 and F1a are closed; U1/U1a/U1b/U1c historical acceptance remains valid. Current mode returns to Maintenance with no active implementation authorization. U2 design/review may be assessed next by ChatGPT, but U2 implementation remains BLOCKED until a new decision-complete plan is written to GD and explicitly authorized.


## 2026-08-22 15:14 CST — ChatGPT U2 design / independent challenge review (read-only)

- [GPT-DESIGN-BASELINE] Automation Foundation remains FINAL CLOSED. Read-only baseline: `patched=9a124ee8b7883b8a8da606547d2b3bddb1e256cf`; fork/main=upstream/main=`6aabea8965a45df9a126d0436404ae8afccfe96f`; current fork version=`2.1.26.1/23601`; upstream baseline version=`2.1.26/236`; formal tag `v2.1.26.1` remains historical release tag.
- [GPT-DESIGN-FINDING] Current `publish-github-release` rebuilds `assembleRelease` after tag creation. That cannot guarantee the public APK is the exact RC artifact; U2 design therefore promotes the already-signed RC binary and removes the second build from the formal publish path.
- [GPT-DESIGN-FINDING] Current GitHub docs state repository `GITHUB_TOKEN` only creates approval-required PR workflows for opened/synchronize/reopened; other token-created events such as PR closed do not create runs. U2 therefore uses the human merge's push to `patched` and revalidates the associated merged PR/merge parents/provenance instead of relying on bot-PR `pull_request:closed`.
- [GPT-DESIGN-FINDING] Persistent fork `versionName/versionCode` edits can conflict with future upstream version bumps before U2 is reached. U2 design adds a narrow U1 version-line overlay rule: only literal versionName/versionCode conflict hunks may preserve patched values; every other conflict remains fail-closed. U2 reads the source version from the exact upstream SHA and later creates the deterministic fork version.
- [GPT-DESIGN-FINDING] Auto signed RC must not expose signing credentials to merged Gradle/build code. Proposed RC pipeline builds unsigned with no secrets, then signs in a separate `release-signing` Environment job that performs no repository checkout/Gradle execution. Existing required reviewer stays in U2a until the isolated signer is proven; reviewer removal is deferred to U2b after the old tag publish path is removed.
- [GPT-DESIGN-FINDING] Current build workflow concurrency cancels in-progress work for the same ref. U2 design isolates release orchestration in `u2-release.yml` with queued/non-canceling concurrency.
- [GPT-DESIGN-FINDING] Formal Release should be created as draft, exact RC APK/update manifest assets downloaded back and verified, then published. Successful formal `v*` tags are immutable; D-011 forward metadata recovery remains in force.
- [GPT-DESIGN] U2 implementation is intentionally staged: U2a = trust/provenance/version-overlay + exact-SHA reusable unsigned-build/isolated-signer RC; U2b = live release orchestrator + production Environment approval + exact-artifact promotion/recovery. ChatGPT review is required between batches.
- [GPT-DESIGN-ACCEPTANCE] U2b cannot close from fixtures alone. It requires a disposable production-shape canary: same helper provenance checks, automatic isolated RC, real `release-production` approval wait, draft-only `u2-canary-*` tag/Release asset promotion and verification, cleanup, and no mutation of formal `v*` tags/public Release/update metadata/main/patched content.
- [EXTERNAL-VERIFICATION] Official GitHub docs checked for GITHUB_TOKEN event recursion, reusable workflow same-commit behavior and Environment secrets, artifacts shared between jobs, deployment approvals, commit-associated PR API, release/draft/asset APIs, and queued concurrency. URLs are recorded in ACTIVE-PLAN.
- [BOUNDARY] This was design/read-only review only. No GitHub repo code/settings/Environment/secrets/merge policy/tag/Release/update metadata were changed. Proposed U2 decisions are not Accepted DECISIONS yet. HANDOFF remains non-AUTHORIZED; implementation stays BLOCKED pending user acceptance and a later ChatGPT-authored U2a execution contract.


## 2026-08-22 15:27 CST — ChatGPT U2 second challenge review refinement (read-only)

- [GPT-DESIGN-REFINEMENT] Rejected the first draft's plan to push the release-version prep commit directly onto real `patched` before production approval. That would expose an unreleased version on the maintenance branch after rejection and complicate a second upstream merge during a waiting approval. Revised design creates a deterministic disposable `automation/release-prep-<source-merge-sha>` commit/ref, builds/signs the exact RC from that SHA, and only after `release-production` approval + fresh CAS check fast-forwards real patched to the exact release SHA.
- [GPT-DESIGN-REFINEMENT] Added explicit stale/supersession semantics: if patched advances before approval, the old RC is never tagged/published; a later independently qualified U1 merge may supersede it only with proven ancestry, otherwise `NEEDS_REPLAN`. Formal `v*` refs remain non-disposable.
- [GPT-DESIGN-REFINEMENT] Hardened the signer boundary further: no repository checkout/Gradle/repository scripts; no third-party action while signing material exists; artifact transport uses concrete artifact IDs/digests and official pinned actions, with keystore removed before artifact upload. U2 RC artifacts use 90-day retention; GitHub approval wait has a 30-day ceiling.
- [GPT-DESIGN-REFINEMENT] Added GitHub immutable releases to U2b. Current GitHub docs recommend draft → attach all assets → publish; once an immutable release is published its associated tag/assets cannot be changed. U2 will pre-verify draft assets, publish, then verify immutable release/asset integrity. The setting applies only to future releases, so historical v2.1.26.1 is not retroactively changed.
- [GPT-DESIGN-BOUNDARY] No GitHub repository/settings/environment/tag/release mutation was performed. U2 remains DESIGNING / implementation BLOCKED; these remain proposed design choices until user acceptance.

- [GPT-DESIGN-REFINEMENT] Final acceptance challenge: U2a changes the real U1 candidate-preparation path, so unit fixtures + no-change force-check are insufficient. Added a required shadow U1-v2 version-bump canary that exercises the actual GITHUB_TOKEN PR/reviewer/idempotency/action-required/cleanup path while proving the narrow version overlay and provenance marker in production shape.
- [GPT-DESIGN-REFINEMENT] Reusable RC contract is explicit: called mode takes exact release/provenance/version inputs and verifies the deterministic prep ref; manual workflow_dispatch remains owner-only/current-patched and cannot become a generic sign-any-SHA endpoint.
- [GPT-DESIGN-REFINEMENT] Immutable-release public transition is not faked with a disposable published release because future immutable release tag names cannot be reused and public notifications are a needless side effect. U2b canary verifies the setting and full draft/asset/approval path; first real immutable publication is an explicit live-observation residual backed by historical M4 public-release evidence.


## 2026-08-22 15:46 CST — ChatGPT U2 second challenge review (read-only)

- [GPT-REVIEW] Re-read the persisted U2 design against current GitHub/Drive baseline. No GitHub repository/settings/Environment/tag/Release mutation was performed; U2 remains DESIGNING / implementation BLOCKED.
- [GPT-FINDING] Critical release-semantic bug found: classifying only the newest merge can lose an earlier unreleased runtime change. Example: runtime merge A waits for approval, docs-only merge B advances patched, A becomes stale, B would bypass. Revised design separates trigger provenance from **cumulative release debt** measured from the last verified formal app Release to the latest qualified merge.
- [GPT-FINDING] Canonical last-release baseline must reconcile `update.json`, published Release and tag before new version/debt planning; unresolved formal partial state blocks a new release intent.
- [GPT-FINDING] Production recovery had a self-inconsistent CAS gate: after approved prep→patched promotion, a later tag/draft failure would rerun with patched already at release_sha, not source_merge_sha. Revised state machine defines a promotion point-of-no-return and accepts exact release_sha/descendants on recovery after identity revalidation.
- [GPT-FINDING] Human rejection was only a one-run event. Revised design records a `human-blocked` debt fingerprint so later docs/control-plane merges cannot silently reissue the same rejected binary state.
- [GPT-FINDING] Stale prep refs were ambiguous version reservations. Revised version planner reconciles active/superseded prep refs and cleans disposable prep refs only after proven publication/supersession/abandonment.
- [GPT-FINDING] Conflict-hunk text matching for `app/build.gradle` version overlay is brittle. Revised U1 prerequisite uses a normalized three-way base/ours/theirs merge with only the uniquely parsed versionName/versionCode values neutralized; any remaining conflict fails closed.
- [GPT-FINDING] Current classifier orders generic `app/**` before Gradle extension logic, so `app/build.gradle` can be mislabeled runtime/high-risk. U2a scope corrects all Gradle/KTS files to build/release-sensitive.
- [GPT-FINDING] Current design's real manual RC test would not prove future reusable called-mode. U2a now requires a real temporary trusted caller → persisted `rc-pipeline.yml` prep-ref RC canary plus a separate D-007 manual wrapper regression.
- [GPT-SECURITY] RC architecture refined to a dedicated workflow_call-only `rc-pipeline.yml`; builder has no secrets/OIDC/attestation write. Isolated signer passes passwords through env-backed apksigner password sources, deletes key/password material before artifact/attestation actions, then emits a GitHub signed-RC attestation. Production must verify this attestation.
- [GPT-SECURITY] Production formal Release authority uses direct GitHub CLI/REST state reconciliation; third-party `softprops/action-gh-release` is removed from the irreversible path.
- [GPT-RECOVERY] A formal tag with expired/missing exact RC identity may not be 'recovered' by rebuilding a different APK under the same tag. This is now fail-closed. U2b canary must also inject and recover a partial draft-asset failure.
- [GPT-PLATFORM] Official GitHub docs reverified: local reusable workflows resolve from the caller's same commit; reusable jobs cannot elevate token permissions above caller; Environment approvals time out after 30 days; `queue: max` supports up to 100 pending runs but queue ordering is not trusted; immutable Releases protect tag/assets only after publication and recommend draft→assets→publish; immutable-release repository setting has admin REST endpoints; artifact attestations are available for public-repo build provenance.
- [GPT-GOVERNANCE] Planned AGENTS clarification: HANDOFF=AUTHORIZED gates agent/human implementation/recovery writes, not normal execution of an already-implemented-and-closed autonomous workflow. OC incident repair still requires a new authorized handoff.
- [GPT-STATE] ACTIVE-PLAN/HANDOFF updated with these revisions. No U2 implementation is authorized and no proposed U2 decision has been appended as Accepted.


## 2026-08-22 16:24 CST — ChatGPT U2 third challenge review (read-only)

- [GPT-REVIEW] Re-reviewed the persisted U2 design against the real long-term fork-maintenance goal; no GitHub repo/settings/Environment/tag/Release mutation was performed. U2 remains DESIGNING / implementation BLOCKED.
- [GPT-FINDING] Removing the old tag-triggered publisher would remove the only formal-release path for a future fork-local bugfix with no new upstream PR. Revised design adds a manual formal release intent restricted to actor `slashinchi` and the **current live patched HEAD only**, with no arbitrary SHA/tag/version input, reusing cumulative debt/RC/production approval.
- [GPT-FINDING] Manual local release cannot use current fork/main blindly because main may already be ahead of patched. Revised source-version rule derives the actually integrated upstream baseline from `merge-base(current_patched, fork/main)` and verifies that commit is on upstream-main history.
- [GPT-FINDING] Whole-workflow `queue:max` around a run that can wait 30 days for Environment approval creates head-of-line blocking: a newer merge cannot build the superseding RC until the old human gate finishes. Revised design removes global U2 concurrency; only short prep-ref and post-approval publish mutation jobs are serialized.
- [GPT-FINDING] Existing strict qualification bound PR head/tree but did not prove the **actual outer human merge tree** equals what the current trusted integration policy would produce against the push-before base. Revised design replays `prepare-candidate(upstream_sha, base=push_before)` read-only and requires replayed tree == actual source merge tree; candidate merge-parent structure is also checked.
- [GPT-SECURITY] Keeping attestation in the same secret-bearing signer job leaves job-wide OIDC/attestation permissions available during the signing window even if the attestation step runs later. Revised RC pipeline splits secret-only signer from a secret-free independent verifier/attestor; signer has no OIDC/attestation/repo write, verifier has no signing secrets and independently checks signer/package/version/SHA before attesting.
- [GPT-SECURITY] Production now independently verifies APK signer fingerprint/package/version/raw SHA plus signed-RC attestation; signer-produced identity text is not sole release authority. Signing tools are prepared before secret env mapping.
- [GPT-RECOVERY] Separate tag push then draft creation enlarged partial formal state. Revised fresh publish path uses GitHub Create Release with `draft:true` + exact `target_commitish=release_sha`, then verifies returned tag/draft identity before asset upload.
- [GPT-PLATFORM] Current GitHub REST docs state Create Release may require Workflows write when target commit modifies `.github/workflows/**` relative to default branch; GITHUB_TOKEN cannot gain that permission. Normal U2 creates draft immediately after CAS when default patched==release SHA. Missing-draft recovery after later workflow changes is explicit fail-closed/NEEDS_REPLAN, with no silent broader PAT.
- [GPT-RECOVERY] Pre-public formal draft/tag state is no longer treated as permanently irrecoverable. Autonomous retries never delete it, but an exact unpublished draft+tag may be explicitly abandoned together in a later ChatGPT-authorized recovery batch. Published immutable Release/tag remains non-movable/non-replaceable.
- [GPT-FINDING] D-011-style metadata repair can regress update.json after a newer Release has already published. Revised U2 reconciliation is monotonic to the newest verified published formal app Release; older metadata recovery becomes superseded/no-op.
- [GPT-FINDING] Repository-wide disabling of squash/rebase is not required for correctness and unnecessarily changes all PR behavior. It is downgraded to an optional operator guard; automatic U2 still rejects non-merge-commit provenance, while manual current-patched release preserves a recovery path.
- [GPT-PLATFORM] Immutable-release setting must be re-read before every formal publication; enabling it once during U2b is insufficient if repo settings later drift.
- [GPT-STATE] ACTIVE-PLAN/HANDOFF updated to the third challenge-review design. Proposed U2 choices remain unaccepted DECISIONS; no U2 implementation is authorized.

- [GPT-FINDING] Existing U2 merge qualification still trusted PR-head provenance more than the actual human merge tree. Revised automatic path replays the trusted U1 candidate preparation against exact push-before + upstream SHA and requires replayed tree == actual source merge tree; candidate merge-parent structure is also verified.
- [GPT-FINDING] Manual-local formal release needs mode-aware RC/prep identity. Revised contract uses generic source SHA/mode/integrated-upstream identity and requires PR fields only in auto-upstream mode; manual mode never fabricates PR provenance.
- [GPT-REFLECTION] Earlier third-review idea to make squash/rebase disabling optional was rejected after deeper ancestry analysis. U1/D-001 depends on upstream commit ancestry in patched; an upstream squash/rebase can break monitor and integrated-upstream derivation. Merge-commit-only remains the proposed operator setting, while U2 independently rejects invalid merge methods.
- [GPT-FINDING] A whole U2 workflow concurrency group can hold the queue for the entire 30-day release-production approval wait. Revised design keeps long approval outside global concurrency and serializes only short prep/publish mutations.
- [GPT-SECURITY] Further signer split: signer has Environment secrets but no OIDC/attestations/repo write; secret-free verifier/attestor independently verifies signer fingerprint/package/version/SHA and only then gets minimal OIDC/attestation write. Production repeats the critical APK identity checks before public state.
- [GPT-RECOVERY] Fresh publish now prefers one Create Release(draft=true,target_commitish=release_sha) provider operation instead of separate formal tag push then draft creation, reducing tag-without-draft partial state. Current GitHub docs note historical-target release creation can require Workflows write unavailable to GITHUB_TOKEN when workflow files differ from default; such recovery is explicit fail-closed, not a reason to add PAT.
- [GPT-RECOVERY] Pre-public exact draft+tag is not automatically deleted, but may be explicitly abandoned together only in a later ChatGPT-authorized recovery if no published immutable Release exists. Published immutable state remains non-disposable.
- [GPT-FINDING] U2b activation itself needed a Handoff boundary. Revised staging adds U2c: U2b installs/canary-tests final orchestrator with TVBOX_U2_ENABLED=false and returns for ChatGPT review; U2c is settings-only cutover, verifies final state, removes release-signing reviewer, proves D-007 RC still works, then enables U2 last.
- [GPT-GOVERNANCE] Manual-local RC reporting no longer assumes a merged PR; auto mode comments PR, manual mode uses Actions summary + deduplicated U2 status Issue.

- [GPT-REFLECTION] Manual-local release cannot be advertised as a safe fallback for an upstream squash/rebase: D-001/U1 depends on upstream ancestry being present in patched. Repo merge-commit-only remains the proposed operator guard; invalid upstream merge ancestry is NEEDS_REPLAN.
- [GPT-FINDING] RC/prep interfaces still used mandatory PR/source-merge fields even after adding manual-local release. Revised identity is mode-aware around generic source SHA; PR is auto-upstream-only, and manual reporting uses job summary + U2 status Issue rather than fabricating a PR.
- [GPT-FINDING] U2b would otherwise both install a new autonomous production authority and make it live before ChatGPT independently reviewed the final disabled state. Revised staging adds TVBOX_U2_ENABLED=false through U2b plus a separate U2c settings-only activation; release-signing reviewer removal and enablement happen only there.
- [GPT-FINDING] Release-debt fingerprint based only on path+blob OID misses Git tree mode/type changes. Revised manifest hashes path + mode + object type + OID/DELETED so executable-bit, symlink and gitlink changes are visible.
- [GPT-SECURITY] `gh attestation verify --repo` alone is broader than desired for a reusable workflow. Revised production verification pins expected `rc-pipeline.yml` signer workflow (and signer/source digest where supported) and treats workflow-controlled predicate metadata as non-authoritative for project version/debt identity.
- [GPT-FINDING] Canonical latest Release selection was under-specified. Revised baseline enumerates verified formal Releases in patched ancestry, derives versionName/versionCode from tagged source, requires a unique monotonic latest, and reconciles update.json to it before new planning.
- [GPT-FINDING] Draft asset validation now requires exactly two public assets (versioned APK + update.json) with exact names/digests/bytes; unexpected extra assets block immutable publication.
- [GPT-STATE] Third challenge-review plan/handoff refined again; no GitHub implementation/settings changes, no Accepted U2 decisions, and no authorization to OC.

- [GPT-FINDING] Final policy-alignment check against live `merge_candidate()` found the design wording for version overlay was too narrow: an upstream version bump may conflict in `app/build.gradle` at the same time as `.github/workflows/**` or another already fork-owned path. Revised rule permits the normalized app-version overlay only when every other conflict is in the existing fork-owned auto-preserve set; any other non-owned conflict still fails closed. Acceptance fixtures now cover this composite case.
- [GPT-PLATFORM] Current GitHub Release docs/CLI rechecked draft/tag semantics: creating a Release for a missing tag with an explicit target automatically creates the associated tag, and immutable-release protections apply only after publication; draft releases and their associated tags remain mutable/deletable before publication. The design therefore may use exact-target draft creation without assuming immutability too early.

## 2026-08-22 16:43 CST — ChatGPT U2 fourth challenge review (read-only)

- [GPT-REVIEW] Confirmed design direction remains goal-first: optimize the real upstream/local maintenance → exact RC → explicit production decision → immutable Release → usable update delivery path, not workflow/code existence.
- [GPT-BLOCKER] Reusable-workflow attestation permission ceiling was incomplete. Current GitHub docs require both caller and reusable workflow to allow `id-token: write` + `attestations: write`; nested workflows cannot elevate above caller. Revised design grants that ceiling only on reusable-call jobs and narrows builder/signer effective job permissions, leaving OIDC/attestation only to the verifier/attestor.
- [GPT-IDENTITY] Attestation identity now separates `workflow_source_sha` from `artifact_source_sha=release_sha`. GitHub OIDC attests the reusable/caller workflow source, not an arbitrary prep commit; production verifies both identities instead of incorrectly pinning source digest to release_sha.
- [GPT-SECURITY] Found that an isolated signer could still modify/substitute APK payload and then sign it validly. Revised RC pipeline moves zipalign to the secret-free builder, emits an aligned-unsigned APK + canonical ZIP payload manifest, makes the signer perform only apksigner, and requires the secret-free verifier to independently prove unsigned/signed payload-manifest equivalence before attestation.
- [GPT-APPROVAL] GitHub environments allow administrator bypass by default. Revised design sets final `release-production` and `release-signing` protection to `can_admins_bypass=false` where applicable and makes publish require explicit current-run approval-history `approved` by `slashinchi`. Durable `human-blocked` state is created only from explicit review-history `rejected`; timeout/cancel/platform failure is not user rejection.
- [GPT-OPERATIONS] Added branch protection/ruleset/tag-rule activation/publication preflight. Current reviewed branch baseline is compatible; future drift fails closed and may not be “fixed” by silently adding a PAT or broader bypass permission.
- [GPT-DELIVERY] Immutable GitHub assets do not cover the configured external APK download proxy. Revised publish flow verifies the generated `apk_url` returns the exact signed RC before root update.json advances; failure leaves clients on the previous metadata and creates a forward-recovery delivery incident. Root update.json is read back after metadata commit.
- [GPT-PROVENANCE] Cumulative debt now reports qualified-upstream vs fork-local vs unknown release-relevant provenance. A merged `automation/upstream-*` integration that failed automatic merge/replay qualification blocks both auto and manual-local release; manual mode cannot launder squash/rebase ancestry damage.
- [GPT-HARDENING] Release-debt path plumbing is NUL/binary-safe; line-oriented untrusted Git filenames/control characters cannot alter fingerprints or workflow-command parsing.
- [GPT-ACTIVATION] U2c now includes a final enabled production `u2-release.yml` manual-current-patched empty-debt no-op smoke after `TVBOX_U2_ENABLED=true`; unexpected release debt blocks closeout rather than causing a release.
- [GPT-CANARY-BOUNDARY] GitHub docs state Create Release can trigger notifications. U2b target-repo draft canary remains never-published and promptly cleaned, but possible platform notification side effects are now explicit/accepted evidence rather than falsely claimed absent.
- [BOUNDARY] Read-only design review only. No GitHub code/settings/Environment/secret/tag/Release/update mutation. HANDOFF/ACTIVE-PLAN remain DESIGNING; proposed U2 decisions remain not Accepted.

- [GPT-REFINEMENT] Delivery-hold semantics were separated from release identity: a newer internally-valid published Release may be temporarily unadvertised because the configured proxy failed verification. That hold does not move cumulative debt baseline backward or permanently block a later urgent Release; a newer deliverable Release may advance root metadata directly and supersede earlier delivery holds.
- [GPT-OPERATIONS] Added a non-U1 local-debt watcher: ordinary local runtime/build pushes never auto-publish, but the enabled U2 read-only path opens/updates one `local-release-debt` Issue when unreleased app debt appears or changes. Docs/control-plane-only pushes remain silent; manual-local dispatch is still the first release-intent gate.
- [GPT-PERMISSIONS] Additional least-privilege correction: authenticated workflow review-history reads require Actions read, repository attestation reads require attestation read, and GitHub sets unspecified `permissions:` scopes to none. Production publish therefore explicitly receives only `contents:write + actions:read + attestations:read`, with no signing secrets, OIDC, or attestation-write scope.
- [GPT-SELF-REVIEW] Reconciled wording so `human-blocked` is created only from current-run `release-production` review history explicitly `rejected` by `slashinchi`; timeout/cancel/failure/no-review is not a business rejection. `release-production` creation, preflight and acceptance all now explicitly require admin bypass disabled.

- [GPT-PLATFORM] Final pre-write audit found the documented GitHub REST `Create or update an environment` schema does not expose an administrator-bypass write field. The design no longer asks OC to depend on an undocumented `can_admins_bypass` parameter. U2b now includes a planned user UI configuration gate to disable administrator bypass for both release environments; provider readback is recorded only if actually surfaced.
- [GPT-APPROVAL] Strengthened the second human gate beyond reviewer/state alone: the RC summary generates a full release/debt/version-bound approval marker, and production requires that exact marker in `release-production` review history from `slashinchi`. This remains authoritative even if environment bypass/settings later drift.
- [GPT-PERMISSIONS] Workflow-run review-history API requires Actions read for authenticated access, and repository attestation reads require attestation read. Production publish permission contract explicitly includes those read scopes in addition to contents write; all unspecified write scopes remain absent.
- [GPT-ARTIFACT] Payload-equivalence logic now rejects duplicate/malformed ZIP entries and does not allow pre-existing signature-style entries to be overwritten under the signing-metadata exception. Attestation verification pins reusable workflow identity and denies self-hosted runner provenance for the U2 v1 GitHub-hosted trust model.

- [GPT-NONBLOCKING-FIX] Final acceptance-placement audit found the canonical release-baseline / delivery-hold logic lives in the U2a trusted helper but its intentional metadata-lag fixture was only explicit in later U2b canary coverage. U2a deterministic fixtures now also cover: an internally-valid published Release held back from root update.json by a delivery-only hold, followed by a newer deliverable Release that advances metadata directly and supersedes the older hold. This keeps delivery-hold semantics verified at the layer where the baseline/debt decision is implemented.


## 2026-08-22 17:20 CST — ChatGPT U2 fifth challenge review: external best-practice / community comparison (read-only)

- [GPT-RESEARCH] Compared the current U2 design with current GitHub immutable-release, artifact-attestation, Secure Use and artifact-action guidance; Gradle wrapper/dependency security guidance; SLSA v1.2 build-isolation requirements; F-Droid Android reproducible-build guidance; current `actions/runner` release workflow; and current community artifact-transport issues. No GitHub repository/settings/Environment/tag/Release mutation was performed.
- [GPT-REPOSITORY-FINDING] Current `gradle/wrapper/gradle-wrapper.properties` uses Gradle 8.7 but has no `distributionSha256Sum`. Official Gradle 8.7 binary checksum is `544c35d6bd849ae8a5ed0bcea39ba677dc40f49df7d1835561582da2009b961d`; official 8.7 wrapper JAR checksum is `cb0da6751c2b753a16ac168bb354870ebb1e162e9083f116729cec9c781156b8`. U2a scope now pins/verifies both.
- [GPT-REPOSITORY-FINDING] Current root `build.gradle` contains `http://4thline.org/m2` with `allowInsecureProtocol true`; no obvious direct 4thline/cling dependency was found in current repository search. U2a must prove an exact clean/cache-free Release build succeeds without this repository and then remove it; if actually required, execution stops `NEEDS_REPLAN` for HTTPS/vendor replacement. Attestation is not treated as compensation for cleartext dependency transport.
- [GPT-BUILD-HARDENING] U2 Release builders now use explicit GitHub-hosted `ubuntu-24.04`, fresh per-job Gradle home/cache-disabled execution, exact build-tools 34.0.0, wrapper checksum verification, and a frozen JDK 17 patch/toolchain record. Current GitHub Ubuntu 24.04 images include Android platform/build-tools 34, so the Release trust path can remove `android-actions/setup-android`.
- [GPT-ACTIONS-HARDENING] GitHub Secure Use confirms full-length commit SHA is the only immutable Action reference. U2a now full-SHA pins all external Actions in fork-owned `patched` workflows and adds GitHub-Actions-only monthly/grouped Dependabot update PRs with no auto-merge. Repository-wide SHA enforcement is deliberately not selected because `main` is an exact upstream mirror and may contain upstream workflows using tags.
- [GPT-ARTIFACT-REVIEW] GitHub upload-artifact v7/download-artifact v8 provide immutable artifact IDs/digests and v7 direct single-file upload. A current open July-2026 GitHub issue (#811) reports download failures for artifacts uploaded from `ubuntu-latest` even with v7/v8 and older versions. U2 therefore keeps raw APK SHA-256 as canonical identity, uses pinned standard archive-mode artifact transport, and does not make new `archive:false` a production prerequisite.
- [GPT-ATTESTATION-REFINEMENT] `actions/attest@v4` supports default SLSA provenance and custom predicates. U2 now creates two attestations for the same signed APK: default GitHub provenance plus a repository-owned custom release-identity predicate binding release/source/debt/version/toolchain/artifact identities. Production verifies both and recomputes custom fields. The design explicitly avoids claiming SLSA Build L3.
- [GPT-PERMISSION-BOUNDARY] Current GitHub binary-attestation guide documents `contents:read + id-token:write + attestations:write`; the generic `actions/attest@v4` README also lists `artifact-metadata:write` for storage records/linked artifacts. Because this project attests a binary APK and does not push a registry artifact/storage record, U2 does not silently widen to `artifact-metadata:write`; the real pinned-v4 U2a canary must prove the minimal permission set or return `NEEDS_REPLAN`.
- [GPT-REPRODUCIBILITY] F-Droid/Gradle guidance supports reproducible output as a security best practice. U2a adds two independent clean/cache-disabled builds of the same release SHA. Byte identity is recorded when achieved; payload-manifest mismatch blocks closeout pending explanation/replan. A raw ZIP-level difference with identical canonical payload is recorded as bounded packaging nondeterminism rather than falsely called reproducible.
- [GPT-RELEASE-REFINEMENT] GitHub immutable-release guidance recommends draft→assets→publish; Create Release can create the associated tag from exact `target_commitish`. The existing U2 design is retained/refined: after CAS, assert default branch=`patched` and patched=`release_sha`, create the draft+tag via REST, verify tag/draft/assets, then publish. This also avoids the GITHUB_TOKEN workflow-write edge for a historical target that differs in `.github/workflows/**`.
- [GPT-DEFERRED] Full Gradle dependency verification/locking was reviewed but not made a U2-v1 hard gate. Current declared external versions are largely fixed and verification metadata is global/maintenance-heavy; forcing it now could turn normal upstream dependency updates into manual checksum maintenance. Residual remote dependency authenticity risk is explicit; a later supply-chain dependency-verification phase remains available. Cosign, SBOM attestation and an extra OpenSSF Scorecards workflow are likewise not added to the U2 core because they do not close a current goal-level gap proportionate to their new trust/maintenance surface.
- [GPT-STATE] HANDOFF/ACTIVE-PLAN updated with these findings. U2 remains DESIGNING / implementation BLOCKED; no proposed U2 decision has been appended as Accepted.


## 2026-08-22 20:01 CST — ChatGPT U2 sixth challenge review: mature-solution substitution / Android release practice (read-only)

- [GPT-RESEARCH] Continued external comparison specifically to reduce bespoke U2 logic rather than add layers. Reviewed current F-Droid reproducible-build/signature-copy practice, `apksigcopier`, Android `zipalign` + 16 KiB page-size guidance, Gradle repository content filtering, GitHub immutable Release/release-attestation guidance, current GitHub runner image contents, and Bitwarden Android's public GitHub Release workflow/Release pages.
- [GPT-REPOSITORY] Current fork `patched` remains `9a124ee8b7883b8a8da606547d2b3bddb1e256cf`; this review made no GitHub repository/settings/Environment/tag/Release mutation.
- [GPT-ANDROID-NATIVE] GitHub repository evidence confirms `quickjs/src/main/jniLibs/arm64-v8a/libquickjs-android-wrapper.so` is a committed native library. Android's current guidance says apps using native code need 16 KiB compatibility checks. Current GitHub `ubuntu-24.04` image (image version observed `20260816.277.1`) includes build-tools `34.0.0` and `35.0.0` plus NDK `28.2.13676358`, so U2 can split signer/checker tools without downloading a new SDK.
- [GPT-APK-EQUIVALENCE] F-Droid current reproducible-build documentation verifies developer-signed APKs by copying their v1/v2/v3 signature onto the independently built unsigned APK and requiring verification. `apksigcopier compare --unsigned` is purpose-built for this; Ubuntu Noble publishes exact `apksigcopier 1.1.1-1`. Revised U2 uses it as the primary signed-vs-unsigned equivalence gate and keeps the custom canonical payload manifest only for diagnostics/reproducibility. This removes a bespoke signing-difference allowlist from the security authority.
- [GPT-APK-TOOLING] Android official `zipalign` docs state AGP already aligns APKs and custom pipelines should verify rather than align again. Revised U2 preserves the exact AGP unsigned bytes, uses build-tools 35 `zipalign -c -P 16 -v 4` read-only, signs with build-tools 34 `apksigner` for apksigcopier/F-Droid compatibility, and statically checks packaged arm64 ELF LOAD alignment with the pinned NDK 28 toolchain. A failure is evidence for `NEEDS_REPLAN`; U2 does not mutate/repack the native binary to hide it.
- [GPT-DEPENDENCY-SOURCES] Gradle documents repository order/filtering as a reliability/security control. Revised GitHub Actions build policy removes Aliyun and cleartext fallback from the trusted candidate/Release path, keeps official Gradle Plugin Portal/Google/Maven Central, and limits HTTPS JitPack queries with a non-exclusive `com.github.*` filter. Local non-Actions Aliyun preference may remain for mainland development. Broad `exclusiveContent` was rejected because it would force source ownership for groups that can legitimately exist in official repositories and would make upstream maintenance more brittle.
- [GPT-DEPENDENCY-EVIDENCE] Strict Gradle dependency verification/locking remains deferred, but U2 now records and hashes a normalized `releaseRuntimeClasspath` report as diagnostic RC evidence. It is explicitly not treated as cryptographic authenticity and cannot override the trusted-repository/HTTPS gates.
- [GPT-RELEASE-TRACE] Current Bitwarden Android release workflow downloads artifacts from a prior Actions run and its public Release body exposes `Builds Source: <Actions run URL>`. U2 adopts the low-cost traceability pattern: every formal Release body gets a trusted `Build / Release Evidence` block containing RC run URL, source mode/PR/upstream identity, release SHA, debt fingerprint, APK SHA, signer and verification command. Bitwarden's unrelated Jira/Azure machinery is not adopted.
- [GPT-RELEASE-ATTESTATION] GitHub immutable Releases automatically generate a Release attestation. U2 keeps the two pre-publication artifact attestations (default provenance + custom release identity) but does not invent an additional custom post-publication format; after publish it uses `gh release verify` and `gh release verify-asset` against the provider-generated Release attestation.
- [GPT-TRADEOFF] StepSecurity/harden-runner, Cosign/KMS, SBOM, full dependency locks and other enterprise supply-chain layers were reconsidered and remain outside U2 v1 because they add trust/maintenance surface without closing a stronger current goal-level gap than the controls above.
- [GPT-STATE] ACTIVE-PLAN/HANDOFF updated as **U2 DESIGNING / sixth external solution review complete / implementation BLOCKED**. No U2 decision was appended to DECISIONS as Accepted; OC remains unauthorized.
- [SOURCES] External evidence used includes: F-Droid Reproducible Builds; F-Droid/fdroidserver apksigcopier implementation; `obfusk/apksigcopier` docs (upstream archived but algorithm still used by F-Droid); Ubuntu Noble `apksigcopier 1.1.1-1`; Android Developers `zipalign` and 16 KiB page-size guidance; Gradle repository-content filtering; GitHub immutable Releases/release integrity/artifact attestations; current `actions/runner-images` Ubuntu 24.04 tool inventory; and Bitwarden Android `github-release.yml` / public Releases.

## 2026-08-22 — U2 final counterexample review / design freeze / U2a authorization

- Scope of this entry is **design review and control-plane authorization only**. No GitHub repository implementation, branch, tag, Release, Environment, secret, or U2 setting was changed by ChatGPT in this review.
- Live baseline re-read before freeze: `patched=9a124ee8b7883b8a8da606547d2b3bddb1e256cf`; no open PR; no `automation/*` branch observed; Automation Foundation remains FINAL CLOSED.
- Current GitHub docs still support the key platform assumptions used by the plan: `GITHUB_TOKEN` bot-PR recursion exception only for opened/synchronize/reopened; reusable-workflow permissions cannot elevate above caller; environment review history returns reviewer/state/comment; unapproved environment jobs fail after 30 days; public Actions artifact/log retention is configurable up to 90 days; `queue:max` supports up to 100 pending; Create Release can require Workflows-write for a non-default historical workflow-changing target, which `GITHUB_TOKEN` cannot gain.
- Counterexample finding: the pre-freeze approval marker bound `release_sha/debt/version` but did **not** bind the signed APK bytes. This violated the real operator goal "the RC I approved is the binary that gets published." Fixed in design with `TVBOX_RELEASE_APPROVE_V2` including signed APK SHA-256 + workflow run/attempt; any regenerated/re-signed RC or new attempt requires fresh approval.
- Counterexample finding: automatic U2 ingress still lacked one live human-merge event proof. U2a now extends the real shadow bot-PR canary through a user-performed merge commit into a disposable shadow base and records the actual `push` actor/parents/associated-PR/`merged_by` semantics. Mismatch is `NEEDS_REPLAN`.
- Non-blocking hardening: RC retention must be explicitly 90 days and repository retention read back; signing cutover explicitly treats the isolated `rc-pipeline.yml` signer as the sole allowed `release-signing` Environment consumer; signer normalizes untrusted build artifacts into fixed validated inputs before secret mapping.
- Accepted residuals after this review: first real **public immutable** U2 Release remains a live observation; `apksigcopier` upstream is archived but current F-Droid practice/toolchain remains pinned and fail-closed; strict Maven dependency verification/locking, Cosign, SBOM and Scorecards remain deferred; GitHub/platform outages and external `gh.xxooo.cf` availability cannot be eliminated; post-U2c automatic signing necessarily trusts the reviewed fork-owned workflow control plane because GitHub Environment secrets cannot be restricted to one workflow.
- Result: no new architecture-level blocker remains after the fixes above. U2 design is frozen for U2a. U2a may now be `AUTHORIZED`; U2b/U2c remain blocked pending independent closeout of prior stages.

## 2026-08-22 — U2a implementation / trusted dependency boundary stop

- [OC-IMPLEMENTATION] With explicit user authorization, implemented and pushed U2a commits `0dedb2e04ee9d5f4ac1010e49044408eb705a575` and follow-up workflow-context fix `3263f2db0a90674d1f39c670e30a8bae67280487` to `patched`. Persistent changes include v2 U1 provenance/Gradle overlay, trusted `u2_release.py` helpers/tests, workflow-call-only `rc-pipeline.yml`, D-007 wrapper, action SHA pins, Dependabot, Gradle 8.7 checksums, and Actions-only HTTPS repository selection.
- [OC-LOCAL-VERIFICATION] Local deterministic suite passed `50/50`; Python compile passed; all three workflow YAML files passed Ruby YAML parsing; `git diff --check` passed. Local Gradle execution was unavailable because this macOS workspace has no Java runtime.
- [OC-REMOTE-BOUNDARY] Initial push run `32580581441` correctly failed closed during workflow parsing because reusable-workflow job-level `env` used unsupported `runner.temp`; this was corrected in `3263f2d` by using `$RUNNER_TEMP` inside Gradle shell steps.
- [OC-REMOTE-BOUNDARY] Follow-up push run `32580681941` parsed and executed the ordinary CI build on `ubuntu-24.04`; Gradle 8.7 distribution checksum validation/download passed, but `:app:dataBindingMergeDependencyArtifactsDebug` failed because `com.kingja.loadsir:loadsir:1.3.8`, `com.lzy.net:okgo:3.0.4`, `com.owen:tv-recyclerview:3.0.0`, and `com.hyman:flowlayout-lib:1.1.2` were not found in the authorized repository set.
- [OC-DEPENDENCY-EVIDENCE] Direct HTTPS probes returned `404` for all four coordinates in Maven Central, Google Maven, and JitPack; the same Aliyun public URLs returned `200`. This proves the trusted official/filtered-JitPack set cannot currently resolve the exact build. Per ACTIVE-PLAN and HANDOFF stop rules, Aliyun/HTTP fallback was not restored and no dependency was silently rewritten or vendored.
- [OC-INVARIANTS] After the push: `patched=3263f2db0a90674d1f39c670e30a8bae67280487`; `main=6aabea8965a45df9a126d0436404ae8afccfe96f` remains the upstream mirror; open PRs are empty; tag `v2.1.26.1` remains `b187b6ff8d89525da30e2543ed77e8e55bc58b2c`; `update.json` blob remains `75e4a9c322e128a77927cf2dc9cef95a27291c4e`; workflow default permissions remain `read` with PR approval capability enabled.
- [OC-STATE] U2a is `NEEDS_REPLAN` at the trusted dependency-resolution boundary. Real RC/signing canary was not started because it would repeat the proven blocked build; no formal tag, Release, update metadata, release-production, immutable-release setting, U2 enablement, or Environment reviewer change occurred.

## 2026-08-23 — U2a-R1 remote execution / native alignment stop

- [OC-PUSH] D-031/D-032 implementation was committed and pushed to `patched`: `3e807fa89c99b7c089f56e95236c4ec4ebf8b6a3`; clean-cache RC follow-up `e78ea40c18bef0e0cade1da32a1f8701a6d3d1ed`; identity-directory fix `b0350b883e246eb4309691179f3eee5bfab8bda0`. Current `patched`, local `HEAD` and `origin/patched` all equal `b0350b883e246eb4309691179f3eee5bfab8bda0`; `main/upstream/main` remain `6aabea8965a45df9a126d0436404ae8afccfe96f`.
- [OC-REMOTE-CI] Ordinary CI run `32612926364` PASS: pinned legacy staging, Gradle dependency resolution and debug APK build/upload succeeded.
- [OC-REMOTE-RC] Manual clean RC run `32613321587` first exposed a missing `build/` directory before identity evidence writes; `b0350b8` added `mkdir -p build`. Manual clean RC run `32613404910` then passed staging, identity, Gradle 8.7 Release, APK generation and build-tools 35 ZIP alignment.
- [OC-NATIVE-STOP] Run `32613404910` failed the accepted NDK 28 native ELF gate before signing: the first APK arm64 native path in lexical order, `lib/arm64-v8a/libavcodec.so`, has a `LOAD` segment alignment other than `0x4000` (16 KiB). The workflow stopped before unsigned bundle upload, signer, verifier and attestations.
- [OC-BOUNDARY] HANDOFF/D-032 explicitly treats QuickJS/native failure as `NEEDS_REPLAN`. OC did not weaken the 16 KiB gate, mutate/repack the APK, substitute a native artifact, access signing secrets, or change tags/Releases/update.json/Environment/U2 settings. Native remediation and any revised provenance/reproducibility contract require ChatGPT replan and authorization.


## 2026-08-23 — ChatGPT U2a-R1 closeout review / native checker counterexample / D-033 replan

- [GPT-STATE] Independently re-read latest GD and GitHub after OC stopped `NEEDS_REPLAN`. Current `patched=b0350b883e246eb4309691179f3eee5bfab8bda0`; fork `main=6aabea8965a45df9a126d0436404ae8afccfe96f` still matches upstream; open PR search is empty; root `update.json` remains historical `2.1.26.1` with blob `75e4a9c322e128a77927cf2dc9cef95a27291c4e`. U2a is **not CLOSED**.
- [GPT-SCOPE] Compare `3263f2d...→b0350b883e246eb4309691179f3eee5bfab8bda0` contains only D-031/D-032/control-plane files and tests; no app/native binary was changed. D-031/D-032 implementation is retained provisionally rather than reverted.
- [GPT-RUN] Ordinary CI `32612926364` passed. Clean manual RC `32613404910` passed exact legacy staging, identity preflight, Gradle 8.7 Release build, unsigned-APK creation and `zipalign -c -P 16 -v 4`; isolated signer and verifier/attestor jobs were skipped because the native step exited first. No signing secret was exposed in that run.
- [GPT-COUNTEREXAMPLE] The native gate used `awk '$1 == "LOAD" && $NF != "0x4000" ...'`, which incorrectly required LOAD alignment to equal 16 KiB. Current Android Developers guidance requires values **not less than `2**14`**. Therefore `libavcodec.so` at `0x10000` (64 KiB) is valid and OC's reported library diagnosis was a false positive caused by the checker. OC was still correct to stop rather than weaken the accepted gate itself.
- [GPT-APK-EVIDENCE] Downloaded the real ordinary-CI APK artifact from run `32612926364` (artifact `9486042700`, archive digest `sha256:517f65061de07ede8fdc487d9f0f4b5a7f188e8ccaf4a4966c0c7dc2899ba62d`) and parsed every `lib/arm64-v8a/*.so`. 11/14 libraries have minimum LOAD alignment `0x10000`. Exactly three have `0x1000`: `libconscrypt_jni.so`, `libquickjs-android-wrapper.so`, `librtmp-jni.so`. All 14 contain `GNU_RELRO`.
- [GPT-D031] Current Actions `build.gradle` resolves the legacy island only from `$TVBOX_LEGACY_REPO`; the committed D-031 manifest pins four POM/AAR pairs by SHA-256 and `legacy_staging.py` validates/stages them. Real CI proved the staging path. No new D-031 blocker found in this review.
- [GPT-D032] Current `rc-pipeline.yml` contains identity-v2, exact setup-java v5.7.0 SHA, exact Temurin `17.0.20+8` for builder and signer, canonical runtime-component hash and custom `actions/attest@v4` path. These later signer/verifier/attestation paths remain **implemented but not yet live-proven** because the native step stopped first.
- [GPT-ROOT-CAUSE] The three true 4 KiB libraries are runtime-compatibility debt, not one control-plane bug. `conscrypt-android:2.5.2` supplies Conscrypt; ExoPlayer 2.18.7 RTMP depends on `io.antmedia:rtmp-client:3.2.0`; the QuickJS module vendors a customized TVBox Java/JNI API plus the old prebuilt binary. Same-line TVBox forks inspected still carry the exact QuickJS blob `1654982bf7484030313cc718046e3ca2ff266f5b`. Modern Harlon wrapper 3.2.3 advertises 16 KiB support but its Java API differs, so a binary-only QuickJS swap is not acceptable.
- [GPT-PLATFORM] Current Android documentation (updated 2026-08-05) says Play's 16 KiB hard requirement applies to API-35+ targets starting 2027-02-01; 16 KiB-kernel devices currently offer a backcompat mode for 4 KiB ELF apps, but Google still recommends true 16 KiB alignment and warns future releases should not depend on recompilation-free compatibility. This fork is currently target 34/GitHub-distributed, so native debt is real but distinct from U2a release-control-plane qualification.
- [GPT-D033] Accepted D-033: fix the checker to `PT_LOAD p_align >= 0x4000`, scan/report all 64-bit libraries + GNU_RELRO, bind the canonical native report into identity-v2, and allow the U2a/D-007 RC canary to continue with the **explicitly attested** three-library debt. Insert separate **N1 Native 16 KiB Compatibility** after U2a and before U2b; N1 must remediate those libraries before U2b/U2c can be authorized. U2a may not claim native-16K/Play readiness.
- [GPT-AUTH] HANDOFF/ACTIVE-PLAN replanned to **U2a-R2 AUTHORIZED** from `b0350b883e246eb4309691179f3eee5bfab8bda0`. OC may only correct/attest native characterization and finish the already-authorized U2a canaries; it may not choose Conscrypt/RTMP/QuickJS replacements, enter N1/U2b/U2c, or mark CLOSED.

## 2026-08-23 — U2a-R2 native correction / planned signing approval gate

- [OC-PUSH] R2 native characterization commit `4598cd01e1c0d5109310f3b7db3b8b272d9c5a95` was committed and pushed to `patched`; local HEAD, origin/patched and the RC release SHA agree. `main/upstream/main` remain `6aabea8965a45df9a126d0436404ae8afccfe96f`.
- [OC-LOCAL-VERIFICATION] Local suite passed `67` tests, including native fixtures for `0x1000` fail, `0x4000`/`0x10000` pass, all 64-bit library path scanning, GNU_RELRO reporting, known-debt classification and unexpected-debt fail-closed; Python compile, 3 workflow YAML parses and `git diff --check` passed.
- [OC-REMOTE-RC] Manual RC run `32616876943` passed staging, identity qualification, corrected native report, Gradle 8.7 Release, APK generation, build-tools 35 ZIP alignment, unsigned transport upload and builder isolation. The report found 14 arm64 libraries: `libavcodec.so` minimum LOAD alignment `0x10000`; exactly three 4 KiB paths: `libconscrypt_jni.so`, `libquickjs-android-wrapper.so`, `librtmp-jni.so`; every current arm64 library has GNU_RELRO.
- [OC-HUMAN-GATE] Isolated signer job `97139343174` is `waiting` on Environment `release-signing`; pending deployment API reports `wait_timer=0` and `current_user_can_approve=true`. No signer step, signing secret or attestation step has run. This is `REVIEW_PENDING / HUMAN_ACTION_REQUIRED`, not N1 authorization.
- [OC-STATE] U2a-R2 is paused at the planned `release-signing` approval. After human approval, OC may resume the same R2 run's verifier/default-attestation/identity-v2 evidence and remaining U2a gates; N1/U2b/U2c remain blocked.

## 2026-08-23 — U2a-R2 signer transport-layout failure / replan stop

- [OC-HUMAN-GATE] User approved the `release-signing` Environment for RC run `32616876943`; pending signer job `97139343174` began and the approval was accepted.
- [OC-REMOTE-FAILURE] Builder job `97138944584` remained PASS. Signer failed at `Validate transport bundle before secret window` before `Capture signer JDK identity` and before the only secret-bearing signing step. Verifier/attestation job `97147283429` was skipped.
- [OC-ROOT-CAUSE] Builder upload used multiple paths. `actions/download-artifact` reconstructed a common-root layout with `build/release-identity.*`, `build/unsigned/*` and `gradle/*`; signer validation expected `unsigned.apk`, `release-identity.*` and `release-fields.env` directly under `$RUNNER_TEMP/unsigned`. The downloaded artifact inspection confirmed this exact layout. This is a signer transport-contract defect, not a secret or native compatibility failure.
- [OC-SAFETY] No signing secret was used, no signed APK or attestation was produced, and no formal tag/Release/update metadata/Environment configuration was changed. The attempted local flat-transport fix was not committed or pushed and was reverted after re-reading the `REVIEW_PENDING` write boundary.
- [OC-STATE] Current U2a-R2 state is `NEEDS_REPLAN`. A new authorized batch must choose and test the artifact normalization contract before any RC retry; N1/U2b/U2c remain blocked.

## 2026-08-23 — ChatGPT U2a-R2 adversarial review / D-034 transport and privilege replan

- [GPT-STATE] Independently re-read latest GD/GitHub after OC stopped `NEEDS_REPLAN`. Current `patched=4598cd01e1c0d5109310f3b7db3b8b272d9c5a95`; parent=`b0350b883e246eb4309691179f3eee5bfab8bda0`; `main=6aabea8965a45df9a126d0436404ae8afccfe96f`. R2 diff is one commit and four files only: `rc-pipeline.yml`, `native_compat.py`, its tests and U2 contract tests. No runtime app code was changed.
- [GPT-RUN] Independently fetched RC run `32616876943`. Builder job `97138944584` PASS. Signer job `97139343174` FAIL at `Validate transport bundle before secret window`; verifier/attestation job skipped. Signer effective token had `actions:read` only; failure occurred before the secret-bearing signing step.
- [GPT-ARTIFACT] Downloaded actual unsigned artifact `9487241812` and inspected its ZIP. Exact paths were `build/unsigned/{unsigned.apk,payload-manifest.json,native-compat.json,releaseRuntimeClasspath.txt,releaseRuntimeClasspath.json}`, `build/{release-identity.txt,release-identity.json,release-source.txt,release-fields.env}`, and `gradle/legacy-dependencies.lock.json`. This independently proves the producer/consumer layout mismatch. Transport archive digest was `sha256:83413233c71a07117844a4098bee2175eb4f8c500689ccfa8eddf81e8f1e6eae`; builder raw APK SHA was `b9c130d1ddd734f0d038b79e0c3fe7ba34d12632577e44a0a7705f47220f8fa7`.
- [GPT-P0-TRANSPORT] A path-only signer fix is insufficient. Current builder uploads heterogeneous workspace paths, while both signer and verifier assume a flat root. Official `actions/upload-artifact` behavior uses the least common ancestor of multiple paths as artifact root; the layout must therefore be an explicit project contract, not inferred from Action behavior. D-034 requires a single staged directory and literal exact allowlists for every cross-job artifact.
- [GPT-P0-EXEC-CLOSURE] Current verifier contains `python3 scripts/native_compat.py ...` but has no `actions/checkout`. On a fresh hosted runner the helper is absent, so after fixing transport layout this would be a deterministic next failure. Existing 67 tests did not validate job executable closure. D-034 requires every project helper execution to occur only in a job with exact trusted checkout and adds semantic tests for this property.
- [GPT-P0-SIGN-BINDING] Current signer reads `unsigned_sha256` from builder text and compares that declaration to the builder output, but does **not** `sha256sum` the actual downloaded `unsigned.apk` before the secret-bearing step. A later verifier might detect a mismatch only after the permanent key had signed the wrong bytes. D-034 requires actual downloaded APK hash equality before secrets.
- [GPT-P0-INPUT-SET] Current signer checks a required subset plus symlink absence, not an exact artifact file set. D-034 requires missing/extra/nested/symlink/non-regular entries to fail, then emits a sanitized sign-input of exactly `unsigned.apk` + canonical JSON.
- [GPT-P1-PREFLIGHT] R2 consumed a human Environment approval before discovering a deterministic transport defect. D-034 inserts a secret-free/no-OIDC/no-Environment `prepare_sign_input` job; user approval is requested only after this preflight validates real bytes and identity.
- [GPT-P1-PRIVILEGE] Current combined verifier has `id-token:write` + `attestations:write` while also running `apt-get` and (once fixed) reviewed repo helper code. D-034 splits a no-OIDC verifier from a minimal attestor so package-manager/repo execution never shares the attestation signing capability.
- [GPT-P1-NATIVE-TRANSITION] Current verifier hardcodes `known-debt`, count 3 and exact paths. `native_compat.py` itself permits a clean state, but the verifier would fail after N1. D-034 allows only the exact current D-033 debt tuple or `clean/0/[]`; every third state remains fail closed. N1 still blocks U2b/U2c.
- [GPT-P1-IDENTITY] Current cross-job logic treats JSON, text and env evidence as overlapping authorities. D-034 makes `release-identity.json` canonical; text/env are diagnostic only. Sign-input is sanitized to exactly the unsigned APK + canonical JSON.
- [GPT-ACTION-RUNTIME] Current `build.yml` still uses `android-actions/setup-android@9fc6c4... # v3` and `gradle/actions/setup-gradle@0b6dd65... # v4`; direct action.yml inspection shows both pins are Node20. GitHub's Node20 deprecation guidance says Actions are moving to Node24 and users should update. setup-android v4.0.1 is Node24; D-034 pins exact SHA `40fd30fb8d7440372e1316f5d1809ec01dcd3699` and preserves the old v3 cmdline-tools build `12266719`. gradle/actions v5.0.2 is Node24 at exact SHA `0723195856401067f7a2779048b490ace7a47d7c`; v6 is deliberately avoided because it adds separate caching distribution/license terms.
- [GPT-ATTEST] Current custom `actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6` is actually immutable **v4.2.2**, the current release at review time. The stale component is the separate default `attest-build-provenance@v2`. Current GitHub guidance says new provenance implementations should use `actions/attest`; D-034 reuses the already-pinned v4.2.2 for both default provenance and custom identity, with no storage record and no `artifact-metadata:write` expansion.
- [GPT-APKSIGCOPIER] `apksigcopier` 1.1.1 upstream is archived, but its documented `compare --unsigned signed.apk unsigned.apk` behavior still matches the intended equivalence gate. Record as a maintenance residual and confine it to the no-OIDC verifier; it is not a U2a blocker by itself.
- [GPT-TEST-GAP] New semantic tests are required for producer/consumer exact schemas, actual APK hash before secrets, helper/checkout closure, no repo/package execution in OIDC attestor, privilege separation, and native `known-debt`/`clean` transition. String-presence tests alone are insufficient closeout evidence.
- [GPT-CROSS-EVAL-LIMIT] User requested executor-pro subagent and agy CLI / Gemini 3.7 Flash High cross-review. This ChatGPT session exposes neither an executor-pro/subagent tool nor an agy/Gemini connector; Plugin Management search for Gemini/agy returned no available plugin. No cross-model result is fabricated. This review instead used live GD, GitHub API/logs, the actual downloaded Actions artifact and current official Action documentation.
- [GPT-D034] Accepted D-034 and rewrote HANDOFF/ACTIVE-PLAN to **U2a-R3 AUTHORIZED**. Scope is explicit flat artifact contracts, secret-free signer preflight, actual unsigned hash before secrets, no-OIDC verifier, minimal OIDC attestor, native clean/debt transition support, semantic workflow tests and the narrow Node24 Action refresh. N1/U2b/U2c remain blocked; no formal release side effects are authorized.

## 2026-08-23 — ChatGPT second simplification review / D-035

- [GPT-STATE] Re-read Protocol v2, current HANDOFF/ACTIVE-PLAN/D-034 and exact GitHub workflow at `4598cd01e1c0d5109310f3b7db3b8b272d9c5a95` before another OC execution.
- [GPT-FINDING] Protocol v2 says HANDOFF should be short (about 1–2 screens) and ACTIVE-PLAN is a current living plan. Current HANDOFF had grown to ~8.4KB and ACTIVE-PLAN to ~126KB with obsolete acceptance text still present.
- [GPT-CONTRADICTION] ACTIVE-PLAN still contained old U2a wording requiring every packaged arm64 native library to pass 16 KiB alignment and saying the verifier emits attestations, while D-033 allows the exact current three-library debt as U2a evidence and D-034 splits verifier from attestor. This is control-plane drift, not execution evidence.
- [GPT-CONCURRENCY] Exact current `build.yml` has workflow-level `group: android-build-${{ github.ref }}` + `cancel-in-progress:true`. Because D-007 manual RC also uses `build.yml` on `patched`, a later run on the same ref can cancel a waiting/running manual RC. D-035 requires cancellation to be ordinary-CI-only.
- [GPT-SIMPLIFICATION] D-034 preflight duplicated builder semantic checks. D-035 reduces it to exact file-layout/hash/identity transport validation before approval; package/version/ZIP/native semantics remain builder/verifier responsibilities.
- [GPT-IDENTITY] D-034's “one release-identity authority” wording was too broad. D-035 uses immutable stage records: builder identity, signer result, then verifier-created final predicate; later stages never rewrite earlier evidence.
- [GPT-SEQUENCING] Unrelated setup-android/setup-gradle Node20 maintenance is removed from U2a-R3 and scheduled as M2 immediately after U2a and before N1. The U2a RC path itself does not use those Actions.
- [GPT-HUMAN-GATE] D-035 reorders work so disposable shadow human-merge and all reachable no-secret gates run before the `release-signing` approval. Builder + secret-free preflight must also pass before the approval request.
- [GPT-CONTROL-PLANE] HANDOFF and ACTIVE-PLAN were holistically rewritten to current-only D-035 execution state; historical design material remains in DECISIONS/FACTS. U2a-R3 remains AUTHORIZED; M2/N1/U2b/U2c remain BLOCKED.

## 2026-08-27 — U2a-R4 Batch 4 dual-builder reproducibility remote acceptance PASS

- [OC-BATCH4-CODE] Committed and pushed to `patched`: `a5eb307` (dual-builder gate + reproducibility.py + u2_build_evidence.sh), `fa742ff` (chmod a-w,u+w cleanup fix), `f93b4ba` (apksigner/zipalign version fields pinned to SDK dir versions), `f617358` (aapt2 version field pinned to 34.0.0). Local tests 88/88 PASS.
- [OC-REMOTE-ACCEPT] Remote run `33075279552` at HEAD `f617358` completed all jobs success: build_unsigned, build_repro, compare_reproducibility (status=equivalent, primary_unsigned_sha256=80ff0606...), prepare_sign_input, sign_exact (release-signing human approval accepted), verify_signed, attest_signed (build provenance + release identity v2 dual attestation).
- [OC-ROOT-CAUSE-SERIES] Three intermediate remote failures, each diagnosed by artifact/log inspection before fix: (1) staged helper root `chmod -R a-w` made post-build re-exec cleanup `rm -rf` fail; (2) apksigner `version` output `0.9` and `zipalign -h` error output did not satisfy verifier schema `contains("34.0.0")`/`contains("35.0.0")`; (3) aapt2 `--version` output `2.19-10229193` likewise failed `contains("34.0.0")`. All three fixed by pinning version fields to Android SDK build-tools directory versions and adding TDD regression assertions.
- [OC-EVIDENCE] Run artifacts: build-evidence (6 files), sign-input (2), signed-output (2), repro-comparison (1), attest-input (2). Artifact digests verified end-to-end; signer certificate fingerprint `11eca31346835da4a0a5ab295647b14070f4c07533f08358679188941ae7d010` matches EXPECTED_SIGNER_SHA256.
- [OC-STATE] Batch 4 code gate complete. Next: Batch 5 (rc-control-v1 ref/ruleset, release-signing Environment restriction + reviewer removal, legacy publisher disable) then Batch 6 (final control-ref dispatch). Formal tag/Release/update.json unchanged.
- [OC-BATCH5-CODE] Control-tag migration committed as `3b50bc81214f909151cee03959b77a67ffdc7034` on `patched` (feat: route RC signing through immutable rc-control-v1 tag workflow). New `.github/workflows/rc-control.yml`: workflow_dispatch-only, hard gate `github.ref == 'refs/tags/rc-control-v1' && github.actor == 'slashinchi'`, read-only `actions/github-script@v7.1.0` getCommit('heads/patched') + 40-hex validation, then `call_rc_pipeline` passes the locked SHA as both release_sha and source_sha via local reusable rc-pipeline (secrets: inherit). `build.yml` lost `build-signed-rc`, `publish-github-release`, the `v*` tag trigger, and `workflow_dispatch` (-8856 chars). TDD red-green with 2 new contract tests + re-pointed signing-env test; 89/89 Python tests PASS locally; ordinary CI `33082281193` build-apk PASS.
- [OC-BATCH5-POLICY] Authority transition executed fail-closed with before/after snapshots in repo `outputs/evidence/2026-08-27--u2a-batch5-policy/`: ruleset `tvbox-patched-r4-pr-checks` (id 21657690, branch target: PR required 1 approval + `build-apk` status check + restrict update/delete/force-push, admin-role bypass only); ruleset `tvbox-rc-control-v1-immutable` (id 21657722, tag target exactly `refs/tags/rc-control-v1`, update/delete/non_fast_forward denied, zero bypass actors); lightweight tag `rc-control-v1` -> `3b50bc8`; `release-signing` Environment deployment policy collapsed to the single tag rule (id 58404945), old `patched`+`v*` rules deleted, required reviewer removed via `reviewers: []`. No secret values were read or modified at any step.
- [OC-BATCH6-ACCEPT] Control dispatch run `33083690142` (event=workflow_dispatch, head_branch=rc-control-v1, head=3b50bc8) all jobs success. sign_exact window 14s with empty approvals API -> zero approval wait confirmed. Digest chain agrees: control tag commit = locked patched SHA = builder/workflow_source = 3b50bc8; dual builders produced identical unsigned.apk sha256=8669f377eaa9ae1d37c8200bc3180fd54c046aaccab647c2b143c4543e8b6919 (repro report status=equivalent, differences=[]); signed sha256=f7793e90993618b89878f628b901726ab75b664631440b29aaa34a4d96704d87; signer fingerprint 11eca31346835da4a0a5ab295647b14070f4c07533f08358679188941ae7d010 matches. Artifact contracts verified 6/6/2/2/2/1 by independent local download. `gh attestation verify` PASS on host for BOTH attestations (slsa provenance v1 + tvbox-release-identity/v2) with signer-workflow rc-pipeline.yml + source-digest 3b50bc8; certificate SAN now `rc-pipeline.yml@refs/tags/rc-control-v1`. JSON retained in `outputs/evidence/2026-08-27--u2a-batch6-control-dispatch/`.
- [OC-B4-B6-DIFF] B6 signed SHA differs from B4 (f7793e90 vs ca279650) by design: B4 built f617358, B6 built 3b50bc8; the only payload-manifest delta across 1423 entries is `META-INF/version-control-info.textproto` embedding the git commit. Runner images identical (20260823.283.1), runtime/legacy digests identical. Identity binding, not nondeterminism.
- [OC-CLOSEOUT] Batch 4 independent attestation verification closed earlier same day: artifact 9647770098 downloaded, signed.apk raw sha256=ca279650fbec4915ab6d1d5e8161365708f33700a2420bee70f8f6c5f658c1f4 matched attestation subject, both predicate types verified with signer-workflow+source-digest constraints (evidence in outputs/evidence/2026-08-27--u2a-batch4-attestation-verify/). Zero formal release side effects across the whole transition: no new v* tag, Releases unchanged (only v2.1.26.1), update.json untouched. U2a-R4 build/sign/verify/attest chain is end-to-end green from the immutable control tag; goal-level closeout pending independent review.
- [OC-RULESET-EXTRA] Hardening: additional tag ruleset `tvbox-rc-control-tag-naming-reserved` (id 21661426) reserves all future `refs/tags/rc-control-*` names (excluding the live `rc-control-v1`) with update+deletion denied and zero bypass actors, closing the recreate-under-new-name path. The primary `rc-control-v1` ruleset keeps update+deletion+non_fast_forward. Ruleset API lesson: for tag targets `update` covers deletion-style protection only alongside the explicit `deletion` rule type; `delete` is not a valid rule type name.
- [OC-KEYSTORE-BACKUP] User confirmed 2026-08-27 23:58 CST that an offline recoverable backup of the release keystore exists (certificate SHA-256 `11eca31346835da4a0a5ab295647b14070f4c07533f08358679188941ae7d010`); no further backup work this cycle. Secret values were never read, copied, exported, or moved during the U2a transition.
- [OC-U2A-CLOSED] U2a-R4 closed 2026-08-27 23:58 CST. Cross-review results: executor evidence pass (E1 refs/rulesets/env, E2 run 33083690142 jobs/artifacts/deployments, E3 Drive/docs/no-side-effects); Grok 4.6 xhigh VERDICT CLOSE; Gemini 3.1 Pro High VERDICT CLOSE (both judged keystore backup operational-only, not a technical blocker). Claude Opus 4.6 Thinking not completed: agy individual quota exhausted (reset ~2026-08-28 01:14 CST); user accepted closure on the two completed independent reviews plus full live evidence, waived the third model for this round. Technical acceptance all PASS, zero formal release side effects; HANDOFF/ACTIVE-PLAN set to CLOSED. U2a scope complete; no further code changes expected. Out-of-scope follow-ups if authorized later: U2b legacy release-path redesign, D-033 native 16 KiB debt, first formal v* release.

## 2026-08-28 — U2b AUTHORIZED (D-037): release orchestrator design approved and baseline aligned

- [OC-U2B-AUTHORIZED] User approved the U2b/U2c release orchestrator design on 2026-08-28 and instructed "落实执行：按刚才确认的注意点执行". Authorization decisions: (1) N1 native 16 KiB remediation is NOT the original goal — deferred to 2026-09-28 upstream observation; GitHub Releases may carry exact attested `known-debt/3` (no Play/API-35/16KiB claims); (2) no `rc-control-v2`; protected `patched` directly calls existing isolated `rc-pipeline.yml`; (3) signing never pauses; only one `release-production` approval before immutable publication; (4) no GitHub App, no watchdog-PAT broadening — new minimal fine-grained `TVBOX_RELEASE_TOKEN` (`Contents: read+write`, single repo) stored only in `release-production` with expiry variable; (5) `patched` ruleset (PR + build-apk, admin bypass only) makes `GITHUB_TOKEN` CAS fast-forward impossible, so post-approval promotion uses the release PAT; (6) immutable releases ON for future Releases, merge-commit-only, `release-signing` policy expanded to exact `patched` + `rc-control-v1`.
- [OC-DOCS] Wrote `docs/requirements/2026-08-28--u2-release-orchestrator.md` (approved spec) and `docs/plans/2026-08-28--u2b-release-orchestrator.md` (implementation plan). Backfilled D-033/D-034/D-035 full text in `tmp/drive-live-decisions.md` (were missing between D-032 and D-036) and appended D-037 (U2b/U2c authorization). Rewrote HANDOFF to AUTHORIZED and ACTIVE-PLAN to the U2b execution plan (Batches 0-6).
- [OC-BASELINE] Current `patched=6dc88bb` (docs-only), `rc-control-v1=3b50bc8`, formal Release only `v2.1.26.1`, immutable disabled, `release-production` absent, `release-signing` = `rc-control-v1` only. Rulesets 3 active. No secret values read.

## 2026-08-28 — U2b Batch 0-3: docs, helpers, disabled workflow, GitHub config

- [OC-B0-DOCS] Wrote `docs/requirements/2026-08-28--u2-release-orchestrator.md` (spec) + `docs/plans/2026-08-28--u2b-release-orchestrator.md` (plan). DECISIONS backfilled D-033/D-034/D-035 full text and appended D-037 (U2b/U2c authorization, N1 deferral to 2026-09-28, release PAT, release-signing expansion). HANDOFF=AUTHORIZED, ACTIVE-PLAN=U2b batches, FACTS appended. Drive upload + byte-equal readback PASS (4 docs).
- [OC-B1-HELPERS] `u2_release.py`: exact approval marker (build/parse/matches, binds version/release-SHA/debt/APK-SHA/run/attempt) + identity-bound `hold_covers_lag` (release tag/target/issue, not boolean). New `u2_publish.py`: `expected_asset_set`, `reconcile_draft_assets` (exact/incomplete/unexpected/digest-mismatch), `immutable_verified`, `monotonic_metadata_next`, `verify_delivery_url`. Tests: `test_u2_publish.py` (9) + `test_u2_release.py` additions (5). Whole-repo single `release-signing` consumer enumeration. 100/100 PASS locally.
- [OC-B2-WORKFLOW] New `.github/workflows/u2-release.yml`: TVBOX_U2_ENABLED gate (missing/not-true → early exit), auto/manual qualification, local rc-pipeline reuse, rc_summary, release-production approval job, publish job (exact marker + token), cleanup. **startup_failure root cause**: reusable caller job requires rc-control.yml-style job permissions (contents/actions/id-token/attestations) + all `with:` inputs (incl. empty strings); fixed. Full workflow success with disabled gate (jobs correctly skipped).
- [OC-B3-CONFIG] Snapshot to `outputs/evidence/2026-08-28--u2b-policy-before/`. Created `release-production` (reviewer slashinchi, prevent_self_review=false, branch policy=patched, var TVBOX_RELEASE_TOKEN_EXPIRES_ON=2027-02-24). Enabled immutable releases (PUT no-body; enabled=true). Merge-commit-only (allow_merge_commit=true, squash/rebase=false). `release-signing` deployment policy = patched(branch) + rc-control-v1(tag). Readbacks all PASS. No secret values read.
- [OC-HUMAN-GATES] Pending: user creates fine-grained PAT (Contents read+write, repo TVBoxOS-Mobile) → `release-production/TVBOX_RELEASE_TOKEN`; user toggles OFF `Allow administrators to bypass` on release-production UI (can_admins_bypass=true→false, no supported REST write).

## 2026-08-28 — U2b Batch 4-5: GitHub config + draft-only canary PASS

- [OC-B4-CONFIG] release-production created (reviewer slashinchi, prevent_self_review=false, branch policy=patched, TVBOX_RELEASE_TOKEN secret user-filled, TVBOX_RELEASE_TOKEN_EXPIRES_ON=2027-02-24). Immutable releases enabled (PUT no-body, readback enabled=true). Merge-commit-only (allow_merge_commit=true, squash/rebase=false). release-signing deployment policy = patched(branch)+rc-control-v1(tag). User toggled OFF admin bypass (can_admins_bypass=false readback). Snapshots in outputs/evidence/2026-08-28--u2b-policy-before/.
- [OC-B5-CANARY] workflow_dispatch canary_mode=true path: first run failed (empty expected_version) → fixed qualify to parse app/build.gradle; second run 33260658260 all green (dual builder, compare, sign 14s window, verify, attest). User approved release-production once (approvals API slashinchi/approved). Draft u2-canary-33260658260 created (target=a593e4b=patched HEAD; asset signed.apk sha256=5972784076939de2dd7b1f4738e7df3ca26ff751f124f883cb30959daefbd398 == downloaded artifact digest; attestation SAN rc-pipeline.yml@refs/heads/patched SLSA v1 PASS). Production publish correctly skipped (canary mode). Disabled path verified: non-canary dispatch → gate enabled=false → all skipped, zero side effects. Cleanup: draft deleted, no canary tag/ref residue, formal release still v2.1.26.1, update.json blob unchanged (75e4a9c3).
- [OC-B5-EVIDENCE] outputs/evidence/2026-08-28--u2b-canary/ retains downloaded signed APK + digest verification record.

## 2026-08-29 — U2b Batch 6: cross-review fixes + canary re-verification PASS

- [OC-B6-REVIEW] Grok 4.6 xhigh + Gemini 3.1 Pro high independent adversarial review of U2b canary stage. Both confirmed P0/P1: (P0-1) qualify had no real debt computation / no no-op exit — flag=true would real-sign; (P0-2) canary_mode bypassed TVBOX_U2_ENABLED; (P1-1) approval was click not marker; (P1-2) canary not production shadow (no attempt/asset contract/concurrency/stale-RC); (P1-3) post_promotion_state killed recoverable states. Main thread: NEEDS_REPLAN → user chose "修复后继续" (fix and continue).
- [OC-B6-FIXES] c32b27e + 6985f1f: (P0-1) gradle/verified-releases.json + scripts/u2_qualify.sh (real cumulative debt via release-debt CLI, docs-only→NOOP, build_rc gated on qualified); (P0-2) canary + manual dispatch both gated on TVBOX_U2_ENABLED; (P1-1) publish reads approvals API comment + approval-matches CLI exact marker check; (P1-2) canary tag includes attempt, asset named TVBox-Mobile-v<version>.apk, mode=manual-local for rc-pipeline; (P1-3) draft-recovery-continue/draft-stale states; (P1-4) write-workflow test enumerates gh release. 101/101 tests PASS.
- [OC-B6-CANARY2] Re-verified canary run 33281873549 (TVBOX_U2_ENABLED temp true → restored false after): all jobs success; one user approval; draft u2-canary-33281873549-attempt1 (target=6985f1f=patched HEAD; asset TVBox-Mobile-v2.1.26.1.apk digest 43ae6817... == downloaded artifact SHA — exact bytes, no rebuild; attestation verify PASS); production publish skipped (canary mode). Cleanup: zero draft/tag residue, formal release still v2.1.26.1, update.json unchanged (blob 75e4a9c3), TVBOX_U2_ENABLED=false. Evidence: outputs/evidence/2026-08-28--u2b-canary/run2/.
