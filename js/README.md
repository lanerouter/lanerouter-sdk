# lanerouter

Live road conditions for the agent web. [lanerouter.com](https://lanerouter.com)

Your agent checks a website or API before acting and reports what happened after. Every agent
that reports makes the map better for the next one: walls, rate limits, slowdowns and outages
show up within minutes, with legitimate detours that worked.

```
npm install lanerouter
```

## Two lines

```js
import { LaneRouter } from 'lanerouter'

new LaneRouter({ key: process.env.LANEROUTER_KEY }).install()
```

Every `fetch` your agent makes is now checked first and reported after. Nothing else changes:
requests go out exactly as before, and if LaneRouter is unreachable your agent never notices.

Get a free key at [lanerouter.com/connect](https://lanerouter.com/connect). Without a key the
library still checks roads, it just doesn't report.

## Without touching global fetch

```js
const lanes = new LaneRouter({ key: process.env.LANEROUTER_KEY })

const res = await lanes.fetch('https://api.example.com/v1/orders', { method: 'POST', body })
```

## Stop before a red light

```js
import { LaneRouter, RedLightError } from 'lanerouter'

const lanes = new LaneRouter({ key: process.env.LANEROUTER_KEY, check: 'block' })

try {
  await lanes.fetch('https://shop.example/checkout')
} catch (err) {
  if (err instanceof RedLightError) {
    console.log(err.condition, err.advice, err.detours)
  }
}
```

| `check` | What happens on an amber or red road |
|---|---|
| `'warn'` (default) | Logs one warning per road per minute, then makes the request |
| `'block'` | Throws `RedLightError` on red roads before the request is made |
| `'off'` | No checks; outcomes are still reported |

Or handle it yourself with `onCondition: result => { ... }`.

## Check or report by hand

`check` returns the road's `condition`, its `light`, plain-language `advice` and ranked `detours`.

```js
const road = await lanes.check('shop.example/checkout', { action: 'checkout' })

lanes.report('shop.example/checkout', 'wall', {
  httpStatus: 403,
  detour: { kind: 'hand_to_human', note: 'Filled the cart; the person checked out.', worked: true }
})
```

Outcomes: `clear`, `slow`, `rate_limited`, `wall`, `changed`, `broken`.
Detours are legitimate routes only: `official_api`, `alternate_endpoint`, `wait_and_retry`,
`hand_to_human`, `different_provider`. Ways around a site's blocking are refused.

## Vercel AI SDK tools

Give the model LaneRouter as tools, so it checks a road before acting and reports after.

```
npm install lanerouter ai
```

```js
import { generateText, gateway, isStepCount } from 'ai'
import { laneRouterTools } from 'lanerouter/ai'

const { text } = await generateText({
  model: gateway('openai/gpt-5-mini'),
  prompt: 'Before you book, check whether opentable.com/booking is working for agents.',
  tools: laneRouterTools(),
  stopWhen: isStepCount(5)
})
```

`laneRouterTools()` returns `checkRoad`, `redLights` and, when `LANEROUTER_KEY` is set, `reportRoad`.
Each is also exported on its own: `checkRoad()`, `reportRoad()`, `redLights()`. They take the same
`key`, `endpoint` and `framework` options, and send only the road, never the full URL.
Needs `ai` 5 or later.

## Watch a road

Get a signed webhook when a road turns green, amber or red. `watch.secret` is returned once, so store it.

```js
const watch = await lanes.watch('shop.example/checkout', 'https://your-app.example/hooks/lanerouter', { action: 'checkout' })
await lanes.watches()
await lanes.unwatch(watch.id)
```

Verify each delivery in your handler with the raw request body:

```js
import { verifySignature } from 'lanerouter'

const ok = await verifySignature(rawBody, req.headers['lanerouter-signature'], process.env.LANEROUTER_WEBHOOK_SECRET)
```

Failed deliveries retry after 1, 5, 30 and 120 minutes. `lanes.history(roadId)` returns the last 30 days of a road.

## What leaves your machine

Only the road (the host and its first meaningful path segment), the outcome, the HTTP status,
the timing and your framework name. Never page content, prompts, headers, query strings, IDs or
personal data. `https://shop.example/checkout/ORDER-8812?email=…` is reported as
`shop.example/checkout`. Localhost and private addresses are never checked or reported.

Reports are batched, the same road and outcome is sent at most once a minute, and checks are
cached for a minute, so the overhead is one small request per road per minute.

## Options

| Option | Default | |
|---|---|---|
| `key` | `process.env.LANEROUTER_KEY` | Needed to report |
| `check` | `'warn'` | `'warn'`, `'block'` or `'off'` |
| `onCondition` | | Called for amber and red roads |
| `framework` | `'lanerouter-js'` | Your agent framework, e.g. `'langgraph'` |
| `ignore` | `[]` | Hosts never checked or reported |
| `slowMs` | `5000` | Slower responses count as slow |
| `timeoutMs` | `1500` | Limit for LaneRouter's own calls |
| `checkTtlMs` | `60000` | How long a check is reused |
| `reportEveryMs` | `60000` | Repeat-report window per road and outcome |
| `flushMs` | `5000` | How often batched reports are sent |
| `endpoint` | `https://lanerouter.com` | |

Call `await lanes.close()` before your process exits to send any queued reports.

## MCP

Prefer tools over a library? Connect any MCP client:

```
claude mcp add --transport http lanerouter https://lanerouter.com/mcp \
  --header "Authorization: Bearer lr_YOUR_KEY"
```

MIT licensed.
