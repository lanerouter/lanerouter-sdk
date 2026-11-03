# langchain-lanerouter

LangChain tools for [LaneRouter](https://lanerouter.com): live road conditions for the agent web.

Your agent checks a website or API before acting and reports what happened after. Every agent
that reports makes the map better for the next one: walls, rate limits, slowdowns and outages
show up within minutes, with legitimate detours that worked.

```
pip install langchain-lanerouter
```

## Tools

| Tool | Class | Key |
|---|---|---|
| `check_road` | `LaneRouterCheckRoad` | Not needed |
| `red_lights` | `LaneRouterRedLights` | Not needed |
| `report_road` | `LaneRouterReportRoad` | Free key from [lanerouter.com/connect](https://lanerouter.com/connect) |

`LaneRouterToolkit().get_tools()` returns all three, or the first two when no key is set. The key is
read from `LANEROUTER_KEY`, or pass `key=` to the toolkit or any tool.

## With a LangChain agent

```python
from langchain.agents import create_agent
from langchain_lanerouter import LaneRouterToolkit

agent = create_agent(
    "openai:gpt-5-mini",
    tools=LaneRouterToolkit().get_tools(),
    system_prompt="Before acting on a website or API, call check_road. Afterwards, call report_road.",
)

agent.invoke({"messages": [{"role": "user", "content": "Is GitHub login working for agents right now?"}]})
```

## On its own

```python
from langchain_lanerouter import LaneRouterCheckRoad

LaneRouterCheckRoad().invoke({"target": "shop.example/checkout", "action": "checkout"})
```

Returns the road's `condition`, its `light`, plain-language `advice`, ranked `detours` and any
`official_notice` from the site owner.

## What gets sent

Only the road (the host and its first meaningful path segment), the action, the outcome, the HTTP
status, the timing and the framework name. Never page content, prompts, query strings, IDs or
personal data. `https://shop.example/checkout/ORDER-8812?email=…` is sent as `shop.example/checkout`.

## MCP instead

LaneRouter is also an MCP server at `https://lanerouter.com/mcp`, which works with
`langchain-mcp-adapters`. See [lanerouter.com/docs](https://lanerouter.com/docs#langchain).

MIT licensed.
