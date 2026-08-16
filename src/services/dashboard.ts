import { getDatabase, withDatabaseAccess } from './database'
import { localDayIsoRange } from '../utils/date'

export interface DashboardStats {
  materialCount: number
  stockedMaterialCount: number
  todayInCount: number
  todayOutCount: number
}

export interface RecentTransaction {
  id: number
  type: 'IN' | 'OUT' | 'ADJUST'
  material_name: string
  quantity: number
  unit_name: string | null
  location_name: string
  destination: string | null
  occurred_at: string
}

export interface StockOverviewRow {
  material_name: string
  unit_name: string | null
  quantity: number
}

export async function loadDashboard() {
  return withDatabaseAccess(async () => {
    const db = await getDatabase()
    const { start, end } = localDayIsoRange()

    const [materialRows, stockedRows, inRows, outRows, recent, overview] = await Promise.all([
      db.select<{ value: number }[]>(`SELECT COUNT(*) AS value FROM materials WHERE status=1`),
      db.select<{ value: number }[]>(`
        SELECT COUNT(DISTINCT material_id) AS value
        FROM inventory_balances
        WHERE quantity > 0
      `),
      db.select<{ value: number }[]>(`
        SELECT COUNT(*) AS value FROM stock_transactions
        WHERE type='IN' AND occurred_at >= $1 AND occurred_at <= $2
      `, [start, end]),
      db.select<{ value: number }[]>(`
        SELECT COUNT(*) AS value FROM stock_transactions
        WHERE type='OUT' AND occurred_at >= $1 AND occurred_at <= $2
      `, [start, end]),
      db.select<RecentTransaction[]>(`
        SELECT t.id,t.type,m.name AS material_name,t.quantity,u.name AS unit_name,
               l.name AS location_name,t.destination,t.occurred_at
        FROM stock_transactions t
        JOIN materials m ON m.id=t.material_id
        LEFT JOIN units u ON u.id=m.unit_id
        JOIN locations l ON l.id=t.location_id
        ORDER BY t.occurred_at DESC,t.id DESC
        LIMIT 8
      `),
      db.select<StockOverviewRow[]>(`
        SELECT m.name AS material_name,u.name AS unit_name,SUM(b.quantity) AS quantity
        FROM inventory_balances b
        JOIN materials m ON m.id=b.material_id
        LEFT JOIN units u ON u.id=m.unit_id
        GROUP BY b.material_id,m.name,u.name
        HAVING SUM(b.quantity) > 0
        ORDER BY m.name
        LIMIT 8
      `),
    ])

    const stats: DashboardStats = {
      materialCount: Number(materialRows[0]?.value ?? 0),
      stockedMaterialCount: Number(stockedRows[0]?.value ?? 0),
      todayInCount: Number(inRows[0]?.value ?? 0),
      todayOutCount: Number(outRows[0]?.value ?? 0),
    }

    return { stats, recent, overview }
  })
}
