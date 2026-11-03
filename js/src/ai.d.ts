import type { Tool } from 'ai'

export interface LaneRouterToolOptions {
  key?: string
  endpoint?: string
  framework?: string
  fetch?: typeof fetch
}

export interface CheckRoadInput { target: string; action?: string }
export interface ReportRoadInput {
  target: string
  action?: string
  outcome: 'clear' | 'slow' | 'rate_limited' | 'wall' | 'changed' | 'broken'
  http_status?: number
  latency_ms?: number
  detour?: { kind: 'official_api' | 'alternate_endpoint' | 'wait_and_retry' | 'hand_to_human' | 'different_provider'; target?: string; note?: string; worked: boolean }
}

export function checkRoad(options?: LaneRouterToolOptions): Tool<CheckRoadInput, any>
export function reportRoad(options?: LaneRouterToolOptions): Tool<ReportRoadInput, any>
export function redLights(options?: LaneRouterToolOptions): Tool<Record<string, never>, any>
export function laneRouterTools(options?: LaneRouterToolOptions): {
  checkRoad: Tool<CheckRoadInput, any>
  redLights: Tool<Record<string, never>, any>
  reportRoad?: Tool<ReportRoadInput, any>
}
