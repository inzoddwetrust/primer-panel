// The pages of the Panel (DM-151): the sign-in and the person. The screens of
// the fleet, the server, the run and the passport come with their cards.
//
// The guard of `/` loads the person; no session (401) -- the sign-in. A path
// the page does not know leads to `/`. The container serves index.html for
// every path (nginx/default.conf.template), so /login opens by its link.

import { createRouter, type RouterHistory } from 'vue-router'
import LoginView from './views/LoginView.vue'
import MeView from './views/MeView.vue'

export function createPanelRouter(history: RouterHistory) {
  return createRouter({
    history,
    routes: [
      { path: '/login', name: 'login', component: LoginView },
      { path: '/', name: 'me', component: MeView },
      { path: '/:rest(.*)*', redirect: '/' },
    ],
  })
}
