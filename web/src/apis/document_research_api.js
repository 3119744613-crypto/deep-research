const PREFIX = '/document-research-api'
export const DOCUMENT_TOKEN_KEY = 'document-research.token.v1'
export const documentTaskKey = (user) => `document-research.task.v1.${encodeURIComponent(user)}`

export class DocumentResearchError extends Error {
  constructor(message, status = 0) {
    super(message)
    this.name = 'DocumentResearchError'
    this.status = status
  }
}

// 本入口只携带专用 token；不导入平台 client，不附带浏览器 cookie。
export function createDocumentResearchApi(getToken, fetcher = globalThis.fetch) {
  async function request(path, { method = 'GET', body, signal, publicRequest = false } = {}) {
    const token = getToken()?.trim()
    if (!publicRequest && !token) throw new DocumentResearchError('请输入文档研发服务的专用访问令牌。', 401)
    const headers = { Accept: 'application/json' }
    if (!publicRequest) headers.Authorization = `Bearer ${token}`
    const isForm = body instanceof FormData
    if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json'
    let response
    try {
      response = await fetcher(`${PREFIX}${path}`, {
        method, headers, credentials: 'omit', redirect: 'error',
        body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
        signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(60000)]) : AbortSignal.timeout(60000)
      })
    } catch (error) {
      if (signal?.aborted) throw error
      throw new DocumentResearchError('无法连接文档研发服务，请确认本机 4198 端口已启动，再重试。')
    }
    let data
    try { data = await response.json() } catch {
      throw new DocumentResearchError('服务返回了非 JSON 响应，请检查专用服务及代理配置。', response.status)
    }
    if (!response.ok) {
      const detail = typeof data.detail === 'string' ? data.detail : '请求未成功，请检查输入或服务日志。'
      throw new DocumentResearchError(detail, response.status)
    }
    return data
  }
  const id = encodeURIComponent
  return {
    health: () => request('/health', { publicRequest: true }),
    session: () => request('/session'),
    libraries: () => request('/libraries'),
    createLibrary: (name) => request('/libraries', { method: 'POST', body: { name } }),
    deleteLibrary: (libraryId) => request(`/libraries/${id(libraryId)}`, { method: 'DELETE' }),
    documents: (libraryId) => request(`/libraries/${id(libraryId)}/documents`),
    upload: (libraryId, file) => {
      const body = new FormData()
      body.append('file', file)
      return request(`/libraries/${id(libraryId)}/documents`, { method: 'POST', body })
    },
    document: (documentId) => request(`/documents/${id(documentId)}`),
    deleteDocument: (documentId) => request(`/documents/${id(documentId)}`, { method: 'DELETE' }),
    createTask: (body) => request('/tasks', { method: 'POST', body }),
    task: (taskId, signal) => request(`/tasks/${id(taskId)}`, { signal }),
    updateTask: (taskId, body) => request(`/tasks/${id(taskId)}`, { method: 'PATCH', body }),
    runTask: (taskId) => request(`/tasks/${id(taskId)}/run`, { method: 'POST', body: {} }),
    cancelTask: (taskId) => request(`/tasks/${id(taskId)}/cancel`, { method: 'POST', body: {} })
  }
}

export function safeSourceUrl(value) {
  if (typeof value !== 'string') return null
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null
  } catch { return null }
}

// 切页、切账号、换任务时 stop() 会阻止在途旧响应写入新页面。
export function createDocumentTaskMonitor({ readTask, onTask, onError, delay = 1500, schedule = setTimeout, unschedule = clearTimeout }) {
  let generation = 0
  let timer
  let controller
  function stop() {
    generation += 1
    unschedule(timer)
    controller?.abort()
  }
  function start(taskId) {
    stop()
    const current = generation
    async function poll() {
      controller = new AbortController()
      try {
        const task = await readTask(taskId, controller.signal)
        if (current !== generation) return
        onTask(task)
        if (task.status === 'running') timer = schedule(poll, delay)
      } catch (error) {
        if (current !== generation) return
        onError(error)
        if (![401, 403, 404].includes(error.status)) timer = schedule(poll, delay * 2)
      }
    }
    void poll()
  }
  return { start, stop }
}
