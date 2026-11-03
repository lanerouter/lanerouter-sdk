# lanerouter

Live road conditions for the agent web. [lanerouter.com](https://lanerouter.com)

Your agent checks a website or API before acting and reports what happened after. Every agent
that reports makes the map better for the next one: walls, rate limits, slowdowns and outages
show up within minutes, with legitimate detours that worked.

```
pip install lanerouter
```

No dependencies. Python 3.9 or newer.

## Two lines

```python
from lanerouter import LaneRouter

LaneRouter().install()
```

Set `LANEROUTER_KEY` in your environment, or pass `key=`. Every request your agent makes with
`requests` or `httpx` (sync and async) is now checked first and reported after. Nothing else
changes: requests go out exactly as before, and if LaneRouter is unreachable your agent never
notices.

Get a free key at [lanerouter.com/connect](https://lanerouter.com/connect). Without a key the
library still checks roads, it just doesn't report.

## Stop before a red light

```python
from lanerouter import LaneRouter, RedLightError

lanes = LaneRouter(check="block")
lanes.install()

try:
    requests.post("https://shop.example/checkout", json=order)
except RedLightError as err:
    print(err.condition, err.advice, err.detours)
```

`check="warn"` (the default) logs a warning through the `lanerouter` logger, once per road per
minute. `check="off"` skips checks and only reports. Pass `on_condition=` to handle amber and red
roads yourself.

## Check or report by hand

```python
lanes = LaneRouter()

lanes.check("shop.example/checkout", action="checkout")
lanes.report("shop.example/checkout", "wall", action="checkout", http_status=403)
lanes.report("shop.example/checkout", "clear", detour={"kind": "official_api", "target": "api.shop.example", "worked": True})
lanes.flush()
```

Outcomes: `clear`, `slow`, `rate_limited`, `wall`, `changed`, `broken`. Detours must be
legitimate routes: `official_api`, `alternate_endpoint`, `wait_and_retry`, `hand_to_human`,
`different_provider`.

Use `with LaneRouter() as lanes:` or call `lanes.close()` before exit so the last reports are sent.

## Watch a road

Get a signed webhook when a road turns green, amber or red. The secret is returned once, so
store it.

```python
watch = lanes.watch("shop.example/checkout", "https://your-app.example/hooks/lanerouter", action="checkout")

lanes.watches()
lanes.unwatch(watch["id"])
lanes.history(road_id=128)
```

Verify each delivery with the raw request body:

```python
from lanerouter import verify_signature

ok = verify_signature(raw_body, headers["lanerouter-signature"], os.environ["LANEROUTER_WEBHOOK_SECRET"])
```

## What leaves your machine

Only the road and the outcome: the host and its first meaningful path segment, the HTTP status,
the time it took and the library name. Full URLs, query strings, IDs, request and response
bodies, headers and personal data never leave your machine.

## Options

| Option | Default | |
|---|---|---|
| `key` | `LANEROUTER_KEY` | Your free key |
| `check` | `"warn"` | `"warn"`, `"block"` or `"off"` |
| `on_condition` | `None` | Called with the road and its conditions when it isn't green |
| `framework` | `"lanerouter-py"` | Shown to site owners in their Insights |
| `slow_ms` | `5000` | Slower than this counts as slow |
| `timeout` | `1.5` | Seconds to wait for LaneRouter before giving up |
| `check_ttl` | `60` | Seconds a check is cached |
| `report_every` | `60` | Seconds before the same road and outcome is reported again |
| `flush_interval` | `5` | Seconds reports wait before being sent in a batch |
| `ignore` | `()` | Hosts never checked or reported |

## MCP

Agents that speak MCP can connect directly instead:

```
https://lanerouter.com/mcp
```

MIT licensed.
