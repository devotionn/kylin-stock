import { getDatabase } from './database'

export interface Unit { id: number; name: string; status: number }
export interface Location { id: number; name: string; remark: string | null; status: number }
export interface Material {
  id: number
  name: string
  unit_id: number | null
  unit_name: string | null
  category: string | null
  default_location_id: number | null
  location_name: string | null
  remark: string | null
  status: number
  created_at: string
  updated_at: string
}

const now = () => new Date().toISOString()

export async function listUnits(): Promise<Unit[]> {
  return (await getDatabase()).select<Unit[]>('SELECT id, name, status FROM units WHERE status = 1 ORDER BY name')
}

export async function createUnit(name: string) {
  const value = name.trim()
  if (!value) throw new Error('单位名称不能为空')
  return (await getDatabase()).execute('INSERT INTO units(name, status) VALUES ($1, 1)', [value])
}

export async function listLocations(): Promise<Location[]> {
  return (await getDatabase()).select<Location[]>('SELECT id, name, remark, status FROM locations WHERE status = 1 ORDER BY name')
}

export async function createLocation(name: string, remark = '') {
  const value = name.trim()
  if (!value) throw new Error('存放位置不能为空')
  return (await getDatabase()).execute('INSERT INTO locations(name, remark, status) VALUES ($1, $2, 1)', [value, remark.trim() || null])
}

export async function listMaterials(keyword = ''): Promise<Material[]> {
  const q = `%${keyword.trim()}%`
  return (await getDatabase()).select<Material[]>(`
    SELECT m.id, m.name, m.unit_id, u.name AS unit_name, m.category,
           m.default_location_id, l.name AS location_name, m.remark,
           m.status, m.created_at, m.updated_at
    FROM materials m
    LEFT JOIN units u ON u.id = m.unit_id
    LEFT JOIN locations l ON l.id = m.default_location_id
    WHERE ($1 = '%%' OR m.name LIKE $1 OR COALESCE(m.category, '') LIKE $1)
    ORDER BY m.status DESC, m.name
  `, [q])
}

export async function saveMaterial(input: {
  id?: number
  name: string
  unitId?: number | null
  category?: string
  locationId?: number | null
  remark?: string
}) {
  const db = await getDatabase()
  const name = input.name.trim()
  if (!name) throw new Error('物资名称不能为空')
  const timestamp = now()
  if (input.id) {
    return db.execute(`UPDATE materials SET name=$1, unit_id=$2, category=$3,
      default_location_id=$4, remark=$5, updated_at=$6 WHERE id=$7`, [
      name, input.unitId ?? null, input.category?.trim() || null,
      input.locationId ?? null, input.remark?.trim() || null, timestamp, input.id,
    ])
  }
  return db.execute(`INSERT INTO materials
    (name, unit_id, category, default_location_id, remark, status, created_at, updated_at)
    VALUES ($1,$2,$3,$4,$5,1,$6,$6)`, [
    name, input.unitId ?? null, input.category?.trim() || null,
    input.locationId ?? null, input.remark?.trim() || null, timestamp,
  ])
}

export async function setMaterialStatus(id: number, status: 0 | 1) {
  return (await getDatabase()).execute('UPDATE materials SET status=$1, updated_at=$2 WHERE id=$3', [status, now(), id])
}
