<template>
  <section class="page" data-module="shift">
    <header class="page-head">
      <div>
        <h2>入井管理</h2>
        <p class="page-desc">
          缺测与超时分开处理：升井时间未上报的按空态展示并标出缺口时段；超过规定时长仍未升井的判超时未升。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记入井记录</button>
        <button class="btn" type="button" @click="exportRows">导出入井管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>记录编号</span>
        <input v-model="keyword" placeholder="按记录编号检索" />
      </label>
      <label class="filter-item">
        <span>入井状态</span>
        <select v-model="status">
          <option value="">全部</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="showDetail(row)">详情</button>
            <button
              v-for="action in actionsFor(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!actionsFor(row).length" class="action-empty">—</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无入井管理数据，可先登记入井记录</td>
        </tr>
      </tbody>
    </table>

    <aside v-if="detail" class="detail-panel">
      <header class="detail-head">
        <h3>入井记录详情 · {{ detail['记录编号'] }}</h3>
        <button class="link" type="button" @click="detail = null">收起</button>
      </header>
      <dl class="detail-grid">
        <template v-for="field in detailFields" :key="field">
          <dt>{{ field }}</dt>
          <dd>{{ detail[field] ?? '—' }}</dd>
        </template>
      </dl>
      <p class="detail-note">{{ detail['状态说明'] }}</p>
      <p class="detail-note">人员定位对照：{{ detail['定位参考'] }}</p>
    </aside>

    <footer class="page-foot">
      <span>共 {{ total }} 条入井管理记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, string | number | null>
type Summary = {
  统计时刻: string
  在井人数: number
  口径: string
  counts: Record<string, number>
}

const ENDPOINT = '/api/shift'
const columns = ["记录编号", "入井人员", "所属班组", "入井时间", "升井时间", "缺口时段", "补登时刻", "在井时长", "入井状态"]
const statuses = ["入井中", "升井缺测", "超时未升", "已升井", "已联系"]
const detailFields = ["记录编号", "入井人员", "所属班组", "入井时间", "升井时间", "携带设备", "出勤区域", "最近上报", "缺口时段", "补登时刻", "在井时长", "入井状态"]
// 每种状态可执行的动作：缺测走续传/补登，超时先联系再登记升井，已升井没有后续动作
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  "入井中": ["登记升井"],
  "升井缺测": ["续传恢复", "补登升井"],
  "超时未升": ["超时联系", "登记升井"],
  "已联系": ["登记升井"],
  "已升井": [],
}

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref([{ label: '在井人数', value: 0 }, { label: '入井中', value: 0 }, { label: '超时未升', value: 0 }, { label: '升井缺测', value: 0 }])
const keyword = ref('')
const status = ref('')
const detail = ref<Row | null>(null)
const noticeMessage = ref('')
const errorMessage = ref('')

function actionsFor(row: Row): string[] {
  return ACTIONS_BY_STATUS[String(row['入井状态'] ?? '')] ?? []
}

function resetFilters() {
  keyword.value = ''
  status.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function openCreate() {
  errorMessage.value = ''
  noticeMessage.value = ''
  const 入井人员 = window.prompt('入井人员姓名')
  if (!入井人员) return
  const 所属班组 = window.prompt('所属班组')
  if (!所属班组) return
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { 入井人员, 所属班组 } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      errorMessage.value = payload.message || '入井记录登记失败'
      return
    }
    noticeMessage.value = payload.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '入井记录登记失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  const values: Record<string, string> = { action }
  if (action === '补登升井') {
    // 补登的是实际升井时间；留空则由后端取当前时刻，补登时刻只记一次
    const input = window.prompt('补登升井时间（格式 2026-10-05 08:30，留空取当前时刻）', '')
    if (input === null) return
    if (input.trim()) values['升井时间'] = input.trim()
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      errorMessage.value = payload.message || '入井管理动作未生效'
      return
    }
    noticeMessage.value = payload.message
    if (detail.value && detail.value.id === row.id) {
      await showDetail(row)
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '入井管理操作失败'
  }
}

async function showDetail(row: Row) {
  errorMessage.value = ''
  try {
    detail.value = await fetchJson<Row>(`${ENDPOINT}/${row.id}`)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '入井记录详情读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value.trim()) query.set('keyword', keyword.value.trim())
  if (status.value) query.set('status', status.value)
  try {
    const payload = await fetchJson<{ items: Row[]; total: number }>(`${ENDPOINT}?${query}`)
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    const summary = await fetchJson<Summary>(`${ENDPOINT}/summary`)
    stats.value = [
      { label: '在井人数', value: summary['在井人数'] },
      { label: '入井中', value: summary.counts['入井中'] ?? 0 },
      { label: '超时未升', value: summary.counts['超时未升'] ?? 0 },
      { label: '升井缺测', value: summary.counts['升井缺测'] ?? 0 },
    ]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '入井管理列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.detail-panel {
  margin-top: 12px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
}
.detail-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.detail-head h3 {
  margin: 0;
  font-size: 14px;
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(4, auto 1fr);
  gap: 6px 12px;
  margin: 10px 0;
  font-size: 13px;
}
.detail-grid dt {
  color: var(--muted);
}
.detail-grid dd {
  margin: 0;
}
.detail-note {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--muted);
}
.notice-text {
  color: #067647;
}
.action-empty {
  color: var(--muted);
}
</style>
