import { invoke } from '@tauri-apps/api/core'
import { open, save } from '@tauri-apps/plugin-dialog'
import { checkDatabaseIntegrity, closeDatabase, getDatabase, reopenDatabase } from './database'

export type BackupType = 'MANUAL' | 'ANNUAL'

export interface BackupRecord {
  id: number
  file_name: string
  file_path: string
  backup_type: BackupType
  backup_year: number | null
  file_size: number | null
  created_at: string
  remark: string | null
}

interface NativeBackupResult {
  fileSize: number
}

interface NativeRestoreResult {
  safetyBackupPath: string | null
  safetyBackupSize: number | null
}

function stamp() {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${y}${m}${day}-${hh}${mm}`
}

function fileName(path: string) {
  return path.split(/[\\/]/).pop() || path
}

async function withDatabaseClosed<T>(operation: () => Promise<T>): Promise<T> {
  await closeDatabase()
  let operationError: unknown
  try {
    return await operation()
  } catch (error) {
    operationError = error
    throw error
  } finally {
    try {
      await reopenDatabase()
    } catch (reopenError) {
      if (operationError) {
        console.error('数据库操作失败后重新打开数据库也失败', reopenError)
      } else {
        throw new Error(`数据库文件操作完成，但重新打开数据库失败：${String(reopenError)}`)
      }
    }
  }
}

async function recordBackup(input: {
  path: string
  type: BackupType
  year?: number | null
  size?: number | null
  remark?: string
}) {
  const now = new Date().toISOString()
  await (await getDatabase()).execute(
    `INSERT INTO backup_records
      (file_name,file_path,backup_type,backup_year,file_size,checksum,created_at,remark)
      VALUES ($1,$2,$3,$4,$5,NULL,$6,$7)`,
    [
      fileName(input.path),
      input.path,
      input.type,
      input.year ?? null,
      input.size ?? null,
      now,
      input.remark?.trim() || null,
    ],
  )
}

export async function listBackupRecords(): Promise<BackupRecord[]> {
  return (await getDatabase()).select<BackupRecord[]>(`
    SELECT id,file_name,file_path,backup_type,backup_year,file_size,created_at,remark
    FROM backup_records
    ORDER BY created_at DESC,id DESC
  `)
}

export async function createBackup(type: BackupType, year?: number) {
  if (type === 'ANNUAL' && (!year || year < 2000 || year > 2100)) {
    throw new Error('请选择正确的年度')
  }

  const defaultName = type === 'ANNUAL'
    ? `KylinStock_${year}年度备份_${stamp()}.db`
    : `KylinStock_即时备份_${stamp()}.db`

  const destination = await save({
    title: type === 'ANNUAL' ? '保存年度数据备份' : '保存数据备份',
    defaultPath: defaultName,
    filters: [{ name: 'KylinStock 数据库备份', extensions: ['db'] }],
  })
  if (!destination) return null

  const result = await withDatabaseClosed(() =>
    invoke<NativeBackupResult>('create_database_backup', { destination }),
  )

  await recordBackup({
    path: destination,
    type,
    year: type === 'ANNUAL' ? year : null,
    size: result.fileSize,
    remark: type === 'ANNUAL' ? `${year} 年度归档备份` : '用户手动创建的即时备份',
  })
  return destination
}

export async function chooseRestoreFile() {
  const selected = await open({
    title: '选择 KylinStock 备份文件',
    multiple: false,
    directory: false,
    filters: [{ name: 'KylinStock 数据库备份', extensions: ['db'] }],
  })
  return typeof selected === 'string' ? selected : null
}

export async function restoreBackup(source: string) {
  const result = await withDatabaseClosed(() =>
    invoke<NativeRestoreResult>('restore_database_backup', { source }),
  )

  const healthy = await checkDatabaseIntegrity()
  if (!healthy) {
    if (result.safetyBackupPath) {
      await withDatabaseClosed(() =>
        invoke<NativeRestoreResult>('restore_database_backup', { source: result.safetyBackupPath! }),
      )
    }
    throw new Error('所选备份未通过完整性检查，系统已尝试恢复到操作前的数据')
  }

  if (result.safetyBackupPath) {
    await recordBackup({
      path: result.safetyBackupPath,
      type: 'MANUAL',
      size: result.safetyBackupSize,
      remark: '执行数据恢复前自动创建的安全副本',
    })
  }

  return result
}
