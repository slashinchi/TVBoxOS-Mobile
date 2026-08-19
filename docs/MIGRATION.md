# Migration From Upstream-Signed TVBoxOS-Mobile

## Why migration is required

This fork keeps `applicationId=com.github.tvbox.osc` but uses its own stable signing key. An APK signed by the upstream project cannot be upgraded in place by an APK signed by this fork.

## Before migrating

1. Open the installed application and use its built-in backup function.
2. Confirm the backup completed and is readable before uninstalling the upstream-signed APK.
3. Keep the backup outside the application data directory until the fork installation and restore have been checked.

Do not put a backup, keystore, password, token, or other secret in this repository, ordinary Google Drive documents, or issue discussions.

## Verified environment

The migration and restore evidence in this project covers **OnePlus PHK110 running Android 14**. It is not a guarantee for every Android version, ROM, device, or storage policy.

## Install and restore

1. Uninstall the upstream-signed `com.github.tvbox.osc` application after confirming the backup.
2. Install the fork APK from the [latest GitHub Release](https://github.com/slashinchi/TVBoxOS-Mobile/releases/latest).
3. Confirm the package is `com.github.tvbox.osc` and the application starts normally.
4. Use the application's restore function and compare the restored state with the pre-migration baseline.

The verified restore set includes sources/subscriptions, favorites, history, and important settings. Recheck credentials, source availability, local files, and any device-specific permissions manually.

## Recovery

If the restore is incomplete, stop changing the original backup and restore it again after confirming the application has been cleared or reinstalled as appropriate. Keep the original backup until the fork has been used successfully for a while.
