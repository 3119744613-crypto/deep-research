import assert from 'node:assert/strict'
import test from 'node:test'
import { createDocumentResearchApi, createDocumentTaskMonitor, safeSourceUrl, documentTaskKey, DocumentResearchError } from '../../src/apis/document_research_api.js'

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
