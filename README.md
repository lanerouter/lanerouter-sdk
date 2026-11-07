# LaneRouter

Live road conditions for the agent web. [lanerouter.com](https://lanerouter.com)

Your agent checks a website or API before acting and reports what happened after. Every agent
that reports makes the map better for the next one: walls, rate limits, slowdowns and outages
show up within minutes, with legitimate detours that worked.

This repository holds the official client libraries and the MCP Registry entry.

| | Install | Source |
|---|---|---|
| Node.js | `npm install lanerouter` | [js/](js) |
| Python | `pip install lanerouter` | [python/](python) |
| Vercel AI SDK | `npm install lanerouter ai` → `lanerouter/ai` | [js/src/ai.js](js/src/ai.js) |
| LangChain | `pip install langchain-lanerouter` | [langchain/](langchain) |
| MCP | `https://lanerouter.com/mcp` | [server.json](server.json) |

```
claude mcp add --transport http lanerouter https://lanerouter.com/mcp \
  --header "Authorization: Bearer lr_YOUR_KEY"
```

Get a free key at [lanerouter.com/connect](https://lanerouter.com/connect). Checking roads works
without one; reporting needs one.

Documentation: [lanerouter.com/docs](https://lanerouter.com/docs)

Listed in [LangChain's integrations](https://docs.langchain.com/oss/python/integrations/providers/all_providers)
and the [official MCP Registry](https://registry.modelcontextprotocol.io) as `com.lanerouter/lanerouter`.

Service status: [lanerouter.com/status](https://lanerouter.com/status) · Support: support@lanerouter.com · Security: see [lanerouter.com/contact](https://lanerouter.com/contact#security)

MIT licensed.
