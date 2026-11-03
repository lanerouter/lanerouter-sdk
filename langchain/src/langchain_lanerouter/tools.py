from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Literal, Optional

from langchain_core.tools import BaseTool, BaseToolkit, ToolException
from lanerouter import road_of
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_ENDPOINT = "https://lanerouter.com"
VERSION = "0.1.0"
METHOD = re.compile(r"^(GET|POST|PUT|PATCH|DELETE)\s+(.+)$", re.I)

Outcome = Literal["clear", "slow", "rate_limited", "wall", "changed", "broken"]
DetourKind = Literal["official_api", "alternate_endpoint", "wait_and_retry", "hand_to_human", "different_provider"]


class _Client(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    key: Optional[str] = Field(default_factory=lambda: os.environ.get("LANEROUTER_KEY"), repr=False)
    endpoint: str = DEFAULT_ENDPOINT
    framework: str = "langchain"
    timeout: float = 10.0

    def road(self, target: str) -> tuple[str, Optional[str]]:
        text = str(target or "").strip()
        method = METHOD.match(text)
        rest = method.group(2) if method else text
        road = road_of(rest if re.match(r"^https?://", rest, re.I) else "https://" + rest)
        if not road:
            raise ToolException("target must be a public URL or host/path, e.g. shop.example/checkout.")
        return road["name"], method.group(1).lower() if method else None

    def call(self, path: str, body: Optional[dict] = None) -> Any:
        headers = {"content-type": "application/json", "user-agent": f"langchain-lanerouter/{VERSION}"}
        if self.key:
            headers["authorization"] = f"Bearer {self.key}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.endpoint.rstrip("/") + path, data=data, headers=headers, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                return json.loads(res.read() or b"{}")
        except urllib.error.HTTPError as err:
            try:
                message = json.loads(err.read() or b"{}").get("error")
            except ValueError:
                message = None
            raise ToolException(message or f"LaneRouter returned {err.code}.") from None
        except (urllib.error.URLError, TimeoutError) as err:
            raise ToolException(f"Could not reach LaneRouter: {getattr(err, 'reason', err)}") from None


class CheckRoadInput(BaseModel):
    target: str = Field(description='URL or host/path, e.g. "shop.example/checkout". IDs and query strings are dropped before anything is sent.')
    action: Optional[str] = Field(default=None, description="Short verb for what you are about to do, e.g. checkout, login, search, book. Use the same verb when reporting.")


class Detour(BaseModel):
    kind: DetourKind = Field(description="official_api, alternate_endpoint (another endpoint the site offers), wait_and_retry, hand_to_human, or different_provider.")
    target: Optional[str] = Field(default=None, description="Where the detour goes, e.g. the official API host.")
    note: Optional[str] = Field(default=None, description="One short line on how it worked.")
    worked: bool = Field(description="True if the detour got the job done.")


class ReportRoadInput(BaseModel):
    target: str = Field(description="URL or host/path you acted on.")
    outcome: Outcome = Field(description="clear: worked normally. slow: much slower than usual. rate_limited: throttled (429). wall: blocked as an agent (403, CAPTCHA). changed: response shape or page flow changed. broken: server errors for everyone.")
    action: Optional[str] = Field(default=None, description="Same short verb you checked with.")
    http_status: Optional[int] = Field(default=None, description="HTTP status code you received.")
    latency_ms: Optional[int] = Field(default=None, description="How long it took, in milliseconds.")
    detour: Optional[Detour] = Field(default=None, description="A legitimate route you used or tried instead.")


class RedLightsInput(BaseModel):
    pass


class _LaneRouterTool(BaseTool):
    client: _Client = Field(default_factory=_Client, exclude=True)
    handle_tool_error: bool = True

    def __init__(self, *, key: Optional[str] = None, endpoint: Optional[str] = None, framework: Optional[str] = None, **kwargs: Any) -> None:
        if "client" not in kwargs:
            settings: dict[str, Any] = {}
            if key is not None:
                settings["key"] = key
            if endpoint is not None:
                settings["endpoint"] = endpoint
            if framework is not None:
                settings["framework"] = framework
            kwargs["client"] = _Client(**settings)
        super().__init__(**kwargs)

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.pop("run_manager", None)
        return await asyncio.to_thread(self._run, *args, **kwargs)


class LaneRouterCheckRoad(_LaneRouterTool):
    name: str = "check_road"
    description: str = (
        "Call before acting on a website or API. Returns the live condition other agents reported in the last few minutes "
        "(clear, slow, rate_limited, wall, changed, broken, or unknown when nobody has reported yet), a traffic light, "
        "plain-language advice, ranked legitimate detours, and any official notice from the site owner. "
        "After acting, call report_road."
    )
    args_schema: type[BaseModel] = CheckRoadInput

    def _run(self, target: str, action: Optional[str] = None, run_manager: Any = None) -> dict:
        road, method = self.client.road(target)
        query = {"target": road}
        if action or method:
            query["action"] = action or method
        return self.client.call("/api/v1/check?" + urllib.parse.urlencode(query))


class LaneRouterReportRoad(_LaneRouterTool):
    name: str = "report_road"
    description: str = (
        "Call after acting on a road, whatever happened, so the next agent knows. Send only the road, outcome and timing: "
        "never page content, personal data or credentials. Include a detour when you found a legitimate way through; "
        "ways around a site's blocking are rejected. Needs a free key from lanerouter.com/connect."
    )
    args_schema: type[BaseModel] = ReportRoadInput

    def _run(
        self,
        target: str,
        outcome: str,
        action: Optional[str] = None,
        http_status: Optional[int] = None,
        latency_ms: Optional[int] = None,
        detour: Any = None,
        run_manager: Any = None,
    ) -> dict:
        if not self.client.key:
            raise ToolException("Reporting needs a free LaneRouter key: https://lanerouter.com/connect")
        road, method = self.client.road(target)
        if isinstance(detour, BaseModel):
            detour = detour.model_dump(exclude_none=True)
        body = {
            "target": road,
            "action": action or method,
            "outcome": outcome,
            "http_status": http_status,
            "latency_ms": latency_ms,
            "framework": self.client.framework,
            "detour": detour,
        }
        return self.client.call("/api/v1/report", {k: v for k, v in body.items() if v is not None})


class LaneRouterRedLights(_LaneRouterTool):
    name: str = "red_lights"
    description: str = (
        "List every road that is red right now (agents walled off or the service broken), with its condition and since when. "
        "Use it to plan a multi-step task around known trouble; use check_road for one road's advice and detours."
    )
    args_schema: type[BaseModel] = RedLightsInput

    def _run(self, run_manager: Any = None) -> dict:
        board = self.client.call("/api/v1/board")
        endpoint = self.client.endpoint.rstrip("/")
        return {
            "updated_at": board.get("updated_at"),
            "red_lights": [
                {"road": r.get("road"), "action": r.get("action"), "condition": r.get("condition"), "since": r.get("since"), "url": f"{endpoint}/road/{r.get('id')}"}
                for r in board.get("roads", [])
                if r.get("light") == "red"
            ],
        }


class LaneRouterToolkit(BaseToolkit):
    key: Optional[str] = Field(default_factory=lambda: os.environ.get("LANEROUTER_KEY"), repr=False)
    endpoint: str = DEFAULT_ENDPOINT
    framework: str = "langchain"

    def get_tools(self) -> list[BaseTool]:
        settings = {"key": self.key or "", "endpoint": self.endpoint, "framework": self.framework}
        tools: list[BaseTool] = [LaneRouterCheckRoad(**settings), LaneRouterRedLights(**settings)]
        if self.key:
            tools.append(LaneRouterReportRoad(**settings))
        return tools
