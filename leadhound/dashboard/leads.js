// Leads view: pipeline stages, ranked list, lead detail with one-click actions, keyboard shortcuts.
import { $, api, el, emit, on, state, store, toast, copyText, scoreClass, safeUrl, BRANDS, modalOpen } from './util.js';
import { t, whyText, findingText, catName } from './i18n.js';

const STAGES = ['new', 'shortlisted', 'contacted', 'replied', 'won', 'lost', 'ignored'];
const F = { status: 'new', q: '', kind: '', min: 0, sort: 'score' };
let leads = [], sel = null, stats = {}, saveTimer = null;
const root = $('#view-leads');
// "new since your last visit": remember the previous visit, then start a new one
const lastVisit = parseFloat(store.get('lh-last-visit')) || 0;
store.set('lh-last-visit', String(Date.now() / 1000));

export const srcName = s => BRANDS[s] || t('src.' + s);
export function ageText(ts) {
  if (!ts) return '';
  const h = (Date.now() / 1000 - ts) / 3600;
  if (h < 1) return t('age.now');
  return h < 48 ? t('age.h', { n: Math.round(h) }) : t('age.d', { n: Math.round(h / 24) });
}
const isNew = l => lastVisit && l.first_seen > lastVisit && l.status === 'new';
const debounce = (fn, ms) => { let tm; return (...a) => { clearTimeout(tm); tm = setTimeout(() => fn(...a), ms); }; };
const select = (id, opts, onchange) => el('select', { id, onchange: e => onchange(e.target.value) }, opts.map(([v, l]) => el('option', { value: v }, l)));

export function initLeads() {
  root.append(el('div', { class: 'leads', id: 'leads' },
    el('aside', { class: 'side' },
      el('div', { class: 'stages', id: 'stages' }),
      el('div', { class: 'filters' },
        el('input', { id: 'q', class: 'wide', type: 'search', placeholder: t('leads.search_ph'), oninput: debounce(e => { F.q = e.target.value; refresh(); }, 250) }),
        select('kind', [['', t('leads.kind_all')], ['post', t('kind.post')], ['issue', t('kind.issue')], ['business', t('kind.business')]], v => { F.kind = v; refresh(); }),
        select('min', [[0, t('leads.any_score')], [35, t('leads.score_min', { n: 35 })], [60, t('leads.score_min', { n: 60 })]], v => { F.min = +v; refresh(); }),
        select('sort', [['score', t('sort.score')], ['newest', t('sort.newest')], ['oldest', t('sort.oldest')]], v => { F.sort = v; refresh(); }),
        el('div', { class: 'row wide' },
          el('button', { class: 'btn sm', onclick: exportCsv }, t('leads.export')),
          el('button', { class: 'btn sm', onclick: skipLow }, t('leads.skip_low')),
          el('span', { class: 'mut sm', id: 'newcount' }))),
      el('div', { class: 'list', id: 'list' })),
    el('section', { class: 'detail', id: 'detail' })));
  document.addEventListener('keydown', onKey);
  on('job-done', () => refresh());
  on('lead-open', id => { F.status = ''; F.q = ''; refresh(id); });
  refresh();
}

async function refresh(selectId) {
  const p = new URLSearchParams({ status: F.status, q: F.q, kind: F.kind, min: F.min, sort: F.sort });
  try {
    [leads, stats] = await Promise.all([api('/api/leads?' + p), api('/api/stats')]);
  } catch (e) { return toast(e.message, 'err'); }
  renderStages();
  const keep = selectId ?? sel?.id;
  sel = leads.find(l => l.id === keep) || (window.innerWidth > 820 ? leads[0] : null) || null;
  const n = leads.filter(isNew).length;
  $('#newcount').textContent = n ? t('leads.new_since', { n }) : '';
  renderList();
  renderDetail();
}

function renderStages() {
  const by = stats.by_status || {};
  $('#stages').replaceChildren(...STAGES.map(k => el('button', { class: 'chip' + (F.status === k ? ' on' : ''),
    onclick: () => { F.status = k; refresh(); } }, t('stage.' + k), el('b', {}, by[k] || 0))));
}

function leadMeta(l) {
  if (l.kind === 'business') {
    return [catName(l.extra.category || 'business'), l.extra.website ? t('meta.has_website') : t('meta.no_website'), l.location].filter(Boolean).join(' · ');
  }
  return [srcName(l.source), ageText(l.created_at), l.budget].filter(Boolean).join(' · ');
}

function renderList() {
  const list = $('#list');
  if (!leads.length) {
    const none = !stats.total;
    list.replaceChildren(el('div', { class: 'empty' },
      el('h2', {}, none ? t('leads.empty_title') : t('leads.empty_stage', { stage: t('stage.' + F.status) })),
      el('p', {}, none ? t('leads.empty_text') : t('leads.empty_stage_text')),
      none && el('button', { class: 'btn primary', onclick: () => emit('goto', 'find') }, t('leads.empty_btn'))));
    return;
  }
  list.replaceChildren(...leads.map(l => el('div', { class: 'item' + (sel?.id === l.id ? ' on' : ''), 'data-id': l.id,
    onclick: () => { sel = l; renderList(); renderDetail(); $('#leads').classList.add('show-detail'); } },
    el('div', { class: 'sc ' + scoreClass(l.score) }, l.score),
    el('div', { class: 't' }, el('div', { class: 'ti' }, isNew(l) && el('span', { class: 'new' }, t('badge.new')), l.title),
      el('div', { class: 'me' }, leadMeta(l))))));
  $('.item.on', list)?.scrollIntoView({ block: 'nearest' });
}

// ---- actions ----
async function setStatus(lead, status) {
  const prev = lead.status;
  if (prev === status) return;
  try {
    const upd = await api('/api/leads/' + lead.id, { status });
    const idx = leads.findIndex(l => l.id === lead.id);
    if (!F.status || F.status === status) { leads[idx] = upd; sel = upd; } else { leads.splice(idx, 1); sel = leads[Math.min(idx, leads.length - 1)] || null; }
    stats = await api('/api/stats');
    renderStages(); renderList(); renderDetail();
    toast(t('leads.moved', { stage: t('stage.' + status) }), '', { label: t('undo'), fn: () => api('/api/leads/' + lead.id, { status: prev }).then(() => refresh(lead.id)) });
  } catch (e) { toast(e.message, 'err'); }
}

async function writeDraft(lead, useAi) {
  const btn = $(useAi ? '#ai' : '#write');
  if (btn) { btn.disabled = true; btn.textContent = useAi ? t('msg.ai_busy') : t('msg.writing'); }
  try {
    const r = await api(`/api/leads/${lead.id}/draft`, { llm: useAi });
    lead.draft = r.draft;
    if (sel?.id === lead.id) renderDetail();
    if (r.engine.includes('failed')) toast(t('msg.ai_failed', { err: r.engine.replace(/^.*failed: /, '').replace(/\)$/, '') }), 'err');
  } catch (e) { toast(e.message, 'err'); renderDetail(); }
}

function saveField(lead, field, value) {
  lead[field] = value;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => api('/api/leads/' + lead.id, { [field]: value }).catch(e => toast(e.message, 'err')), 600);
}

async function exportCsv() {
  try {
    const blob = await api('/api/export?status=' + F.status);
    const a = el('a', { href: URL.createObjectURL(blob), download: 'leads.csv' });
    a.click(); URL.revokeObjectURL(a.href);
  } catch (e) { toast(e.message, 'err'); }
}

async function skipLow() {
  const n = parseInt(prompt(t('leads.skip_prompt'), '30'), 10);
  if (!(n > 0)) return;
  const ids = leads.filter(l => l.status === 'new' && l.score < n).map(l => l.id);
  if (!ids.length) return toast(t('leads.skip_none', { n }));
  if (!confirm(t('leads.skip_confirm', { count: ids.length, n }))) return;
  try { await api('/api/leads/bulk', { ids, status: 'ignored' }); toast(t('leads.skipped', { n: ids.length })); refresh(); } catch (e) { toast(e.message, 'err'); }
}

// ---- detail ----
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const copyBtn = text => el('button', { class: 'btn sm', onclick: async () => toast(await copyText(text) ? t('copied') : t('copy_blocked')) }, t('copy'));

function contactRows(l) {
  return (l.contact || '').split(', ').filter(Boolean).map(c => {
    const reddit = /^reddit DM: u\/([\w-]+)$/.exec(c), hn = /^HN: ([\w-]+)$/.exec(c), masto = /^Mastodon: @(.+)$/.exec(c);
    const link = reddit ? 'https://www.reddit.com/message/compose/?to=' + reddit[1] : hn ? 'https://news.ycombinator.com/user?id=' + hn[1]
      : (l.source === 'freelancer' || masto) ? safeUrl(l.url) : null;
    const phone = /^\+?[\d\s().-]{6,}$/.test(c) ? 'tel:' + c.replace(/[^\d+]/g, '') : null;
    return el('div', { class: 'contact' }, el('span', { class: 'val' }, c), copyBtn(c),
      (link || phone) && el('a', { class: 'btn sm', href: link || phone, target: link ? '_blank' : null, rel: 'noopener noreferrer' }, phone ? t('call') : t('open')));
  });
}

function mailto(l) {
  const to = (l.contact || '').split(', ').find(c => EMAIL.test(c));
  if (!to || !l.draft) return null;
  const m = /^[^\n:]{1,20}: (.*)\n\n?/.exec(l.draft);  // "Subject: ..." in any language
  const body = m ? l.draft.slice(m[0].length) : l.draft;
  return `mailto:${to}?subject=${encodeURIComponent(m ? m[1] : l.title)}&body=${encodeURIComponent(body)}`;
}

function renderDetail() {
  const d = $('#detail');
  const l = sel;
  if (!l) {
    d.replaceChildren(el('div', { class: 'empty' }, el('h2', {}, t('leads.pick_title')), el('p', {}, t('leads.pick_text'))));
    return;
  }
  const url = safeUrl(l.url);
  const why = l.extra.why ? l.extra.why.map(w => [w[0], whyText(w)]) : l.reasons.map(r => [r.startsWith('-') ? -1 : 1, r]);
  const sections = [
    el('button', { class: 'btn sm back', onclick: () => $('#leads').classList.remove('show-detail') }, t('detail.back')),
    el('div', { class: 'dh' },
      el('div', {}, el('h2', {}, l.title),
        el('div', { class: 'mut' }, [srcName(l.source), l.kind === 'business' ? catName(l.extra.category || '') : '', ageText(l.created_at), l.budget, l.location].filter(Boolean).join(' · '), ' ',
          url && el('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, l.kind === 'business' ? t('detail.open_website') : t('detail.open_original')))),
      el('div', { class: 'big ' + scoreClass(l.score) }, l.score, el('small', {}, t('detail.score')))),
    el('div', { class: 'stagebar' }, STAGES.map(k => el('button', { class: 'chip' + (l.status === k ? ' on' : ''), onclick: () => setStatus(l, k) }, t('stage.' + k)))),
    l.contact && el('h3', {}, t('h.contact')), l.contact && contactRows(l),
    el('h3', {}, t('h.message')), messageBox(l),
    el('h3', {}, t('h.why', { score: l.score })),
    el('ul', { class: 'why' }, why.map(([p, text]) => el('li', { class: p != null && p < 0 ? 'neg' : '' }, text))),
    l.extra.audit && auditBox(l.extra.audit),
    l.body && [el('h3', {}, t('h.post')), el('details', { open: l.kind !== 'business' }, el('summary', {}, t('show_hide')), el('pre', { class: 'post' }, l.body))],
    el('h3', {}, t('h.notes')), el('textarea', { rows: 3, placeholder: t('notes_ph'), value: l.notes, oninput: e => saveField(l, 'notes', e.target.value) }),
  ];
  d.replaceChildren(...sections.flat(Infinity).filter(Boolean));
  d.scrollTop = 0;
}

function messageBox(l) {
  const mail = mailto(l);
  const ready = state.meta.llm_ready;
  return el('div', { class: 'msg' },
    el('textarea', { id: 'draft', placeholder: t('msg.ph'), value: l.draft, oninput: e => saveField(l, 'draft', e.target.value) }),
    el('div', { class: 'row', style: 'margin-top:8px' },
      el('button', { id: 'write', class: 'btn' + (l.draft ? '' : ' primary'), onclick: () => writeDraft(l, false) }, l.draft ? t('msg.rewrite') : t('msg.write')),
      el('button', { id: 'ai', class: 'btn', disabled: !ready, title: ready ? '' : t('msg.ai_setup'), onclick: () => writeDraft(l, true) }, t('msg.ai')),
      el('button', { class: 'btn', disabled: !l.draft, onclick: async () => toast(await copyText(l.draft) ? t('copied') : t('copy_blocked')) }, t('copy')),
      el('button', { class: 'btn', disabled: !l.draft, onclick: async () => { if (await copyText(l.draft)) setStatus(l, 'contacted'); } }, t('msg.copy_mark')),
      mail && el('a', { class: 'btn', href: mail }, t('msg.email'))));
}

function auditBox(a) {
  const head = `${t('h.audit')} · ${a.final_url || a.url}${a.seconds ? ` · ${a.seconds}s` : ''}${a.tech?.length ? ' · ' + a.tech.join(', ') : ''}`;
  if (a.blocked) return el('div', {}, el('h3', {}, head), el('p', { class: 'mut' }, t('audit.blocked')));
  return el('div', {}, el('h3', {}, head),
    !a.findings.length && el('p', { class: 'mut' }, t('audit.ok')),
    a.findings.map(f => {
      const { title, pitch } = findingText(f);
      return el('div', { class: 'find-i s' + f.severity }, el('span', { class: 'tag s' + f.severity }, t('sev.' + f.severity)), ' ', el('b', {}, title),
        el('div', { class: 'pitch' }, pitch), f.detail && el('div', { class: 'mut' }, f.detail.slice(0, 160)));
    }));
}

// ---- keyboard ----
function onKey(e) {
  if (e.metaKey || e.ctrlKey || e.altKey || modalOpen() || $('#view-leads').hidden) return;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName)) { if (e.key === 'Escape') document.activeElement.blur(); return; }
  const i = leads.findIndex(l => l.id === sel?.id);
  const go = n => { const x = leads[Math.max(0, Math.min(leads.length - 1, n))]; if (x) { sel = x; renderList(); renderDetail(); } };
  const keys = {
    j: () => go(i + 1), ArrowDown: () => go(i + 1), k: () => go(i - 1), ArrowUp: () => go(i - 1),
    s: () => sel && setStatus(sel, 'shortlisted'), c: () => sel && setStatus(sel, 'contacted'),
    x: () => sel && setStatus(sel, 'ignored'), g: () => sel && writeDraft(sel, false),
    o: () => sel && safeUrl(sel.url) && window.open(sel.url, '_blank', 'noopener'), '/': () => $('#q').focus(),
  };
  if (keys[e.key]) { e.preventDefault(); keys[e.key](); }
}
