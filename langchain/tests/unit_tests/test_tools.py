import json

import pytest
from langchain_core.tools import ToolException
from langchain_tests.unit_tests import ToolsUnitTests

from langchain_lanerouter import LaneRouterCheckRoad, LaneRouterRedLights, LaneRouterReportRoad, LaneRouterToolkit


class TestCheckRoadStandard(ToolsUnitTests):
    @property
    def tool_constructor(self):
        return LaneRouterCheckRoad

    @property
    def tool_constructor_params(self) -> dict:
        return {"key": ""}

    @property
    def tool_invoke_params_example(self) -> dict:
        return {"target": "shop.example/checkout", "action": "checkout"}


class TestReportRoadStandard(ToolsUnitTests):
    @property
    def tool_constructor(self):
        return LaneRouterReportRoad

    @property
    def tool_constructor_params(self) -> dict:
        return {"key": "lr_test"}

    @property
    def tool_invoke_params_example(self) -> dict:
        return {"target": "shop.example/checkout", "outcome": "wall", "http_status": 403}


def recorder(tool, response):
    calls = []

    def call(path, body=None):
        calls.append((path, body))
        return response

    object.__setattr__(tool.client, "call", call)
    return calls


def test_check_sends_only_the_road():
    tool = LaneRouterCheckRoad(key="")
    calls = recorder(tool, {"light": "green"})
    assert tool.invoke({"target": "https://www.shop.example/checkout/ORDER-8812?email=a@b.c", "action": "checkout"}) == {"light": "green"}
    assert calls == [("/api/v1/check?target=shop.example%2Fcheckout&action=checkout", None)]


def test_method_becomes_the_action():
    tool = LaneRouterCheckRoad(key="")
    calls = recorder(tool, {})
    tool.invoke({"target": "POST api.github.com/repos/x/y/pulls"})
    assert calls[0][0] == "/api/v1/check?target=api.github.com%2Frepos&action=post"


def test_report_strips_the_road_and_tags_the_framework():
    tool = LaneRouterReportRoad(key="lr_test")
    calls = recorder(tool, {"accepted": True})
    tool.invoke({"target": "shop.example/checkout/123", "outcome": "wall", "http_status": 403, "detour": {"kind": "hand_to_human", "worked": True}})
    path, body = calls[0]
    assert path == "/api/v1/report"
    assert body == {"target": "shop.example/checkout", "outcome": "wall", "http_status": 403, "framework": "langchain", "detour": {"kind": "hand_to_human", "worked": True}}


def test_report_without_a_key_returns_the_reason_to_the_model():
    tool = LaneRouterReportRoad(key="")
    calls = recorder(tool, {})
    assert "free LaneRouter key" in tool.invoke({"target": "shop.example", "outcome": "clear"})
    assert calls == []


def test_bad_target_is_a_tool_error():
    tool = LaneRouterCheckRoad(key="")
    with pytest.raises(ToolException):
        tool._run(target="localhost")


def test_red_lights_keeps_only_red_roads():
    tool = LaneRouterRedLights(key="", endpoint="https://lanerouter.test")
    recorder(tool, {"updated_at": "t", "roads": [{"id": 7, "road": "shop.example/checkout", "light": "red", "condition": "wall"}, {"id": 8, "road": "a.example", "light": "green"}]})
    out = tool.invoke({})
    assert [r["road"] for r in out["red_lights"]] == ["shop.example/checkout"]
    assert out["red_lights"][0]["url"] == "https://lanerouter.test/road/7"


def test_toolkit_leaves_out_reporting_without_a_key():
    assert [t.name for t in LaneRouterToolkit(key="").get_tools()] == ["check_road", "red_lights"]
    assert [t.name for t in LaneRouterToolkit(key="lr_test").get_tools()] == ["check_road", "red_lights", "report_road"]


def test_key_never_appears_in_the_tool_repr():
    assert "lr_secret" not in repr(LaneRouterReportRoad(key="lr_secret"))
    assert "lr_secret" not in json.dumps(LaneRouterToolkit(key="lr_secret").get_tools()[0].tool_call_schema.model_json_schema())
