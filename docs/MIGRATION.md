# 从上游签名版迁移到本 fork

## 为什么需要迁移

本 fork 保持 `applicationId=com.github.tvbox.osc`，但使用自己的稳定 signing key。上游项目签名的 APK 不能由本 fork 签名的 APK 直接覆盖升级。

## 迁移前

1. 打开已安装的应用，使用应用自身的备份功能。
2. 在卸载上游签名版 APK 前，确认备份已完成且可以读取。
3. 在安装和恢复检查完成前，将备份保存在应用数据目录之外。

不要把备份、keystore、密码、token 或其他敏感信息放入本仓库、普通 Google Drive 文档或 issue 讨论。

## 已验证环境与边界

本项目的迁移和恢复证据仅覆盖 **OnePlus PHK110 / Android 14**。这不构成对其他 Android 版本、ROM、设备或存储策略的保证。

## 安装与恢复

1. 确认备份有效后，卸载上游签名的 `com.github.tvbox.osc` 应用。
2. 从 [最新 GitHub Release](https://github.com/slashinchi/TVBoxOS-Mobile/releases/latest) 安装本 fork APK。
3. 确认包名仍为 `com.github.tvbox.osc`，并确认应用可以正常启动。
4. 使用应用的恢复功能，并与迁移前基线对照恢复状态。

已验证恢复项包括 sources/subscriptions、favorites、history 和重要 settings。请人工重新核对 credentials、源的可用性、本地文件以及设备特定权限。

## 恢复不完整时

如果恢复不完整，不要覆盖或丢弃原始备份；先确认应用已按需要清理或重新安装，再重新执行恢复。确认本 fork 已稳定使用一段时间并且数据完整前，始终保留原始备份。

---

# Migration From Upstream-Signed TVBoxOS-Mobile

## Why migration is required

This fork keeps `applicationId=com.github.tvbox.osc` but uses its own stable signing key. An APK signed by the upstream project cannot be upgraded in place by an APK signed by this fork.

## Before migrating

1. Open the installed application and use its built-in backup function.
2. Confirm the backup completed and is readable before uninstalling the upstream-signed APK.
3. Keep the backup outside the application data directory until the fork installation and restore checks are complete.

Do not put a backup, keystore, password, token, or other sensitive information in this repository, ordinary Google Drive documents, or issue discussions.

## Verified environment and boundary

The migration and restore evidence in this project covers **OnePlus PHK110 / Android 14** only. This is not a guarantee for other Android versions, ROMs, devices, or storage policies.

## Install and restore

1. After confirming the backup is valid, uninstall the upstream-signed `com.github.tvbox.osc` application.
2. Install the fork APK from the [latest GitHub Release](https://github.com/slashinchi/TVBoxOS-Mobile/releases/latest).
3. Confirm that the package remains `com.github.tvbox.osc` and that the application starts normally.
4. Use the application's restore function and compare the restored state with the pre-migration baseline.

The verified restore set includes sources/subscriptions, favorites, history, and important settings. Manually recheck credentials, source availability, local files, and device-specific permissions.

## If the restore is incomplete

If the restore is incomplete, do not overwrite or discard the original backup. First confirm that the application has been cleared or reinstalled as needed, then retry the restore. Keep the original backup until the fork has been used successfully for a while and the data has been confirmed intact.
