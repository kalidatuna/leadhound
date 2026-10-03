// Today: the simple screen. Find clients, write a message, send it. Nothing else.
import { $, api, el, emit, on, state, store, toast, copyText, scoreClass, safeUrl, openModal, closeModal } from './util.js';
import { t, whyText } from './i18n.js';
import { startJob, runQueue, defaultSources, rememberPlace } from './find.js';
import { srcName, ageText } from './leads.js';

const root = $('#view-today');
let shown = 5, leads = [], stats = {}, job = null;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function initToday() {
  let seen = 0;
  on('job', j => {
    job = j;
    paintTop();
    // a source just finished ("freelancer: 138 leads (138 new)"): show the new matches right away
    const fresh = j.log.slice(seen).some(line => /: \d+ (leads|businesses)/.test(line));
    seen = j.log.length;
    if (fresh) refresh();
  });
  on('job-done', refresh);
  on('profile-changed', refresh);
  root.append(el('div', { class: 'page' }, el('div', { class: 'wrap today' },
    el('ol', { class: 'steps3' }, [['1', t('today.step1')], ['2', t('today.step2')], ['3', t('today.step3')]].map(([n, label]) => el('li', {}, el('b', {}, n), label))),
    el('div', { id: 'top' }), el('div', { id: 'cards' }), el('div', { id: 'foot' }))));
  refresh();
}

async function refresh() {
  try {
    [leads, stats] = await Promise.all([api('/api/leads?status=new&sort=score&limit=60'), api('/api/stats')]);
  } catch (e) { return toast(e.message, 'err'); }
  paintTop();
  paintCards();
}

const running = () => job && job.status === 'running';

function findNow() {
  const jobs = [{ kind: 'scan', params: { sources: defaultSources() } }];
  const place = store.get('lh-place');
  if (place && state.cfg.categories.length) {
    jobs.push({ kind: 'local', params: { place, categories: state.cfg.categories, website: 'no', audit: false, limit: 40 } });
  }
  runQueue(jobs);
}

function paintTop() {
  const box = $('#top');
  if (!box) return;
  const by = stats.by_status || {};
  const busy = running();
  const last = busy ? (job.log[job.log.length - 1] || '') : '';
  box.replaceChildren(...[
    el('div', { class: 'findbar' },
      el('button', { class: 'btn primary big-btn', disabled: busy, onclick: findNow }, busy ? t('today.finding') : t('today.find_btn')),
      busy && el('button', { class: 'btn', onclick: () => api(`/api/jobs/${job.id}/cancel`, {}) }, t('stop')),
      !busy && stats.total > 0 && el('span', { class: 'mut' }, t('today.counts', { new: by.new || 0, sent: by.contacted || 0 }))),
    busy && last && el('div', { class: 'mut sm', dir: 'ltr' }, last),
    job && job.status === 'error' && el('div', { class: 'bad' }, t('toast.failed'))].filter(Boolean));
}

function reasonLine(l) {
  const good = (l.extra.why || []).filter(w => w[0] > 0 && !['age_unknown'].includes(w[1])).sort((a, b) => b[0] - a[0]).slice(0, 2);
  return good.length ? good.map(w => whyText([null, w[1], w[2]])).join(' · ') : t('today.reason_none');
}

function paintCards() {
  const box = $('#cards'), foot = $('#foot');
  if (!stats.total) {
    box.replaceChildren(el('div', { class: 'empty' }, el('h2', {}, t('today.empty_title')), el('p', {}, t('today.empty_text'))));
    foot.replaceChildren();
    return;
  }
  if (!leads.length) {
    box.replaceChildren(el('div', { class: 'empty' }, el('h2', {}, t('today.done_title')), el('p', {}, t('today.done_text'))));
  } else {
    box.replaceChildren(el('h2', { class: 'hello' }, t('today.hello')), ...leads.slice(0, shown).map(card));
  }
  foot.replaceChildren(...[
    leads.length > shown && el('button', { class: 'btn', onclick: () => { shown += 5; paintCards(); } }, t('today.more')),
    !store.get('lh-place') && el('div', { class: 'card cityask' }, el('b', {}, t('today.city_q')),
      el('div', { class: 'row' }, el('input', { id: 'tcity', placeholder: t('find.city_ph'), style: 'flex:1;min-width:200px' }),
        el('button', { class: 'btn', onclick: () => { const v = $('#tcity').value.trim(); if (v) { rememberPlace(v); findNow(); } } }, t('today.city_btn'))))].filter(Boolean));
}

function card(l) {
  const meta = [srcName(l.source), ageText(l.created_at), l.budget].filter(Boolean).join(' · ');
  return el('div', { class: 'card lead' },
    el('div', { class: 'sc ' + scoreClass(l.score) }, l.score),
    el('div', { class: 'lt' }, el('div', { class: 'ti' }, l.title), el('div', { class: 'me' }, meta), el('div', { class: 'why1' }, reasonLine(l)),
      el('div', { class: 'row', style: 'margin-top:10px' },
        el('button', { class: 'btn primary', onclick: () => openMessage(l) }, t('today.write')),
        el('button', { class: 'btn ghost', onclick: () => skip(l) }, t('today.skip')))));
}

async function skip(l) {
  try {
    await api('/api/leads/' + l.id, { status: 'ignored' });
    toast(t('leads.moved', { stage: t('stage.ignored') }), '', { label: t('undo'), fn: () => api('/api/leads/' + l.id, { status: 'new' }).then(refresh) });
    refresh();
  } catch (e) { toast(e.message, 'err'); }
}

async function openMessage(l) {
  if (!l.draft) {
    try { l.draft = (await api(`/api/leads/${l.id}/draft`, { llm: false })).draft; } catch (e) { return toast(e.message, 'err'); }
  }
  const contacts = (l.contact || '').split(', ').filter(Boolean);
  const email = contacts.find(c => EMAIL.test(c));
  const reddit = /^reddit DM: u\/([\w-]+)$/.exec(contacts.find(c => c.startsWith('reddit DM')) || '');
  const page = reddit ? 'https://www.reddit.com/message/compose/?to=' + reddit[1] : safeUrl(l.url);
  const ta = el('textarea', { rows: 12, value: l.draft, oninput: e => { l.draft = e.target.value; save(l); } });
  const m = /^[^\n:]{1,20}: (.*)\n\n?/.exec(l.draft);
  const mail = email && `mailto:${email}?subject=${encodeURIComponent(m ? m[1] : l.title)}&body=${encodeURIComponent(m ? l.draft.slice(m[0].length) : l.draft)}`;
  openModal([
    el('h2', {}, l.title), el('p', { class: 'mut' }, t('today.msg_hint')),
    contacts.length ? el('p', { class: 'sm' }, el('b', {}, t('today.send_to') + ': '), contacts.slice(0, 3).join(', ')) : el('p', { class: 'mut sm' }, t('today.no_contact')),
    ta,
    el('div', { class: 'row', style: 'margin-top:12px' },
      el('button', { class: 'btn primary', onclick: async () => toast(await copyText(ta.value) ? t('copied') : t('copy_blocked')) }, t('today.copy_btn')),
      mail && el('a', { class: 'btn', href: mail }, t('msg.email')),
      page && el('a', { class: 'btn', href: page, target: '_blank', rel: 'noopener noreferrer' }, t('today.open_page'))),
    el('div', { class: 'row', style: 'margin-top:18px' },
      el('button', { class: 'btn primary', onclick: async () => {
        await api('/api/leads/' + l.id, { status: 'contacted', draft: ta.value }).catch(e => toast(e.message, 'err'));
        closeModal(); toast(t('today.nice')); refresh();
      } }, t('today.sent')),
      el('button', { class: 'btn ghost', onclick: closeModal }, t('today.close'))),
  ]);
}

let timer = null;
function save(l) {
  clearTimeout(timer);
  timer = setTimeout(() => api('/api/leads/' + l.id, { draft: l.draft }).catch(() => {}), 600);
}

void emit;
