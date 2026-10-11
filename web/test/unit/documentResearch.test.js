import assert from 'node:assert/strict'
import test from 'node:test'
import { createDocumentResearchApi, createDocumentTaskMonitor, createDocumentRetrievalPreview, runDocumentTaskOnce, safeSourceUrl, documentTaskKey, DocumentResearchError } from '../../src/apis/document_research_api.js'
import { citedSourceIds, revealSource } from '../../src/views/document-research/evidencePresentation.js'

test('document research request sends only dedicated bearer with cookies omitted and redirects refused', async () => {
  const calls = []
  const api = createDocumentResearchApi(() => ' dedicated-token ', async (...args) => {
    calls.push(args)
    return new Response(JSON.stringify({ items: [] }), { status: 200 })
  })
  await api.libraries()
  assert.equal(calls[0][0], '/document-research-api/libraries')
  assert.equal(calls[0][1].credentials, 'omit')
  assert.equal(calls[0][1].redirect, 'error')
  assert.deepEqual(calls[0][1].headers, { Accept: 'application/json', Authorization: 'Bearer dedicated-token' })
  await api.health()
  assert.equal(calls[1][1].headers.Authorization, undefined)
})

test('missing dedicated token never dispatches authenticated request', async () => {
  let requests = 0
  const api = createDocumentResearchApi(() => '', async () => { requests += 1 })
  await assert.rejects(api.session(), (error) => error.status === 401)
  assert.equal(requests, 0)
})

test('library identifiers are URL encoded and uploads leave boundary to browser', async () => {
  let call
  const api = createDocumentResearchApi(() => 'token', async (...args) => {
    call = args
    return new Response('{}', { status: 200 })
  })
  await api.upload('id/a?b', new File(['private sample'], 'sample.txt', { type: 'text/plain' }))
  assert.equal(call[0], '/document-research-api/libraries/id%2Fa%3Fb/documents')
  assert.equal(call[1].headers['Content-Type'], undefined)
  assert.equal(call[1].body.get('file').name, 'sample.txt')
  assert.equal(call[1].credentials, 'omit')
})

test('task request preserves only explicit selected libraries and outbound choices', async () => {
  let call
  const api = createDocumentResearchApi(() => 'token', async (...args) => {
    call = args
    return new Response('{}', { status: 200 })
  })
  const payload = { problem: 'table extraction', library_ids: [], allow_public: false, public_query: '', allow_external_model: false }
  await api.createTask(payload)
  assert.deepEqual(JSON.parse(call[1].body), payload)
  assert.equal(call[1].method, 'POST')
})

test('HTTP denial, unconfigured provider, malformed proxy and network errors remain errors', async () => {
  for (const status of [403, 503]) {
    const api = createDocumentResearchApi(() => 'token', async () => new Response('{"detail":"provider unavailable"}', { status }))
    await assert.rejects(api.runTask('task'), (error) => error.status === status && error.message === 'provider unavailable')
  }
  const htmlApi = createDocumentResearchApi(() => 'token', async () => new Response('<html>proxy</html>', { status: 502 }))
  await assert.rejects(htmlApi.session(), /非 JSON/)
  const offlineApi = createDocumentResearchApi(() => 'token', async () => { throw new TypeError('Failed to fetch') })
  await assert.rejects(offlineApi.session(), /4198/)
})

test('source links reject script, relative, embedded credentials and malformed values', () => {
  for (const value of ['javascript:alert(1)', 'data:text/html,test', '/private', 'file:///etc/passwd', 'https://user:secret@example.com', {}, null]) assert.equal(safeSourceUrl(value), null)
  assert.equal(safeSourceUrl('https://example.com/paper?q=a#source'), 'https://example.com/paper?q=a#source')
  assert.equal(safeSourceUrl('http://example.com'), 'http://example.com/')
  assert.notEqual(documentTaskKey('alice'), documentTaskKey('bob'))
})

const flush = () => new Promise((resolve) => queueMicrotask(resolve))

test('task monitor ignores late response from previous task and aborts old network request', async () => {
  const pending = new Map()
  const values = []
  const monitor = createDocumentTaskMonitor({
    readTask: (id, signal) => new Promise((resolve) => pending.set(id, { resolve, signal })),
    onTask: (task) => values.push(task), onError: assert.fail
  })
  monitor.start('old')
  monitor.start('new')
  assert.equal(pending.get('old').signal.aborted, true)
  pending.get('old').resolve({ id: 'old', status: 'completed' })
  pending.get('new').resolve({ id: 'new', status: 'completed' })
  await flush()
  assert.deepEqual(values, [{ id: 'new', status: 'completed' }])
  monitor.stop()
})

test('task monitor recovers from connection loss and stops at authoritative terminal status', async () => {
  let attempts = 0
  let scheduled
  const states = []
  const errors = []
  const monitor = createDocumentTaskMonitor({
    readTask: async () => { attempts += 1; if (attempts === 1) throw new DocumentResearchError('offline'); return { status: 'cancelled' } },
    onTask: (task) => states.push(task.status), onError: (error) => errors.push(error.message),
    schedule: (fn) => { scheduled = fn }, unschedule: () => {}
  })
  monitor.start('task')
  await flush()
  assert.deepEqual(errors, ['offline'])
  const retry = scheduled
  scheduled = null
  await retry()
  assert.deepEqual(states, ['cancelled'])
  assert.equal(scheduled, null)
  monitor.stop()
})

test('task monitor does not retry revoked or deleted tasks and never writes after unmount', async () => {
  for (const status of [401, 403, 404]) {
    let scheduled = false
    let observed
    const monitor = createDocumentTaskMonitor({
      readTask: async () => { throw new DocumentResearchError('revoked', status) },
      onTask: assert.fail, onError: (error) => { observed = error.status },
      schedule: () => { scheduled = true }, unschedule: () => {}
    })
    monitor.start('task')
    await flush()
    assert.equal(observed, status)
    assert.equal(scheduled, false)
    monitor.stop()
  }
  let finish
  const monitor = createDocumentTaskMonitor({ readTask: () => new Promise((resolve) => { finish = resolve }), onTask: assert.fail, onError: assert.fail })
  monitor.start('task')
  monitor.stop()
  finish({ status: 'completed' })
  await flush()
})

test('accepted run with lost response recovers through status reads without a second billable start', async () => {
  let starts = 0
  let reads = 0
  let backendStatus = 'ready'
  let pending = false
  let scheduled
  const states = []
  const unknown = []
  const onTask = (task) => { pending = false; states.push(task.status) }
  const monitor = createDocumentTaskMonitor({
    readTask: async (id) => { reads += 1; assert.equal(id, 'accepted'); return { id, status: backendStatus } },
    onTask, onError: assert.fail,
    schedule: (fn) => { scheduled = fn }, unschedule: () => {}
  })
  await runDocumentTaskOnce({
    taskId: 'accepted',
    runTask: async () => { starts += 1; backendStatus = 'running'; throw new DocumentResearchError('response lost') },
    isCurrent: () => true, onTask, onPending: (value) => { pending = value },
    onError: assert.fail, onUnknown: (error) => unknown.push(error.message), monitor
  })
  await flush()
  assert.deepEqual(unknown, ['response lost'])
  assert.deepEqual(states, ['running'])
  backendStatus = 'completed'
  await scheduled()
  assert.deepEqual(states, ['running', 'completed'])
  assert.equal(starts, 1)
  assert.equal(reads, 2)
  assert.equal(pending, false)
  monitor.stop()
})

test('run rejection for revoked or missing task clears pending state and never monitors or retries', async () => {
  for (const status of [401, 403, 404]) {
    let starts = 0
    let stops = 0
    let observed
    const pending = []
    await runDocumentTaskOnce({
      taskId: 'revoked', runTask: async () => { starts += 1; throw new DocumentResearchError('denied', status) },
      isCurrent: () => true, onTask: assert.fail, onPending: (value) => pending.push(value),
      onError: (error) => { observed = error.status }, onUnknown: assert.fail,
      monitor: { start: assert.fail, stop: () => { stops += 1 } }
    })
    assert.equal(starts, 1)
    assert.equal(stops, 1)
    assert.equal(observed, status)
    assert.deepEqual(pending, [true, false])
  }
})

test('late run success or failure after task or identity switch cannot change or restart current task', async () => {
  for (const response of ['success', 'lost', 'revoked']) {
    let finish
    let fail
    let current = true
    const pending = []
    const run = runDocumentTaskOnce({
      taskId: 'old', runTask: () => new Promise((resolve, reject) => { finish = resolve; fail = reject }),
      isCurrent: () => current, onTask: assert.fail, onPending: (value) => pending.push(value),
      onError: assert.fail, onUnknown: assert.fail, monitor: { start: assert.fail, stop: assert.fail }
    })
    current = false
    if (response === 'success') finish({ id: 'old', status: 'running' })
    else fail(new DocumentResearchError('late failure', response === 'revoked' ? 401 : 0))
    await run
    assert.deepEqual(pending, [true])
  }
  await runDocumentTaskOnce({
    taskId: 'already stale', runTask: assert.fail, isCurrent: () => false, onTask: assert.fail,
    onPending: assert.fail, onError: assert.fail, onUnknown: assert.fail, monitor: { start: assert.fail, stop: assert.fail }
  })
})


test('retrieval preview sends explicit search opt-in and public query without model consent or platform cookies', async () => {
  let call
  const api = createDocumentResearchApi(() => 'preview-token', async (...args) => {
    call = args
    return new Response(JSON.stringify({ sources: [], warnings: [], retrieval_status: [{ provider: 'zhipu', status: 'empty', count: 0 }] }))
  })
  const controller = new AbortController()
  const payload = { problem: 'private problem', library_ids: ['zhipu:allowed'], allow_public: false, public_query: 'public table benchmark', allow_web_search: true }
  const result = await api.retrieve(payload, controller.signal)
  assert.equal(call[0], '/document-research-api/retrieve')
  assert.equal(call[1].method, 'POST')
  assert.equal(call[1].credentials, 'omit')
  assert.equal(call[1].redirect, 'error')
  assert.deepEqual(JSON.parse(call[1].body), payload)
  assert.equal(result.retrieval_status[0].status, 'empty')
  controller.abort()
  assert.equal(call[1].signal.aborted, true)
})

test('answer task preserves its mode and independent public search setting', async () => {
  let call
  const api = createDocumentResearchApi(() => 'token', async (...args) => { call = args; return new Response('{}') })
  const payload = { mode: 'answer', problem: 'what is supported?', library_ids: ['local-id'], allow_web_search: false, allow_external_model: true }
  await api.createTask(payload)
  assert.deepEqual(JSON.parse(call[1].body), payload)
})

test('retrieval preview stop aborts request and suppresses late results after scope changes', async () => {
  const pending = new Map()
  const results = []
  const loading = []
  const preview = createDocumentRetrievalPreview({
    retrieve: (body, signal) => new Promise((resolve, reject) => pending.set(body.problem, { resolve, reject, signal })),
    onResult: (result) => results.push(result), onError: assert.fail, onLoading: (value) => loading.push(value)
  })
  const old = preview.start({ problem: 'old scope' })
  const current = preview.start({ problem: 'new scope' })
  assert.equal(pending.get('old scope').signal.aborted, true)
  pending.get('old scope').resolve({ sources: ['private old source'] })
  await old
  assert.deepEqual(results, [])
  assert.equal(loading.at(-1), true)
  pending.get('new scope').resolve({ sources: [] })
  await current
  assert.deepEqual(results, [{ sources: [] }])
  assert.equal(loading.at(-1), false)
  const unmounted = preview.start({ problem: 'unmounted' })
  preview.stop()
  assert.equal(pending.get('unmounted').signal.aborted, true)
  pending.get('unmounted').reject(new DocumentResearchError('old forbidden', 403))
  await unmounted
  assert.deepEqual(results, [{ sources: [] }])
})

test('retrieval failure is an error rather than a zero-hit result and stops the loading indicator', async () => {
  const errors = []
  const loading = []
  const preview = createDocumentRetrievalPreview({
    retrieve: async () => { throw new DocumentResearchError('provider unavailable', 503) },
    onResult: assert.fail, onError: (error) => errors.push(error), onLoading: (value) => loading.push(value)
  })
  await preview.start({ problem: 'query' })
  assert.equal(errors.length, 1)
  assert.equal(errors[0].status, 503)
  assert.equal(loading.at(-1), false)
})

test('source usage distinguishes provided context from citations across answer, research and graph', () => {
  assert.deepEqual(citedSourceIds({ sources: [{ id: 'unused' }], answer: [{ source_id: 'S1' }], graph: [{ source_id: 'S2' }, { source_id: 'S1' }] }), ['S2', 'S1'])
  assert.deepEqual(citedSourceIds({ comparisons: [{ source_ids: ['S1'] }], experiments: [{ source_ids: ['S2', 'S1'] }], recommendation: { source_ids: ['S3'] }, sources: [{ id: 'S4' }] }), ['S1', 'S2', 'S3'])
  assert.deepEqual(citedSourceIds({}), [])
})

test('source citation opens folded evidence before focusing and scrolling to it', () => {
  const events = []
  const element = {
    open: false,
    querySelector: (selector) => { assert.equal(selector, 'summary'); return { focus: (options) => events.push(['focus', options, element.open]) } },
    scrollIntoView: (options) => events.push(['scroll', options, element.open])
  }
  revealSource(element)
  assert.equal(element.open, true)
  assert.deepEqual(events, [['focus', { preventScroll: true }, true], ['scroll', { block: 'nearest' }, true]])
  revealSource(null)
})
