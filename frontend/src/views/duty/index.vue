<template>
  <section class="page" data-module="duty">
    <header class="page-head">
      <div>
        <h2>值班台账</h2>
        <p class="page-desc">
          在井人数与超时未升名单直接取自入井管理（/api/shift），两边始终是同一份数据；
          超时记录在入井管理页补登升井后，本名单自动移除。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="reload">刷新台账</button>
        <RouterLink class="btn" to="/shift">前往入井管理处理 →</RouterLink>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card stat-key">
        <span class="stat-label">在井人数（= 入井中 + 超时未升）</span>
        <strong class="stat-value">{{ headcount['在井人数'] ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">入井中</span>
        <strong class="stat-value">{{ headcount['入井中人数'] ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">超时未升</span>
        <strong class="stat-value num-warn">{{ headcount['超时未升人数'] ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">缺测（人在否未知，不计入在井）</span>
        <strong class="stat-value num-missing">{{ headcount['缺测人数'] ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">已升井</span>
        <strong class="stat-value">{{ headcount['已升井人数'] ?? 0 }}</strong>
      </article>
    </div>

    <h3 class="list-title">超时未升名单</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>处理入口</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in overtimeRows" :key="String(row.id)">
          <td>{{ row['记录编号'] }}</td>
          <td>{{ row['入井人员'] }}</td>
          <td>{{ row['所属班组'] }}</td>
          <td>{{ row['出勤区域'] ?? '—' }}</td>
          <td>{{ row['入井时间'] ?? '—' }}</td>
          <td>{{ row['在井时长'] ?? '—' }}</td>
          <td>
            <span class="status-badge" :class="row['入井状态'] === '缺测' ? 'badge-missing' : 'badge-overdue'">
              {{ row['入井状态'] }}
            </span>
          </td>
          <td>
            <span v-if="gapsOf(row).length" class="gap-hint">含已续接缺口 {{ gapsOf(row).length }} 段</span>
            <RouterLink class="link" :to="{ path: '/shift' }">去补登升井</RouterLink>
          </td>
        </tr>
        <tr v-if="!overtimeRows.length">
          <td :colspan="columns.length + 1" class="empty-state">当前没有超时未升人员</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ overtimeRows.length }} 名超时未升人员 · 统计口径：入井管理 /api/shift/headcount</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Gap = { '开始时间': string; '结束时间': string | null }
type Row = { id?: number; gaps?: Gap[] } & Record<string, unknown>

function gapsOf(row: Row): Gap[] {
  return Array.isArray(row.gaps) ? row.gaps : []
}

const columns = ['记录编号', '入井人员', '所属班组', '出勤区域', '入井时间', '累计在井时长', '状态']
const overtimeRows = ref<Row[]>([])
const headcount = ref<Record<string, number>>({})
const errorMessage = ref('')

async function reload() {
  errorMessage.value = ''
  try {
    const [overtimeRes, countRes] = await Promise.all([
      request('/api/shift/overtime'),
      request('/api/shift/headcount'),
    ])
    if (!overtimeRes.ok || !countRes.ok) throw new Error('值班台账读取失败')
    const overtime = await overtimeRes.json()
    overtimeRows.value = overtime.items ?? []
    headcount.value = await countRes.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '值班台账读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.stat-key { border-color: #1f6feb; box-shadow: inset 0 2px 0 #1f6feb; }
.num-warn { color: #b42318; }
.num-missing { color: #b54708; }
.list-title { font-size: 14px; margin: 18px 0 8px; }
.gap-hint { display: block; font-size: 11px; color: #b54708; margin-bottom: 2px; }
.status-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; }
.badge-overdue { background: #fee4e2; color: #b42318; }
.badge-missing { background: #fef3c7; color: #b54708; }
</style>
