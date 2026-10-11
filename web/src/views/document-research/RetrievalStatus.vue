<script setup>
defineProps({ items: { type: Array, default: () => [] } })
const providers = { local: '本地资料', zhipu: '智谱知识库', public_readme: '官方项目资料', public_search: '公开网络检索' }
const statuses = { ok: '检索成功', empty: '没有可用片段', partial: '部分来源不可用' }
</script>
<template>
  <ul v-if="items.length" class="retrieval-status" aria-label="各来源检索状态">
    <li v-for="item in items" :key="item.provider"><strong>{{ providers[item.provider] || '其他来源' }}</strong>：{{ statuses[item.status] || '状态未知' }} · {{ item.count }} 个片段</li>
  </ul>
</template>
<style scoped>
.retrieval-status { padding: 12px 16px 12px 32px; background: var(--gray-50); border-radius: 8px; color: var(--gray-700); font-size: 13px; }
li { margin: 4px 0; overflow-wrap: anywhere; }
</style>
