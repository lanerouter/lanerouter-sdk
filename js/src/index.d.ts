export type Outcome = 'clear' | 'slow' | 'rate_limited' | 'wall' | 'changed' | 'broken'
export type Condition = Outcome | 'unknown'
export type Light = 'green' | 'amber' | 'red' | 'off'
export type DetourKind = 'official_api' | 'alternate_endpoint' | 'wait_and_retry' | 'hand_to_human' | 'different_provider'

export interface Detour {
  kind: DetourKind
  target?: string
  note?: string
  worked: boolean
}

export interface CheckResult {
  road: string
  action: string
  condition: Condition
  light: Light
  confidence: number
  reports: number
  reporters: number
  since: string | null
  patrol_only?: boolean
  detours: Array<{ kind: DetourKind; target: string | null; note: string | null; success_rate: number; reporters: number }>
  advice: string
  known: boolean
  url?: string
}

export interface LaneRouterOptions {
  key?: string
  endpoint?: string
  framework?: string
  check?: 'warn' | 'block' | 'off'
  onCondition?: (result: CheckResult & { road: string }) => void
  slowMs?: number
  timeoutMs?: number
  checkTtlMs?: number
  reportEveryMs?: number
  flushMs?: number
  ignore?: string[]
  fetch?: typeof fetch
  debug?: boolean
}

export declare class RedLightError extends Error {
  road: string
  condition: Condition
  detours: CheckResult['detours']
  advice: string
}

export interface Watch {
  id: number
  road: string
  action: string
  road_id: number
  url: string
  active: boolean
  condition: Condition
  light: Light
  created_at: string
  last_delivery: { state: 'pending' | 'sending' | 'sent' | 'failed'; status: number | null; error: string | null; attempts: number; at: string } | null
}

export interface RoadChangedEvent {
  type: 'road.changed'
  test: boolean
  watch_id: number
  road: string
  action: string
  road_id: number
  url: string
  condition: Condition
  light: Light
  previous_light: Light | null
  changed_at: string
  delivery_id: number
  attempt: number
}

export interface History {
  road: string
  action: string
  days: { date: string; counts: Record<Outcome, number>; total: number; light: Light }[]
  changes: { condition: Condition; light: Light; previous: Condition | null; at: string }[]
}

export declare class LaneRouterError extends Error {
  status: number
}

export declare function verifySignature(body: string | Uint8Array, header: string | null | undefined, secret: string, options?: { toleranceSec?: number; now?: number }): Promise<boolean>

export declare class LaneRouter {
  constructor(options?: LaneRouterOptions)
  fetch: typeof fetch
  check(target: string | URL, options?: { action?: string }): Promise<CheckResult | null>
  report(target: string | URL, outcome: Outcome, options?: { action?: string; httpStatus?: number; latencyMs?: number; detour?: Detour }): boolean
  flush(): Promise<void>
  install(): () => void
  uninstall(): void
  close(): Promise<void>
  watch(target: string | URL, url: string, options?: { action?: string }): Promise<Watch & { secret: string }>
  unwatch(id: number): Promise<void>
  watches(): Promise<Watch[]>
  history(roadId: number, options?: { days?: number }): Promise<History>
}

export declare function roadOf(input: string | URL): { host: string; path: string; name: string } | null
export declare function classify(input: { status: number; latencyMs?: number; body?: string; slowMs?: number }): Outcome
export declare const OUTCOMES: Outcome[]
export declare const DETOUR_KINDS: DetourKind[]
export default LaneRouter
