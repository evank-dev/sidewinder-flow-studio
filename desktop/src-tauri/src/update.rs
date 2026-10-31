//! Updates: on launch, ask GitHub Releases whether a newer version exists.
//!
//! The endpoint (tauri.conf.json → plugins.updater) is the `latest.json` of the
//! latest *published* release, so drafts are never offered. Every package is
//! verified against the public key in tauri.conf.json before it is installed;
//! the private key lives only in CI secrets (see desktop/README.md).
//!
//! If an update exists the user is asked; on yes it is downloaded, the backend
//! is stopped (Windows can't replace files in use), the update is installed and
//! the app restarts. Failures are logged, never shown: a missing network must
//! not get in the way of opening the app.

use std::fs::OpenOptions;
use std::io::Write;

use tauri::AppHandle;
use tauri::Manager;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_updater::UpdaterExt;

/// Whether this build should check: release builds only, not a deb/rpm install
/// on Linux (the package manager owns those files; only the AppImage updates
/// itself), and not when SFS_NO_UPDATE_CHECK is set.
pub fn enabled() -> bool {
    if cfg!(debug_assertions) || std::env::var_os("SFS_NO_UPDATE_CHECK").is_some() {
        return false;
    }
    if cfg!(target_os = "linux") && std::env::var_os("APPIMAGE").is_none() {
        return false;
    }
    true
}

fn log(app: &AppHandle, message: &str) {
    if let Ok(dir) = app.path().app_data_dir() {
        if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(dir.join("logs").join("update.log")) {
            let _ = writeln!(f, "{message}");
        }
    }
}

pub fn check_in_background(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        if let Err(e) = check(&app).await {
            log(&app, &format!("update check failed: {e}"));
        }
    });
}

async fn check(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let Some(update) = app.updater()?.check().await? else {
        log(app, "up to date");
        return Ok(());
    };
    log(app, &format!("update available: {} -> {}", update.current_version, update.version));

    // SFS_AUTO_UPDATE=1 installs without asking (managed machines, and tests).
    let yes = std::env::var("SFS_AUTO_UPDATE").as_deref() == Ok("1") || {
        let message = format!(
            "Sidewinder Flow Studio {} is available (you have {}).\n\n{}\n\nYour projects and settings are kept.",
            update.version, update.current_version, update.body.as_deref().unwrap_or("").trim());
        let dialog = app.dialog().clone();
        tauri::async_runtime::spawn_blocking(move || {
            dialog
                .message(message)
                .title("Update available")
                .kind(MessageDialogKind::Info)
                .buttons(MessageDialogButtons::OkCancelCustom("Install and restart".into(), "Later".into()))
                .blocking_show()
        })
        .await
        .unwrap_or(false)
    };
    if !yes {
        log(app, "update postponed");
        return Ok(());
    }

    let bytes = update.download(|_, _| {}, || {}).await?;
    log(app, "downloaded; installing");
    crate::stop_backend(app);
    update.install(bytes)?;         // on Windows this hands over to the installer and exits
    log(app, "installed; restarting");
    #[cfg(target_os = "linux")]
    forget_appimage_mount();
    app.restart();
}

/// An AppImage runs from a temporary mount ($APPDIR) and prepends it to
/// LD_LIBRARY_PATH, XDG_DATA_DIRS, PATH and others. The restarted app gets a
/// new mount, so drop the old one from what it inherits (environment, working
/// directory, open descriptors); otherwise the old mount stays alive and the
/// new app may load libraries from the old version.
#[cfg(target_os = "linux")]
fn forget_appimage_mount() {
    let Some(appdir) = std::env::var_os("APPDIR") else { return };
    let appdir = appdir.to_string_lossy().trim_end_matches('/').to_string();
    for (key, value) in std::env::vars() {
        if !value.contains(&appdir) {
            continue;
        }
        let kept: Vec<&str> = value
            .split(':')
            .filter(|p| !p.is_empty() && !p.starts_with(&appdir))
            .collect();
        if kept.is_empty() {
            std::env::remove_var(&key);
        } else {
            std::env::set_var(&key, kept.join(":"));
        }
    }
    // AppRun also changes into the mount; $APPIMAGE (the file) stays, since
    // restart() uses it to launch the new AppImage.
    if let Some(home) = std::env::var_os("HOME") {
        let _ = std::env::set_current_dir(home);
    }
    // The old AppImage runtime stays mounted while anyone holds the descriptors
    // it left open without close-on-exec (its keep-alive pipe, its mount
    // directory). The new app needs nothing inherited, so close all on exec.
    if let Ok(entries) = std::fs::read_dir("/proc/self/fd") {
        for entry in entries.flatten() {
            if let Ok(fd) = entry.file_name().to_string_lossy().parse::<i32>() {
                if fd > 2 {
                    // SAFETY: only sets a flag on a descriptor this process owns
                    unsafe { libc::fcntl(fd, libc::F_SETFD, libc::FD_CLOEXEC) };
                }
            }
        }
    }
}
