from langchain_tests.integration_tests import ToolsIntegrationTests

from langchain_lanerouter import LaneRouterCheckRoad, LaneRouterRedLights


class TestCheckRoadLive(ToolsIntegrationTests):
    @property
    def tool_constructor(self):
        return LaneRouterCheckRoad

    @property
    def tool_constructor_params(self) -> dict:
        return {"key": ""}

    @property
    def tool_invoke_params_example(self) -> dict:
        return {"target": "github.com/login", "action": "login"}


def test_red_lights_live():
    out = LaneRouterRedLights(key="").invoke({})
    assert "red_lights" in out
