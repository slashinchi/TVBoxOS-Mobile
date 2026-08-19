# <p align="center"><img src="website/tvbox/images/logo.png" width="150" alt="TVBoxOS-Mobile logo" /><br>TVBoxOS-Mobile Maintenance Fork</p>

<p align="center">面向现代 Android 兼容性与可持续发布的长期维护 fork。</p>

<p align="center">
  <a href="https://github.com/slashinchi/TVBoxOS-Mobile/actions/workflows/build.yml?query=branch%3Apatched"><img src="https://github.com/slashinchi/TVBoxOS-Mobile/actions/workflows/build.yml/badge.svg?branch=patched" alt="Build patched" /></a>
  <a href="https://github.com/slashinchi/TVBoxOS-Mobile/releases/latest"><img src="https://img.shields.io/github/v/release/slashinchi/TVBoxOS-Mobile?display_name=tag&sort=semver" alt="Latest Release" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/slashinchi/TVBoxOS-Mobile" alt="AGPL-3.0 License" /></a>
</p>

本项目源自 [kukuqi666/TVBoxOS-Mobile](https://github.com/kukuqi666/TVBoxOS-Mobile)。这是一个独立维护的 fork，不代表上游项目，也不代表或背书任何第三方源、接口或继承资源。

## Why this fork

- 面向 Android 14 / targetSdk 34 的兼容性与行为修复
- 稳定的 fork signing identity 与可持续覆盖升级路径
- 动态 JAR / JS loader 兼容性维护
- PIP、后台播放与生命周期稳定性修复
- 可重复的 signed RC、Release 与 metadata 发布链

## Compatibility

- 构建安装下限：Android 7.0 / API 24；ABI：`arm64-v8a`。
- `compileSdk` / `targetSdk`：34。
- 已完成真机运行验证：OnePlus PHK110 / Android 14。
- API24/API33 代表设备 smoke 为 Deferred（D-010）；不宣称所有旧系统、设备、ROM 或后续 Android 版本均已实测。

## Download

请从 [GitHub Releases](https://github.com/slashinchi/TVBoxOS-Mobile/releases/latest) 查看和下载最新版本。README 不固定当前版本号或版本化 APK 下载地址。

## Migration notice

本 fork 保持相同的 `applicationId=com.github.tvbox.osc`，但使用不同的 signing key。已有 upstream-signed 安装不能直接覆盖安装 fork；迁移前请先使用应用自身备份功能并确认备份有效，再按 [迁移说明](docs/MIGRATION.md) 操作。

## Branch & maintenance model

```text
upstream/main
      ↓
fork/main       # upstream mirror / synchronization layer
      ↓ merge
fork/patched    # default branch / user-facing / maintained fork
```

- `patched` 是 GitHub 默认分支、日常开发和 Pull Request base，也是 fork Release 的来源分支。
- `main` 只同步上游，不承载 fork 专属 README、代码或 metadata。
- 上游同步固定走 `upstream/main → fork/main → merge fork/patched`；不要把 GitHub “Sync fork” 直接同步到 `patched` 作为常规维护方式。

## Upstream, credits & license

- 上游项目：[kukuqi666/TVBoxOS-Mobile](https://github.com/kukuqi666/TVBoxOS-Mobile)
- 本仓库依据 [GNU AGPL-3.0](LICENSE) 发布。
- 本 fork 继承的应用代码、源、接口和其他资源可能来自上游或第三方；其时效性、可用性和内容责任不由本 fork 额外保证。

## Disclaimer

本项目及其继承资源仅用于学习、测试和研究。请遵守适用法律、服务条款和相关开源许可证，不要将第三方内容用于未经授权的用途。使用者自行承担使用本项目及其资源产生的责任。
