<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { open } from '@tauri-apps/plugin-dialog'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listLocations, listMaterials, type Location, type Material } from '../services/masterData'
import {
  importScannedDocument,
  recognizeTransferDocument,
  type RecognizedDocumentLine,
  type RecognizedTransferDocument,
} from '../services/documentRecognition'
import { toLocalInputValue } from '../utils/date'

type MatchState = 'MATCHED' | 'UNMATCHED' | 'AMBIGUOUS' | 'MANUAL'

interface DraftLine extends RecognizedDocumentLine {
  materialId?: number
  locationId?: number
  matchState: MatchState
}

const loading = ref(false)
const recognizing = ref(false)
const posting = ref(false)
const imported = ref(false)
const sourcePath = ref('')
const recognized = ref<RecognizedTransferDocument | null>(null)
const materials = ref<Material[]>([])
const locations = ref<Location[]>([])
const lines = ref<DraftLine[]>([])
const lastTransactionNumbers = ref<string[]>([])
const form = reactive({
  transferBasis: '',
  supplierUnit: '',
  receiverUnit: '',
  occurredAt: toLocalInputValue(),
  handler: '',
})

const busy = computed(() => loading.value || recognizing.value || posting.value)
const unresolvedCount = computed(() => lines.value.filter((line) => !line.materialId || !line.locationId || !(Number(line.quantity) > 0)).length)
const readyToPost = computed(() => Boolean(
  recognized.value?.sourceSha256
  && form.occurredAt
  && lines.value.length
  && unresolvedCount.value === 0
  && !imported.value,
))

function normalizeIdentity(value?: string | null) {
  return (value ?? '')
    .trim()
    .toLocaleLowerCase()
    .replace(/[\s（）()【】\[\]·,，。._\-—_/\\]/g, '')
}

function materialLabel(material: Material) {
  const specification = material.specification ? ` / ${material.specification}` : ''
  const unit = material.unit_name ? `（${material.unit_name}）` : ''
  return `${material.name}${specification}${unit}`
}

function sourceFileName() {
  return sourcePath.value.split(/[\\/]/).filter(Boolean).pop() || 'scan-image'
}

function confidenceTag(score: number) {
  if (score >= 0.9) return 'success'
  if (score >= 0.75) return 'warning'
  return 'danger'
}

function confidenceText(score: number) {
  return `${Math.round(Math.max(0, Math.min(1, score)) * 100)}%`
}

function autoMatchLine(line: DraftLine, force = false) {
  if (line.materialId && !force) return
  line.materialId = undefined
  line.locationId = undefined

  const targetName = normalizeIdentity(line.itemName)
  const targetSpec = normalizeIdentity(line.specification)
  if (!targetName) {
    line.matchState = 'UNMATCHED'
    return
  }

  const sameName = materials.value.filter((material) => normalizeIdentity(material.name) === targetName)
  let matches: Material[] = []
  if (targetSpec) {
    matches = sameName.filter((material) => normalizeIdentity(material.specification) === targetSpec)
  } else if (sameName.length === 1) {
    matches = sameName
  }

  if (matches.length === 1) {
    const material = matches[0]
    line.materialId = material.id
    line.locationId = material.default_location_id ?? undefined
    line.matchState = 'MATCHED'
  } else {
    line.matchState = matches.length > 1 || (!targetSpec && sameName.length > 1) ? 'AMBIGUOUS' : 'UNMATCHED'
  }
}

function rematchAll(force = false) {
  lines.value.forEach((line) => autoMatchLine(line, force))
}

function onMaterialChange(line: DraftLine, materialId?: number) {
  const material = materials.value.find((item) => item.id === materialId)
  if (!material) {
    line.materialId = undefined
    line.locationId = undefined
    line.matchState = 'UNMATCHED'
    return
  }
  line.materialId = material.id
  line.locationId = material.default_location_id ?? line.locationId
  line.itemName = material.name
  line.specification = material.specification ?? ''
  line.matchState = 'MANUAL'
}

async function loadMasterData() {
  loading.value = true
  try {
    const [materialRows, locationRows] = await Promise.all([listMaterials(), listLocations()])
    materials.value = materialRows.filter((item) => item.status === 1)
    locations.value = locationRows.filter((item) => item.status === 1)
    rematchAll(false)
  } catch (error) {
    ElMessage.error(`基础资料加载失败：${error instanceof Error ? error.message : String(error)}`)
  } finally {
    loading.value = false
  }
}

function applyRecognition(result: RecognizedTransferDocument) {
  recognized.value = result
  form.transferBasis = result.transferBasis
  form.supplierUnit = result.supplierUnit
  form.receiverUnit = result.receiverUnit
  form.occurredAt = toLocalInputValue()
  imported.value = false
  lastTransactionNumbers.value = []
  lines.value = result.lines.map((line) => ({
    ...line,
    materialId: undefined,
    locationId: undefined,
    matchState: 'UNMATCHED',
  }))
  rematchAll(true)
}

async function chooseAndRecognize() {
  if (busy.value) return
  try {
    const selected = await open({
      title: '选择调拨（接收）通知单扫描图片',
      multiple: false,
      directory: false,
      filters: [{ name: '扫描图片', extensions: ['jpg', 'jpeg', 'png', 'bmp', 'tif', 'tiff'] }],
    })
    if (!selected || typeof selected !== 'string') return

    sourcePath.value = selected
    recognizing.value = true
    const result = await recognizeTransferDocument(selected)
    applyRecognition(result)
    ElMessage.success(`识别完成：发现 ${result.lines.length} 条明细，请核对后再入库`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : String(error))
  } finally {
    recognizing.value = false
  }
}

function addManualLine() {
  if (busy.value) return
  lines.value.push({
    itemName: '',
    specification: '',
    quantity: 1,
    confidence: 0,
    warnings: ['人工补录'],
    materialId: undefined,
    locationId: undefined,
    matchState: 'MANUAL',
  })
}

function removeLine(index: number) {
  if (busy.value) return
  lines.value.splice(index, 1)
}

function resetDraft() {
  if (busy.value) return
  sourcePath.value = ''
  recognized.value = null
  lines.value = []
  imported.value = false
  lastTransactionNumbers.value = []
  Object.assign(form, {
    transferBasis: '',
    supplierUnit: '',
    receiverUnit: '',
    occurredAt: toLocalInputValue(),
    handler: '',
  })
}

async function postDocument() {
  if (posting.value || !readyToPost.value || !recognized.value) return
  posting.value = true
  try {
    await ElMessageBox.confirm(
      `确认将本单 ${lines.value.length} 条物资一次性入库？系统会原子写入：任一行失败则整单回滚。`,
      '确认扫描单据入库',
      { confirmButtonText: '确认入库', cancelButtonText: '继续核对', type: 'warning' },
    )

    const occurredAt = new Date(form.occurredAt).toISOString()
    const sourceName = sourceFileName()
    const numbers = await importScannedDocument({
      sourceHash: recognized.value.sourceSha256,
      sourceFileName: sourceName,
      documentType: 'TRANSFER_RECEIVE',
      transferBasis: form.transferBasis,
      supplierUnit: form.supplierUnit,
      receiverUnit: form.receiverUnit,
      items: lines.value.map((line) => ({
        materialId: Number(line.materialId),
        locationId: Number(line.locationId),
        quantity: Number(line.quantity),
        occurredAt,
        relatedUnit: form.supplierUnit,
        handler: form.handler,
        remark: [
          '扫描调拨（接收）通知单导入',
          form.transferBasis ? `调拨依据：${form.transferBasis}` : '',
          form.receiverUnit ? `接收单位：${form.receiverUnit}` : '',
          line.specification ? `规格型号：${line.specification}` : '',
          `源文件：${sourceName}`,
        ].filter(Boolean).join('；'),
      })),
    })
    lastTransactionNumbers.value = numbers
    imported.value = true
    ElMessage.success(`整单入库成功，共写入 ${numbers.length} 条库存流水`)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(error instanceof Error ? error.message : String(error))
    }
  } finally {
    posting.value = false
  }
}

onMounted(loadMasterData)
</script>

<template>
  <div class="document-import">
    <el-card shadow="never" class="intro-card">
      <div class="intro-row">
        <div>
          <h3>扫描单据识别导入</h3>
          <p>针对固定格式“调拨（接收）通知单”：本地 OCR 先提取，再人工核对，最后整单原子入库。</p>
        </div>
        <div class="actions">
          <el-button :disabled="busy" @click="loadMasterData">刷新基础资料</el-button>
          <el-button type="primary" :loading="recognizing" :disabled="busy" @click="chooseAndRecognize">
            {{ recognized ? '重新选择并识别' : '选择扫描图片并识别' }}
          </el-button>
          <el-button :disabled="busy || (!recognized && !lines.length)" @click="resetDraft">清空</el-button>
        </div>
      </div>
      <el-alert
        title="安全边界：OCR 结果不会自动入账；同一图片会按 SHA-256 指纹防重复导入。"
        type="info"
        :closable="false"
        show-icon
      />
    </el-card>

    <el-card v-if="recognized" shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <strong>1. 单据信息核对</strong>
          <span class="source-name">{{ sourceFileName() }} · {{ recognized.ocrEngine }} · 文本块 {{ recognized.recognizedTextCount }}</span>
        </div>
      </template>

      <el-alert
        v-if="recognized.warnings.length"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom:16px"
      >
        <template #title>识别存在 {{ recognized.warnings.length }} 项提示，黄色区域也必须人工确认</template>
        <div class="warning-list">{{ recognized.warnings.join('；') }}</div>
      </el-alert>

      <el-form label-width="100px" :disabled="busy || imported">
        <div class="form-grid">
          <el-form-item label="调拨依据"><el-input v-model="form.transferBasis" /></el-form-item>
          <el-form-item label="供应单位"><el-input v-model="form.supplierUnit" /></el-form-item>
          <el-form-item label="接收单位"><el-input v-model="form.receiverUnit" /></el-form-item>
          <el-form-item label="业务时间" required>
            <el-date-picker v-model="form.occurredAt" type="datetime" value-format="YYYY-MM-DDTHH:mm" style="width:100%" />
          </el-form-item>
          <el-form-item label="经办人"><el-input v-model="form.handler" /></el-form-item>
          <el-form-item label="表头置信度">
            <el-tag :type="confidenceTag(recognized.headerConfidence)">{{ confidenceText(recognized.headerConfidence) }}</el-tag>
          </el-form-item>
        </div>
      </el-form>
    </el-card>

    <el-card v-if="recognized" shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <strong>2. 物资明细与系统匹配</strong>
          <div>
            <el-tag :type="unresolvedCount ? 'warning' : 'success'">
              {{ unresolvedCount ? `${unresolvedCount} 行待处理` : '全部可入库' }}
            </el-tag>
            <el-button link type="primary" :disabled="busy || imported" @click="addManualLine">补一行</el-button>
          </div>
        </div>
      </template>

      <el-table :data="lines" border stripe empty-text="OCR 未提取到明细，可点击“补一行”人工录入">
        <el-table-column label="OCR 名称" min-width="140">
          <template #default="{ row }"><el-input v-model="row.itemName" :disabled="busy || imported" @blur="autoMatchLine(row, true)" /></template>
        </el-table-column>
        <el-table-column label="OCR 规格型号" min-width="160">
          <template #default="{ row }"><el-input v-model="row.specification" :disabled="busy || imported" @blur="autoMatchLine(row, true)" /></template>
        </el-table-column>
        <el-table-column label="应发数量" width="135">
          <template #default="{ row }"><el-input-number v-model="row.quantity" :disabled="busy || imported" :min="0" :precision="3" style="width:110px" /></template>
        </el-table-column>
        <el-table-column label="置信度" width="90" align="center">
          <template #default="{ row }"><el-tag size="small" :type="confidenceTag(row.confidence)">{{ confidenceText(row.confidence) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="对应系统物资" min-width="240">
          <template #default="{ row }">
            <el-select
              v-model="row.materialId"
              :disabled="busy || imported"
              filterable
              clearable
              placeholder="必须确认系统物资"
              style="width:100%"
              @change="(value: number | undefined) => onMaterialChange(row, value)"
            >
              <el-option v-for="material in materials" :key="material.id" :label="materialLabel(material)" :value="material.id" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="入库位置" min-width="170">
          <template #default="{ row }">
            <el-select v-model="row.locationId" :disabled="busy || imported" filterable placeholder="请选择位置" style="width:100%">
              <el-option v-for="location in locations" :key="location.id" :label="location.name" :value="location.id" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.materialId && row.locationId && Number(row.quantity) > 0" type="success" size="small">可入库</el-tag>
            <el-tag v-else-if="row.matchState === 'AMBIGUOUS'" type="warning" size="small">同名多规格</el-tag>
            <el-tag v-else type="danger" size="small">需人工处理</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" align="center">
          <template #default="{ $index }"><el-button link type="danger" :disabled="busy || imported" @click="removeLine($index)">删除</el-button></template>
        </el-table-column>
      </el-table>

      <el-alert
        v-if="lines.some((line) => line.warnings.length)"
        title="OCR 行级提示只用于辅助判断；最终以你选择的系统物资、位置和数量为准。"
        type="warning"
        :closable="false"
        show-icon
        style="margin-top:14px"
      />
    </el-card>

    <el-card v-if="recognized" shadow="never" class="section-card">
      <template #header><strong>3. 确认入库</strong></template>
      <div class="submit-row">
        <div>
          <div v-if="!imported">共 {{ lines.length }} 行；{{ unresolvedCount ? `还有 ${unresolvedCount} 行未完成匹配/位置/数量` : '校验通过，可以整单入库' }}</div>
          <div v-else class="success-text">本单已入库，生成 {{ lastTransactionNumbers.length }} 条流水；重复选择同一图片也会被数据库拒绝。</div>
        </div>
        <el-button
          type="success"
          size="large"
          :loading="posting"
          :disabled="busy || !readyToPost"
          @click="postDocument"
        >
          人工确认并整单入库
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.document-import { display:flex; flex-direction:column; gap:16px; }
.intro-card h3 { margin:0 0 8px; font-size:18px; }
.intro-card p { margin:0; color:#606266; }
.intro-row { display:flex; justify-content:space-between; align-items:flex-start; gap:18px; margin-bottom:16px; flex-wrap:wrap; }
.actions { display:flex; gap:10px; flex-wrap:wrap; }
.section-card { overflow:visible; }
.card-header { display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; }
.source-name { color:#909399; font-size:13px; }
.form-grid { display:grid; grid-template-columns:repeat(2, minmax(260px, 1fr)); gap:0 20px; }
.warning-list { margin-top:6px; line-height:1.7; }
.submit-row { display:flex; justify-content:space-between; gap:20px; align-items:center; flex-wrap:wrap; }
.success-text { color:#529b2e; font-weight:600; }
@media (max-width: 900px) { .form-grid { grid-template-columns:1fr; } }
</style>
