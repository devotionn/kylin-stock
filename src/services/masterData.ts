import { getDatabase, withDatabaseAccess, withDatabaseMutation } from './database'

export interface Unit { id: number; name: string; status: number }
export interface Location { id: number; name: string; remark: string | null; status: number }
export interface Material {
  id: number
  name: string
  specification: string | null
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

function normalizeIdentityPart(value?: string | null) {
  return value?.trim() || null
}

export async function listUnits(): Promise<Unit[]> {
  return withDatabaseAccess(async () =>
    (await getDatabase()).select<Unit[]>('SELECT id, name, status FROM units WHERE status = 1 ORDER BY name'),
  )
}

export async function createUnit(name: string) {
  const value = name.trim()
  if (!value) throw new Error('单位名称不能为空')
  return withDatabaseMutation(async () =>
    (await getDatabase()).execute('INSERT INTO units(name, status) VALUES ($1, 1)', [value]),
  )
}

export async function listLocations(): Promise<Location[]> {
  return withDatabaseAccess(async () =>
    (await getDatabase()).select<Location[]>('SELECT id, name, remark, status FROM locations WHERE status = 1 ORDER BY name'),
  )
}

export async function createLocation(name: string, remark = '') {
  const value = name.trim()
  const normalizedRemark = remark.trim() || null
  if (!value) throw new Error('存放位置不能为空')
  return withDatabaseMutation(async () =>
    (await getDatabase()).execute('INSERT INTO locations(name, remark, status) VALUES ($1, $2, 1)', [value, normalizedRemark]),
  )
}

export async function listMaterials(keyword = ''): Promise<Material[]> {
  const q = `%${keyword.trim()}%`
  return withDatabaseAccess(async () =>
    (await getDatabase()).select<Material[]>(`
      SELECT m.id, m.name, m.specification, m.unit_id, u.name AS unit_name, m.category,
             m.default_location_id, l.name AS location_name, m.remark,
             m.status, m.created_at, m.updated_at
      FROM materials m
      LEFT JOIN units u ON u.id = m.unit_id
      LEFT JOIN locations l ON l.id = m.default_location_id
      WHERE ($1 = '%%' OR m.name LIKE $1 OR COALESCE(m.specification, '') LIKE $1 OR COALESCE(m.category, '') LIKE $1)
      ORDER BY m.status DESC, m.name, COALESCE(m.specification, '')
    `, [q]),
  )
}

export async function saveMaterial(input: {
  id?: number
  name: string
  specification?: string | null
  unitId?: number | null
  category?: string
  locationId?: number | null
  remark?: string
}) {
  const normalized = {
    id: input.id,
    name: input.name.trim(),
    specification: normalizeIdentityPart(input.specification),
    unitId: input.unitId ?? null,
    category: input.category?.trim() || null,
    locationId: input.locationId ?? null,
    remark: input.remark?.trim() || null,
  }
  if (!normalized.name) throw new Error('物资名称不能为空')

  return withDatabaseMutation(async () => {
    const db = await getDatabase()

    // Scanned documents often distinguish otherwise identical material names by
    // specification/model. Treat (name, specification) as the human-facing
    // identity while keeping the whole precheck + write in one mutation turn.
    const conflicts = await db.select<{ id: number; status: number }[]>(`
      SELECT id, status
      FROM materials
      WHERE name = $1 COLLATE NOCASE
        AND COALESCE(specification, '') = COALESCE($2, '') COLLATE NOCASE
        AND ($3 IS NULL OR id <> $3)
      LIMIT 1
    `, [normalized.name, normalized.specification, normalized.id ?? null])
    if (conflicts.length) {
      throw new Error(conflicts[0].status === 0
        ? '已存在同名同规格物资，但当前处于停用状态，请直接重新启用原物资'
        : '已存在同名同规格物资，请勿重复添加')
    }

    const timestamp = now()
    if (normalized.id) {
      return db.execute(`UPDATE materials SET name=$1, specification=$2, unit_id=$3, category=$4,
        default_location_id=$5, remark=$6, updated_at=$7 WHERE id=$8`, [
        normalized.name, normalized.specification, normalized.unitId, normalized.category,
        normalized.locationId, normalized.remark, timestamp, normalized.id,
      ])
    }
    return db.execute(`INSERT INTO materials
      (name, specification, unit_id, category, default_location_id, remark, status, created_at, updated_at)
      VALUES ($1,$2,$3,$4,$5,$6,1,$7,$7)`, [
      normalized.name, normalized.specification, normalized.unitId, normalized.category,
      normalized.locationId, normalized.remark, timestamp,
    ])
  })
}

export async function setMaterialStatus(id: number, status: 0 | 1) {
  const materialId = Number(id)
  const nextStatus = status
  return withDatabaseMutation(async () =>
    (await getDatabase()).execute('UPDATE materials SET status=$1, updated_at=$2 WHERE id=$3', [nextStatus, now(), materialId]),
  )
}
