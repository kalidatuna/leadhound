// Entry: translations, tabs, background-job pill, update notice, first-run wizard.
import { $, $$, api, el, on, state, store } from './util.js';
import { initI18n, t, LANG, setLang } from './i18n.js';
import { initToday } from './today.js';
import { initLeads } from './leads.js';
import { initFind } from './find.js';
import { initSettings, showWizard, checkUpdate } from './settings.js';

const VIEWS = ['today', 'leads', 'find', 'settings'];
let mode = store.get('lh-mode') === 'advanced' ? 'advanced' : 'simple';
let paintMode = () => {};
function setMode(m) { mode = m; store.set('lh-mode', m); paintMode(); }

function show(view) {
  if (!VIEWS.includes(view)) view = mode === 'simple' ? 'today' : 'leads';
  if (mode === 'simple') view = 'today';  // the simple view has one screen; Advanced has the rest
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
  document.body.dataset.mode = mode;
  const modeBtn = $('#mode');
  paintMode = () => { document.body.dataset.mode = mode; modeBtn.textContent = mode === 'simple' ? t('mode.advanced') : t('mode.simple'); };
  paintMode();
  modeBtn.addEventListener('click', () => { setMode(mode === 'simple' ? 'advanced' : 'simple'); show(mode === 'simple' ? 'today' : 'leads'); });
  const lang = $('#lang');
  lang.replaceChildren(...Object.entries(state.meta.languages).map(([c, n]) => el('option', { value: c, selected: c === LANG }, n)));
  lang.addEventListener('change', () => setLang(lang.value));
  if (!state.meta.cloud) {
    const q = $('#quit');
    q.hidden = false; q.textContent = t('quit');
    q.addEventListener('click', async () => {
      await api('/api/quit', {}).catch(() => {});
      document.body.replaceChildren(el('div', { class: 'empty' }, el('h2', {}, t('quit.title')), el('p', {}, t('quit.text'))));
    });
  }
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
  initToday();
  const first = state.meta.first_run;
  show(first ? 'today' : location.hash.slice(1) || (mode === 'simple' ? 'today' : 'leads'));
  if (first) showWizard();
  // quiet update notice in the header (checked at most twice a day by the server)
  checkUpdate(null, false).then(u => {
    if (u && u.newer) $('#upd-pill').replaceChildren(el('button', { class: 'pill', onclick: () => { setMode('advanced'); show('settings'); $('#upd')?.scrollIntoView(); } }, t('banner.update', { v: u.latest })));
  });
}

boot();
