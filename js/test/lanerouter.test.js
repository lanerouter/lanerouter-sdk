import { test } from 'node:test'
import assert from 'node:assert/strict'
import { LaneRouter, RedLightError, roadOf, classify } from '../src/index.js'

function fakeWorld({ condition = 'clear', light = 'green', siteStatus = 200, siteBody = 'ok', siteType = 'text/plain', delay = 0 } = {}) {
  const calls = { checks: [], reports: [], site: 0 }
  const fetch = async (input, init = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url)
    if (url.hostname === 'lanerouter.test') {
      if (url.pathname === '/api/v1/check') {
        calls.checks.push(url.searchParams.get('target'))
        return new Response(JSON.stringify({ road: url.searchParams.get('target'), condition, light, advice: 'Use the official API.', detours: [{ kind: 'official_api', target: 'api.shop.example' }] }), { headers: { 'content-type': 'application/json' } })
      }
      if (url.pathname === '/api/v1/reports') {
        calls.reports.push(...JSON.parse(init.body).reports)
        calls.auth = init.headers.authorization
        return new Response(JSON.stringify({ accepted: 1 }), { status: 202, headers: { 'content-type': 'application/json' } })
      }
    }
    calls.site++
    if (delay) await new Promise(r => setTimeout(r, delay))
    return new Response(siteBody, { status: siteStatus, headers: { 'content-type': siteType } })
  }
  return { calls, fetch }
}

const make = (world, extra = {}) => new LaneRouter({ key: 'lr_test', endpoint: 'https://lanerouter.test', fetch: world.fetch, flushMs: 10_000, ...extra })

test('roads keep only the host and first meaningful segment', () => {
  assert.equal(roadOf('https://www.shop.example/checkout/ABC123XYZ456?token=secret').name, 'shop.example/checkout')
  assert.equal(roadOf('https://api.github.com/repos/acme/app/pulls').name, 'api.github.com/repos')
  assert.equal(roadOf('https://api.openai.com/v1/responses').name, 'api.openai.com/v1/responses')
  assert.equal(roadOf('http://localhost:3000/x'), null)
  assert.equal(roadOf('http://192.168.1.2/admin'), null)
})

test('responses are classified like the server does', () => {
  assert.equal(classify({ status: 200, latencyMs: 300 }), 'clear')
  assert.equal(classify({ status: 200, latencyMs: 9000 }), 'slow')
  assert.equal(classify({ status: 429 }), 'rate_limited')
  assert.equal(classify({ status: 403 }), 'wall')
  assert.equal(classify({ status: 200, body: '<title>Just a moment...</title>' }), 'wall')
  assert.equal(classify({ status: 502 }), 'broken')
  assert.equal(classify({ status: 404 }), 'changed')
})

test('fetch checks first, reports after, and never sends the full URL', async () => {
  const world = fakeWorld()
  const lr = make(world)
  const res = await lr.fetch('https://shop.example/checkout/ORDER12345678?email=a@b.c', { method: 'POST' })
  assert.equal(res.status, 200)
  await lr.flush()
  assert.deepEqual(world.calls.checks, ['shop.example/checkout'])
  assert.equal(world.calls.reports.length, 1)
  assert.equal(world.calls.reports[0].target, 'shop.example/checkout')
  assert.equal(world.calls.reports[0].action, 'post')
  assert.equal(world.calls.reports[0].outcome, 'clear')
  assert.equal(world.calls.auth, 'Bearer lr_test')
  assert.ok(!JSON.stringify(world.calls.reports).includes('email'))
})

test('a blocked page is reported as a wall, read from the challenge body', async () => {
  const world = fakeWorld({ siteStatus: 403, siteType: 'text/html', siteBody: '<html><title>Just a moment...</title></html>' })
  const lr = make(world)
  const res = await lr.fetch('https://shop.example/checkout')
  assert.equal(await res.text(), '<html><title>Just a moment...</title></html>')
  await lr.flush()
  assert.equal(world.calls.reports[0].outcome, 'wall')
  assert.equal(world.calls.reports[0].http_status, 403)
})

test('block mode throws on red roads before touching the site', async () => {
  const world = fakeWorld({ condition: 'wall', light: 'red' })
  const lr = make(world, { check: 'block' })
  await assert.rejects(lr.fetch('https://shop.example/checkout'), err => err instanceof RedLightError && err.detours[0].kind === 'official_api')
  assert.equal(world.calls.site, 0)
})

test('warn mode calls onCondition and still makes the request', async () => {
  const world = fakeWorld({ condition: 'slow', light: 'amber' })
  const seen = []
  const lr = make(world, { onCondition: r => seen.push(r.condition) })
  const res = await lr.fetch('https://shop.example/search')
  assert.equal(res.status, 200)
  assert.deepEqual(seen, ['slow'])
})

test('checks are cached and repeat reports are deduplicated', async () => {
  const world = fakeWorld()
  const lr = make(world)
  for (let i = 0; i < 5; i++) await lr.fetch('https://shop.example/search?q=' + i)
  await lr.flush()
  assert.equal(world.calls.checks.length, 1)
  assert.equal(world.calls.reports.length, 1)
  assert.equal(world.calls.site, 5)
})

test('without a key it checks but never reports', async () => {
  const world = fakeWorld()
  const lr = new LaneRouter({ endpoint: 'https://lanerouter.test', fetch: world.fetch, key: '' })
  await lr.fetch('https://shop.example/search')
  await lr.flush()
  assert.equal(world.calls.checks.length, 1)
  assert.equal(world.calls.reports.length, 0)
})

test('LaneRouter being unreachable never breaks the agent', async () => {
  const site = async () => new Response('ok')
  const broken = async (input) => {
    if (String(typeof input === 'string' ? input : input.url).includes('lanerouter.test')) throw new Error('offline')
    return site()
  }
  const lr = new LaneRouter({ key: 'lr_test', endpoint: 'https://lanerouter.test', fetch: broken })
  const res = await lr.fetch('https://shop.example/search')
  assert.equal(await res.text(), 'ok')
  await lr.flush()
})

test('private hosts, ignored hosts and LaneRouter itself pass straight through', async () => {
  const world = fakeWorld()
  const lr = make(world, { ignore: ['internal.example.com'] })
  await lr.fetch('http://localhost:8080/health')
  await lr.fetch('https://internal.example.com/jobs')
  await lr.flush()
  assert.equal(world.calls.checks.length, 0)
  assert.equal(world.calls.reports.length, 0)
})

test('install wraps global fetch and close restores it', async () => {
  const original = globalThis.fetch
  const world = fakeWorld()
  const lr = make(world)
  lr.install()
  assert.notEqual(globalThis.fetch, original)
  await lr.close()
  assert.equal(globalThis.fetch, original)
})

test('legitimate detours can be reported; unknown kinds are refused', () => {
  const lr = make(fakeWorld())
  assert.equal(lr.report('shop.example/checkout', 'wall', { detour: { kind: 'hand_to_human', worked: true } }), true)
  assert.throws(() => lr.report('shop.example/checkout', 'wall', { detour: { kind: 'proxy', worked: true } }))
})

test('verifySignature accepts a valid signature and rejects tampering or old timestamps', async () => {
  const { verifySignature } = await import('../src/index.js')
  const crypto = await import('node:crypto')
  const secret = 'whsec_test'
  const body = JSON.stringify({ type: 'road.changed', light: 'red' })
  const t = Math.floor(Date.now() / 1000)
  const header = `t=${t},v1=${crypto.createHmac('sha256', secret).update(`${t}.${body}`).digest('hex')}`
  assert.equal(await verifySignature(body, header, secret), true)
  assert.equal(await verifySignature(body + ' ', header, secret), false)
  assert.equal(await verifySignature(body, header, 'whsec_other'), false)
  assert.equal(await verifySignature(body, header, secret, { now: (t + 600) * 1000 }), false)
  assert.equal(await verifySignature(body, undefined, secret), false)
})

test('watch helpers send the key and surface API errors', async () => {
  const { LaneRouter, LaneRouterError } = await import('../src/index.js')
  const calls = []
  const fake = async (url, init = {}) => {
    calls.push({ url, init })
    if (init.method === 'POST') return new Response(JSON.stringify({ error: 'url must use https.' }), { status: 422 })
    return new Response(JSON.stringify({ watches: [{ id: 1 }] }), { status: 200 })
  }
  const lanes = new LaneRouter({ key: 'lr_test', endpoint: 'https://lr.example', fetch: fake })
  assert.deepEqual(await lanes.watches(), [{ id: 1 }])
  assert.equal(calls[0].init.headers.authorization, 'Bearer lr_test')
  await assert.rejects(lanes.watch('shop.example/checkout', 'http://x'), e => e instanceof LaneRouterError && e.status === 422 && /https/.test(e.message))
  await assert.rejects(new LaneRouter({ key: null, fetch: fake }).watches(), LaneRouterError)
})
