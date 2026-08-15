<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listInventory, type InventoryRow } from '../services/inventory'

const loading = ref(false)
const keyword = ref('')
const rows = ref<InventoryRow[]>([])

async function refresh() {
  loading.value = true
  try { rows.value = await listInventory(keyword.value) }
  catch (e) { ElMessage.error(String(e)) }
  finally { loading.value = false }
}

onMounted(refresh)
</script>

<template>
  <el-card shadow="never">
    <div class="toolbar">
      <el-input v-model="keyword" clearable placeholder="搜索物资名称或存放位置" style="width:300px" @keyup.enter="refresh" />
      <el-button type="primary" @click="refresh">查询</el-button>
      <el-button @click="keyword=''; refresh()">重置</el-button>
    </div>
    <el-table v-loading="loading" :data="rows" border stripe empty-text="暂无库存">
      <el-table-column prop="material_name" label="物资名称" min-width="180" />
      <el-table-column prop="unit_name" label="单位" width="100" />
      <el-table-column prop="location_name" label="存放位置" min-width="160" />
      <el-table-column prop="quantity" label="当前库存" width="140" />
      <el-table-column prop="updated_at" label="最后更新时间" min-width="200" />
    </el-table>
  </el-card>
</template>

<style scoped>.toolbar{display:flex;gap:10px;margin-bottom:18px}</style>
