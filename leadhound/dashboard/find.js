// Find view: start searches, watch live progress, see a plain-language summary.
import { $, api, el, emit, on, toast, pretty, SOURCE_NAMES } from './util.js';

let job = null, timer = null, queue = [];
const root = $('#view-find');
const LS = { get: k => { try { return localStorage.getItem(k) || ''; } catch { return ''; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } } };

const SOURCE_INFO = [
  ['reddit', 'Reddit', 'Hiring posts in r/forhire, r/jobbit and the subreddits from Settings'],
  ['hn', 'Hacker News', '"Seeking freelancer" and contract posts from the monthly threads'],
  ['github', 'GitHub', 'Open issues with bounty and help-wanted labels'],
  ['rss', 'Job boards', 'RSS feeds you added in Settings'],
];
const QUICK_CATS = ['restaurant', 'cafe', 'dentist', 'hairdresser', 'beauty', 'plumber', 'lawyer', 'hotel', 'gym', 'car_repair'];
const picked = new Set(['restaurant', 'dentist']);

export function initFind() {
  const srcBoxes = SOURCE_INFO.map(([id, name, desc]) => el('label', { class: 'check' },
    el('input', { type: 'checkbox', checked: true, 'data-src': id }), el('span', {}, name, el('small', {}, desc))));
  const catChips = el('div', { class: 'chips', id: 'cats' });
  const drawCats = () => catChips.replaceChildren(...[...new Set([...QUICK_CATS, ...picked])].map(c =>
    el('button', { class: 'chip' + (picked.has(c) ? ' on' : ''), type: 'button', onclick: () => { picked.has(c) ? picked.delete(c) : picked.add(c); drawCats(); } }, pretty(c))));
  drawCats();

  root.append(el('div', { class: 'page' }, el('div', { class: 'wrap' },
    el('div', { class: 'card', id: 'progress', hidden: true }),
    el('div', { class: 'card' }, el('h2', {}, 'People hiring right now'),
      el('p', {}, 'Finds posts where someone asks for a freelancer, ranked by how well they match your skills.'),
      srcBoxes, el('div', { class: 'row', style: 'margin-top:10px' }, el('button', { class: 'btn primary', id: 'run-scan', onclick: runScan }, 'Search now'),
        el('span', { class: 'mut' }, 'Takes about a minute. Reddit is slow on purpose to stay polite.'))),
    el('div', { class: 'card' }, el('h2', {}, 'Local businesses that need help'),
      el('p', {}, 'Finds nearby businesses and checks their websites for problems you can fix.'),
      el('label', { class: 'f' }, el('small', {}, 'City or address'), el('input', { id: 'place', placeholder: 'e.g. Tbilisi, Georgia', value: LS.get('lh-place') })),
      el('label', { class: 'f' }, el('small', {}, 'What kind of business? (click to choose)')), catChips,
      el('div', { class: 'row' }, el('input', { id: 'custom-cat', placeholder: 'Other: type a category, or an OpenStreetMap tag like shop=bicycle', style: 'flex:1;min-width:240px' }),
        el('button', { class: 'btn sm', onclick: () => { const v = $('#custom-cat').value.trim(); if (v) { picked.add(v); $('#custom-cat').value = ''; drawCats(); } } }, 'Add')),
      el('div', { class: 'two' },
        el('label', { class: 'f' }, el('small', {}, 'How far from the center'), sel('radius', [[1000, '1 km'], [3000, '3 km'], [5000, '5 km'], [10000, '10 km']], 3000)),
        el('label', { class: 'f' }, el('small', {}, 'Show'), sel('website', [['any', 'All businesses'], ['no', 'Only without a website'], ['yes', 'Only with a website']], 'any'))),
      el('label', { class: 'check' }, el('input', { type: 'checkbox', id: 'do-audit', checked: true }), el('span', {}, 'Check their websites for problems', el('small', {}, 'Slower, but this is what gives you something concrete to say.'))),
      el('div', { class: 'row', style: 'margin-top:8px' }, el('button', { class: 'btn primary', id: 'run-local', onclick: runLocal }, 'Find businesses'),
        el('span', { class: 'mut' }, 'Tip: "Only without a website" is the quickest way to find clients who need a site.'))),
    el('div', { class: 'card' }, el('h2', {}, 'Check one website'),
      el('p', {}, 'Paste any business website to see what is wrong with it and get a ready-made pitch.'),
      el('div', { class: 'row' }, el('input', { id: 'site', placeholder: 'example.com', style: 'flex:1;min-width:240px', onkeydown: e => e.key === 'Enter' && runAudit() }),
        el('button', { class: 'btn primary', id: 'run-audit', onclick: runAudit }, 'Check')),
      el('label', { class: 'check' }, el('input', { type: 'checkbox', id: 'booking' }), el('span', {}, 'This business takes bookings (restaurant, clinic, salon…)'))))));
  on('job', renderProgress);
  resume();
}

function sel(id, opts, def) {
  return el('select', { id }, opts.map(([v, l]) => el('option', { value: v, selected: v === def }, l)));
}

async function resume() {
  try { const j = await api('/api/jobs/current'); if (j) { setJob(j); if (j.status === 'running') poll(); } else renderProgress(null); } catch { renderProgress(null); }
}

function setJob(j) { job = j; emit('job', j); }

export async function startJob(kind, params) {
  try {
    setJob(await api('/api/jobs', { kind, params }));
    emit('goto', 'find');
    poll();
  } catch (e) { toast(e.message, 'err'); queue = []; }
}

export function runQueue(items) { queue = items.slice(1); startJob(items[0].kind, items[0].params); }

function poll() {
  clearInterval(timer);
  timer = setInterval(async () => {
    try {
      const j = await api('/api/jobs/' + job.id);
      setJob(j);
      if (j.status !== 'running') {
        clearInterval(timer);
        emit('job-done', j);
        const n = Object.values(j.result.new || {}).reduce((a, b) => a + b, 0);
        toast(j.status === 'cancelled' ? 'Search stopped' : j.status === 'error' ? 'Search failed' : `Done: ${n} new lead${n === 1 ? '' : 's'}`, j.status === 'error' ? 'err' : '');
        if (queue.length && j.status !== 'cancelled') { const nx = queue.shift(); startJob(nx.kind, nx.params); } else queue = [];
      }
    } catch { clearInterval(timer); }
  }, 800);
}

const friendly = msg => /429/.test(msg) ? 'The site asked us to slow down. Try again in a few minutes.'
  : /403/.test(msg) ? 'The site refused the request.' : /not found/.test(msg) ? 'That place was not found. Try a bigger city name.' : msg;

function renderProgress(j) {
  const box = $('#progress');
  if (!box) return;
  const busy = j?.status === 'running';
  ['run-scan', 'run-local', 'run-audit'].forEach(id => { const b = $('#' + id); if (b) b.disabled = busy; });
  box.hidden = !j;
  if (!j) return;
  const title = { scan: 'People hiring right now', local: 'Local businesses', audit: 'Website check' }[j.kind];
  const parts = [el('h2', {}, busy ? el('span', {}, el('span', { class: 'spin' }), '  ', title, ' · working…') : `${title} · ${{ done: 'finished', error: 'failed', cancelled: 'stopped' }[j.status]}`)];
  if (busy) parts.push(el('button', { class: 'btn sm', onclick: () => api(`/api/jobs/${j.id}/cancel`, {}) }, 'Stop'));
  else {
    const sum = el('div', { class: 'sum' });
    for (const [src, n] of Object.entries(j.result.found || {})) sum.append(el('div', {}, `${SOURCE_NAMES[src] || src}: ${n} found, ${(j.result.new || {})[src] || 0} new`));
    for (const [src, msg] of Object.entries(j.result.errors || {})) sum.append(el('div', { class: 'bad' }, `${SOURCE_NAMES[src] || src}: ${friendly(msg)}`));
    parts.push(sum);
    const acts = el('div', { class: 'row' });
    if (j.result.lead_id) acts.append(el('button', { class: 'btn primary', onclick: () => { emit('goto', 'leads'); emit('lead-open', j.result.lead_id); } }, 'See the result'));
    else acts.append(el('button', { class: 'btn primary', onclick: () => emit('goto', 'leads') }, 'See leads'));
    parts.push(acts);
  }
  const log = el('div', { class: 'log' }, j.log.join('\n') || 'starting…');
  parts.push(log);
  box.replaceChildren(...parts);
  log.scrollTop = log.scrollHeight;
  if (busy && !box.dataset.seen) { box.dataset.seen = 1; box.scrollIntoView({ block: 'start' }); }
  if (!busy) delete box.dataset.seen;
}

export const rememberPlace = p => LS.set('lh-place', p);

const checked = id => $('#' + id).checked;

function runScan() {
  const sources = [...document.querySelectorAll('[data-src]')].filter(c => c.checked).map(c => c.dataset.src);
  if (!sources.length) return toast('Pick at least one source', 'err');
  startJob('scan', { sources });
}

export function localParams() {
  return { place: $('#place').value, categories: [...picked], radius: +$('#radius').value, website: $('#website').value, audit: checked('do-audit') };
}

function runLocal() {
  if (!picked.size) return toast('Choose at least one kind of business', 'err');
  LS.set('lh-place', $('#place').value);
  startJob('local', localParams());
}

function runAudit() {
  const url = $('#site').value.trim();
  if (!url) return toast('Enter a website address', 'err');
  startJob('audit', { url, booking: checked('booking') });
}

export const pickedCategories = picked;
export const currentJob = () => job;
