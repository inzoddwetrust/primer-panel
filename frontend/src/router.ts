// The pages of the Panel: the sign-in and the person (DM-151); the projects,
// a project and the superadmin's admins (DM-152); the fleet (DM-154); a
// server's card (DM-155); a run (DM-156); a new server (DM-157); a server's
// passport (DM-158). The screens of the fleet,
// the server, the run and the passport come with their cards.
//
// The guard (src/main.ts, `guard`) loads the person for every page but the
// sign-in; no session (401) -- the sign-in; the superadmin's page to anybody
// else -- the projects. A path
// the page does not know leads to `/`. The container serves index.html for
// every path (nginx/default.conf.template), so /login opens by its link.
//
// A parameter of a path has its form (DM-210, PRIMER-PANEL-REVIEW-0001): a
// server and a project are UUIDs, a run is the machine's run id. vue-router
// decodes a parameter -- `/servers/..%2F..%2Fusers` gave `../../users` to
// the screen, which put it into a path of the API (measured, 4.6.4). A
// parameter off its form matches no page: the path is one the Panel does not
// know and leads to `/`, and no screen is made of it. What the Panel writes
// itself -- a link to a run keeps its colons -- is of the form.

import { createRouter, type RouterHistory } from 'vue-router'
import AddServerView from './views/AddServerView.vue'
import AdminsView from './views/AdminsView.vue'
import FleetView from './views/FleetView.vue'
import LoginView from './views/LoginView.vue'
import MeView from './views/MeView.vue'
import PassportView from './views/PassportView.vue'
import ProjectView from './views/ProjectView.vue'
import ProjectsView from './views/ProjectsView.vue'
import RunView from './views/RunView.vue'
import ServerView from './views/ServerView.vue'

// Written out, as vue-router takes them: the form of a UUID, and of a run's
// id (pridem.report.schema.RUN_ID: `2026-11-25T10:00:00Z-a3f9`).
export const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
export const RUN_ID = '[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z-[0-9a-f]{4}'
const SERVER = `/servers/:serverId(${UUID})`
const PROJECT = `/projects/:projectId(${UUID})`

export function createPanelRouter(history: RouterHistory) {
  return createRouter({
    history,
    routes: [
      { path: '/login', name: 'login', component: LoginView },
      // The fleet is the main page (DM-154); the person is in the menu.
      { path: '/', name: 'fleet', component: FleetView },
      { path: '/me', name: 'me', component: MeView },
      // A server's card (DM-155)
      { path: SERVER, name: 'server', component: ServerView, props: true },
      // A server's passport (DM-158)
      {
        path: `${SERVER}/passport`,
        name: 'passport',
        component: PassportView,
        props: true,
      },
      // A run (DM-156)
      {
        path: `${SERVER}/runs/:runId(${RUN_ID})`,
        name: 'run',
        component: RunView,
        props: true,
      },
      // The screens of access (DM-152)
      { path: '/projects', name: 'projects', component: ProjectsView },
      { path: PROJECT, name: 'project', component: ProjectView, props: true },
      // A new server of a project (DM-157)
      {
        path: `${PROJECT}/servers/new`,
        name: 'add-server',
        component: AddServerView,
        props: true,
      },
      { path: '/superadmin/admins', name: 'admins', component: AdminsView },
      { path: '/:rest(.*)*', redirect: '/' },
    ],
  })
}

// What every page but the sign-in needs first: the person of the session.
export function guard(
  load: () => Promise<'signed_in' | 'unauthorized' | 'failed'>,
  superadmin: () => boolean,
) {
  return async (to: { name?: unknown }) => {
    if (to.name === 'login') {
      return true
    }
    if ((await load()) === 'unauthorized') {
      return { name: 'login' }
    }
    if (to.name === 'admins' && !superadmin()) {
      return { name: 'projects' }
    }
    return true
  }
}
