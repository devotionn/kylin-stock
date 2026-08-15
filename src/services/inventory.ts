import { getDatabase } from './database'

export interface InventoryRow {
  material_id: number
  material_name: string
  unit_name: string | null
  location_id: number
  location_name: string
  quantity: number
  updated_at: string
}

export interface LedgerRow {
  id: number
  transaction_no: string
  type: 'IN' | 'OUT' | 'ADJUST'
  material_name: string
  unit_name: string | null
  location_name: string
  quantity: number
  occurred_at: string
  related_unit: string | null
  destination: string | null
  handler: string | null
  receiver: string | null
  remark: string | null
}

export interface InventoryFilters {
  keyword?: string
  unit?: string
  location?: string
}

export interface LedgerFilters {
  material?: string
  type?: string
  relatedUnit?: string
  destination?: string
  startAt?: string
  endAt?: string
}

export interface StockOperationInput {
  materialId: number
  locationId: number
  quantity: number
  occurredAt: string
  relatedUnit?: string
  destination?: string
  handler?: string
  receiver?: string
  remark?: string
}

const transactionNo = (type: 'IN' | 'OUT') => {
  const d = new Date()
  const stamp = d.toISOString().replace(/[-:TZ.]/g, '').slice(0, 14)
  return `${type}-${stamp}-${Math.random().toString(36).slice(2, 7).toUpperCase()}`
}

async function withTransaction<T>(task: () => Promise<T>): Promise<T> {
  const db = await getDatabase()
  await db.execute('BEGIN IMMEDIATE')
  try {
    const result = await task()
    await db.execute('COMMIT')
    return result
  } catch (error) {
    try { await db.execute('ROLLBACK') } catch { /* no-op */ }
    throw error
  }
}

function validate(input: StockOperationInput) {
  if (!input.materialId) throw new Error('请选择物资')
  if (!input.locationId) throw new Error('请选择存放位置')
  if (!Number.isFinite(input.quantity) || input.quantity <= 0) throw new Error('数量必须大于 0')
  if (!input.occurredAt) throw new Error('请选择业务时间')
}

export async function stockIn(input: StockOperationInput) {
  validate(input)
  return withTransaction(async () => {
    const db = await getDatabase()
    const now = new Date().toISOString()
    await db.execute(`INSERT INTO stock_transactions
      (transaction_no,type,material_id,location_id,quantity,occurred_at,related_unit,destination,handler,receiver,remark,created_at)
      VALUES ($1,'IN',$2,$3,$4,$5,$6,NULL,$7,$8,$9,$10)`, [
      transactionNo('IN'), input.materialId, input.locationId, input.quantity, input.occurredAt,
      input.relatedUnit?.trim() || null, input.handler?.trim() || null, input.receiver?.trim() || null,
      input.remark?.trim() || null, now,
    ])
    await db.execute(`INSERT INTO inventory_balances(material_id,location_id,quantity,updated_at)
      VALUES ($1,$2,$3,$4)
      ON CONFLICT(material_id,location_id) DO UPDATE SET
      quantity = quantity + excluded.quantity, updated_at = excluded.updated_at`, [
      input.materialId, input.locationId, input.quantity, now,
    ])
  })
}

export async function stockOut(input: StockOperationInput) {
  validate(input)
  if (!input.destination?.trim()) throw new Error('出库去向不能为空')
  return withTransaction(async () => {
    const db = await getDatabase()
    const rows = await db.select<{ quantity: number }[]>(
      'SELECT quantity FROM inventory_balances WHERE material_id=$1 AND location_id=$2',
      [input.materialId, input.locationId],
    )
    const available = Number(rows[0]?.quantity ?? 0)
    if (available < input.quantity) throw new Error(`库存不足，当前可用库存为 ${available}`)

    const now = new Date().toISOString()
    await db.execute(`INSERT INTO stock_transactions
      (transaction_no,type,material_id,location_id,quantity,occurred_at,related_unit,destination,handler,receiver,remark,created_at)
      VALUES ($1,'OUT',$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`, [
      transactionNo('OUT'), input.materialId, input.locationId, input.quantity, input.occurredAt,
      input.relatedUnit?.trim() || null, input.destination.trim(), input.handler?.trim() || null,
      input.receiver?.trim() || null, input.remark?.trim() || null, now,
    ])
    await db.execute(`UPDATE inventory_balances
      SET quantity = quantity - $1, updated_at=$2
      WHERE material_id=$3 AND location_id=$4`, [input.quantity, now, input.materialId, input.locationId])
  })
}

export async function listInventory(filters: InventoryFilters | string = {}): Promise<InventoryRow[]> {
  const normalized: InventoryFilters = typeof filters === 'string' ? { keyword: filters } : filters
  const keyword = `%${(normalized.keyword ?? '').trim()}%`
  const unit = `%${(normalized.unit ?? '').trim()}%`
  const location = `%${(normalized.location ?? '').trim()}%`
  return (await getDatabase()).select<InventoryRow[]>(`
    SELECT b.material_id, m.name AS material_name, u.name AS unit_name,
           b.location_id, l.name AS location_name, b.quantity, b.updated_at
    FROM inventory_balances b
    JOIN materials m ON m.id=b.material_id
    LEFT JOIN units u ON u.id=m.unit_id
    JOIN locations l ON l.id=b.location_id
    WHERE b.quantity <> 0
      AND ($1='%%' OR m.name LIKE $1)
      AND ($2='%%' OR COALESCE(u.name,'') LIKE $2)
      AND ($3='%%' OR l.name LIKE $3)
    ORDER BY m.name, l.name`, [keyword, unit, location])
}

export async function listLedger(filters: LedgerFilters = {}): Promise<LedgerRow[]> {
  const material = `%${(filters.material ?? '').trim()}%`
  const relatedUnit = `%${(filters.relatedUnit ?? '').trim()}%`
  const destination = `%${(filters.destination ?? '').trim()}%`
  return (await getDatabase()).select<LedgerRow[]>(`
    SELECT t.id,t.transaction_no,t.type,m.name AS material_name,u.name AS unit_name,
           l.name AS location_name,t.quantity,t.occurred_at,t.related_unit,t.destination,
           t.handler,t.receiver,t.remark
    FROM stock_transactions t
    JOIN materials m ON m.id=t.material_id
    LEFT JOIN units u ON u.id=m.unit_id
    JOIN locations l ON l.id=t.location_id
    WHERE ($1='%%' OR m.name LIKE $1)
      AND ($2='' OR t.type=$2)
      AND ($3='%%' OR COALESCE(t.related_unit,'') LIKE $3)
      AND ($4='%%' OR COALESCE(t.destination,'') LIKE $4)
      AND ($5='' OR t.occurred_at >= $5)
      AND ($6='' OR t.occurred_at <= $6)
    ORDER BY t.occurred_at DESC,t.id DESC`, [
      material,
      filters.type ?? '',
      relatedUnit,
      destination,
      filters.startAt ?? '',
      filters.endAt ?? '',
    ])
}
