// Entry: translations, header (accounts, mode, the ⋯ menu with language, theme and quit), views, background-job pill, update notice, first-run wizard.
import { $, $$, api, el, on, emit, state, store } from './util.js';
import { initI18n, t, LANG, setLang } from './i18n.js';
import { icon } from './icons.js';
import { initToday } from './today.js';
import { initLeads, addLead } from './leads.js';
import { initFind } from './find.js';
import { initSettings, showWizard, checkUpdate } from './settings.js';
import { initAccounts, loadAccounts } from './accounts.js';
import { initPlan, loadPlan } from './plan.js';

const VIEWS = ['today', 'accounts', 'leads', 'find', 'settings'];
const SIMPLE_VIEWS = ['today', 'accounts'];  // the simple view has Today and Accounts; Advanced has the rest
let mode = store.get('lh-mode') === 'advanced' ? 'advanced' : 'simple';
let paintMode = () => {};
function setMode(m) { mode = m; store.set('lh-mode', m); paintMode(); }

let current = 'today', lastJob = null;
function paintJobPill() {  // Today and Find show the search themselves; the header pill is for the other screens
  const pill = $('#pill'), j = lastJob;
  pill.hidden = !j || j.status !== 'running' || j.kind === 'update' || current === 'today' || current === 'find';
  if (!pill.hidden) pill.replaceChildren(el('span', { class: 'spin' }), t('pill.searching'));
}

function show(view) {
  if (!VIEWS.includes(view)) view = mode === 'simple' ? 'today' : 'leads';
  if (mode === 'simple' && !SIMPLE_VIEWS.includes(view)) view = 'today';
  current = view;
  document.body.dataset.view = view;
  paintJobPill();
  VIEWS.forEach(v => { $('#view-' + v).hidden = v !== view; });
  $$('.tab').forEach(x => x.classList.toggle('on', x.dataset.view === view));
  $('#acct-btn').classList.toggle('on', view === 'accounts');
  try { history.replaceState(null, '', '#' + view); } catch { /* sandboxed */ }
}

const THEMES = ['auto', 'light', 'dark'];
const theme = () => (THEMES.includes(store.get('lh-theme')) ? store.get('lh-theme') : 'auto');
function setTheme(v) {
  store.set('lh-theme', v);
  if (v === 'auto') document.documentElement.removeAttribute('data-theme'); else document.documentElement.dataset.theme = v;
}

// The ⋯ menu: language, theme and Quit, so the header stays on one line.
function moreMenu() {
  const btn = $('#more-btn'), menu = $('#more-menu');
  btn.replaceChildren(icon('more'));
  btn.setAttribute('aria-label', t('hdr.more'));
  btn.title = t('hdr.more');
  const close = () => { menu.hidden = true; btn.setAttribute('aria-expanded', 'false'); document.removeEventListener('click', away, true); document.removeEventListener('keydown', esc); };
  const away = e => { if (!menu.contains(e.target) && !btn.contains(e.target)) close(); };
  const esc = e => { if (e.key === 'Escape') { close(); btn.focus(); } };
  const item = (label, attrs, ...kids) => el('button', { role: 'menuitem', ...attrs }, el('span', {}, label), ...kids);
  const radio = (label, on_, fn, attrs = {}) => el('button', { role: 'menuitemradio', 'aria-checked': on_, onclick: fn, ...attrs }, el('span', {}, label), on_ && icon('check'));
  const page = name => {
    if (name === 'lang') {
      menu.replaceChildren(item(t('hdr.language'), { onclick: () => page('main') }, icon('back')),
        ...Object.entries(state.meta.languages).map(([code, n]) => radio(n, code === LANG, () => { close(); if (code !== LANG) setLang(code); }, { lang: code })));
    } else if (name === 'theme') {
      menu.replaceChildren(item(t('hdr.theme'), { onclick: () => page('main') }, icon('back')),
        ...THEMES.map(v => radio(t('theme.' + v), v === theme(), () => { setTheme(v); page('theme'); })));
    } else {
      menu.replaceChildren(...[
        item(t('hdr.language'), { onclick: () => page('lang') }, el('span', { class: 'mv' }, state.meta.languages[LANG]), icon('chev')),
        item(t('hdr.theme'), { onclick: () => page('theme') }, el('span', { class: 'mv' }, t('theme.' + theme())), icon('chev')),
        !state.meta.cloud && el('hr'),
        !state.meta.cloud && item(t('quit'), { onclick: () => { close(); confirmQuit(); } }, icon('power'))].filter(Boolean));
    }
    (menu.querySelector('[aria-checked=true]') || menu.querySelector('button')).focus();
  };
  btn.addEventListener('click', () => {
    if (!menu.hidden) return close();
    menu.hidden = false; btn.setAttribute('aria-expanded', 'true');
    page('main');
    setTimeout(() => { document.addEventListener('click', away, true); document.addEventListener('keydown', esc); });
  });
  menu.addEventListener('keydown', e => {
    const items = $$('button', menu), i = items.indexOf(document.activeElement);
    if (e.key === 'ArrowDown') { items[(i + 1) % items.length].focus(); e.preventDefault(); }
    if (e.key === 'ArrowUp') { items[(i - 1 + items.length) % items.length].focus(); e.preventDefault(); }
  });
}

function confirmQuit() {
  const d = $('#quit-dialog');
  d.replaceChildren(el('div', { class: 'sheet' },
    el('div', { class: 'sheet-h' }, el('div', { class: 'ai' }, icon('power')), el('div', {}, el('h3', {}, t('quit.confirm_title')), el('p', {}, t('quit.confirm_text')))),
    el('div', { class: 'sheet-f' }, el('button', { class: 'btn ghost', onclick: () => d.close() }, t('quit.keep')),
      el('button', { class: 'cta sm', onclick: async () => {
        d.close();
        await api('/api/quit', {}).catch(() => {});
        document.body.replaceChildren(el('div', { class: 'bye' }, el('img', { class: 'logo', src: '/static/logo.svg', alt: '' }), el('h2', {}, t('quit.title')), el('p', {}, t('quit.text'))));
      } }, t('quit')))));
  d.showModal();
}

// #add?url=…&title=…&text=… and #check?url=… come from the browser extension. They only fill in a form: you confirm.
function fromExtension() {
  const [route, query] = location.hash.slice(1).split('?');
  const p = new URLSearchParams(query || '');
  if (!['add', 'check'].includes(route) || !/^https?:\/\//.test(p.get('url') || '')) return false;
  setMode('advanced');
  show(route === 'add' ? 'leads' : 'find');
  if (route === 'add') addLead({ url: p.get('url'), title: (p.get('title') || '').slice(0, 200), text: (p.get('text') || '').slice(0, 6000) });
  else { const site = $('#site'); site.value = p.get('url'); site.focus(); site.scrollIntoView({ block: 'center' }); }
  return true;
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
  moreMenu();
  if (state.meta.demo) document.body.prepend(el('div', { class: 'demobar', role: 'status' }, t('demo.banner')));
  on('goto', show);
  on('open-settings', () => { setMode('advanced'); show('settings'); });
  on('job', j => { lastJob = j; paintJobPill(); });
  $('#pill').addEventListener('click', () => show('find'));
  await Promise.all([initSettings(), loadAccounts(), loadPlan()]);
  initAccounts();
  initPlan();
  on('plan-changed', () => emit('profile-changed'));
  initFind();
  initLeads();
  initToday();
  const first = state.meta.first_run;
  if (first) { show('today'); showWizard(); }
  else if (!fromExtension()) show(location.hash.slice(1) || (mode === 'simple' ? 'today' : 'leads'));
  window.addEventListener('hashchange', fromExtension);
  // quiet update notice in the header (checked at most twice a day by the server)
  checkUpdate(null, false).then(u => {
    if (u && u.newer) $('#upd-pill').replaceChildren(el('button', { class: 'pill', onclick: () => { setMode('advanced'); show('settings'); $('#upd')?.scrollIntoView(); } }, t('banner.update', { v: u.latest })));
  });
}

boot();
void emit;
