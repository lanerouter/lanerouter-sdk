import { test } from 'node:test'
import assert from 'node:assert/strict'
import { laneRouterTools, checkRoad, reportRoad } from '../src/ai.js'

function fake() {
  const calls = []
  const fetch = async (input, init = {}) => {
    const url = new URL(input)
    calls.push({ path: url.pathname, query: Object.fromEntries(url.searchParams), init })
    if (url.pathname === '/api/v1/board') {
      return Response.json({ updated_at: 't', roads: [{ id: 7, road: 'shop.example/checkout', action: 'checkout', condition: 'wall', light: 'red', since: 's' }, { id: 8, road: 'a.example', action: 'visit', condition: 'clear', light: 'green' }] })
    }
    if (url.pathname === '/api/v1/report') return Response.json({ accepted: true }, { status: 202 })
    if (url.pathname === '/api/v1/check') return Response.json({ road: url.searchParams.get('target'), condition: 'clear', light: 'green' })
    return Response.json({ error: 'nope' }, { status: 404 })
  }
  return { calls, fetch }
}

const ctx = { toolCallId: 'call_1', messages: [] }

test('checkRoad sends only the road and the action', async () => {
  const w = fake()
  const out = await checkRoad({ endpoint: 'https://lanerouter.test', fetch: w.fetch }).execute({ target: 'https://www.shop.example/checkout/ORDER-8812?email=a@b.c', action: 'checkout' }, ctx)
  assert.equal(out.light, 'green')
  assert.deepEqual(w.calls[0].query, { target: 'shop.example/checkout', action: 'checkout' })
  assert.equal(w.calls[0].init.headers.authorization, undefined)
})

test('a leading HTTP method becomes the action', async () => {
  const w = fake()
  await checkRoad({ endpoint: 'https://lanerouter.test', fetch: w.fetch }).execute({ target: 'POST api.github.com/repos/x/y/pulls' }, ctx)
  assert.deepEqual(w.calls[0].query, { target: 'api.github.com/repos', action: 'post' })
})

test('reportRoad posts a stripped report with the key and framework', async () => {
  const w = fake()
  await reportRoad({ key: 'lr_test', endpoint: 'https://lanerouter.test', fetch: w.fetch }).execute({ target: 'shop.example/checkout/123', outcome: 'wall', http_status: 403, detour: { kind: 'hand_to_human', worked: true } }, ctx)
  const body = JSON.parse(w.calls[0].init.body)
  assert.equal(w.calls[0].path, '/api/v1/report')
  assert.equal(w.calls[0].init.headers.authorization, 'Bearer lr_test')
  assert.equal(body.target, 'shop.example/checkout')
  assert.equal(body.framework, 'ai-sdk')
  assert.equal(body.detour.kind, 'hand_to_human')
})

test('reportRoad without a key explains how to get one', async () => {
  const w = fake()
  await assert.rejects(reportRoad({ key: '', endpoint: 'https://lanerouter.test', fetch: w.fetch }).execute({ target: 'shop.example', outcome: 'clear' }, ctx), /free LaneRouter key/)
  assert.equal(w.calls.length, 0)
})

test('laneRouterTools leaves out reporting without a key', () => {
  assert.deepEqual(Object.keys(laneRouterTools({ key: '' })).sort(), ['checkRoad', 'redLights'])
  assert.deepEqual(Object.keys(laneRouterTools({ key: 'lr_test' })).sort(), ['checkRoad', 'redLights', 'reportRoad'])
})

test('redLights keeps only red roads', async () => {
  const w = fake()
  const out = await laneRouterTools({ key: '', endpoint: 'https://lanerouter.test', fetch: w.fetch }).redLights.execute({}, ctx)
  assert.deepEqual(out.red_lights.map(r => r.road), ['shop.example/checkout'])
  assert.equal(out.red_lights[0].url, 'https://lanerouter.test/road/7')
})

test('tools carry JSON schemas the AI SDK can send to a model', async () => {
  const tools = laneRouterTools({ key: 'lr_test' })
  for (const t of Object.values(tools)) {
    const schema = await t.inputSchema.jsonSchema
    assert.equal(schema.type, 'object')
  }
  assert.deepEqual((await tools.reportRoad.inputSchema.jsonSchema).required, ['target', 'outcome'])
})
