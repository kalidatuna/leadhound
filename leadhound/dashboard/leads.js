// Leads view: pipeline stages, ranked list, lead detail with one-click actions, keyboard shortcuts.
import { $, api, el, emit, on, state, toast, copyText, ageText, scoreClass, safeUrl, pretty, SOURCE_NAMES, modalOpen } from './util.js';

const STAGES = [['new', 'Inbox'], ['shortlisted', 'Shortlist'], ['contacted', 'Contacted'], ['replied', 'Replied'],
  ['won', 'Won'], ['lost', 'Lost'], ['ignored', 'Skipped']];
const STAGE_NAME = Object.fromEntries(STAGES);
const F = { status: 'new', q: '', kind: '', min: 0, sort: 'score' };
let leads = [], sel = null, stats = {}, saveTimer = null;
const root = $('#view-leads');

export function initLeads() {
  root.append(el('div', { class: 'leads', id: 'leads' },
    el('aside', { class: 'side' },
      el('div', { class: 'stages', id: 'stages' }),
      el('div', { class: 'filters' },
        el('input', { id: 'q', class: 'wide', type: 'search', placeholder: 'Search leads   ( / )', oninput: debounce(e => { F.q = e.target.value; refresh(); }, 250) }),
        select('kind', [['', 'All types'], ['post', 'People hiring'], ['issue', 'GitHub issues'], ['business', 'Local businesses']], v => { F.kind = v; refresh(); }),
        select('min', [[0, 'Any score'], [35, 'Score 35+'], [60, 'Score 60+']], v => { F.min = +v; refresh(); }),
        select('sort', [['score', 'Best first'], ['newest', 'Newest found'], ['oldest', 'Oldest found']], v => { F.sort = v; refresh(); }),
        el('div', { class: 'row wide' },
          el('button', { class: 'btn sm', onclick: exportCsv }, 'Export CSV'),
          el('button', { class: 'btn sm', onclick: skipLow }, 'Skip low scores…'))),
      el('div', { class: 'list', id: 'list' })),
    el('section', { class: 'detail', id: 'detail' })));
  document.addEventListener('keydown', onKey);
  on('job-done', () => refresh());
  on('lead-open', id => { F.status = ''; F.q = ''; refresh(id); });
  refresh();
}

const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
function select(id, opts, onchange) {
  return el('select', { id, onchange: e => onchange(e.target.value) }, opts.map(([v, l]) => el('option', { value: v }, l)));
}

async function refresh(selectId) {
  const p = new URLSearchParams({ status: F.status, q: F.q, kind: F.kind, min: F.min, sort: F.sort });
  try {
    [leads, stats] = await Promise.all([api('/api/leads?' + p), api('/api/stats')]);
  } catch (e) { return toast(e.message, 'err'); }
  renderStages();
  const keep = selectId ?? sel?.id;
  sel = leads.find(l => l.id === keep) || (window.innerWidth > 820 ? leads[0] : null) || null;
  renderList();
  renderDetail();
}

function renderStages() {
  const by = stats.by_status || {};
  const chips = STAGES.map(([k, label]) => el('button', { class: 'chip' + (F.status === k ? ' on' : ''),
    onclick: () => { F.status = k; refresh(); } }, label, el('b', {}, by[k] || 0)));
  $('#stages').replaceChildren(...chips);
}

function leadMeta(l) {
  if (l.kind === 'business') {
    const cat = pretty(l.extra.category || 'business');
    return [cat, l.extra.website ? 'has website' : 'no website listed', l.location].filter(Boolean).join(' · ');
  }
  return [SOURCE_NAMES[l.source] || l.source, ageText(l.created_at), l.budget].filter(Boolean).join(' · ');
}

function renderList() {
  const list = $('#list');
  if (!leads.length) {
    const none = !stats.total;
    list.replaceChildren(el('div', { class: 'empty' },
      el('h2', {}, none ? 'No leads yet' : `Nothing in ${STAGE_NAME[F.status] || 'this view'}`),
      el('p', {}, none ? 'Search for people who are hiring or local businesses that need help.' : 'Change the filters or pick another stage above.'),
      none && el('button', { class: 'btn primary', onclick: () => emit('goto', 'find') }, 'Find clients')));
    return;
  }
  list.replaceChildren(...leads.map(l => el('div', { class: 'item' + (sel?.id === l.id ? ' on' : ''), 'data-id': l.id,
    onclick: () => { sel = l; renderList(); renderDetail(); $('#leads').classList.add('show-detail'); } },
    el('div', { class: 'sc ' + scoreClass(l.score) }, l.score),
    el('div', { class: 't' }, el('div', { class: 'ti' }, l.title), el('div', { class: 'me' }, leadMeta(l))))));
  $('.item.on', list)?.scrollIntoView({ block: 'nearest' });
}

// ---- actions ----
async function setStatus(lead, status, { undo = true } = {}) {
  const prev = lead.status;
  if (prev === status) return;
  try {
    const upd = await api('/api/leads/' + lead.id, { status });
    const idx = leads.findIndex(l => l.id === lead.id);
    const stays = !F.status || F.status === status;
    if (stays) { leads[idx] = upd; sel = upd; }
    else { leads.splice(idx, 1); sel = leads[Math.min(idx, leads.length - 1)] || null; }
    stats = await api('/api/stats');
    renderStages(); renderList(); renderDetail();
    toast(`Moved to ${STAGE_NAME[status]}`, '', undo ? { label: 'Undo', fn: () => api('/api/leads/' + lead.id, { status: prev }).then(() => refresh(lead.id)) } : null);
  } catch (e) { toast(e.message, 'err'); }
}

async function writeDraft(lead, useAi) {
  const btn = $(useAi ? '#ai' : '#write');
  if (btn) { btn.disabled = true; btn.textContent = useAi ? 'Asking the AI…' : 'Writing…'; }
  try {
    const r = await api(`/api/leads/${lead.id}/draft`, { llm: useAi });
    lead.draft = r.draft;
    if (sel?.id === lead.id) renderDetail();
    if (r.engine.includes('failed')) toast('AI failed, used the template instead: ' + r.engine.replace(/^.*failed: /, '').replace(')', ''), 'err');
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
  const n = parseInt(prompt('Skip every Inbox lead scoring below:', '30'), 10);
  if (!(n > 0)) return;
  const ids = leads.filter(l => l.status === 'new' && l.score < n).map(l => l.id);
  if (!ids.length) return toast('No Inbox leads below ' + n);
  if (!confirm(`Skip ${ids.length} leads scoring below ${n}? You can find them under Skipped.`)) return;
  try { await api('/api/leads/bulk', { ids, status: 'ignored' }); toast(`Skipped ${ids.length} leads`); refresh(); } catch (e) { toast(e.message, 'err'); }
}

// ---- detail ----
function contactRows(l) {
  return (l.contact || '').split(', ').filter(Boolean).map(c => {
    const email = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(c);
    const reddit = /^reddit DM: u\/([\w-]+)$/.exec(c), hn = /^HN: ([\w-]+)$/.exec(c);
    const link = reddit ? 'https://www.reddit.com/message/compose/?to=' + reddit[1] : hn ? 'https://news.ycombinator.com/user?id=' + hn[1] : null;
    return el('div', { class: 'contact' }, el('span', { class: 'val' }, c),
      el('button', { class: 'btn sm', onclick: async () => toast(await copyText(c) ? 'Copied' : 'Copy blocked by the browser') }, 'Copy'),
      link && el('a', { class: 'btn sm', href: link, target: '_blank', rel: 'noopener noreferrer' }, 'Open'));
  });
}

function mailto(l) {
  const to = (l.contact || '').split(', ').find(c => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(c));
  if (!to || !l.draft) return null;
  const m = /^Subject: (.*)\n\n?/.exec(l.draft);
  const body = m ? l.draft.slice(m[0].length) : l.draft;
  return `mailto:${to}?subject=${encodeURIComponent(m ? m[1] : 'Re: ' + l.title)}&body=${encodeURIComponent(body)}`;
}

function renderDetail() {
  const d = $('#detail');
  const l = sel;
  if (!l) {
    d.replaceChildren(el('div', { class: 'empty' }, el('h2', {}, 'Pick a lead'), el('p', {}, 'Select one on the left. Keys: j / k to move, s shortlist, x skip, c contacted, g write message.')));
    return;
  }
  const url = safeUrl(l.url);
  const audit = l.extra.audit;
  const sections = [
    el('button', { class: 'btn sm back', onclick: () => $('#leads').classList.remove('show-detail') }, '← Back to list'),
    el('div', { class: 'dh' },
      el('div', {}, el('h2', {}, l.title),
        el('div', { class: 'mut' }, [SOURCE_NAMES[l.source] || l.source, l.kind === 'business' ? pretty(l.extra.category || '') : '', ageText(l.created_at), l.budget, l.location].filter(Boolean).join(' · '), ' ',
          url && el('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, l.kind === 'business' ? 'Open website ↗' : 'Open original ↗'))),
      el('div', { class: 'big ' + scoreClass(l.score) }, l.score, el('small', {}, 'SCORE'))),
    el('div', { class: 'stagebar' }, STAGES.map(([k, label]) => el('button', { class: 'chip' + (l.status === k ? ' on' : ''), onclick: () => setStatus(l, k) }, label))),
    l.contact && el('h3', {}, 'Contact'), l.contact && contactRows(l),
    el('h3', {}, 'Your message'), messageBox(l),
    el('h3', {}, `Why score ${l.score}`),
    el('ul', { class: 'why' }, l.reasons.map(r => el('li', { class: r.startsWith('-') ? 'neg' : '' }, r))),
  ];
  if (audit) sections.push(auditBox(audit));
  if (l.body) sections.push(el('h3', {}, 'Original post'), el('details', { open: l.kind !== 'business' }, el('summary', {}, 'Show / hide'), el('pre', { class: 'post' }, l.body)));
  sections.push(el('h3', {}, 'Notes'), el('textarea', { rows: 3, placeholder: 'Anything to remember (autosaved)', value: l.notes, oninput: e => saveField(l, 'notes', e.target.value) }));
  d.replaceChildren(...sections.flat(Infinity).filter(Boolean));
  d.scrollTop = 0;
}

function messageBox(l) {
  const mail = mailto(l);
  const ta = el('textarea', { id: 'draft', placeholder: 'Click "Write message" to draft a first message from this lead\'s details. You review it and send it yourself.',
    value: l.draft, oninput: e => saveField(l, 'draft', e.target.value) });
  return el('div', { class: 'msg' }, ta, el('div', { class: 'row', style: 'margin-top:8px' },
    el('button', { id: 'write', class: 'btn' + (l.draft ? '' : ' primary'), onclick: () => writeDraft(l, false) }, l.draft ? 'Rewrite' : 'Write message'),
    el('button', { id: 'ai', class: 'btn', disabled: !state.meta.llm_ready, title: state.meta.llm_ready ? '' : 'Set up an AI provider in Settings first', onclick: () => writeDraft(l, true) }, 'Write with AI'),
    el('button', { class: 'btn', disabled: !l.draft, onclick: async () => toast(await copyText(l.draft) ? 'Copied' : 'Copy blocked by the browser') }, 'Copy'),
    el('button', { class: 'btn', disabled: !l.draft, onclick: async () => { if (await copyText(l.draft)) setStatus(l, 'contacted'); } }, 'Copy & mark contacted'),
    mail && el('a', { class: 'btn', href: mail }, 'Open in email')));
}

const SEV = { 3: ['Critical', 's3'], 2: ['Hurts customers', 's2'], 1: ['Minor', 's1'] };
function auditBox(a) {
  const head = `Website check · ${a.final_url || a.url}${a.seconds ? ` · ${a.seconds}s` : ''}${a.tech?.length ? ' · ' + a.tech.join(', ') : ''}`;
  if (a.blocked) return el('div', {}, el('h3', {}, head), el('p', { class: 'mut' }, 'This site blocked the automated check (bot protection). Open it in your browser and look yourself before pitching.'));
  return el('div', {}, el('h3', {}, head),
    !a.findings.length && el('p', { class: 'mut' }, 'No issues found. This site looks fine; pitch something else or move on.'),
    a.findings.map(f => el('div', { class: 'find-i s' + f.severity }, el('span', { class: 'tag s' + f.severity }, SEV[f.severity][0]), ' ', el('b', {}, f.title),
      el('div', { class: 'pitch' }, f.pitch), f.detail && el('div', { class: 'mut' }, f.detail.slice(0, 160)))));
}

// ---- keyboard ----
function onKey(e) {
  if (e.metaKey || e.ctrlKey || e.altKey || modalOpen() || $('#view-leads').hidden) return;
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName);
  if (typing) { if (e.key === 'Escape') document.activeElement.blur(); return; }
  const i = leads.findIndex(l => l.id === sel?.id);
  const go = n => { const t = leads[Math.max(0, Math.min(leads.length - 1, n))]; if (t) { sel = t; renderList(); renderDetail(); } };
  const keys = {
    j: () => go(i + 1), ArrowDown: () => go(i + 1), k: () => go(i - 1), ArrowUp: () => go(i - 1),
    s: () => sel && setStatus(sel, 'shortlisted'), c: () => sel && setStatus(sel, 'contacted'),
    x: () => sel && setStatus(sel, 'ignored'), g: () => sel && writeDraft(sel, false),
    o: () => sel && safeUrl(sel.url) && window.open(sel.url, '_blank', 'noopener'),
    '/': () => $('#q').focus(),
  };
  if (keys[e.key]) { e.preventDefault(); keys[e.key](); }
}
