<script setup>
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'

// 12 个模块 = 12 个“商品”，按四大类归组；分组与侧边栏一致
const modules = [
  { path: '/dashboard', label: '生产总览', icon: '⌂', group: '运营', tint: 'blue',
    desc: '工单、车队、质量与设备异常的运营总览', hot: ['总览', '看板', '首页'] },
  { path: '/work-orders', label: '生产工单', icon: '▤', group: '运营', tint: 'indigo',
    desc: '计划、运输、质检与异常的统一业务主线', hot: ['工单', '排产', '主线'] },
  { path: '/alerts', label: '告警中心', icon: '◉', group: '运营', tint: 'rose',
    desc: '统一确认与处置设备、质量和交期异常', hot: ['告警', '异常', '处置'] },

  { path: '/dispatch', label: '调度中心', icon: '⌁', group: '生产执行', tint: 'teal',
    desc: '单台智能调度与多台 AGV 协同调度', hot: ['调度', 'AGV', '协同'] },
  { path: '/tasks', label: '运输任务', icon: '◇', group: '生产执行', tint: 'cyan',
    desc: '运输任务生命周期、路线与执行状态管理', hot: ['任务', '运输', '路线'] },
  { path: '/map', label: '地图监控', icon: '◎', group: '生产执行', tint: 'emerald',
    desc: '仓库拓扑、AGV 位置与实时规划路线', hot: ['地图', '定位', '路线'] },
  { path: '/plans', label: '生产计划', icon: '▥', group: '生产执行', tint: 'amber',
    desc: '预测驱动的计划、排程与执行工单追踪', hot: ['计划', '排程', '预测'] },

  { path: '/agvs', label: 'AGV 管理', icon: '▣', group: '资源与质量', tint: 'sky',
    desc: '车辆状态、电量、载重与位置管理', hot: ['车辆', '电量', '载重'] },
  { path: '/equipment', label: '设备监测', icon: '◈', group: '资源与质量', tint: 'violet',
    desc: '传感器状态分类、磨损识别与规则告警', hot: ['设备', '振动', '磨损'] },
  { path: '/vision', label: '视觉质检', icon: '◍', group: '资源与质量', tint: 'fuchsia',
    desc: '裂纹、缺陷与工件识别并关联工单', hot: ['质检', '缺陷', '图像'] },

  { path: '/forecast', label: '订单预测', icon: '◒', group: '计划与系统', tint: 'orange',
    desc: '需求预测、模型回测与生产计划生成', hot: ['预测', '需求', '模型'] },
  { path: '/master-data', label: '主数据管理', icon: '▦', group: '计划与系统', tint: 'slate',
    desc: '站点、产品和设备的统一编码档案', hot: ['编码', '档案', '站点'] },
]

const groups = ['全部', '运营', '生产执行', '资源与质量', '计划与系统']
const activeGroup = ref('全部')
const keyword = ref('')

const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  return modules.filter((m) => {
    const inGroup = activeGroup.value === '全部' || m.group === activeGroup.value
    const inKey = !k
      || m.label.toLowerCase().includes(k)
      || m.desc.toLowerCase().includes(k)
      || m.hot.some((h) => h.toLowerCase().includes(k))
    return inGroup && inKey
  })
})

const hotWords = ['工单', '调度', '告警', '缺陷', '预测', 'AGV']
const countByGroup = (g) => (g === '全部' ? modules.length : modules.filter((m) => m.group === g).length)
</script>

<template>
  <div class="wb">
    <!-- ① 头部横幅：搜索 + 热词，模仿电商首页的“搜索入口” -->
    <section class="hero">
      <div class="hero-copy">
        <div class="hero-eyebrow">智能调度 · 生产运营</div>
        <h1 class="hero-title">今天要处理什么？</h1>
        <div class="search-box">
          <span class="search-icon">⌕</span>
          <input v-model="keyword" type="text" placeholder="搜索模块、功能或关键词，例如：工单 / 缺陷 / 预测" />
          <button v-if="keyword" class="search-clear" @click="keyword = ''">清除</button>
        </div>
        <div class="hot-row">
          <span class="hot-label">热门</span>
          <button v-for="w in hotWords" :key="w" class="hot-chip" @click="keyword = w">{{ w }}</button>
        </div>
      </div>
      <div class="hero-side">
        <div class="mini-card">
          <span class="mini-label">在线服务</span>
          <strong>12</strong>
          <small>模块可用</small>
        </div>
        <div class="mini-card">
          <span class="mini-label">当前分组</span>
          <strong>{{ activeGroup }}</strong>
          <small>{{ filtered.length }} 个入口</small>
        </div>
      </div>
    </section>

    <!-- ② 左侧分类 + 右侧卡片网格 -->
    <div class="body">
      <aside class="rail">
        <div class="rail-title">功能分类</div>
        <button
          v-for="g in groups" :key="g"
          class="rail-item" :class="{ active: activeGroup === g }"
          @click="activeGroup = g">
          <span>{{ g }}</span>
          <em>{{ countByGroup(g) }}</em>
        </button>
        <div class="rail-note">
          找不到？直接用上面的搜索框，支持按关键词过滤。
        </div>
      </aside>

      <main class="grid-area">
        <div v-if="filtered.length" class="cards">
          <RouterLink v-for="m in filtered" :key="m.path" :to="m.path" class="card" :class="`tint-${m.tint}`">
            <div class="card-top">
              <span class="card-icon">{{ m.icon }}</span>
              <span class="card-group">{{ m.group }}</span>
            </div>
            <div class="card-title">{{ m.label }}</div>
            <p class="card-desc">{{ m.desc }}</p>
            <div class="card-foot">
              <span class="card-hint">进入 →</span>
              <span class="card-tag">{{ m.hot[0] }}</span>
            </div>
          </RouterLink>
        </div>
        <div v-else class="empty">
          <span class="empty-icon">⌕</span>
          <div class="empty-title">没有匹配的模块</div>
          <div class="empty-desc">换个关键词，或点左侧「全部」恢复</div>
          <button class="btn btn-sm" @click="keyword = ''; activeGroup = '全部'">重置筛选</button>
        </div>
      </main>

      <aside class="side">
        <section class="side-card">
          <div class="side-title">快捷操作</div>
          <RouterLink class="quick" to="/work-orders">＋ 新建生产工单</RouterLink>
          <RouterLink class="quick" to="/dispatch">⌁ 发起一次调度</RouterLink>
          <RouterLink class="quick" to="/vision">◍ 上传缺陷图片</RouterLink>
        </section>
        <section class="side-card">
          <div class="side-title">使用提示</div>
          <p class="side-tip">所有模块共享同一套工单主线：下达 → 调度 → 运输 → 质检 → 完成。</p>
          <p class="side-tip">异常会自动汇入告警中心，不必逐个页面查找。</p>
        </section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.wb { display: grid; gap: 18px; }

/* ---------- 头部横幅 ---------- */
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 18px;
  padding: 26px 28px;
  border-radius: 18px;
  background:
    radial-gradient(760px 320px at 4% -18%, rgba(185,226,106,.3), transparent 62%),
    radial-gradient(720px 300px at 96% -6%, rgba(47,214,195,.26), transparent 62%),
    linear-gradient(135deg, #08281c 0%, #0b3527 46%, #04160f 100%);
  border: 1px solid rgba(163,233,195,.18);
}
.hero-eyebrow { color: var(--cyan); font-size: 11px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }
.hero-title { margin: 6px 0 14px; font-size: 26px; line-height: 1.2; color: #f6fdf9; font-weight: 760; }

.search-box {
  display: flex; align-items: center; gap: 10px;
  height: 46px; padding: 0 8px 0 14px;
  background: rgba(2,14,9,.5); border: 1px solid rgba(163,233,195,.26); border-radius: 999px;
  box-shadow: inset 0 1px 3px rgba(0,0,0,.4);
}
.search-icon { color: var(--cyan); font-size: 16px; }
.search-box input { flex: 1; min-width: 0; height: 100%; border: 0; outline: 0; font-size: 13px; color: var(--text); background: transparent; }
.search-clear { border: 0; background: rgba(255,255,255,.1); color: var(--muted); font-size: 11px; padding: 5px 10px; border-radius: 999px; cursor: pointer; }

.hot-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.hot-label { color: var(--muted); font-size: 11px; }
.hot-chip {
  border: 1px solid var(--line); background: rgba(255,255,255,.07); color: var(--text-soft);
  font-size: 11.5px; padding: 4px 11px; border-radius: 999px; cursor: pointer;
  transition: all 140ms ease;
}
.hot-chip:hover { border-color: var(--cyan); color: var(--cyan); transform: translateY(-1px); }

.hero-side { display: grid; gap: 12px; align-content: center; }
.mini-card {
  display: grid; gap: 2px; padding: 14px 16px;
  background: rgba(255,255,255,.07); border: 1px solid var(--line); border-radius: 14px;
}
.mini-label { color: var(--muted); font-size: 11px; }
.mini-card strong { color: #f6fdf9; font-size: 22px; font-weight: 800; font-variant-numeric: tabular-nums; }
.mini-card small { color: var(--muted); font-size: 10.5px; }

/* ---------- 主体三栏 ---------- */
.body { display: grid; grid-template-columns: 168px minmax(0, 1fr) 250px; gap: 18px; align-items: start; }

.rail {
  display: grid; gap: 4px; padding: 12px;
  background: var(--glass); border: 1px solid var(--line); border-radius: 14px;
  position: sticky; top: 12px;
}
.rail-title { color: var(--muted); font-size: 11px; letter-spacing: .1em; padding: 4px 8px 8px; }
.rail-item {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 9px 10px; border: 0; border-radius: 9px; background: transparent;
  color: var(--text-soft); font-size: 12.5px; text-align: left; cursor: pointer;
  transition: background 140ms ease, color 140ms ease;
}
.rail-item em { color: var(--muted); font-size: 10.5px; font-style: normal; font-variant-numeric: tabular-nums; }
.rail-item:hover { background: var(--nav-hover-bg); }
.rail-item.active { background: var(--nav-active-bg); border-color: var(--nav-active-line); color: var(--nav-active-fg); font-weight: 700; }
.rail-item.active em { color: var(--nav-active-icon); }
.rail-note { margin-top: 8px; padding: 8px; border-top: 1px dashed var(--line); color: var(--muted); font-size: 10.5px; line-height: 1.6; }

/* ---------- 卡片网格 ---------- */
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 14px; }
.card {
  position: relative; display: grid; gap: 6px; padding: 16px 16px 14px;
  background: var(--glass); border: 1px solid var(--line); border-radius: 14px;
  text-decoration: none; overflow: hidden;
  transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease;
}
.card::after {
  content: ""; position: absolute; inset: -40% 60% 60% -40%;
  background: radial-gradient(circle, currentColor 0%, transparent 70%);
  opacity: .05; pointer-events: none;
}
.card:hover { transform: translateY(-3px); box-shadow: 0 12px 26px rgba(16,34,43,.1); border-color: transparent; }
.card-top { display: flex; align-items: center; justify-content: space-between; }
.card-icon {
  display: grid; place-items: center; width: 38px; height: 38px; border-radius: 11px;
  font-size: 17px; color: #fff;
  background: linear-gradient(135deg, var(--tint) 0%, color-mix(in srgb, var(--tint) 72%, #0b2a35) 100%);
  box-shadow: 0 6px 14px color-mix(in srgb, var(--tint) 28%, transparent);
}
.card-group { color: var(--muted); font-size: 10.5px; padding: 3px 8px; border-radius: 999px; background: var(--fill-2); }
.card-title { margin-top: 6px; color: var(--text); font-size: 15px; font-weight: 700; }
.card-desc { margin: 0; color: var(--muted); font-size: 11.5px; line-height: 1.6; min-height: 36px; }
.card-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 6px; padding-top: 8px; border-top: 1px dashed var(--line); }
.card-hint { color: var(--tint); font-size: 11.5px; font-weight: 700; opacity: .9; }
.card-tag { color: var(--muted); font-size: 10.5px; }

/* 每种色调：只用 --tint 一个变量，图标、箭头、光晕都跟着走 */
.tint-blue { --tint: #6f9cff; } .tint-indigo { --tint: #8b8cf5; } .tint-rose { --tint: #ff7fa0; }
.tint-teal { --tint: #2fd6c3; } .tint-cyan { --tint: #45d9e6; } .tint-emerald { --tint: #55e08c; }
.tint-amber { --tint: #f3c04b; } .tint-sky { --tint: #5fb8f7; } .tint-violet { --tint: #b795ff; }
.tint-fuchsia { --tint: #e57fe0; } .tint-orange { --tint: #ff9d5c; } .tint-slate { --tint: #9fb6ab; }

/* ---------- 右栏 ---------- */
.side { display: grid; gap: 14px; }
.side-card { padding: 14px 16px; background: var(--glass); border: 1px solid var(--line); border-radius: 14px; display: grid; gap: 8px; }
.side-title { color: var(--text); font-size: 12.5px; font-weight: 700; }
.quick { color: var(--link-fg); font-size: 12px; text-decoration: none; padding: 7px 9px; border-radius: 8px; background: var(--fill-2); }
.quick:hover { background: var(--accent-tint-weak); }
.side-tip { margin: 0; color: var(--muted); font-size: 11px; line-height: 1.65; }

/* ---------- 空状态 ---------- */
.empty { display: grid; justify-items: center; gap: 6px; padding: 60px 12px; text-align: center; }
.empty-icon { display: grid; place-items: center; width: 44px; height: 44px; border-radius: 50%; background: var(--fill-2); color: var(--muted); font-size: 20px; }
.empty-title { color: var(--text); font-size: 13px; font-weight: 700; }
.empty-desc { color: var(--muted); font-size: 11.5px; }

/* ---------- 响应式 ---------- */
@media (max-width: 1280px) {
  .body { grid-template-columns: 150px minmax(0, 1fr); }
  .side { display: none; }
}
@media (max-width: 900px) {
  .hero { grid-template-columns: 1fr; }
  .hero-side { grid-template-columns: repeat(2, 1fr); }
  .body { grid-template-columns: 1fr; }
  .rail { position: static; }
  .rail-item { justify-content: flex-start; gap: 10px; }
}
</style>
