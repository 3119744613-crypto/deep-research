<script setup>
import { safeSourceUrl } from '@/apis/document_research_api'
defineProps({ report: { type: Object, required: true } })
const originLabel = { local: '本地资料', zhipu: '智谱知识库', public: '公开来源' }
</script>

<template>
  <article class="report" aria-label="文档解析研究报告">
    <div class="report-heading"><h2>研究方案</h2><span class="badge">未实测 · 待验证</span></div>
    <p>以下为建议方案、实验步骤与拟定验收指标，未运行候选解析器实验。</p>
    <p class="summary">{{ report.summary }}</p>
    <section v-if="report.warnings?.length" class="notice"><h3>本次限制</h3><ul><li v-for="(item, i) in report.warnings" :key="i">{{ item }}</li></ul></section>

    <section><h3>方案比较</h3>
      <p v-if="!report.comparisons?.length">证据不足，暂未形成可比较方案。</p>
      <div v-for="(candidate, i) in report.comparisons" :key="i" class="comparison">
        <h4>{{ candidate.name }}</h4><p>{{ candidate.approach }}</p>
        <div class="pros-cons"><div><strong>优点</strong><ul><li v-for="(item, n) in candidate.pros" :key="n">{{ item }}</li></ul></div><div><strong>局限</strong><ul><li v-for="(item, n) in candidate.cons" :key="n">{{ item }}</li></ul></div></div>
        <div class="citations">依据：<a v-for="id in candidate.source_ids" :key="id" :href="`#document-source-${encodeURIComponent(id)}`">[{{ id }}]</a><span v-if="!candidate.source_ids?.length">无引用，待验证</span></div>
      </div>
    </section>

    <section><h3>实验步骤与验收指标</h3>
      <div v-for="(experiment, i) in report.experiments" :key="i" class="comparison">
        <h4>{{ i + 1 }}. {{ experiment.name }}</h4><ol><li v-for="(step, n) in experiment.steps" :key="n">{{ step }}</li></ol>
        <strong>拟定指标</strong><ul><li v-for="(metric, n) in experiment.metrics" :key="n">{{ metric }}</li></ul>
        <p><strong>验收条件：</strong>{{ experiment.acceptance }}</p>
        <div class="citations">依据：<a v-for="id in experiment.source_ids" :key="id" :href="`#document-source-${encodeURIComponent(id)}`">[{{ id }}]</a><span v-if="!experiment.source_ids?.length">建议实验，待验证</span></div>
      </div>
    </section>

    <section class="recommendation"><h3>推荐理由</h3><p>{{ report.recommendation?.text || '证据不足，暂无确定推荐。' }}</p>
      <div class="citations"><a v-for="id in report.recommendation?.source_ids" :key="id" :href="`#document-source-${encodeURIComponent(id)}`">[{{ id }}]</a></div>
    </section>
    <section v-if="report.assumptions?.length"><h3>假设</h3><ul><li v-for="(item, i) in report.assumptions" :key="i">{{ item }}</li></ul></section>
    <section v-if="report.gaps?.length"><h3>证据缺口与待验证项</h3><ul><li v-for="(item, i) in report.gaps" :key="i">{{ item }}</li></ul></section>

    <section><h3>证据关系</h3><p>原文陈述只表示存在对应引文，不代表关系已获独立核实。</p>
      <p v-if="!report.graph?.length">本次未形成可展示的证据关系。</p>
      <div v-for="(edge, i) in report.graph" :key="i" class="relation">
        <span class="badge">{{ edge.kind === 'fact' ? '原文陈述 · 未独立核实' : '待验证线索' }}</span>
        <p><strong>{{ edge.subject }}</strong> → {{ edge.relation }} → <strong>{{ edge.object }}</strong></p>
        <blockquote v-if="edge.quote">{{ edge.quote }}</blockquote>
        <a v-if="edge.source_id" :href="`#document-source-${encodeURIComponent(edge.source_id)}`">[{{ edge.source_id }}]</a>
      </div>
    </section>

    <section><h3>实际使用的来源</h3><p v-if="!report.sources?.length">没有可用来源。</p>
      <details v-for="source in report.sources" :id="`document-source-${encodeURIComponent(source.id)}`" :key="source.id" class="source">
        <summary>[{{ source.id }}] {{ source.title }} <span class="badge">{{ originLabel[source.origin] || '来源类型未知' }}</span><span v-if="source.page !== null && source.page !== undefined"> · 第 {{ source.page }} 页</span></summary>
        <p v-if="source.page === null || source.page === undefined" class="muted">来源未提供页码。</p>
        <a v-if="safeSourceUrl(source.source_url)" :href="safeSourceUrl(source.source_url)" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">打开原始来源 ↗</a>
        <pre>{{ source.text }}</pre>
      </details>
    </section>
  </article>
</template>

<style scoped>
.report { color: var(--gray-900); line-height: 1.7; overflow-wrap: anywhere; }
.report-heading { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
h2 { font-size: 22px; margin: 0; } h3 { font-size: 17px; margin: 0 0 12px; } h4 { font-size: 16px; margin: 0 0 8px; }
p { margin: 8px 0 12px; } section { margin-top: 28px; } ul, ol { padding-left: 24px; } li { margin: 5px 0; }
.summary { white-space: pre-wrap; } .comparison, .relation { border: 1px solid var(--gray-200); border-radius: 10px; padding: 18px; margin: 12px 0; }
.pros-cons { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.badge { display: inline-block; font-size: 12px; font-weight: 500; padding: 2px 8px; border-radius: 5px; color: var(--main-800); background: var(--main-50); }
.notice, .recommendation { padding: 18px; background: var(--main-20); border-left: 3px solid var(--main-color); border-radius: 6px; }
.citations { display: flex; flex-wrap: wrap; gap: 6px; font-size: 13px; } a { color: var(--main-color); text-decoration: underline; }
blockquote { margin: 8px 0; padding: 8px 14px; border-left: 3px solid var(--gray-200); white-space: pre-wrap; }
.source { border-top: 1px solid var(--gray-200); padding: 16px 0; scroll-margin-top: 90px; } summary { cursor: pointer; }
pre { margin: 12px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; max-height: 320px; overflow-y: auto; background: var(--gray-50); padding: 12px; border-radius: 6px; }
.muted { color: var(--gray-600); font-size: 13px; }
@media (max-width: 600px) { .pros-cons { grid-template-columns: 1fr; gap: 4px; } .comparison, .relation { padding: 12px; } }
</style>
