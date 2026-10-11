<script setup>
import { safeSourceUrl } from '@/apis/document_research_api'
import { revealSource } from './evidencePresentation'
defineProps({ sources: { type: Array, default: () => [] }, citedIds: { type: Array, default: null }, prefix: { type: String, default: 'document-source' } })
const originLabel = { local: '本地资料', zhipu: '智谱知识库', public: '公开来源' }
const sourceElements = new Map()
function setElement(id, node) { node ? sourceElements.set(id, node) : sourceElements.delete(id) }
function openSource(id) { revealSource(sourceElements.get(id)) }
defineExpose({ openSource })
</script>

<template>
  <div class="evidence-sources">
    <details v-for="source in sources" :id="`${prefix}-${encodeURIComponent(source.id)}`" :key="source.id" :ref="(node) => setElement(source.id, node)" class="source">
      <summary>[{{ source.id }}] {{ source.title }} <span class="badge">{{ originLabel[source.origin] || '来源类型未知' }}</span><span v-if="source.content_kind === 'search_excerpt'" class="badge">搜索摘要 · 未核验全文</span><span v-if="citedIds" class="badge">{{ citedIds.includes(source.id) ? '被回答或报告引用' : '仅供参考 · 未引用' }}</span><span v-if="source.page !== null && source.page !== undefined"> · 第 {{ source.page }} 页</span></summary>
      <p v-if="source.page === null || source.page === undefined" class="muted">来源未提供页码。</p>
      <a v-if="safeSourceUrl(source.source_url)" :href="safeSourceUrl(source.source_url)" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">打开原始来源 ↗</a>
      <pre>{{ source.text }}</pre>
    </details>
  </div>
</template>

<style scoped>
.source { border-top: 1px solid var(--gray-200); padding: 16px 0; scroll-margin-top: 90px; overflow-wrap: anywhere; } summary { cursor: pointer; }
summary:focus-visible, a:focus-visible { outline: 2px solid var(--main-color); outline-offset: 3px; }
.badge { display: inline-block; font-size: 12px; font-weight: 500; padding: 2px 8px; border-radius: 5px; color: var(--main-800); background: var(--main-50); margin: 3px; }
a { color: var(--main-color); text-decoration: underline; } .muted { color: var(--gray-600); font-size: 13px; }
pre { margin: 12px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; max-height: 320px; overflow-y: auto; background: var(--gray-50); padding: 12px; border-radius: 6px; }
</style>
