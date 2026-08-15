import Database from '@tauri-apps/plugin-sql'

let database: Database | null = null

const schema = [
  `CREATE TABLE IF NOT EXISTS units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    status INTEGER NOT NULL DEFAULT 1
  )`,
  `CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    remark TEXT,
    status INTEGER NOT NULL DEFAULT 1
  )`,
  `CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    unit_id INTEGER,
    category TEXT,
    default_location_id INTEGER,
    remark TEXT,
    status INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(unit_id) REFERENCES units(id),
    FOREIGN KEY(default_location_id) REFERENCES locations(id)
  )`,
  `CREATE TABLE IF NOT EXISTS inventory_balances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL,
    location_id INTEGER NOT NULL,
    quantity NUMERIC NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE(material_id, location_id),
    FOREIGN KEY(material_id) REFERENCES materials(id),
    FOREIGN KEY(location_id) REFERENCES locations(id)
  )`,
  `CREATE TABLE IF NOT EXISTS stock_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_no TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK(type IN ('IN', 'OUT', 'ADJUST')),
    material_id INTEGER NOT NULL,
    location_id INTEGER NOT NULL,
    quantity NUMERIC NOT NULL CHECK(quantity > 0),
    occurred_at TEXT NOT NULL,
    related_unit TEXT,
    destination TEXT,
    handler TEXT,
    receiver TEXT,
    remark TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(material_id) REFERENCES materials(id),
    FOREIGN KEY(location_id) REFERENCES locations(id)
  )`,
  `CREATE TABLE IF NOT EXISTS backup_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    backup_type TEXT NOT NULL CHECK(backup_type IN ('MANUAL', 'ANNUAL')),
    backup_year INTEGER,
    file_size INTEGER,
    checksum TEXT,
    created_at TEXT NOT NULL,
    remark TEXT
  )`,
  `CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS idx_materials_name ON materials(name)`,
  `CREATE INDEX IF NOT EXISTS idx_transactions_material ON stock_transactions(material_id)`,
  `CREATE INDEX IF NOT EXISTS idx_transactions_occurred_at ON stock_transactions(occurred_at)`,
  `CREATE INDEX IF NOT EXISTS idx_transactions_type ON stock_transactions(type)`,
  `CREATE INDEX IF NOT EXISTS idx_transactions_destination ON stock_transactions(destination)`
]

export async function initializeDatabase() {
  if (database) return database

  database = await Database.load('sqlite:kylin-stock.db')
  await database.execute('PRAGMA foreign_keys = ON')

  for (const statement of schema) {
    await database.execute(statement)
  }

  return database
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
