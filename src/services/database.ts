import { invoke } from '@tauri-apps/api/core'
import Database from '@tauri-apps/plugin-sql'

let database: Database | null = null
let initialization: Promise<Database> | null = null

export async function initializeDatabase() {
  if (database) return database
  if (initialization) return initialization

  initialization = (async () => {
    // Schema creation/upgrades run in Rust on one dedicated SQLite connection.
    // This guarantees that BEGIN/COMMIT and PRAGMA user_version belong to the
    // same connection instead of relying on several calls through a SQL pool.
    await invoke<number>('initialize_database_schema')

    const opened = await Database.load('sqlite:kylin-stock.db')
    try {
      await opened.execute('PRAGMA foreign_keys = ON')
      database = opened
      return opened
    } catch (error) {
      await opened.close().catch(() => false)
      throw error
    }
  })()

  try {
    return await initialization
  } finally {
    initialization = null
  }
}

export async function getDatabase() {
  return database ?? initializeDatabase()
}

export async function closeDatabase() {
  if (!database) return
  const current = database
  database = null
  const closed = await current.close()
  if (!closed) {
    database = current
    throw new Error('数据库连接未能安全关闭')
  }
}

export async function reopenDatabase() {
  if (database) await closeDatabase()
  return initializeDatabase()
}

export async function checkDatabaseIntegrity() {
  const rows = await (await getDatabase()).select<Record<string, string>[]>('PRAGMA integrity_check')
  const result = rows[0] ? String(Object.values(rows[0])[0] ?? '') : ''
  return result.toLowerCase() === 'ok'
}
