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
| MCP | `https://lanerouter.com/mcp` | [server.json](server.json) |

```
claude mcp add --transport http lanerouter https://lanerouter.com/mcp \
  --header "Authorization: Bearer lr_YOUR_KEY"
```

Get a free key at [lanerouter.com/connect](https://lanerouter.com/connect). Checking roads works
without one; reporting needs one.

Documentation: [lanerouter.com/docs](https://lanerouter.com/docs)

Support: support@lanerouter.com · Security: see [lanerouter.com/contact](https://lanerouter.com/contact#security)

MIT licensed.
