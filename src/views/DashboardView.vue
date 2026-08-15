<script setup lang="ts">
const stats = [
  { label: '物资品种', value: '--', note: '已建档物资' },
  { label: '库存总量', value: '--', note: '当前库存汇总' },
  { label: '今日入库', value: '--', note: '今日入库数量' },
  { label: '今日出库', value: '--', note: '今日出库数量' },
]
</script>

<template>
  <div class="page-stack">
    <el-row :gutter="16">
      <el-col v-for="stat in stats" :key="stat.label" :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-label">{{ stat.label }}</div>
          <div class="stat-value">{{ stat.value }}</div>
          <div class="stat-note">{{ stat.note }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :span="14">
        <el-card shadow="never">
          <template #header><strong>最近出入库记录</strong></template>
          <el-empty description="暂无业务记录" />
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card shadow="never">
          <template #header><strong>库存概览</strong></template>
          <el-empty description="录入物资后显示库存信息" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>
