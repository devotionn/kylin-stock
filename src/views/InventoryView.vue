<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listInventory, type InventoryRow } from '../services/inventory'
import { exportInventoryRows } from '../services/export'
import { formatDateTime } from '../utils/date'

const loading = ref(false)
const exporting = ref(false)
const rows = ref<InventoryRow[]>([])
const filters = reactive({ keyword: '', unit: '', location: '' })

async function refresh() {
  loading.value = true
  try {
    rows.value = await listInventory(filters)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    loading.value = false
  }
}

function reset() {
  Object.assign(filters, { keyword: '', unit: '', location: '' })
  refresh()
}

async function exportCurrent() {
  if (!rows.value.length) return ElMessage.warning('当前没有可导出的库存数据')
  exporting.value = true
  try {
    const path = await exportInventoryRows(rows.value)
    if (path) ElMessage.success('库存物资分布已导出')
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
      <el-input v-model="filters.keyword" clearable placeholder="物资名称" style="width:220px" @keyup.enter="refresh" />
      <el-input v-model="filters.unit" clearable placeholder="计量单位" style="width:150px" @keyup.enter="refresh" />
      <el-input v-model="filters.location" clearable placeholder="存放位置" style="width:180px" @keyup.enter="refresh" />
      <el-button type="primary" @click="refresh">查询</el-button>
      <el-button @click="reset">重置</el-button>
      <el-button type="success" :loading="exporting" :disabled="!rows.length" @click="exportCurrent">
        导出当前结果（{{ rows.length }}）
      </el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe empty-text="暂无库存">
      <el-table-column prop="material_name" label="物资名称" min-width="180" />
      <el-table-column prop="unit_name" label="单位" width="100" />
      <el-table-column prop="location_name" label="存放位置" min-width="160" />
      <el-table-column prop="quantity" label="当前库存" width="140" />
      <el-table-column label="最后更新时间" min-width="180"><template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template></el-table-column>
    </el-table>
  </el-card>
</template>

<style scoped>
.toolbar { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:18px; align-items:center; }
</style>
