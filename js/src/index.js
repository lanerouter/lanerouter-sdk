const DEFAULT_ENDPOINT = 'https://lanerouter.com'
const VERSION = '0.2.0'

const OPAQUE = [
  /^\d+$/,
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
  /^[0-9a-f]{12,}$/i,
  /@/,
  /^(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9_-]{10,}$/
]
const PREFIX = /^(v\d+(\.\d+)?|api|apis|rest|graphql|wp-json)$/i
const CHALLENGE = /just a moment\.\.\.|cf-chl|challenge-platform|px-captcha|_incapsula_|request unsuccessful|are you a robot|unusual traffic from your|perimeterx|datadome|pardon our interruption|automated access|unauthorized (ai )?agent|enable javascript and cookies to continue|access to this page has been denied|g-recaptcha|h-captcha|hcaptcha\.com/i

export const OUTCOMES = ['clear', 'slow', 'rate_limited', 'wall', 'changed', 'broken']
export const DETOUR_KINDS = ['official_api', 'alternate_endpoint', 'wait_and_retry', 'hand_to_human', 'different_provider']

export class RedLightError extends Error {
  constructor(road, result) {
    super(`LaneRouter: ${road} is ${result.condition}. ${result.advice || ''}`.trim())
    this.name = 'RedLightError'
    this.road = road
    this.condition = result.condition
    this.detours = result.detours || []
    this.advice = result.advice || ''
  }
}

function privateHost(host) {
  if (host === 'localhost' || host.endsWith('.local') || host.endsWith('.internal') || host.endsWith('.localhost')) return true
  if (/^\d+\.\d+\.\d+\.\d+$/.test(host)) return true
  return host.includes(':') || !host.includes('.')
}

export function roadOf(input) {
  let url
  try { url = input instanceof URL ? input : new URL(String(input)) } catch { return null }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null
  const host = url.hostname.toLowerCase().replace(/^www\./, '').replace(/\.$/, '')
  if (privateHost(host)) return null
  const segments = []
  for (const s of url.pathname.split('/').filter(Boolean)) {
    let seg
    try { seg = decodeURIComponent(s) } catch { seg = s }
    if (OPAQUE.some(r => r.test(seg))) break
    segments.push(seg.toLowerCase().slice(0, 48))
    if (!PREFIX.test(seg) || segments.length >= 4) break
  }
  return { host, path: '/' + segments.join('/'), name: host + (segments.length ? '/' + segments.join('/') : '') }
}

export function classify({ status, latencyMs = 0, body = '', slowMs = 5000 }) {
  if (body && CHALLENGE.test(body)) return 'wall'
  if (status === 429) return 'rate_limited'
  if (status === 401 || status === 403) return 'wall'
  if (status >= 500) return 'broken'
  if (status === 404 || status === 410) return 'changed'
  return latencyMs > slowMs ? 'slow' : 'clear'
}

async function readStart(response, cap = 64_000) {
  try {
    const reader = response.body?.getReader()
    if (!reader) return ''
    const chunks = []
    let size = 0
    while (size < cap) {
      const { value, done } = await reader.read()
      if (done) break
      chunks.push(value)
      size += value.length
    }
    reader.cancel().catch(() => {})
    return new TextDecoder().decode(chunks.length === 1 ? chunks[0] : concat(chunks))
  } catch { return '' }
}

function concat(chunks) {
  const out = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0))
  let i = 0
  for (const c of chunks) { out.set(c, i); i += c.length }
  return out
}

function requestInfo(input, init) {
  if (typeof Request !== 'undefined' && input instanceof Request) return { url: input.url, method: (init?.method || input.method || 'GET').toUpperCase() }
  return { url: input instanceof URL ? input.href : String(input), method: (init?.method || 'GET').toUpperCase() }
}

export class LaneRouterError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'LaneRouterError'
    this.status = status
  }
}

const enc = new TextEncoder()

function hex(buf) {
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('')
}

export async function verifySignature(body, header, secret, { toleranceSec = 300, now = Date.now() } = {}) {
  if (typeof header !== 'string' || !secret) return false
  const parts = Object.fromEntries(header.split(',').map(p => p.trim().split('=')))
  const t = Number(parts.t)
  if (!parts.v1 || !Number.isFinite(t) || Math.abs(now / 1000 - t) > toleranceSec) return false
  const raw = typeof body === 'string' ? body : new TextDecoder().decode(body)
  const key = await globalThis.crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  const expected = hex(await globalThis.crypto.subtle.sign('HMAC', key, enc.encode(`${t}.${raw}`)))
  if (expected.length !== parts.v1.length) return false
  let diff = 0
  for (let i = 0; i < expected.length; i++) diff |= expected.charCodeAt(i) ^ parts.v1.charCodeAt(i)
  return diff === 0
}

export class LaneRouter {
  constructor(options = {}) {
    this.key = options.key ?? (typeof process !== 'undefined' ? process.env?.LANEROUTER_KEY : undefined)
    this.endpoint = (options.endpoint || DEFAULT_ENDPOINT).replace(/\/$/, '')
    this.framework = options.framework ? String(options.framework).slice(0, 40) : 'lanerouter-js'
    this.mode = options.check ?? 'warn'
    this.onCondition = options.onCondition || null
    this.slowMs = options.slowMs ?? 5000
    this.timeoutMs = options.timeoutMs ?? 1500
    this.checkTtlMs = options.checkTtlMs ?? 60_000
    this.reportEveryMs = options.reportEveryMs ?? 60_000
    this.flushMs = options.flushMs ?? 5000
    this.ignore = new Set((options.ignore || []).map(h => String(h).toLowerCase().replace(/^www\./, '')))
    this.debug = !!options.debug
    this._fetch = (options.fetch || globalThis.fetch).bind(globalThis)
    this._endpointHost = new URL(this.endpoint).hostname.replace(/^www\./, '')
    this._checks = new Map()
    this._sent = new Map()
    this._warned = new Map()
    this._queue = []
    this._timer = null
    this._installed = null
    this.fetch = this.fetch.bind(this)
  }

  _log(...args) { if (this.debug) console.debug('[lanerouter]', ...args) }

  _skip(road) {
    return !road || road.host === this._endpointHost || this.ignore.has(road.host)
  }

  async _call(path, init = {}) {
    const ctrl = new AbortController()
    const t = setTimeout(() => ctrl.abort(), this.timeoutMs)
    try {
      const headers = { 'content-type': 'application/json', 'user-agent': `lanerouter-js/${VERSION}`, ...(this.key ? { authorization: `Bearer ${this.key}` } : {}) }
      const res = await this._fetch(this.endpoint + path, { ...init, headers, signal: ctrl.signal })
      if (!res.ok) { this._log('api', path, res.status); res.body?.cancel().catch(() => {}); return null }
      return await res.json()
    } catch (err) {
      this._log('api failed', path, err?.message)
      return null
    } finally {
      clearTimeout(t)
    }
  }

  async _manage(path, init = {}) {
    if (!this.key) throw new LaneRouterError('A LaneRouter key is required.', 401)
    const res = await this._fetch(this.endpoint + path, {
      ...init,
      headers: { 'content-type': 'application/json', 'user-agent': `lanerouter-js/${VERSION}`, authorization: `Bearer ${this.key}` }
    })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new LaneRouterError(body.error || `LaneRouter returned ${res.status}`, res.status)
    return body
  }

  watch(target, url, { action } = {}) {
    return this._manage('/api/v1/watches', { method: 'POST', body: JSON.stringify({ target: String(target), action, url }) })
  }

  async unwatch(id) {
    await this._manage(`/api/v1/watches/${Number(id)}`, { method: 'DELETE' })
  }

  async watches() {
    return (await this._manage('/api/v1/watches')).watches
  }

  async history(roadId, { days = 30 } = {}) {
    const res = await this._fetch(`${this.endpoint}/api/v1/roads/${Number(roadId)}/history?days=${Number(days)}`)
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new LaneRouterError(body.error || `LaneRouter returned ${res.status}`, res.status)
    return body
  }

  async check(target, { action } = {}) {
    const road = typeof target === 'string' && !/^https?:\/\//i.test(target) ? roadOf('https://' + target) : roadOf(target)
    if (!road) return null
    const k = `${road.name}|${action || ''}`
    const cached = this._checks.get(k)
    if (cached && Date.now() - cached.at < this.checkTtlMs) return cached.value
    const q = new URLSearchParams({ target: road.name })
    if (action) q.set('action', action)
    const value = await this._call(`/api/v1/check?${q}`)
    this._checks.set(k, { at: Date.now(), value })
    return value
  }

  report(target, outcome, { action, httpStatus, latencyMs, detour } = {}) {
    if (!this.key) return false
    if (!OUTCOMES.includes(outcome)) throw new TypeError(`outcome must be one of: ${OUTCOMES.join(', ')}`)
    if (detour && !DETOUR_KINDS.includes(detour.kind)) throw new TypeError(`detour.kind must be one of: ${DETOUR_KINDS.join(', ')}`)
    const road = typeof target === 'string' && !/^https?:\/\//i.test(target) ? roadOf('https://' + target) : roadOf(target)
    if (this._skip(road)) return false
    const k = `${road.name}|${action || ''}|${outcome}`
    const last = this._sent.get(k)
    if (!detour && last && Date.now() - last < this.reportEveryMs) return false
    this._sent.set(k, Date.now())
    const item = { target: road.name, outcome, framework: this.framework }
    if (action) item.action = action
    if (Number.isFinite(httpStatus)) item.http_status = httpStatus
    if (Number.isFinite(latencyMs)) item.latency_ms = Math.round(latencyMs)
    if (detour) item.detour = { kind: detour.kind, worked: !!detour.worked, ...(detour.target ? { target: String(detour.target) } : {}), ...(detour.note ? { note: String(detour.note).slice(0, 140) } : {}) }
    this._queue.push(item)
    if (this._queue.length >= 25) this.flush()
    else this._schedule()
    return true
  }

  _schedule() {
    if (this._timer) return
    this._timer = setTimeout(() => { this._timer = null; this.flush() }, this.flushMs)
    if (typeof this._timer === 'object' && this._timer?.unref) this._timer.unref()
  }

  async flush() {
    if (this._timer) { clearTimeout(this._timer); this._timer = null }
    while (this._queue.length) {
      const batch = this._queue.splice(0, 50)
      await this._call('/api/v1/reports', { method: 'POST', body: JSON.stringify({ reports: batch }) })
    }
  }

  async fetch(input, init) {
    const { url, method } = requestInfo(input, init)
    const road = roadOf(url)
    if (this._skip(road)) return this._fetch(input, init)
    const action = method.toLowerCase()

    if (this.mode !== 'off') {
      const result = await this.check(url, { action })
      if (result && result.light && result.light !== 'green' && result.light !== 'off') {
        if (this.onCondition) {
          try { this.onCondition({ road: road.name, ...result }) } catch {}
        } else if (this.mode === 'warn') {
          const w = this._warned.get(road.name)
          if (!w || Date.now() - w > this.checkTtlMs) {
            this._warned.set(road.name, Date.now())
            console.warn(`[lanerouter] ${road.name}: ${result.condition}. ${result.advice || ''}`.trim())
          }
        }
        if (this.mode === 'block' && result.light === 'red') throw new RedLightError(road.name, result)
      }
    }

    const started = Date.now()
    const response = await this._fetch(input, init)
    const latencyMs = Date.now() - started
    let body = ''
    const type = response.headers?.get?.('content-type') || ''
    if ([401, 403, 503].includes(response.status) && /html/i.test(type)) body = await readStart(response.clone())
    this.report(url, classify({ status: response.status, latencyMs, body, slowMs: this.slowMs }), { action, httpStatus: response.status, latencyMs })
    return response
  }

  install() {
    if (this._installed) return () => this.uninstall()
    this._installed = globalThis.fetch
    globalThis.fetch = this.fetch
    return () => this.uninstall()
  }

  uninstall() {
    if (this._installed) { globalThis.fetch = this._installed; this._installed = null }
  }

  async close() {
    this.uninstall()
    await this.flush()
  }
}

export default LaneRouter
