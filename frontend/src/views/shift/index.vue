<template>
  <section class="page" data-module="shift">
    <header class="page-head">
      <div>
        <h2>入井管理</h2>
        <p class="page-desc">
          维护入井/升井记录：升井时间未上报且定位数据中断记为「缺测」并标出缺口时段；
          数据连续但超过规定时长（{{ limitHours }} 小时）仍未升井记为「超时未升」，两种异常分开处理。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记入井记录</button>
        <button class="btn" type="button" @click="exportRows">导出入井管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">在井人数（同值班台账）</span>
        <strong class="stat-value">{{ headcount['在井人数'] ?? 0 }}</strong>
      </article>
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="item.cls">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>记录编号</span>
        <input v-model="filters.keyword" placeholder="按记录编号检索" />
      </label>
      <label class="filter-item">
        <span>入井人员</span>
        <input v-model="filters.person" placeholder="按姓名检索" />
      </label>
      <label class="filter-item">
        <span>入井状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
      <RouterLink class="ledger-link" to="/duty">前往值班台账查看超时名单 →</RouterLink>
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
          <td>{{ row['记录编号'] }}</td>
          <td>{{ row['入井人员'] }}</td>
          <td>{{ row['所属班组'] }}</td>
          <td>{{ row['入井时间'] ?? '—' }}</td>
          <td>
            <template v-if="row['升井时间显示']">{{ row['升井时间显示'] }}</template>
            <div v-else class="gap-cell">
              <span class="tag tag-muted">升井时间未上报</span>
              <span v-if="row['缺口时段']" class="gap-text">{{ row['缺口时段'] }}</span>
            </div>
          </td>
          <td>
            {{ row['在井时长'] ?? '—' }}
            <span v-if="row['入井状态'] === '超时未升'" class="tag tag-overdue">已超{{ limitHours }}小时</span>
          </td>
          <td>{{ row['出勤区域'] ?? '—' }}</td>
          <td>
            <span class="status-badge" :class="statusClass(row['入井状态'])">{{ row['入井状态'] }}</span>
            <div v-if="row['补登']" class="supplement-hint">事后补登</div>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button
              v-if="isOpen(row) && !hasOpenGap(row)"
              class="link"
              type="button"
              @click="runAction('上报缺口', row)"
            >
              上报缺口
            </button>
            <button
              v-if="hasOpenGap(row)"
              class="link"
              type="button"
              @click="runAction('续接记录', row)"
            >
              续接记录
            </button>
            <button
              v-if="canSupplement(row)"
              class="link link-warn"
              type="button"
              @click="openSupplement(row)"
            >
              补登升井
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无符合条件的入井记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条入井记录</span>
      <span v-if="notice" :class="noticeOk ? 'ok-text' : 'error-text'">{{ notice }}</span>
    </footer>

    <!-- 补登升井弹窗 -->
    <div v-if="supplementTarget" class="modal-mask" @click.self="supplementTarget = null">
      <div class="modal">
        <h3>补登升井 · {{ supplementTarget['入井人员'] }}（{{ supplementTarget['记录编号'] }}）</h3>
        <p class="modal-tip">
          当前状态「{{ supplementTarget['入井状态'] }}」。补登后记录回到已升井；
          补登时刻只记录一次，重复补登不生效。时间留空则取当前时刻。
        </p>
        <label class="form-item">
          <span>实际升井时间</span>
          <input v-model="supplementTime" type="datetime-local" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="supplementTarget = null">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="confirmSupplement">确认补登</button>
        </div>
      </div>
    </div>

    <!-- 登记入井弹窗 -->
    <div v-if="creating" class="modal-mask" @click.self="creating = false">
      <div class="modal">
        <h3>登记入井记录</h3>
        <label v-for="f in createFields" :key="f.key" class="form-item">
          <span>{{ f.label }}<em v-if="f.required">*</em></span>
          <input v-model="createForm[f.key]" :type="f.type ?? 'text'" :placeholder="f.placeholder ?? ''" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="creating = false">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="confirmCreate">登记</button>
        </div>
      </div>
    </div>

    <!-- 详情抽屉 -->
    <div v-if="detail" class="drawer-mask" @click.self="detail = null">
      <aside class="drawer">
        <header class="drawer-head">
          <h3>入井记录详情 · {{ detail['记录编号'] }}</h3>
          <button class="link" type="button" @click="detail = null">关闭</button>
        </header>

        <div class="detail-status">
          <span class="status-badge big" :class="statusClass(detail['入井状态'])">{{ detail['入井状态'] }}</span>
          <p class="status-explain">{{ statusExplain(detail) }}</p>
        </div>

        <dl class="detail-grid">
          <template v-for="f in detailFields" :key="f.key">
            <dt>{{ f.label }}</dt>
            <dd>{{ detail[f.key] ?? '—' }}</dd>
          </template>
          <dt>规定在井时长</dt>
          <dd>{{ limitHours }} 小时</dd>
          <dt>累计在井时长</dt>
          <dd>{{ detail['在井时长'] ?? '—' }}</dd>
          <dt>是否补登</dt>
          <dd>{{ detail['补登'] ? `是（补登登记时刻：${detail['补登时刻'] ?? '—'}）` : '否' }}</dd>
        </dl>

        <h4 class="detail-sub">升井时间</h4>
        <p v-if="detail['升井时间显示']" class="detail-line">
          {{ detail['升井时间显示'] }}<span v-if="detail['补登']" class="tag tag-muted">事后补登，仅记录一次</span>
        </p>
        <div v-else class="detail-line gap-box">
          <span class="tag tag-muted">升井时间未上报（空态）</span>
          <span v-if="detail['入井状态'] === '超时未升'" class="tag tag-overdue">
            数据未中断且已超 {{ limitHours }} 小时，判超时未升，不按缺测处理
          </span>
        </div>

        <h4 class="detail-sub">数据缺口时段（续接在原记录上）</h4>
        <ul v-if="gapsOf(detail).length" class="gap-list">
          <li v-for="(g, i) in gapsOf(detail)" :key="i">
            <span>{{ g['开始时间'] }} ~ {{ g['结束时间'] ?? '中断中，待续接' }}</span>
            <span class="gap-meta">{{ g['来源'] ?? '值班登记' }}{{ g['闭合方式'] ? ` · ${g['闭合方式']}` : '' }}</span>
          </li>
        </ul>
        <p v-else class="detail-line muted">无数据中断缺口</p>

        <h4 class="detail-sub">人员定位对照</h4>
        <dl class="detail-grid">
          <dt>定位终端编号</dt>
          <dd>{{ detail['定位终端编号'] ?? '未绑定' }}</dd>
          <dt>终端在线状态</dt>
          <dd>
            <span v-if="detail['定位终端状态']" class="status-badge" :class="personnelStatusClass(detail['定位终端状态'])">
              {{ detail['定位终端状态'] }}
            </span>
            <span v-else>—</span>
          </dd>
          <dt>最后位置</dt>
          <dd>{{ detail['定位所在位置'] ?? '—' }}</dd>
          <dt>对照结论</dt>
          <dd>{{ detail['定位对照'] ?? '—' }}</dd>
        </dl>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Gap = { '开始时间': string; '结束时间': string | null; '来源'?: string; '闭合方式'?: string }
type Row = { id?: number; gaps?: Gap[] } & Record<string, unknown>

function gapsOf(row: Row): Gap[] {
  return Array.isArray(row.gaps) ? row.gaps : []
}
function hasOpenGap(row: Row): boolean {
  return gapsOf(row).some((g) => !g['结束时间'])
}
function isOpen(row: Row): boolean {
  return openStatuses.includes(String(row['入井状态'] ?? ''))
}
function canSupplement(row: Row): boolean {
  return ['超时未升', '缺测'].includes(String(row['入井状态'] ?? ''))
}

const ENDPOINT = '/api/shift'
const columns = ['记录编号', '入井人员', '所属班组', '入井时间', '升井时间', '在井时长', '出勤区域', '入井状态']
const statuses = ['入井中', '已升井', '超时未升', '缺测']
const openStatuses = ['入井中', '超时未升', '缺测']
const limitHours = 8

const rows = ref<Row[]>([])
const total = ref(0)
const notice = ref('')
const noticeOk = ref(false)
const submitting = ref(false)
const headcount = ref<Record<string, number>>({})
const filters = reactive<Record<string, string>>({ keyword: '', person: '', status: '' })

const statCards = computed(() => [
  { label: '入井中人数', value: headcount.value['入井中人数'] ?? 0, cls: '' },
  { label: '超时未升人数', value: headcount.value['超时未升人数'] ?? 0, cls: 'num-warn' },
  { label: '缺测人数', value: headcount.value['缺测人数'] ?? 0, cls: 'num-missing' },
  { label: '已升井人数', value: headcount.value['已升井人数'] ?? 0, cls: '' },
])

const detailFields = [
  { key: '记录编号', label: '记录编号' },
  { key: '入井人员', label: '入井人员' },
  { key: '所属班组', label: '所属班组' },
  { key: '入井时间', label: '入井时间' },
  { key: '携带设备', label: '携带设备' },
  { key: '出勤区域', label: '出勤区域' },
  { key: '定位终端编号', label: '绑定定位终端' },
]

// ---- 补登 ----
const supplementTarget = ref<Row | null>(null)
const supplementTime = ref('')

function openSupplement(row: Row) {
  supplementTarget.value = row
  supplementTime.value = ''
}

async function confirmSupplement() {
  if (!supplementTarget.value) return
  const values: Record<string, string> = { action: '补登升井' }
  if (supplementTime.value) values['升井时间'] = supplementTime.value.replace('T', ' ')
  await submitAction(supplementTarget.value.id as number, values)
  supplementTarget.value = null
}

// ---- 登记 ----
const creating = ref(false)
const createFields = [
  { key: '记录编号', label: '记录编号', required: true, placeholder: '如 SHIF-0101' },
  { key: '入井人员', label: '入井人员', required: true },
  { key: '所属班组', label: '所属班组', required: true },
  { key: '入井时间', label: '入井时间', required: true, type: 'datetime-local' },
  { key: '定位终端编号', label: '定位终端编号', placeholder: '如 PERS-0001' },
  { key: '携带设备', label: '携带设备' },
  { key: '出勤区域', label: '出勤区域' },
]
const emptyForm = () => Object.fromEntries(createFields.map((f) => [f.key, '']))
const createForm = reactive<Record<string, string>>(emptyForm())

function openCreate() {
  Object.assign(createForm, emptyForm())
  creating.value = true
}

async function confirmCreate() {
  const values: Record<string, string> = { ...createForm }
  if (values['入井时间']) values['入井时间'] = values['入井时间'].replace('T', ' ')
  notice.value = ''
  submitting.value = true
  try {
    const response = await request(ENDPOINT, { method: 'POST', body: JSON.stringify({ values }) })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message ?? '入井记录登记失败')
    notice.value = payload.message
    noticeOk.value = true
    creating.value = false
    await reload()
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '入井记录登记失败'
    noticeOk.value = false
  } finally {
    submitting.value = false
  }
}

// ---- 详情 ----
const detail = ref<Row | null>(null)

async function openDetail(row: Row) {
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    detail.value = response.ok ? ((await response.json()) as Row) : row
  } catch {
    detail.value = row
  }
}

function statusExplain(row: Row): string {
  switch (row['入井状态']) {
    case '入井中':
      return '升井时间尚未登记，定位数据连续且未超过规定时长，人员在井下作业。'
    case '超时未升':
      return `定位数据连续、终端显示人员仍在井下，但入井已超过 ${limitHours} 小时仍未升井；与“缺测”是两种不同原因。`
    case '缺测':
      return '升井时间未上报且定位数据中断，无法确认人员是否仍在井下；数据恢复后可在本记录上续接，不另开新记录。'
    case '已升井':
      return row['补登'] ? '升井时间为事后补登，补登时刻仅记录一次。' : '升井时间已正常登记，人员已升井。'
    default:
      return ''
  }
}

// ---- 列表动作 ----
async function runAction(action: string, row: Row) {
  await submitAction(row.id as number, { action })
}

async function submitAction(id: number, values: Record<string, string>) {
  notice.value = ''
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/${id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message ?? '操作未生效，请稍后重试')
    notice.value = payload.message
    noticeOk.value = true
    await reload()
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '操作失败'
    noticeOk.value = false
  } finally {
    submitting.value = false
  }
}

function statusClass(status: unknown): string {
  if (status === '超时未升') return 'badge-overdue'
  if (status === '缺测') return 'badge-missing'
  if (status === '已升井') return 'badge-lifted'
  return 'badge-under'
}

function personnelStatusClass(status: unknown): string {
  if (status === '离线') return 'badge-missing'
  if (status === '低电量') return 'badge-warn'
  return 'badge-under'
}

function resetFilters() {
  filters.keyword = ''
  filters.person = ''
  filters.status = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function reload() {
  notice.value = ''
  const params = new URLSearchParams()
  if (filters.keyword) params.set('keyword', filters.keyword)
  if (filters.person) params.set('person', filters.person)
  if (filters.status) params.set('status', filters.status)
  params.set('size', '200')
  try {
    const [listRes, countRes] = await Promise.all([
      request(`${ENDPOINT}?${params.toString()}`),
      request(`${ENDPOINT}/headcount`),
    ])
    if (!listRes.ok) throw new Error('入井记录列表读取失败')
    const payload = await listRes.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (countRes.ok) headcount.value = await countRes.json()
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '入井管理列表读取失败'
    noticeOk.value = false
  }
}

onMounted(reload)
</script>

<style scoped>
.page-actions { display: flex; gap: 8px; }
.num-warn { color: #b42318; }
.num-missing { color: #b54708; }
.ledger-link { font-size: 12px; color: #1f6feb; text-decoration: none; margin-left: auto; }
.ok-text { color: #067647; }
.filter-item select { padding: 6px 8px; border: 1px solid #d8dee6; border-radius: 6px; font-size: 13px; }
.gap-cell { display: flex; flex-direction: column; gap: 2px; }
.gap-text { color: #b54708; font-size: 12px; }
.supplement-hint { font-size: 11px; color: var(--muted); margin-top: 2px; }
.link-warn { color: #b42318; }

.status-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; white-space: nowrap; }
.status-badge.big { font-size: 13px; padding: 4px 12px; }
.badge-under { background: #e8f1fe; color: #1f6feb; }
.badge-overdue { background: #fee4e2; color: #b42318; }
.badge-missing { background: #fef3c7; color: #b54708; }
.badge-lifted { background: #dcfae6; color: #067647; }
.badge-warn { background: #fffaeb; color: #b54708; }

.tag { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 11px; white-space: nowrap; }
.tag-muted { background: #f1f5f9; color: #64748b; }
.tag-overdue { background: #fee4e2; color: #b42318; }

.modal-mask, .drawer-mask {
  position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); z-index: 50;
  display: flex; align-items: center; justify-content: center;
}
.modal { background: #fff; border-radius: 10px; padding: 20px 24px; width: 420px; }
.modal h3 { margin: 0 0 8px; font-size: 16px; }
.modal-tip { font-size: 12px; color: var(--muted); margin: 0 0 12px; line-height: 1.6; }
.form-item { display: block; margin-bottom: 10px; font-size: 12px; color: var(--muted); }
.form-item span { display: block; margin-bottom: 4px; }
.form-item em { color: #b42318; font-style: normal; margin-left: 2px; }
.form-item input { width: 100%; padding: 7px 9px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }

.drawer-mask { justify-content: flex-end; }
.drawer { background: #fff; width: 520px; max-width: 92vw; height: 100%; padding: 20px 24px; overflow-y: auto; }
.drawer-head { display: flex; justify-content: space-between; align-items: center; }
.drawer-head h3 { margin: 0; font-size: 16px; }
.detail-status { margin: 14px 0; padding: 12px; background: #f8fafc; border-radius: 8px; }
.status-explain { margin: 8px 0 0; font-size: 12px; color: #475569; line-height: 1.7; }
.detail-grid { display: grid; grid-template-columns: 110px 1fr; gap: 6px 12px; margin: 0 0 12px; font-size: 13px; }
.detail-grid dt { color: var(--muted); }
.detail-grid dd { margin: 0; }
.detail-sub { font-size: 13px; margin: 16px 0 6px; padding-top: 10px; border-top: 1px solid #eef2f7; }
.detail-line { font-size: 13px; margin: 0 0 6px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.detail-line.muted { color: var(--muted); }
.gap-box { align-items: center; }
.gap-list { list-style: none; margin: 0; padding: 0; font-size: 13px; }
.gap-list li { display: flex; justify-content: space-between; gap: 8px; padding: 6px 0; border-bottom: 1px dashed #e2e8f0; }
.gap-meta { color: var(--muted); font-size: 12px; white-space: nowrap; }
</style>
