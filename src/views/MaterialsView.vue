<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createLocation, createUnit, listLocations, listMaterials, listUnits, saveMaterial, setMaterialStatus, type Location, type Material, type Unit } from '../services/masterData'
import { exportMaterialRows } from '../services/export'

const loading = ref(false)
const exporting = ref(false)
const keyword = ref('')
const materials = ref<Material[]>([])
const units = ref<Unit[]>([])
const locations = ref<Location[]>([])
const dialogVisible = ref(false)
const dialogTitle = ref('新增物资')
const form = reactive({ id: undefined as number | undefined, name: '', unitId: undefined as number | undefined, category: '', locationId: undefined as number | undefined, remark: '' })

async function refresh() {
  loading.value = true
  try {
    ;[materials.value, units.value, locations.value] = await Promise.all([listMaterials(keyword.value), listUnits(), listLocations()])
  } catch (e) { ElMessage.error(String(e)) } finally { loading.value = false }
}
function openCreate() { Object.assign(form, { id: undefined, name: '', unitId: undefined, category: '', locationId: undefined, remark: '' }); dialogTitle.value = '新增物资'; dialogVisible.value = true }
function openEdit(row: Material) { Object.assign(form, { id: row.id, name: row.name, unitId: row.unit_id ?? undefined, category: row.category ?? '', locationId: row.default_location_id ?? undefined, remark: row.remark ?? '' }); dialogTitle.value = '编辑物资'; dialogVisible.value = true }
async function submit() {
  try { await saveMaterial(form); dialogVisible.value = false; ElMessage.success('保存成功'); await refresh() } catch (e) { ElMessage.error(String(e)) }
}
async function toggle(row: Material) {
  const next = row.status === 1 ? 0 : 1
  await ElMessageBox.confirm(`确认${next ? '启用' : '停用'}“${row.name}”？`, '操作确认')
  await setMaterialStatus(row.id, next as 0 | 1); ElMessage.success('操作成功'); await refresh()
}
async function quickUnit() {
  const { value } = await ElMessageBox.prompt('请输入计量单位，例如：个、箱、kg', '新增单位', { inputPattern: /\S+/, inputErrorMessage: '单位不能为空' })
  await createUnit(value); ElMessage.success('单位已添加'); await refresh()
}
async function quickLocation() {
  const { value } = await ElMessageBox.prompt('请输入存放位置，例如：一号库、A区货架', '新增存放位置', { inputPattern: /\S+/, inputErrorMessage: '位置不能为空' })
  await createLocation(value); ElMessage.success('位置已添加'); await refresh()
}
async function exportCurrent() {
  if (!materials.value.length) return ElMessage.warning('当前没有可导出的物资数据')
  exporting.value = true
  try {
    const path = await exportMaterialRows(materials.value)
    if (path) ElMessage.success('物资明细已导出')
  } catch (e) {
    ElMessage.error(`导出失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    exporting.value = false
  }
}
onMounted(refresh)
</script>

<template>
  <el-card shadow="never">
    <div class="toolbar">
      <div class="search-group">
        <el-input v-model="keyword" clearable placeholder="搜索物资名称或分类" style="width: 280px" @keyup.enter="refresh" />
        <el-button type="primary" @click="refresh">查询</el-button>
        <el-button @click="keyword=''; refresh()">重置</el-button>
        <el-button type="success" :loading="exporting" :disabled="!materials.length" @click="exportCurrent">导出当前结果（{{ materials.length }}）</el-button>
      </div>
      <div>
        <el-button @click="quickUnit">新增单位</el-button>
        <el-button @click="quickLocation">新增位置</el-button>
        <el-button type="primary" @click="openCreate">新增物资</el-button>
      </div>
    </div>

    <el-table v-loading="loading" :data="materials" border stripe empty-text="暂无物资，请先新增">
      <el-table-column prop="name" label="物资名称" min-width="180" />
      <el-table-column prop="unit_name" label="单位" width="100" />
      <el-table-column prop="category" label="分类" min-width="130" />
      <el-table-column prop="location_name" label="默认存放位置" min-width="160" />
      <el-table-column prop="remark" label="备注" min-width="180" show-overflow-tooltip />
      <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="row.status === 1 ? 'success' : 'info'">{{ row.status === 1 ? '正常' : '停用' }}</el-tag></template></el-table-column>
      <el-table-column label="操作" width="180"><template #default="{ row }"><el-button link type="primary" @click="openEdit(row)">编辑</el-button><el-button link :type="row.status === 1 ? 'danger' : 'success'" @click="toggle(row)">{{ row.status === 1 ? '停用' : '启用' }}</el-button></template></el-table-column>
    </el-table>
  </el-card>

  <el-dialog v-model="dialogVisible" :title="dialogTitle" width="520px">
    <el-form label-width="110px">
      <el-form-item label="物资名称" required><el-input v-model="form.name" maxlength="100" /></el-form-item>
      <el-form-item label="计量单位"><el-select v-model="form.unitId" clearable style="width:100%"><el-option v-for="item in units" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
      <el-form-item label="物资分类"><el-input v-model="form.category" /></el-form-item>
      <el-form-item label="存放位置"><el-select v-model="form.locationId" clearable style="width:100%"><el-option v-for="item in locations" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
      <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="3" /></el-form-item>
    </el-form>
    <template #footer><el-button @click="dialogVisible=false">取消</el-button><el-button type="primary" @click="submit">保存</el-button></template>
  </el-dialog>
</template>

<style scoped>
.toolbar { display:flex; justify-content:space-between; gap:16px; margin-bottom:18px; flex-wrap:wrap; }
.search-group { display:flex; gap:10px; flex-wrap:wrap; }
</style>
