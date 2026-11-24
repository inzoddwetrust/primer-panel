// The pages of the Panel: the sign-in and the person (DM-151); the projects,
// a project and the superadmin's admins (DM-152); the fleet (DM-154); a
// server's card (DM-155). The screens of the fleet,
// the server, the run and the passport come with their cards.
//
// The guard (src/main.ts, `guard`) loads the person for every page but the
// sign-in; no session (401) -- the sign-in; the superadmin's page to anybody
// else -- the projects. A path
// the page does not know leads to `/`. The container serves index.html for
// every path (nginx/default.conf.template), so /login opens by its link.

import { createRouter, type RouterHistory } from 'vue-router'
import AdminsView from './views/AdminsView.vue'
import FleetView from './views/FleetView.vue'
import LoginView from './views/LoginView.vue'
import MeView from './views/MeView.vue'
import ProjectView from './views/ProjectView.vue'
import ProjectsView from './views/ProjectsView.vue'
import ServerView from './views/ServerView.vue'

export function createPanelRouter(history: RouterHistory) {
  return createRouter({
    history,
    routes: [
      { path: '/login', name: 'login', component: LoginView },
      // The fleet is the main page (DM-154); the person is in the menu.
      { path: '/', name: 'fleet', component: FleetView },
      { path: '/me', name: 'me', component: MeView },
      // A server's card (DM-155)
      { path: '/servers/:serverId', name: 'server', component: ServerView, props: true },
      // The screens of access (DM-152)
      { path: '/projects', name: 'projects', component: ProjectsView },
      { path: '/projects/:projectId', name: 'project', component: ProjectView, props: true },
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
