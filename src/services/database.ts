import { invoke } from '@tauri-apps/api/core'
import Database from '@tauri-apps/plugin-sql'

let database: Database | null = null
let initialization: Promise<Database> | null = null
let mutationTail: Promise<void> = Promise.resolve()

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

/**
 * Serialize application-level database mutations within the single KylinStock
 * webview process. This is intentionally a service-layer invariant rather than
 * only a button/loading guard: callers that forget to disable a UI control are
 * still queued behind the mutation already in progress.
 *
 * Backup/restore also owns this queue for its complete database lifecycle so a
 * stock or master-data write cannot overlap snapshot/close/swap/reopen work.
 * Reads remain concurrent; KylinStock V1 has no background polling and restore
 * is only exposed from the dedicated backup view.
 *
 * Do not call withDatabaseMutation() recursively from inside an operation that
 * already owns the queue; nested acquisition would wait on itself.
 */
export async function withDatabaseMutation<T>(operation: () => Promise<T>): Promise<T> {
  let release!: () => void
  const turn = new Promise<void>((resolve) => { release = resolve })
  const previous = mutationTail
  mutationTail = turn

  await previous
  try {
    return await operation()
  } finally {
    release()
  }
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
