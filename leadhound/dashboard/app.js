// Entry: tabs, background-job pill, first-run wizard.
import { $, $$, api, el, on, state } from './util.js';
import { initLeads } from './leads.js';
import { initFind } from './find.js';
import { initSettings, showWizard } from './settings.js';

const VIEWS = ['leads', 'find', 'settings'];

function show(view) {
  if (!VIEWS.includes(view)) view = 'leads';
  VIEWS.forEach(v => { $('#view-' + v).hidden = v !== view; });
  $$('.tab').forEach(t => t.classList.toggle('on', t.dataset.view === view));
  try { history.replaceState(null, '', '#' + view); } catch { /* file or sandbox */ }
}

async function boot() {
  try {
    state.meta = await api('/api/meta');
  } catch (e) {
    document.body.replaceChildren(el('div', { class: 'empty' }, el('h2', {}, 'Cannot reach leadhound'), el('p', {}, e.message + ' Restart it from the terminal and reload this page.')));
    return;
  }
  $$('.tab').forEach(t => t.addEventListener('click', () => show(t.dataset.view)));
  on('goto', show);
  on('job', j => {
    const pill = $('#pill');
    pill.hidden = !j || j.status !== 'running';
    if (!pill.hidden) pill.replaceChildren(el('span', { class: 'spin' }), 'Searching… see progress');
  });
  $('#pill').addEventListener('click', () => show('find'));
  await initSettings();
  initFind();
  initLeads();
  const first = state.meta.first_run;
  show(first ? 'leads' : location.hash.slice(1) || 'leads');
  if (first) showWizard();
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('#modal').hidden && !first) $('#modal').hidden = true; });
}

boot();
