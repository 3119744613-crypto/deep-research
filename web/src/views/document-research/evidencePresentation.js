export function citedSourceIds(report) {
  const ids = new Set()
  const add = (id) => { if (typeof id === 'string' && id) ids.add(id) }
  for (const section of ['comparisons', 'experiments']) {
    for (const item of report[section] || []) for (const id of item.source_ids || []) add(id)
  }
  for (const id of report.recommendation?.source_ids || []) add(id)
  for (const item of [...(report.graph || []), ...(report.answer || [])]) add(item.source_id)
  return [...ids]
}

export function revealSource(element) {
  if (!element) return
  element.open = true
  element.querySelector('summary')?.focus({ preventScroll: true })
  element.scrollIntoView({ block: 'nearest' })
}
