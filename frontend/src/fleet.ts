// A server of the fleet as the API gives it (GET /api/v1/servers, DM-154):
// every field is what the box sent, null when there is no data; `reasons` --
// why it is red, a closed list of the API; the API gives the order.

export interface FleetServer {
  id: string
  name: string
  role: string
  project: { id: string; slug: string; name: string; kind: string }
  heartbeat_at: string | null
  machine_version: string | null
  machine_release: string
  verdict: {
    run_id: string
    verb: string
    result: string
    finished: string
    verified: boolean
  } | null
  stacks: { stack: string; release: string | null }[] | null
  health: { healthy: number; unhealthy: number; starting: number; none: number } | null
  ssl: { mode: string; expires: string; renews_from: string | null } | null
  measured_at: string | null
  reasons: string[]
}
