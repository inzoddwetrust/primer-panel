// The screens of access, as rules a test can read (DM-152).
//
// The page shows a person only what they may do; the API checks it again
// (DM-149) -- the page is never the only guard.
//
// - The columns of permissions are the API's list (/api/v1/permissions), in
//   the code's order: a new permission is a column off in every row. The
//   page knows no list of its own.
// - A member's permissions show as `effective` (what they may do -- the API
//   adds `people` to an admin); a change sets `permissions` (what is stored).
// - A person sees and gives only the permissions they hold (the superadmin,
//   all). What a staff member holds out of the giver's sight is never taken
//   by a save: the set sent is the chosen ∪ the stored the giver cannot see.

export interface Person {
  id: string
  telegram_id: number
  first_name: string | null
  username: string | null
}

export interface Member {
  user: Person
  is_admin: boolean
  permissions: string[]
  effective: string[]
}

export interface Project {
  id: string
  slug: string
  name: string
  kind: string
  repo: string
  archived_at: string | null
}

export interface Invite {
  id: string
  is_admin: boolean
  permissions: string[]
  expires_at: string
  used_at: string | null
  revoked_at: string | null
}

// What a person sees of the list: what they hold; the superadmin, all.
export function visiblePermissions(
  all: readonly string[],
  held: readonly string[],
  superadmin: boolean,
): string[] {
  return superadmin ? [...all] : all.filter((permission) => held.includes(permission))
}

// The set a save sends: the chosen, and what the member holds out of sight.
export function setToSend(
  all: readonly string[],
  chosen: readonly string[],
  stored: readonly string[],
  visible: readonly string[],
): string[] {
  const kept = stored.filter((permission) => !visible.includes(permission))
  const sent = new Set([...chosen, ...kept])
  return all.filter((permission) => sent.has(permission))
}

// A permission on in a row by what the member may do; changeable only when
// it is stored (an admin's `people` is the API's, not a checkbox).
export function cell(member: Member, permission: string): { on: boolean; fixed: boolean } {
  const on = member.effective.includes(permission)
  return { on, fixed: on && !member.permissions.includes(permission) }
}

// The rows "on for the column" changes: those where it is off.
export function columnTargets<R extends { member: Member }>(
  rows: readonly R[],
  permission: string,
): R[] {
  return rows.filter((row) => !row.member.effective.includes(permission))
}

// The staff of a project the permissions taken from an admin are taken from
// (TZ-1 1.1: from every staff member of the project): how many it touches.
export function staffTouched(members: readonly Member[], taken: readonly string[]): number {
  return members.filter(
    (member) =>
      !member.is_admin && taken.some((permission) => member.permissions.includes(permission)),
  ).length
}

// The link of an invite: the page's own sign-in with the token (gate DM-151 R6).
export function inviteLink(origin: string, token: string): string {
  return `${origin}/login?invite=${encodeURIComponent(token)}`
}

export type InviteState = 'active' | 'used' | 'revoked' | 'expired'

export function inviteState(invite: Invite, now: Date): InviteState {
  if (invite.used_at) return 'used'
  if (invite.revoked_at) return 'revoked'
  if (new Date(invite.expires_at) <= now) return 'expired'
  return 'active'
}

// Who may change a member: an admin -- the superadmin alone; staff -- whoever
// holds `people` in the project (the superadmin too).
export function mayChange(member: Member, held: readonly string[], superadmin: boolean): boolean {
  if (member.is_admin) return superadmin
  return superadmin || held.includes('people')
}

export function personName(person: Person): string {
  return person.first_name ?? person.username ?? String(person.telegram_id)
}
