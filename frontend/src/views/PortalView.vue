<script setup>
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'

// 12 个模块 = 12 个“商品”，按四大类归组
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

const promos = [
  { to: '/work-orders', title: '工单主线', sub: '下达 · 调度 · 质检 · 完成', tint: 'promo-teal', icon: '▤' },
  { to: '/vision', title: '视觉质检', sub: '缺陷识别并回写工单', tint: 'promo-violet', icon: '◍' },
  { to: '/forecast', title: '订单预测', sub: '需求预测驱动排产', tint: 'promo-amber', icon: '◒' },
]
</script>

<template>
  <div class="portal">
    <!-- ① 深色主视觉 -->
    <section class="hero">
      <div class="glow glow-a"></div>
      <div class="glow glow-b"></div>
      <!-- 背景装饰：一枚极大的浅色词 + 一列竖排等宽标签 -->
      <span class="hero-bgword" aria-hidden="true">WORKBENCH</span>
      <span class="hero-ring" aria-hidden="true"></span>

      <div class="hero-main">
        <div class="brand">
          <img class="brand-logo" src="/logo-agv.svg" alt="AGV" />
          <div>
            <div class="brand-eyebrow">Intelligent Operations Platform</div>
            <div class="brand-name">AGV 制造运营中心</div>
          </div>
        </div>

        <div class="hero-title-row">
          <h1 class="hero-title">今天要处理什么？</h1>
          <span class="hero-ghost" aria-hidden="true">WHAT'S ON TODAY</span>
        </div>
        <p class="hero-sub">12 个模块，用一条“工单主线”串起来：下达 → 调度 → 运输 → 质检 → 完成</p>

        <div class="search-box">
          <span class="search-icon">⌕</span>
          <input v-model="keyword" type="text" placeholder="搜索模块、功能或关键词，例如：工单 / 缺陷 / 预测" />
          <button v-if="keyword" class="search-clear" @click="keyword = ''">清除</button>
          <button class="search-go">搜索</button>
        </div>

        <div class="hot-row">
          <span class="hot-label">热门</span>
          <button v-for="w in hotWords" :key="w" class="hot-chip" @click="keyword = w">{{ w }}</button>
        </div>
      </div>

      <div class="hero-stats">
        <div class="tile">
          <span class="tile-label">可用模块</span>
          <strong>12</strong>
          <small>运营 / 执行 / 质量 / 计划</small>
        </div>
        <div class="tile">
          <span class="tile-label">当前分组</span>
          <strong class="tile-text">{{ activeGroup }}</strong>
          <small>{{ filtered.length }} 个入口</small>
        </div>
      </div>
    </section>

    <!-- ② 三栏 -->
    <div class="body">
      <aside class="rail">
        <div class="rail-title">功能分类</div>
        <button v-for="g in groups" :key="g"
                class="rail-item" :class="{ active: activeGroup === g }"
                @click="activeGroup = g">
          <span>{{ g }}</span><em>{{ countByGroup(g) }}</em>
        </button>
        <div class="rail-note">找不到？用上面的搜索框，支持按关键词过滤。</div>
      </aside>

      <main class="grid-area">
        <div v-if="filtered.length" class="cards">
          <RouterLink v-for="m in filtered" :key="m.path" :to="m.path" class="card" :class="`tint-${m.tint}`">
            <span class="stripe"></span>
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
        <RouterLink v-for="p in promos" :key="p.to" :to="p.to" class="promo" :class="p.tint">
          <div class="promo-copy">
            <div class="promo-title">{{ p.title }}</div>
            <div class="promo-sub">{{ p.sub }}</div>
          </div>
          <span class="promo-icon">{{ p.icon }}</span>
        </RouterLink>

        <section class="side-card">
          <div class="side-title">快捷操作</div>
          <RouterLink class="quick" to="/work-orders">＋ 新建生产工单</RouterLink>
          <RouterLink class="quick" to="/dispatch">⌁ 发起一次调度</RouterLink>
          <RouterLink class="quick" to="/vision">◍ 上传缺陷图片</RouterLink>
        </section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.portal { display: grid; gap: 18px; }

/* ================= 主视觉：森林夜色 + 玻璃 ================= */
.hero {
  position: relative; display: grid;
  grid-template-columns: minmax(0, 1fr) 290px;
  gap: 24px; padding: 26px 30px 24px;
  border-radius: 20px; overflow: hidden; color: #eaf7f0;
  background:
    radial-gradient(760px 320px at 4% -18%, rgba(185,226,106,.34), transparent 62%),
    radial-gradient(720px 300px at 96% -6%, rgba(47,214,195,.30), transparent 62%),
    linear-gradient(135deg, #08281c 0%, #0b3527 46%, #04160f 100%);
  border: 1px solid rgba(163,233,195,.18);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.08), 0 20px 46px rgba(0,0,0,.38);
}
/* 壁纸感的弧形高光 */
.hero::after {
  content: ""; position: absolute; left: -12%; right: -12%; bottom: -64%; height: 120%;
  border-radius: 50% 50% 0 0; pointer-events: none;
  background: radial-gradient(circle at 50% 0%, rgba(185,226,106,.09), transparent 62%);
}
.glow { position: absolute; border-radius: 50%; filter: blur(46px); pointer-events: none; }
.glow-a { width: 280px; height: 280px; right: -70px; top: -110px; background: rgba(47,214,195,.30); }
.glow-b { width: 240px; height: 240px; left: 26%; bottom: -130px; background: rgba(185,226,106,.22); }

/* ---------- 主视觉里的背景排版装饰 ---------- */
.hero-bgword {
  position: absolute; right: 250px; top: 4px; z-index: 0;
  font-family: var(--font-display); font-size: 84px; line-height: 1;
  letter-spacing: .06em; text-transform: uppercase;
  color: rgba(226, 250, 238, 0.05); white-space: nowrap; pointer-events: none;
}
.hero-ring {
  position: absolute; right: -70px; bottom: -160px; z-index: 0;
  width: 380px; height: 380px; border-radius: 50%;
  border: 1px solid rgba(226, 250, 238, 0.08);
  box-shadow: inset 0 0 0 34px rgba(226, 250, 238, 0.02);
  pointer-events: none;
}
@media (max-width: 1180px) {
  .hero-bgword { right: 24px; font-size: 58px; }
}

.hero-main { position: relative; z-index: 1; }
.brand { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.brand-logo { width: 42px; height: 42px; border-radius: 12px; box-shadow: 0 8px 22px rgba(0,0,0,.45), 0 0 0 1px rgba(255,255,255,.14); }
.brand-eyebrow { color: #b9e26a; font-size: 9.5px; font-weight: 700; letter-spacing: .18em; text-transform: uppercase; }
.brand-name { color: #f2fbf6; font-size: 14.5px; font-weight: 750; }

.hero-title-row { display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap; }
.hero-title {
  position: relative; margin: 4px 0 6px; padding-bottom: 5px;
  font-family: var(--font-display); font-size: 32px; line-height: 1.1; font-weight: 900;
  color: #f8fffb; letter-spacing: .005em;
  background-image: linear-gradient(90deg, rgba(185,226,106,.95) 0%, rgba(47,214,195,.75) 58%, transparent 100%);
  background-size: 100% 3px; background-position: 0 100%; background-repeat: no-repeat;
}
.hero-title::before, .hero-title::after {
  content: ""; position: absolute; width: 10px; height: 10px;
  border: 0 solid rgba(185, 226, 106, 0.55);
}
.hero-title::before { left: -11px; top: -3px; border-width: 1.5px 0 0 1.5px; }
.hero-title::after { right: -10px; bottom: 5px; border-width: 0 1.5px 1.5px 0; }
.hero-ghost {
  font-family: var(--font-ghost); font-size: 24px; font-weight: 300; line-height: 1;
  letter-spacing: .14em; text-transform: uppercase; color: rgba(226, 247, 236, 0.2);
  white-space: nowrap; user-select: none; pointer-events: none;
}
.hero-sub { margin: 0 0 16px; color: rgba(214,236,224,.72); font-size: 12.5px; }

.search-box {
  display: flex; align-items: center; gap: 8px; height: 46px; padding: 0 6px 0 16px;
  background: rgba(2,14,9,.55); border: 1px solid rgba(163,233,195,.26); border-radius: 999px;
  box-shadow: inset 0 1px 3px rgba(0,0,0,.4), 0 10px 26px rgba(0,0,0,.28);
  transition: border-color 160ms ease, box-shadow 160ms ease;
}
.search-box:focus-within { border-color: rgba(47,214,195,.62); box-shadow: 0 0 0 3px rgba(47,214,195,.16), inset 0 1px 3px rgba(0,0,0,.4); }
.search-icon { color: var(--lime); font-size: 16px; }
.search-box input { flex: 1; min-width: 0; height: 100%; border: 0; outline: 0; font-size: 13px; color: #eaf7f0; background: transparent; box-shadow: none; }
.search-box input::placeholder { color: #7e9c8c; }
.search-clear { border: 0; background: rgba(255,255,255,.1); color: var(--text-soft); font-size: 11px; padding: 5px 10px; border-radius: 999px; cursor: pointer; }
.search-clear:hover { background: rgba(255,255,255,.18); color: #fff; }
.search-go {
  height: 34px; padding: 0 20px; border: 0; border-radius: 999px; cursor: pointer;
  background: linear-gradient(180deg, #c6ee7f, #8ad772); color: #062313; font-size: 12.5px; font-weight: 750;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.5), 0 6px 16px rgba(126,202,108,.3);
}
.search-go:hover { filter: brightness(1.06); }

.hot-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 13px; }
.hot-label { color: rgba(214,236,224,.55); font-size: 11px; }
.hot-chip {
  border: 1px solid rgba(255,255,255,.16); background: rgba(255,255,255,.07);
  color: #dcf5e8; font-size: 11.5px; padding: 4px 12px; border-radius: 999px; cursor: pointer;
  transition: all 140ms ease;
}
.hot-chip:hover { background: rgba(185,226,106,.2); border-color: rgba(185,226,106,.5); color: #f4ffd9; transform: translateY(-1px); }

.hero-stats { position: relative; z-index: 1; display: grid; gap: 12px; align-content: center; }
.tile {
  display: grid; gap: 2px; padding: 14px 16px; border-radius: 14px;
  background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.14);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.08);
  backdrop-filter: blur(10px);
}
.tile-label { color: rgba(214,236,224,.6); font-size: 10.5px; }
.tile strong { color: #f6fdf9; font-size: 24px; font-weight: 780; font-variant-numeric: tabular-nums; line-height: 1.15; }
.tile .tile-text { font-size: 16px; }
.tile small { color: rgba(214,236,224,.5); font-size: 10px; }

/* ================= 三栏 ================= */
.body { display: grid; grid-template-columns: 168px minmax(0, 1fr) 252px; gap: 18px; align-items: start; }

.rail {
  display: grid; gap: 3px; padding: 11px;
  background: var(--glass); border: 1px solid var(--line); border-radius: 16px;
  box-shadow: var(--shadow); backdrop-filter: blur(16px);
  position: sticky; top: 12px;
}
.rail-title { color: var(--faint); font-size: 10px; letter-spacing: .12em; padding: 4px 8px 7px; }
.rail-item {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 8px 10px; border: 1px solid transparent; border-radius: 9px; background: transparent;
  color: var(--text-soft); font-size: 12px; text-align: left; cursor: pointer; transition: all 140ms ease;
}
.rail-item em { color: var(--faint); font-size: 10.5px; font-style: normal; font-variant-numeric: tabular-nums; }
.rail-item:hover { background: var(--nav-hover-bg); color: var(--text); }
.rail-item.active { background: var(--nav-active-bg); border-color: var(--nav-active-line); color: var(--nav-active-fg); font-weight: 650; box-shadow: var(--nav-active-shadow); }
.rail-item.active em { color: var(--nav-active-icon); }
.rail-note { margin-top: 8px; padding: 8px 2px 2px; border-top: 1px dashed var(--line); color: var(--faint); font-size: 10px; line-height: 1.65; }

/* ================= 卡片 ================= */
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(228px, 1fr)); gap: 14px; }
.card {
  position: relative; display: grid; gap: 6px; padding: 16px 16px 14px 18px;
  background: var(--glass); border: 1px solid var(--line); border-radius: 16px;
  text-decoration: none; overflow: hidden;
  box-shadow: var(--shadow); backdrop-filter: blur(16px);
  transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease, background 160ms ease;
}
.card::after {
  content: ""; position: absolute; right: -40px; bottom: -60px; width: 160px; height: 160px; border-radius: 50%;
  background: radial-gradient(circle, var(--tint) 0%, transparent 68%); opacity: .16; pointer-events: none;
  transition: opacity 160ms ease;
}
.card:hover { transform: translateY(-3px); border-color: color-mix(in srgb, var(--tint) 46%, transparent); box-shadow: inset 0 1px 0 rgba(255,255,255,.1), var(--shadow-md); background: var(--card-bg), var(--glass); }
.card:hover::after { opacity: .28; }
.stripe { position: absolute; left: 0; top: 14px; bottom: 14px; width: 3px; border-radius: 0 3px 3px 0; background: var(--tint); box-shadow: 0 0 12px color-mix(in srgb, var(--tint) 60%, transparent); }
.card-top { display: flex; align-items: center; justify-content: space-between; }
.card-icon {
  display: grid; place-items: center; width: 36px; height: 36px; border-radius: 11px; font-size: 16px; color: #04170d;
  background: linear-gradient(140deg, color-mix(in srgb, var(--tint) 82%, #ffffff) 0%, var(--tint) 60%, color-mix(in srgb, var(--tint) 62%, #04170d) 100%);
  box-shadow: 0 6px 16px color-mix(in srgb, var(--tint) 34%, transparent), inset 0 1px 0 rgba(255,255,255,.35);
}
.card-group { color: var(--muted); font-size: 10px; padding: 3px 8px; border-radius: 999px; background: var(--fill-2); border: 1px solid var(--line); }
.card-title { margin-top: 6px; color: var(--text); font-size: 14.5px; font-weight: 650; }
.card-desc { margin: 0; color: var(--muted); font-size: 11.5px; line-height: 1.6; min-height: 36px; }
.card-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 6px; padding-top: 8px; border-top: 1px dashed var(--line); }
.card-hint { color: color-mix(in srgb, var(--tint) 70%, var(--text)); font-size: 11.5px; font-weight: 700; }
.card-tag { color: var(--faint); font-size: 10.5px; }

/* 每种色调：暗底上提亮一档，保证图标与文字都跳得出来 */
.tint-blue { --tint: #6f9cff; } .tint-indigo { --tint: #8b8cf5; } .tint-rose { --tint: #ff7fa0; }
.tint-teal { --tint: #2fd6c3; } .tint-cyan { --tint: #45d9e6; } .tint-emerald { --tint: #55e08c; }
.tint-amber { --tint: #f3c04b; } .tint-sky { --tint: #5fb8f7; } .tint-violet { --tint: #b795ff; }
.tint-fuchsia { --tint: #e57fe0; } .tint-orange { --tint: #ff9d5c; } .tint-slate { --tint: #9fb6ab; }

/* ================= 右栏彩色推荐 ================= */
.side { display: grid; gap: 12px; }
.promo {
  position: relative; display: flex; align-items: center; justify-content: space-between; gap: 10px;
  min-height: 82px; padding: 14px 16px; border-radius: 16px; text-decoration: none; overflow: hidden;
  border: 1px solid rgba(255,255,255,.14);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.14), 0 12px 26px rgba(0,0,0,.3);
  transition: transform 150ms ease, box-shadow 150ms ease, filter 150ms ease;
}
.promo:hover { transform: translateY(-2px); box-shadow: inset 0 1px 0 rgba(255,255,255,.18), 0 16px 32px rgba(0,0,0,.4); filter: brightness(1.06); }
.promo-copy { position: relative; z-index: 1; }
.promo-title { color: #f4fffa; font-size: 14px; font-weight: 700; text-shadow: 0 1px 2px rgba(0,0,0,.28); }
.promo-sub { color: rgba(244,255,250,.76); font-size: 10.5px; margin-top: 3px; }
.promo-icon {
  position: relative; z-index: 1; display: grid; place-items: center; width: 38px; height: 38px;
  border-radius: 11px; font-size: 17px; background: rgba(255,255,255,.14); color: #f4fffa;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.2);
}
.promo::after { content: ""; position: absolute; right: -26px; bottom: -34px; width: 120px; height: 120px; border-radius: 50%; background: rgba(255,255,255,.12); }
.promo-teal { background: linear-gradient(135deg, #0e5f4c 0%, #1f9d7d 55%, #48cb9a 100%); }
.promo-violet { background: linear-gradient(135deg, #3b3270 0%, #6b57c9 55%, #9a7bff 100%); }
.promo-amber { background: linear-gradient(135deg, #7a4a12 0%, #b8791a 55%, #e6a92f 100%); }

.side-card { padding: 14px 16px; background: var(--glass); border: 1px solid var(--line); border-radius: 16px; display: grid; gap: 7px; box-shadow: var(--shadow); backdrop-filter: blur(16px); }
.side-title { color: var(--text); font-size: 12px; font-weight: 650; }
.quick { color: var(--link-fg); font-size: 11.5px; text-decoration: none; padding: 8px 10px; border-radius: 9px; background: var(--fill-2); border: 1px solid transparent; transition: all 140ms ease; }
.quick:hover { background: var(--accent-tint-weak); border-color: var(--accent-line); color: var(--text); }

/* ================= 空状态 ================= */
.empty { display: grid; justify-items: center; gap: 6px; padding: 56px 12px; text-align: center; }
.empty-icon { display: grid; place-items: center; width: 44px; height: 44px; border-radius: 50%; background: var(--fill-2); border: 1px solid var(--line); color: var(--muted); font-size: 19px; }
.empty-title { color: var(--text); font-size: 12.5px; font-weight: 650; }
.empty-desc { color: var(--muted); font-size: 11.5px; }

/* ================= 响应式 ================= */
@media (max-width: 1280px) {
  .body { grid-template-columns: 150px minmax(0, 1fr); }
  .side { display: none; }
}
@media (max-width: 960px) {
  .hero { grid-template-columns: 1fr; }
  .hero-stats { grid-template-columns: repeat(2, 1fr); }
  .hero-title { font-size: 24px; }
  .body { grid-template-columns: 1fr; }
  .rail { position: static; }
  .rail-item { justify-content: flex-start; gap: 10px; }
}
</style>
