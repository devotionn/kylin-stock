<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { listLocations, listMaterials, type Location, type Material } from '../services/masterData'
import { stockIn, stockOut } from '../services/inventory'

const route = useRoute()
const isOut = computed(() => route.path === '/stock-out')
const submitting = ref(false)
const materials = ref<Material[]>([])
const locations = ref<Location[]>([])
const form = reactive({ materialId: undefined as number | undefined, locationId: undefined as number | undefined, quantity: 1, occurredAt: new Date().toISOString().slice(0, 16), relatedUnit: '', destination: '', handler: '', receiver: '', remark: '' })

async function load() {
  ;[materials.value, locations.value] = await Promise.all([listMaterials(), listLocations()])
  materials.value = materials.value.filter((item) => item.status === 1)
}

function onMaterialChange(id: number) {
  const material = materials.value.find((item) => item.id === id)
  if (material?.default_location_id) form.locationId = material.default_location_id
}

function reset() {
  Object.assign(form, { materialId: undefined, locationId: undefined, quantity: 1, occurredAt: new Date().toISOString().slice(0, 16), relatedUnit: '', destination: '', handler: '', receiver: '', remark: '' })
}

async function submit() {
  submitting.value = true
  try {
    const payload = { materialId: form.materialId!, locationId: form.locationId!, quantity: Number(form.quantity), occurredAt: new Date(form.occurredAt).toISOString(), relatedUnit: form.relatedUnit, destination: form.destination, handler: form.handler, receiver: form.receiver, remark: form.remark }
    if (isOut.value) await stockOut(payload)
    else await stockIn(payload)
    ElMessage.success(isOut.value ? '出库登记成功' : '入库登记成功')
    reset()
  } catch (e) { ElMessage.error(e instanceof Error ? e.message : String(e)) }
  finally { submitting.value = false }
}

onMounted(load)
</script>

<template>
  <el-card shadow="never" class="operation-card">
    <template #header><strong>{{ isOut ? '出库登记' : '入库登记' }}</strong></template>
    <el-form label-width="110px" style="max-width: 720px">
      <el-form-item label="物资名称" required>
        <el-select v-model="form.materialId" filterable style="width:100%" placeholder="请选择物资" @change="onMaterialChange">
          <el-option v-for="item in materials" :key="item.id" :label="`${item.name}${item.unit_name ? `（${item.unit_name}）` : ''}`" :value="item.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="存放位置" required><el-select v-model="form.locationId" style="width:100%"><el-option v-for="item in locations" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
      <el-form-item :label="isOut ? '出库数量' : '入库数量'" required><el-input-number v-model="form.quantity" :min="0.001" :precision="3" style="width:100%" /></el-form-item>
      <el-form-item label="业务时间" required><el-date-picker v-model="form.occurredAt" type="datetime" value-format="YYYY-MM-DDTHH:mm" style="width:100%" /></el-form-item>
      <el-form-item :label="isOut ? '领用单位' : '来源单位'"><el-input v-model="form.relatedUnit" /></el-form-item>
      <el-form-item v-if="isOut" label="出库去向" required><el-input v-model="form.destination" placeholder="例如：一车间、XX项目、维修使用" /></el-form-item>
      <el-form-item label="经办人"><el-input v-model="form.handler" /></el-form-item>
      <el-form-item v-if="isOut" label="领用人"><el-input v-model="form.receiver" /></el-form-item>
      <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="3" /></el-form-item>
      <el-form-item><el-button type="primary" :loading="submitting" @click="submit">确认{{ isOut ? '出库' : '入库' }}</el-button><el-button @click="reset">重置</el-button></el-form-item>
    </el-form>
  </el-card>
</template>

<style scoped>.operation-card { min-height: 560px; }</style>
