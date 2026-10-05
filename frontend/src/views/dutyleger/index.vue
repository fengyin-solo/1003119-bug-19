<template>
  <section class="page" data-module="dutyleger">
    <header class="page-head">
      <div>
        <h2>值班台账</h2>
        <p class="page-desc">
          在井人数与超时未升名单直接取入井管理的同一份记录，本页不另存数据；{{ ledger?.['口径'] }}
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="reload">刷新台账</button>
        <button class="btn" type="button" @click="exportRows">导出超时未升名单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <h3 class="section-title">超时未升名单</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in overtimeColumns" :key="column">{{ column }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in overtimeRows" :key="String(row.id)">
          <td v-for="column in overtimeColumns" :key="column">{{ row[column] ?? '—' }}</td>
        </tr>
        <tr v-if="!overtimeRows.length">
          <td :colspan="overtimeColumns.length" class="empty-state">当前没有超时未升人员</td>
        </tr>
      </tbody>
    </table>

    <h3 class="section-title">升井缺测（数据缺口，待核实）</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in missingColumns" :key="column">{{ column }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in missingRows" :key="String(row.id)">
          <td v-for="column in missingColumns" :key="column">{{ row[column] ?? '—' }}</td>
        </tr>
        <tr v-if="!missingRows.length">
          <td :colspan="missingColumns.length" class="empty-state">当前没有升井缺测记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span v-if="ledger">统计时刻 {{ ledger['统计时刻'] }} · {{ ledger['来源'] }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchJson } from '@/api/client'

type Row = Record<string, string | number | null>
type Ledger = {
  统计时刻: string
  在井人数: number
  口径: string
  来源: string
  counts: Record<string, number>
  超时未升名单: Row[]
  升井缺测名单: Row[]
}

const ENDPOINT = '/api/dutyleger'
const overtimeColumns = ["记录编号", "入井人员", "所属班组", "入井时间", "在井时长", "出勤区域", "携带设备"]
const missingColumns = ["记录编号", "入井人员", "所属班组", "入井时间", "缺口时段", "出勤区域"]

const ledger = ref<Ledger | null>(null)
const overtimeRows = ref<Row[]>([])
const missingRows = ref<Row[]>([])
const stats = ref([{ label: '在井人数', value: 0 }, { label: '入井中', value: 0 }, { label: '超时未升', value: 0 }, { label: '升井缺测', value: 0 }, { label: '已联系', value: 0 }])
const errorMessage = ref('')

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await fetchJson<Ledger>(ENDPOINT)
    ledger.value = payload
    overtimeRows.value = payload['超时未升名单'] ?? []
    missingRows.value = payload['升井缺测名单'] ?? []
    stats.value = [
      { label: '在井人数', value: payload['在井人数'] },
      { label: '入井中', value: payload.counts['入井中'] ?? 0 },
      { label: '超时未升', value: payload.counts['超时未升'] ?? 0 },
      { label: '升井缺测', value: payload.counts['升井缺测'] ?? 0 },
      { label: '已联系', value: payload.counts['已联系'] ?? 0 },
    ]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '值班台账读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.section-title {
  margin: 16px 0 8px;
  font-size: 14px;
}
</style>
