<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listLedger, type LedgerRow } from '../services/inventory'

const loading = ref(false)
const rows = ref<LedgerRow[]>([])
const filters = reactive({ keyword: '', type: '', destination: '' })

async function refresh() {
  loading.value = true
  try { rows.value = await listLedger(filters) }
  catch (e) { ElMessage.error(String(e)) }
  finally { loading.value = false }
}

function reset() { Object.assign(filters, { keyword: '', type: '', destination: '' }); refresh() }
onMounted(refresh)
</script>

<template>
  <el-card shadow="never">
    <div class="toolbar">
      <el-input v-model="filters.keyword" clearable placeholder="物资名称 / 单位" style="width:220px" />
      <el-select v-model="filters.type" clearable placeholder="业务类型" style="width:140px"><el-option label="入库" value="IN" /><el-option label="出库" value="OUT" /><el-option label="调整" value="ADJUST" /></el-select>
      <el-input v-model="filters.destination" clearable placeholder="出库去向" style="width:220px" />
      <el-button type="primary" @click="refresh">查询</el-button>
      <el-button @click="reset">重置</el-button>
    </div>
    <el-table v-loading="loading" :data="rows" border stripe empty-text="暂无出入库记录">
      <el-table-column prop="transaction_no" label="流水号" min-width="190" />
      <el-table-column label="类型" width="90"><template #default="{row}"><el-tag :type="row.type==='IN'?'success':row.type==='OUT'?'warning':'info'">{{ row.type==='IN'?'入库':row.type==='OUT'?'出库':'调整' }}</el-tag></template></el-table-column>
      <el-table-column prop="material_name" label="物资名称" min-width="160" />
      <el-table-column prop="quantity" label="数量" width="110" />
      <el-table-column prop="unit_name" label="单位" width="90" />
      <el-table-column prop="location_name" label="存放位置" min-width="130" />
      <el-table-column prop="related_unit" label="相关单位" min-width="140" />
      <el-table-column prop="destination" label="出库去向" min-width="150" />
      <el-table-column prop="handler" label="经办人" width="100" />
      <el-table-column prop="receiver" label="领用人" width="100" />
      <el-table-column prop="occurred_at" label="业务时间" min-width="190" />
      <el-table-column prop="remark" label="备注" min-width="180" show-overflow-tooltip />
    </el-table>
  </el-card>
</template>

<style scoped>.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px}</style>
