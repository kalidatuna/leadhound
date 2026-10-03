// Today: three steps. Find clients, write a message, send it. Plus a calm home with your goal, best match and week.
import { $, $$, api, el, emit, on, state, store, toast } from './util.js';
import { t, LANG } from './i18n.js';
import { icon } from './icons.js';
import { runQueue, defaultSources } from './find.js';
import { srcName, ageText, reasonLine, isNew } from './leads.js';
import { renderCompose } from './compose.js';
import { SEND, LINK, TOTAL, acct, platIcon, platName, readyCount, sendCount } from './accounts.js';
import { isPro, loadPlan, openPlan, plan } from './plan.js';

const root = $('#view-today');
let leads = [], stats = {}, job = null, step = 0, pick = null, found = null, busy = false, wasRunning = false;
const running = () => job && job.status === 'running';
const goal = () => state.cfg.daily_goal || 5;
const rate = n => [1, 2, 3, 4, 5].map(i => el('i', { class: i <= n ? 'on' : '' }));
const dayName = d => new Intl.DateTimeFormat(LANG, { weekday: 'short' }).format(d);

export function initToday() {
  let seen = 0;
  on('job', j => {
    job = j;
    if (j.status === 'running' && !wasRunning) found = null;  // a new search starts: forget the last result line
    wasRunning = j.status === 'running';
    paintHero();
    // a source just finished ("freelancer: 138 leads (138 new)"): show the new matches right away
    const fresh = j.log.slice(seen).some(line => /: \d+ (leads|businesses)/.test(line));
    seen = j.log.length;
    if (fresh) refresh();
  });
  on('job-done', j => {
    const added = Object.values(j.result?.new || {}).reduce((a, b) => a + b, 0);
    if (j.status === 'done' && j.kind !== 'update') found = { added };
    loadPlan().then(paintHero);  // the free search counter moved
    refresh();
  });
  on('profile-changed', refresh);
  on('plan-changed', refresh);
  on('accounts-changed', paintConnect);
  window.addEventListener('resize', () => slide());
  draw();
  refresh();
}

function greeting() {
  const h = new Date().getHours(), part = h < 12 ? 'morning' : h < 18 ? 'afternoon' : 'evening', name = (state.cfg.name || '').trim();
  const h1 = el('h1', {});
  if (name) {  // the name is set in italics; the sentence comes from the translation with a {name} marker
    const [a, b = ''] = t('today.hi.' + part, { name: '\u0000' }).split('\u0000');
    h1.append(a, el('em', {}, name), b);
  } else h1.textContent = t('today.hi.' + part + '0');
  return h1;
}

function draw() {
  root.replaceChildren(el('div', { class: 'today' },
    el('div', { id: 'hello' }, greeting()), el('p', { class: 'lead-sub' }, t('today.sub')),
    el('div', { class: 'stepbar', id: 'stepbar' }, el('div', { class: 'slider', id: 'slider' }),
      [0, 1, 2].map(i => el('button', { class: 'step', onclick: () => stepClick(i) }, el('span', { class: 'badge' }, i + 1),
        el('span', {}, el('b', {}, [t('today.step1'), t('today.step2'), t('today.step3')][i]), el('small', { id: 's' + i }))))),
    el('div', { class: 'stage' },
      el('section', { class: 'panel', id: 'p0' }, hero(), tiles(), el('div', { id: 'cityask' }), connectBar()),
      el('section', { class: 'panel', id: 'p1' }, el('div', { class: 'grid', id: 'grid' })),
      el('section', { class: 'panel', id: 'p2' }))));
  show(0, false);
  [...$$('.step'), $('.hero'), ...$$('.tile'), $('.connectbar')].forEach((n, i) => { n.classList.add('rise'); n.style.setProperty('--i', i); });
}

// ---------- steps ----------
function stepClick(i) {
  if (i === 2 && !pick) { toast(t('today.pick_first'), ''); return show(1); }
  show(i);
}

function show(i, animate = true) {
  step = i;
  $$('.panel').forEach((p, k) => { p.classList.toggle('show', k === i); if (k === i && animate) { p.style.animation = 'none'; void p.offsetWidth; p.style.animation = ''; } });
  if (i === 1) paintGrid();
  if (i === 2 && pick) renderCompose($('#p2'), pick, { onBack: () => show(1), onSent });
  paintSteps();
  slide();
}

function paintSteps() {
  const goalN = goal(), sent = stats.sent_today || 0;
  $('#s0').textContent = t('today.s1_sub', { n: leads.length });
  $('#s1').textContent = pick ? t('today.s2_sub1', { name: pick.title.slice(0, 18) + (pick.title.length > 18 ? '…' : '') }) : t('today.s2_sub0');
  $('#s2').replaceChildren(t('today.s3_sub', { n: sent, goal: goalN }), el('span', { class: 'dots' }, Array.from({ length: Math.min(goalN, 12) }, (_, k) => el('i', { class: k < sent ? 'on' : '' }))));
  $$('.step').forEach((b, k) => {
    b.classList.toggle('on', k === step);
    b.classList.toggle('done', (k === 0 && leads.length > 0 && step > 0) || (k === 1 && step > 1) || (k === 2 && sent >= goalN));
  });
}

function slide() {
  const b = $$('.step')[step], s = $('#slider');
  if (!b || !s) return;
  s.style.width = b.offsetWidth + 'px'; s.style.height = b.offsetHeight + 'px'; s.style.transform = `translateX(${b.offsetLeft}px)`;
}

async function refresh() {
  try { [leads, stats] = await Promise.all([api('/api/leads?status=new&sort=score&limit=60'), api('/api/stats')]); } catch (e) { return toast(e.message, 'err'); }
  paintSteps(); paintHero(); paintGoal(); paintBest(); paintWeek(); paintSources(); paintConnect(); paintCity();
  if (step === 1) paintGrid();
}

// ---------- home ----------
function hero() {
  return el('div', { class: 'hero' }, el('div', {},
    el('div', { class: 'eyebrow' }, new Intl.DateTimeFormat(LANG, { weekday: 'long', day: 'numeric', month: 'long' }).format(new Date())),
    el('h2', { id: 'h0' }), el('p', { id: 'h0p' }), el('div', { class: 'acts', id: 'acts' }), el('div', { class: 'progress', id: 'prog', dir: 'ltr' })),
    el('div', { class: 'radar', id: 'radar' }, el('i'), el('i'), el('i'), el('span', {}, icon('search'))));
}

function findNow() {
  if (!isPro() && plan().searches_left === 0) return openPlan();  // today's free searches are used
  const jobs = [{ kind: 'scan', params: { sources: defaultSources() } }];
  const place = store.get('lh-place');
  if (isPro() && place && state.cfg.categories.length) jobs.push({ kind: 'local', params: { place, categories: state.cfg.categories, website: 'no', audit: false, limit: 40 } });
  runQueue(jobs, true);
}

function paintHero() {
  const acts = $('#acts');
  if (!acts) return;
  const busy_ = running(), n = leads.length;
  $('#radar').classList.toggle('run', !!busy_);
  const empty = !stats.total && !busy_;
  $('#h0').textContent = found ? (found.added ? t('today.found', { new: found.added, total: n }) : t('today.found0')) : empty ? t('today.empty_title') : t('today.hero_title');
  $('#h0p').textContent = found ? (found.added && leads[0] ? t('today.found_text', { score: leads[0].score }) : t('today.found_text0')) : empty ? t('today.empty_text') : t('today.hero_text');
  const left = plan().searches_left;
  $('#prog').textContent = busy_ ? (job.log[job.log.length - 1] || '') : !isPro() && left != null ? t('plan.searches_left', { n: left }) : '';
  acts.replaceChildren(...[el('button', { class: 'cta', disabled: busy_, onclick: findNow }, busy_ ? el('span', { class: 'spin' }) : icon('search'), busy_ ? t('today.finding') : t('today.find_btn')),
    busy_ && el('button', { class: 'cta ghost', onclick: () => api(`/api/jobs/${job.id}/cancel`, {}) }, t('stop')),
    !busy_ && n > 0 && found && el('button', { class: 'cta ghost', onclick: () => show(1) }, t('today.see'), icon('arrow'))].filter(Boolean));
}

function tiles() {
  return el('div', { class: 'tiles' },
    el('div', { class: 'tile t-goal' }, el('h4', {}, t('today.goal')),
      el('div', { class: 'ring' }, ringSvg(),
        el('b', {}, el('div', {}, el('span', { id: 'ringn', class: 'num' }), el('span', { class: 'of', id: 'ringof' })))),
      el('p', { id: 'goalp' })),
    el('div', { class: 'tile t-best', id: 'best' }),
    el('div', { class: 'tile t-week' }, el('h4', {}, t('today.week')), el('div', { class: 'wk' }, el('b', { class: 'num', id: 'weekn' }), el('span', {}, t('today.week_sent'))), el('div', { class: 'bars', id: 'bars' })),
    el('div', { class: 'tile t-src' }, el('h4', {}, t('today.sources')), el('div', { class: 'srcs', id: 'srcs' }), el('p', {}, t('today.sources_text'))));
}

const C = 2 * Math.PI * 44;
function ringSvg() {
  const NS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 100 100');
  for (const cls of ['tr', 'pg']) {
    const c = document.createElementNS(NS, 'circle');
    for (const [k, v] of Object.entries({ class: cls, cx: 50, cy: 50, r: 44 })) c.setAttribute(k, v);
    svg.append(c);
  }
  return svg;
}
function paintGoal() {
  const g = goal(), sent = stats.sent_today || 0, pg = $('.ring .pg');
  pg.style.strokeDasharray = C; pg.style.strokeDashoffset = C * (1 - Math.min(1, sent / g)); pg.style.opacity = sent ? 1 : 0;
  $('#ringn').textContent = sent; $('#ringof').textContent = ' / ' + g; $('#goalp').textContent = t('today.goal_text', { n: g });
}

function paintBest() {
  const l = leads[0], box = $('#best');
  box.replaceChildren(el('h4', {}, t('today.best')), ...(l ? [
    el('div', { class: 'bm' }, el('div', { class: 'bm-main' },
      el('div', { class: 'top2' }, el('span', { class: 'src' }, srcName(l.source)), isNew(l) && el('span', { class: 'src fresh' }, t('badge.new'))),
      el('h3', {}, l.title), !!l.budget && el('div', { class: 'budget num' }, l.budget), el('p', { class: 'why' }, reasonLine(l))),
      el('div', { class: 'bm-score' }, el('b', { class: 'num' }, l.score), el('span', {}, t('today.match')))),
    el('div', { class: 'acts' }, el('button', { class: 'btn primary', onclick: () => write(l) }, icon('pen'), t('today.write')),
      el('button', { class: 'btn ghost', onclick: () => show(1) }, t('today.see_all', { n: leads.length }), icon('arrow')))] : [el('p', { class: 'why mut' }, t('today.best_none'))]));
}

function paintWeek() {
  const wk = stats.sent_week || [0, 0, 0, 0, 0, 0, 0], max = Math.max(5, ...wk), today = new Date();
  $('#weekn').textContent = wk.reduce((a, b) => a + b, 0);
  $('#bars').replaceChildren(...wk.map((v, i) => {
    const d = new Date(today); d.setDate(d.getDate() - (6 - i));
    const bar = el('i', {}); bar.style.setProperty('--h', Math.max(6, v / max * 100) + '%');
    return el('div', { class: i === 6 ? 'now' : '', title: String(v) }, bar, el('span', {}, i === 6 ? t('today.today') : dayName(d)));
  }));
}

function paintSources() {
  const c = state.cfg, place = store.get('lh-place');
  const all = [['Freelancer.com', c.freelancer], ['Reddit', c.reddit_subreddits.length > 0], ['Hacker News', c.hn], ['GitHub', c.github], ['Mastodon', c.mastodon], [t('src.osm'), !!place]];
  $('#srcs').replaceChildren(...all.map(([n, on_]) => el('button', { class: 'srcchip' + (on_ ? '' : ' off'), onclick: () => emit('open-settings') }, el('i'), n)),
    el('button', { class: 'srcchip add', onclick: () => emit('open-settings') }, t('today.add_feed')));
}

function connectBar() {
  return el('div', { class: 'connectbar', id: 'cbar' }, el('div', { class: 'cb-t' }, el('b', {}, t('today.cb_title')), el('span', { id: 'cbs' })), el('div', { class: 'cb-i', id: 'cbi' }), el('button', { class: 'btn primary', id: 'cbgo', onclick: () => emit('goto', 'accounts') }));
}

function paintConnect() {
  const n = sendCount();
  if (!$('#cbs')) return;
  $('#cbs').textContent = n ? t('today.cb_some', { ready: readyCount(), total: TOTAL, n }) : t('today.cb_none');
  $('#cbi').replaceChildren(...[...SEND, ...LINK].map(id => el('span', { class: 'mark' + (acct(id).ready ? ' on' : ''), title: platName(id) }, platIcon(id))));
  $('#cbgo').textContent = n ? t('today.cb_manage') : t('today.cb_btn');
}

function paintCity() {
  const box = $('#cityask');
  if (!box) return;
  if (store.get('lh-place') || !stats.total) return box.replaceChildren();
  box.replaceChildren(el('div', { class: 'card', style: 'margin-top:16px' }, el('b', {}, t('today.city_q')),
    el('div', { class: 'row', style: 'margin-top:10px' }, el('input', { id: 'tcity', placeholder: t('find.city_ph'), style: 'flex:1;min-width:200px' }),
      el('button', { class: 'btn', onclick: () => { const v = $('#tcity').value.trim(); if (v) { store.set('lh-place', v); findNow(); paintCity(); paintSources(); } } }, t('today.city_btn')))));
}

// ---------- matches ----------
function paintGrid() {
  const grid = $('#grid');
  if (!stats.total || !leads.length) {
    grid.replaceChildren(el('div', { class: 'empty', style: 'grid-column:1/-1' }, el('h2', {}, stats.total ? t('today.done_title') : t('today.empty_title')), el('p', {}, stats.total ? t('today.done_text') : t('today.empty_text')),
      el('button', { class: 'cta', onclick: () => { show(0); findNow(); } }, icon('search'), t('today.find_btn'))));
    return;
  }
  grid.replaceChildren(...[...leads.slice(0, 40).map((l, i) => post(l, i)),
    !isPro() && (stats.by_status || {}).new > leads.length && el('div', { class: 'more rise', style: '--i:2' }, el('b', {}, t('plan.badge')), el('p', {}, t('plan.upgrade_matches', { n: leads.length, total: stats.by_status.new })), el('button', { class: 'btn primary', onclick: openPlan }, t('plan.upgrade_btn'))),
    leads.length % 2 === 1 && el('div', { class: 'more rise', style: '--i:3' }, el('b', {}, t('today.more_title')), el('p', {}, t('today.more_text')), el('button', { class: 'btn', onclick: () => { show(0); findNow(); } }, icon('search'), t('today.search_again')))].filter(Boolean));
}

function post(l, i) {
  const card = el('article', { class: 'post rise', style: `--i:${i % 6}` },
    el('div', { class: 'top2' }, el('span', { class: 'src' }, srcName(l.source)), isNew(l) && el('span', { class: 'src fresh' }, t('badge.new')),
      el('span', { class: 'rate', title: String(l.score) }, rate(Math.max(1, Math.min(5, Math.round(l.score / 20)))))),
    el('h3', {}, l.title), !!(l.budget || l.created_at) && el('div', { class: 'budget num' }, [l.budget, ageText(l.created_at)].filter(Boolean).join(' · ')), el('div', { class: 'why' }, reasonLine(l)),
    el('div', { class: 'acts' }, el('button', { class: 'btn primary', onclick: () => write(l) }, icon('pen'), t('today.write')),
      el('button', { class: 'btn ghost', onclick: () => skip(l, card) }, t('today.skip'))));
  return card;
}

function write(l) { pick = l; show(2); }

async function skip(l, card) {
  card.classList.add('leaving');
  try {
    await api('/api/leads/' + l.id, { status: 'ignored' });
    toast(t('leads.moved', { stage: t('stage.ignored') }), '', { label: t('undo'), fn: () => api('/api/leads/' + l.id, { status: 'new' }).then(refresh) });
    setTimeout(refresh, 250);
  } catch (e) { card.classList.remove('leaving'); toast(e.message, 'err'); }
}

// ---------- after sending ----------
function celebrate() {
  const dots = Array.from({ length: 14 }, (_, i) => { const a = i / 14 * Math.PI * 2, r = i % 2 ? 150 : 118, d = el('i', { class: 'p' }); d.style.setProperty('--x', Math.cos(a) * r + 'px'); d.style.setProperty('--y', Math.sin(a) * r + 'px'); return d; });
  const c = el('div', { class: 'cele' }, el('div', { class: 'core' }, icon('check')), dots);
  document.body.append(c);
  setTimeout(() => c.remove(), 1200);
  return new Promise(r => setTimeout(r, 900));
}

async function onSent(info) {
  if (busy) return;
  busy = true;
  await celebrate();
  pick = null;
  await refresh();
  show(1);
  busy = false;
  const g = (stats.sent_today || 0) >= goal();
  toast(g ? t('today.goal_done') : info && info.via ? t('compose.sent_toast', { name: info.via, as: info.as }) : t('today.nice'));
}
