// Entry: translations, tabs, background-job pill, update notice, first-run wizard.
import { $, $$, api, el, on, state } from './util.js';
import { initI18n, t } from './i18n.js';
import { initLeads } from './leads.js';
import { initFind } from './find.js';
import { initSettings, showWizard, checkUpdate } from './settings.js';

const VIEWS = ['leads', 'find', 'settings'];

function show(view) {
  if (!VIEWS.includes(view)) view = 'leads';
  VIEWS.forEach(v => { $('#view-' + v).hidden = v !== view; });
  $$('.tab').forEach(x => x.classList.toggle('on', x.dataset.view === view));
  try { history.replaceState(null, '', '#' + view); } catch { /* sandboxed */ }
}

async function boot() {
  try {
    state.meta = await api('/api/meta');
    [state.cfg] = await Promise.all([api('/api/config'), initI18n(state.meta.languages)]);
  } catch (e) {
    document.body.replaceChildren(el('div', { class: 'empty' }, el('h2', {}, 'leadhound'), el('p', {}, e.message)));
    return;
  }
  $$('.tab').forEach(x => { x.textContent = t('nav.' + x.dataset.view); x.addEventListener('click', () => show(x.dataset.view)); });
  on('goto', show);
  on('job', j => {
    const pill = $('#pill');
    pill.hidden = !j || j.status !== 'running' || j.kind === 'update';
    if (!pill.hidden) pill.replaceChildren(el('span', { class: 'spin' }), t('pill.searching'));
  });
  $('#pill').addEventListener('click', () => show('find'));
  await initSettings();
  initFind();
  initLeads();
  const first = state.meta.first_run;
  show(first ? 'leads' : location.hash.slice(1) || 'leads');
  if (first) showWizard();
  // quiet update notice in the header (checked at most twice a day by the server)
  checkUpdate(null, false).then(u => {
    if (u && u.newer) $('#upd-pill').replaceChildren(el('button', { class: 'pill', onclick: () => { show('settings'); $('#upd')?.scrollIntoView(); } }, t('banner.update', { v: u.latest })));
  });
}

boot();
