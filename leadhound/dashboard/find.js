// Find view: start searches, watch live progress, see a plain-language summary.
import { $, api, el, emit, on, state, store, toast, BRANDS } from './util.js';
import { t, catName } from './i18n.js';
import { proTag } from './plan.js';

let job = null, timer = null, queue = [];
const root = $('#view-find');
const SOURCES = ['freelancer', 'reddit', 'hn', 'github', 'mastodon', 'rss'];
const QUICK = ['restaurant', 'cafe', 'dentist', 'hairdresser', 'beauty', 'gym', 'hotel', 'plumber', 'lawyer', 'car_repair'];
const picked = new Set();
const srcLabel = s => BRANDS[s] || t('src.' + s);

export function defaultSources() {
  const c = state.cfg;
  const on_ = { freelancer: c.freelancer, github: c.github, hn: c.hn, mastodon: c.mastodon,
    reddit: c.reddit_subreddits.length > 0, rss: c.rss_feeds.length > 0 };
  return SOURCES.filter(id => on_[id]);
}

export function initFind() {
  (state.cfg.categories || ['restaurant', 'dentist']).forEach(c => picked.add(c));
  const enabled = { freelancer: state.cfg.freelancer, github: state.cfg.github, hn: state.cfg.hn, mastodon: state.cfg.mastodon,
    reddit: state.cfg.reddit_subreddits.length > 0, rss: state.cfg.rss_feeds.length > 0 };
  const srcBoxes = SOURCES.map(id => el('label', { class: 'check' },
    el('input', { type: 'checkbox', checked: !!enabled[id], 'data-src': id }), el('span', {}, srcLabel(id), el('small', {}, t('src_desc.' + id)))));
  const catChips = el('div', { class: 'chips', id: 'cats' });
  const drawCats = () => catChips.replaceChildren(...[...new Set([...QUICK, ...picked])].map(c =>
    el('button', { class: 'chip' + (picked.has(c) ? ' on' : ''), type: 'button', onclick: () => { picked.has(c) ? picked.delete(c) : picked.add(c); drawCats(); } }, catName(c))));
  drawCats();
  on('profile-changed', () => {  // wizard or Settings picked a profession: follow its targets and sources
    picked.clear();
    (state.cfg.categories || []).forEach(c => picked.add(c));
    drawCats();
    const on_ = { freelancer: state.cfg.freelancer, github: state.cfg.github, hn: state.cfg.hn, mastodon: state.cfg.mastodon,
      reddit: state.cfg.reddit_subreddits.length > 0, rss: state.cfg.rss_feeds.length > 0 };
    document.querySelectorAll('[data-src]').forEach(cb => { cb.checked = !!on_[cb.dataset.src]; });
  });
  const more = el('select', { onchange: e => { if (e.target.value) { picked.add(e.target.value); e.target.value = ''; drawCats(); } } },
    el('option', { value: '' }, t('find.more_kinds')),
    state.meta.categories.filter(c => !QUICK.includes(c)).map(c => [c, catName(c)]).sort((a, b) => a[1].localeCompare(b[1])).map(([c, n]) => el('option', { value: c }, n)));

  root.append(el('div', { class: 'page' }, el('div', { class: 'wrap' },
    el('div', { class: 'card', id: 'progress', hidden: true }),
    el('div', { class: 'card' }, el('h2', {}, t('find.hiring_title')), el('p', {}, t('find.hiring_desc')),
      srcBoxes, el('div', { class: 'row', style: 'margin-top:10px' }, el('button', { class: 'btn primary', id: 'run-scan', onclick: runScan }, t('find.search_now')),
        el('span', { class: 'mut' }, t('find.search_hint')))),
    el('div', { class: 'card' }, el('h2', {}, t('find.local_title'), ' ', proTag()), el('p', {}, t('find.local_desc')),
      el('label', { class: 'f' }, el('small', {}, t('find.city')), el('input', { id: 'place', placeholder: t('find.city_ph'), value: store.get('lh-place') })),
      el('label', { class: 'f' }, el('small', {}, t('find.kind_q'))), catChips,
      el('div', { class: 'row' }, more,
        el('input', { id: 'custom-cat', placeholder: t('find.other_ph'), style: 'flex:1;min-width:200px' }),
        el('button', { class: 'btn sm', onclick: () => { const v = $('#custom-cat').value.trim(); if (v) { picked.add(v); $('#custom-cat').value = ''; drawCats(); } } }, t('find.add'))),
      el('div', { class: 'two' },
        el('label', { class: 'f' }, el('small', {}, t('find.distance')), sel('radius', [[1000, '1 km'], [3000, '3 km'], [5000, '5 km'], [10000, '10 km'], [0, t('find.whole_city')]], 3000)),
        el('label', { class: 'f' }, el('small', {}, t('find.show')), sel('website', [['any', t('find.show_all')], ['no', t('find.show_no')], ['yes', t('find.show_yes')]], 'any'))),
      el('label', { class: 'check' }, el('input', { type: 'checkbox', id: 'do-audit', checked: true }), el('span', {}, t('find.check_sites'), el('small', {}, t('find.check_sites_hint')))),
      el('div', { class: 'row', style: 'margin-top:8px' }, el('button', { class: 'btn primary', id: 'run-local', onclick: runLocal }, t('find.local_btn')),
        el('span', { class: 'mut' }, t('find.local_tip')))),
    el('div', { class: 'card' }, el('h2', {}, t('find.check_title'), ' ', proTag()), el('p', {}, t('find.check_desc')),
      el('div', { class: 'row' }, el('input', { id: 'site', placeholder: 'example.com', style: 'flex:1;min-width:220px', onkeydown: e => e.key === 'Enter' && runAudit() }),
        el('button', { class: 'btn primary', id: 'run-audit', onclick: runAudit }, t('find.check_btn'))),
      el('label', { class: 'check' }, el('input', { type: 'checkbox', id: 'booking' }), el('span', {}, t('find.booking')))))));
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

let queueStay = false;  // searches started from Today stay on Today instead of jumping to the Find screen
export async function startJob(kind, params, stay = false) {
  try {
    setJob(await api('/api/jobs', { kind, params }));
    if (kind !== 'update' && !stay) emit('goto', 'find');
    poll();
    return true;
  } catch (e) { toast(e.message, 'err'); queue = []; return false; }
}

export function runQueue(items, stay = false) { queueStay = stay; queue = items.slice(1); startJob(items[0].kind, items[0].params, stay); }

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
        if (j.kind !== 'update') toast(j.status === 'cancelled' ? t('toast.stopped') : j.status === 'error' ? t('toast.failed') : t('toast.done', { n }), j.status === 'error' ? 'err' : '');
        if (queue.length && j.status !== 'cancelled') { const nx = queue.shift(); startJob(nx.kind, nx.params, queueStay); } else queue = [];
      }
    } catch { clearInterval(timer); }
  }, 800);
}

const friendly = msg => /429/.test(msg) ? t('err.429') : /403/.test(msg) ? t('err.403') : /not found/.test(msg) ? t('err.notfound') : msg;

function renderProgress(j) {
  const box = $('#progress');
  if (!box || (j && j.kind === 'update')) return;
  const busy = j?.status === 'running';
  ['run-scan', 'run-local', 'run-audit'].forEach(id => { const b = $('#' + id); if (b) b.disabled = busy; });
  box.hidden = !j;
  if (!j) return;
  const title = t('prog.title.' + j.kind);
  const parts = [el('h2', {}, busy ? el('span', {}, el('span', { class: 'spin' }), '  ', title, ' · ', t('prog.working')) : `${title} · ${t('prog.' + j.status)}`)];
  if (busy) parts.push(el('button', { class: 'btn sm', onclick: () => api(`/api/jobs/${j.id}/cancel`, {}) }, t('stop')));
  else {
    const sum = el('div', { class: 'sum' });
    for (const [src, n] of Object.entries(j.result.found || {})) sum.append(el('div', {}, t('prog.found', { src: srcLabel(src), n, new: (j.result.new || {})[src] || 0 })));
    for (const [src, msg] of Object.entries(j.result.errors || {})) sum.append(el('div', { class: 'bad' }, `${srcLabel(src)}: ${friendly(msg)}`));
    parts.push(sum, el('div', { class: 'row' }, j.result.lead_id
      ? el('button', { class: 'btn primary', onclick: () => { emit('goto', 'leads'); emit('lead-open', j.result.lead_id); } }, t('prog.see_result'))
      : el('button', { class: 'btn primary', onclick: () => emit('goto', 'leads') }, t('prog.see_leads'))));
  }
  const log = el('div', { class: 'log', dir: 'ltr' }, j.log.join('\n') || t('prog.starting'));
  parts.push(log);
  box.replaceChildren(...parts);
  log.scrollTop = log.scrollHeight;
  if (busy && !box.dataset.seen) { box.dataset.seen = 1; box.scrollIntoView({ block: 'start' }); }
  if (!busy) delete box.dataset.seen;
}

function runScan() {
  const sources = [...document.querySelectorAll('[data-src]')].filter(c => c.checked).map(c => c.dataset.src);
  if (!sources.length) return toast(t('find.pick_source'), 'err');
  startJob('scan', { sources });
}

function runLocal() {
  if (!picked.size) return toast(t('find.pick_kind'), 'err');
  store.set('lh-place', $('#place').value);
  startJob('local', { place: $('#place').value, categories: [...picked], radius: +$('#radius').value, website: $('#website').value, audit: $('#do-audit').checked });
}

function runAudit() {
  const url = $('#site').value.trim();
  if (!url) return toast(t('find.enter_site'), 'err');
  startJob('audit', { url, booking: $('#booking').checked });
}

export const rememberPlace = p => { store.set('lh-place', p); const i = $('#place'); if (i) i.value = p; };
export const currentJob = () => job;
