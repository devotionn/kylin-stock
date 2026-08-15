use serde::Serialize;
use std::{
    fs::{self, File},
    io::Read,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};
use tauri::{AppHandle, Manager};

const DATABASE_FILE: &str = "kylin-stock.db";
const SQLITE_HEADER: &[u8; 16] = b"SQLite format 3\0";

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BackupResult {
    pub file_size: u64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RestoreResult {
    pub safety_backup_path: Option<String>,
    pub safety_backup_size: Option<u64>,
}

fn timestamp_millis() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}

fn database_path(app: &AppHandle) -> Result<PathBuf, String> {
    let app_config = app
        .path()
        .app_config_dir()
        .map_err(|e| format!("无法获取应用数据目录：{e}"))?;
    fs::create_dir_all(&app_config).map_err(|e| format!("无法创建应用数据目录：{e}"))?;
    Ok(app_config.join(DATABASE_FILE))
}

fn sync_file(path: &Path) -> Result<(), String> {
    File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(|e| format!("无法将文件同步到磁盘：{e}"))
}

fn copy_and_sync(source: &Path, destination: &Path) -> Result<u64, String> {
    if let Some(parent) = destination.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("无法创建目标目录：{e}"))?;
    }
    let size = fs::copy(source, destination).map_err(|e| format!("复制数据库失败：{e}"))?;
    sync_file(destination)?;
    Ok(size)
}

fn validate_sqlite_file(path: &Path) -> Result<(), String> {
    let metadata = fs::metadata(path).map_err(|e| format!("无法读取备份文件：{e}"))?;
    if !metadata.is_file() || metadata.len() < 100 {
        return Err("所选文件不是有效的 SQLite 数据库备份".into());
    }

    let mut file = File::open(path).map_err(|e| format!("无法打开备份文件：{e}"))?;
    let mut header = [0_u8; 16];
    file.read_exact(&mut header)
        .map_err(|e| format!("无法读取备份文件头：{e}"))?;
    if &header != SQLITE_HEADER {
        return Err("所选文件不是有效的 SQLite 数据库文件".into());
    }
    Ok(())
}

#[tauri::command]
pub fn create_database_backup(app: AppHandle, destination: String) -> Result<BackupResult, String> {
    let source = database_path(&app)?;
    if !source.exists() {
        return Err("当前业务数据库不存在，无法创建备份".into());
    }

    let destination = PathBuf::from(destination);
    if destination == source {
        return Err("备份文件不能覆盖正在使用的业务数据库".into());
    }

    let temp = destination.with_extension(format!("backup-{}.tmp", timestamp_millis()));
    if temp.exists() {
        fs::remove_file(&temp).map_err(|e| format!("无法清理临时备份文件：{e}"))?;
    }

    let size = copy_and_sync(&source, &temp)?;
    if destination.exists() {
        fs::remove_file(&destination).map_err(|e| format!("无法覆盖已有备份文件：{e}"))?;
    }
    fs::rename(&temp, &destination).map_err(|e| format!("无法完成备份文件写入：{e}"))?;
    sync_file(&destination)?;

    Ok(BackupResult { file_size: size })
}

#[tauri::command]
pub fn restore_database_backup(app: AppHandle, source: String) -> Result<RestoreResult, String> {
    let source = PathBuf::from(source);
    validate_sqlite_file(&source)?;

    let target = database_path(&app)?;
    if source == target {
        return Err("不能从当前正在使用的数据库文件执行恢复".into());
    }

    let app_config = target
        .parent()
        .ok_or_else(|| "无法确定应用数据目录".to_string())?
        .to_path_buf();
    let safety_dir = app_config.join("backups");
    fs::create_dir_all(&safety_dir).map_err(|e| format!("无法创建恢复安全目录：{e}"))?;

    let (safety_backup_path, safety_backup_size) = if target.exists() {
        let safety = safety_dir.join(format!("pre-restore-{}.db", timestamp_millis()));
        let size = copy_and_sync(&target, &safety)?;
        (Some(safety), Some(size))
    } else {
        (None, None)
    };

    let temp = app_config.join("kylin-stock.restore.tmp");
    let old = app_config.join("kylin-stock.pre-swap.old");
    if temp.exists() {
        fs::remove_file(&temp).map_err(|e| format!("无法清理恢复临时文件：{e}"))?;
    }
    if old.exists() {
        fs::remove_file(&old).map_err(|e| format!("无法清理旧恢复文件：{e}"))?;
    }

    copy_and_sync(&source, &temp)?;
    validate_sqlite_file(&temp)?;

    if target.exists() {
        fs::rename(&target, &old).map_err(|e| format!("无法准备当前数据库用于恢复：{e}"))?;
    }

    if let Err(error) = fs::rename(&temp, &target) {
        if old.exists() {
            let _ = fs::rename(&old, &target);
        }
        return Err(format!("无法替换业务数据库：{error}"));
    }
    sync_file(&target)?;

    if old.exists() {
        let _ = fs::remove_file(&old);
    }
    for suffix in ["-wal", "-shm"] {
        let sidecar = PathBuf::from(format!("{}{}", target.display(), suffix));
        if sidecar.exists() {
            let _ = fs::remove_file(sidecar);
        }
    }

    Ok(RestoreResult {
        safety_backup_path: safety_backup_path.map(|path| path.to_string_lossy().into_owned()),
        safety_backup_size,
    })
}
