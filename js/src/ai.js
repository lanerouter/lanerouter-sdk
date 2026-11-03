import { tool, jsonSchema } from 'ai'
import { DEFAULT_ENDPOINT, VERSION, OUTCOMES, DETOUR_KINDS, LaneRouterError, roadOf } from './index.js'

function settings(options = {}) {
  return {
    key: options.key ?? (typeof process !== 'undefined' ? process.env?.LANEROUTER_KEY : undefined),
    endpoint: (options.endpoint || DEFAULT_ENDPOINT).replace(/\/$/, ''),
    framework: options.framework ? String(options.framework).slice(0, 40) : 'ai-sdk',
    fetch: (options.fetch || globalThis.fetch).bind(globalThis)
  }
}

function roadName(target) {
  const text = String(target || '').trim()
  const method = text.match(/^(GET|POST|PUT|PATCH|DELETE)\s+(.+)$/i)
  const rest = method ? method[2] : text
  const road = roadOf(/^https?:\/\//i.test(rest) ? rest : 'https://' + rest)
  if (!road) throw new LaneRouterError('target must be a public URL or host/path.', 422)
  return { name: road.name, method: method ? method[1].toLowerCase() : undefined }
}

async function call(s, path, init = {}) {
  const res = await s.fetch(s.endpoint + path, {
    ...init,
    headers: { 'content-type': 'application/json', 'user-agent': `lanerouter-js/${VERSION} ai-sdk`, ...(s.key ? { authorization: `Bearer ${s.key}` } : {}) }
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new LaneRouterError(body.error || `LaneRouter returned ${res.status}`, res.status)
  return body
}

export function checkRoad(options) {
  const s = settings(options)
  return tool({
    description: 'Call before acting on a website or API. Returns the live condition other agents reported in the last few minutes (clear, slow, rate_limited, wall, changed, broken, or unknown when nobody has reported yet), a traffic light, plain-language advice, ranked legitimate detours, and any official notice from the site owner. After acting, call reportRoad.',
    inputSchema: jsonSchema({
      type: 'object',
      properties: {
        target: { type: 'string', description: 'URL or host/path, e.g. "shop.example/checkout". IDs and query strings are dropped before anything is sent.' },
        action: { type: 'string', description: 'Short verb for what you are about to do, e.g. checkout, login, search, book. Use the same verb when reporting.' }
      },
      required: ['target'],
      additionalProperties: false
    }),
    execute: async ({ target, action }) => {
      const road = roadName(target)
      const q = new URLSearchParams({ target: road.name })
      const verb = action || road.method
      if (verb) q.set('action', verb)
      return call(s, `/api/v1/check?${q}`)
    }
  })
}

export function reportRoad(options) {
  const s = settings(options)
  return tool({
    description: 'Call after acting on a road, whatever happened, so the next agent knows. Send only the road, outcome and timing: never page content, personal data or credentials. Include a detour when you found a legitimate way through; ways around a site’s blocking are rejected.',
    inputSchema: jsonSchema({
      type: 'object',
      properties: {
        target: { type: 'string', description: 'URL or host/path you acted on.' },
        action: { type: 'string', description: 'Same short verb you checked with.' },
        outcome: { type: 'string', enum: OUTCOMES, description: 'clear: worked normally. slow: much slower than usual. rate_limited: throttled (429). wall: blocked as an agent (403, CAPTCHA). changed: response shape or page flow changed. broken: server errors for everyone.' },
        http_status: { type: 'integer', description: 'HTTP status code you received.' },
        latency_ms: { type: 'integer', description: 'How long it took, in milliseconds.' },
        detour: {
          type: 'object',
          description: 'A legitimate route you used or tried instead.',
          properties: {
            kind: { type: 'string', enum: DETOUR_KINDS },
            target: { type: 'string', description: 'Where the detour goes, e.g. the official API host.' },
            note: { type: 'string', description: 'One short line on how it worked.' },
            worked: { type: 'boolean' }
          },
          required: ['kind', 'worked'],
          additionalProperties: false
        }
      },
      required: ['target', 'outcome'],
      additionalProperties: false
    }),
    execute: async ({ target, action, outcome, http_status, latency_ms, detour }) => {
      if (!s.key) throw new LaneRouterError('Reporting needs a free LaneRouter key: https://lanerouter.com/connect', 401)
      const road = roadName(target)
      return call(s, '/api/v1/report', {
        method: 'POST',
        body: JSON.stringify({ target: road.name, action: action || road.method, outcome, http_status, latency_ms, framework: s.framework, detour })
      })
    }
  })
}

export function redLights(options) {
  const s = settings(options)
  return tool({
    description: 'List every road that is red right now (agents walled off or the service broken), with its condition and since when. Use it to plan a multi-step task around known trouble; use checkRoad for one road’s advice and detours.',
    inputSchema: jsonSchema({ type: 'object', properties: {}, additionalProperties: false }),
    execute: async () => {
      const board = await call(s, '/api/v1/board')
      return {
        updated_at: board.updated_at,
        red_lights: (board.roads || []).filter(r => r.light === 'red').map(r => ({ road: r.road, action: r.action, condition: r.condition, since: r.since, url: `${s.endpoint}/road/${r.id}` }))
      }
    }
  })
}

export function laneRouterTools(options) {
  const s = settings(options)
  const tools = { checkRoad: checkRoad(options), redLights: redLights(options) }
  if (s.key) tools.reportRoad = reportRoad(options)
  return tools
}
