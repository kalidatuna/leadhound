// Entry: translations, header (accounts, language, mode, quit), views, background-job pill, update notice, first-run wizard.
import { $, $$, api, el, on, emit, state, store } from './util.js';
import { initI18n, t, LANG, setLang } from './i18n.js';
import { icon } from './icons.js';
import { initToday } from './today.js';
import { initLeads } from './leads.js';
import { initFind } from './find.js';
import { initSettings, showWizard, checkUpdate } from './settings.js';
import { initAccounts, loadAccounts } from './accounts.js';
import { initPlan, loadPlan } from './plan.js';

const VIEWS = ['today', 'accounts', 'leads', 'find', 'settings'];
const SIMPLE_VIEWS = ['today', 'accounts'];  // the simple view has Today and Accounts; Advanced has the rest
let mode = store.get('lh-mode') === 'advanced' ? 'advanced' : 'simple';
let paintMode = () => {};
function setMode(m) { mode = m; store.set('lh-mode', m); paintMode(); }

function show(view) {
  if (!VIEWS.includes(view)) view = mode === 'simple' ? 'today' : 'leads';
  if (mode === 'simple' && !SIMPLE_VIEWS.includes(view)) view = 'today';
  VIEWS.forEach(v => { $('#view-' + v).hidden = v !== view; });
  $$('.tab').forEach(x => x.classList.toggle('on', x.dataset.view === view));
  $('#acct-btn').classList.toggle('on', view === 'accounts');
  try { history.replaceState(null, '', '#' + view); } catch { /* sandboxed */ }
}

function languageMenu() {
  const btn = $('#lang-btn'), menu = $('#lang-menu');
  btn.firstChild.textContent = state.meta.languages[LANG];
  btn.setAttribute('aria-label', t('hdr.language'));
  const close = () => { menu.hidden = true; btn.setAttribute('aria-expanded', 'false'); document.removeEventListener('click', away, true); document.removeEventListener('keydown', esc); };
  const away = e => { if (!menu.contains(e.target) && !btn.contains(e.target)) close(); };
  const esc = e => { if (e.key === 'Escape') { close(); btn.focus(); } };
  btn.addEventListener('click', () => {
    if (!menu.hidden) return close();
    menu.replaceChildren(...Object.entries(state.meta.languages).map(([code, name]) =>
      el('button', { role: 'menuitemradio', 'aria-checked': code === LANG, lang: code, onclick: () => { close(); if (code !== LANG) setLang(code); } }, el('span', {}, name), code === LANG && icon('check'))));
    menu.hidden = false; btn.setAttribute('aria-expanded', 'true');
    menu.querySelector('[aria-checked=true]').focus();
    setTimeout(() => { document.addEventListener('click', away, true); document.addEventListener('keydown', esc); });
  });
  menu.addEventListener('keydown', e => {
    const items = $$('button', menu), i = items.indexOf(document.activeElement);
    if (e.key === 'ArrowDown') { items[(i + 1) % items.length].focus(); e.preventDefault(); }
    if (e.key === 'ArrowUp') { items[(i - 1 + items.length) % items.length].focus(); e.preventDefault(); }
  });
}

function quitButton() {
  const q = $('#quit'), d = $('#quit-dialog');
  q.hidden = false; q.textContent = t('quit');
  q.addEventListener('click', () => {
    d.replaceChildren(el('div', { class: 'sheet' },
      el('div', { class: 'sheet-h' }, el('div', { class: 'ai' }, icon('power')), el('div', {}, el('h3', {}, t('quit.confirm_title')), el('p', {}, t('quit.confirm_text')))),
      el('div', { class: 'sheet-f' }, el('button', { class: 'btn ghost', onclick: () => d.close() }, t('quit.keep')),
        el('button', { class: 'cta sm', onclick: async () => {
          d.close();
          await api('/api/quit', {}).catch(() => {});
          document.body.replaceChildren(el('div', { class: 'bye' }, el('span', { class: 'logo' }, 'l'), el('h2', {}, t('quit.title')), el('p', {}, t('quit.text'))));
        } }, t('quit')))));
    d.showModal();
  });
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
  paintMode = () => { document.body.dataset.mode = mode; modeBtn.textContent = mode === 'simple' ? t('mode.advanced') : t('mode.simple'); modeBtn.setAttribute('aria-pressed', mode === 'advanced'); $('#nav').hidden = mode === 'simple'; };
  paintMode();
  modeBtn.addEventListener('click', () => { setMode(mode === 'simple' ? 'advanced' : 'simple'); show(mode === 'simple' ? 'today' : 'leads'); });
  languageMenu();
  if (!state.meta.cloud) quitButton();
  on('goto', show);
  on('open-settings', () => { setMode('advanced'); show('settings'); });
  on('job', j => {
    const pill = $('#pill');
    pill.hidden = !j || j.status !== 'running' || j.kind === 'update';
    if (!pill.hidden) pill.replaceChildren(el('span', { class: 'spin' }), t('pill.searching'));
  });
  $('#pill').addEventListener('click', () => show('find'));
  await Promise.all([initSettings(), loadAccounts(), loadPlan()]);
  initAccounts();
  initPlan();
  on('plan-changed', () => emit('profile-changed'));
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
void emit;
