// Accounts: where leadhound can send from. The list page and the connect dialog.
// Secrets are typed here once and go straight to the server. The server never sends them back.
import { $, api, el, emit, state, toast } from './util.js';
import { t } from './i18n.js';
import { icon } from './icons.js';
import { isPro, openPlan, proTag } from './plan.js';

export const SEND = ['email', 'mastodon', 'github', 'reddit'];
export const LINK = ['gmail', 'outlook', 'freelancer', 'whatsapp', 'telegram'];
const ICON = { gmail: 'gmail', outlook: 'outlook', email: 'mail', mastodon: 'mastodon', github: 'github', reddit: 'reddit', freelancer: 'freelancer', whatsapp: 'whatsapp', telegram: 'telegram', page: 'globe' };
export const platIcon = id => icon(ICON[id] || 'globe');
export const platName = id => ({ gmail: 'Gmail', outlook: 'Outlook', email: t('plat.email'), mastodon: 'Mastodon', github: 'GitHub', reddit: 'Reddit', freelancer: 'Freelancer.com',
  whatsapp: 'WhatsApp', telegram: 'Telegram', page: t('plat.page') })[id] || id;

const root = $('#view-accounts');

export async function loadAccounts() {
  try { state.accts = await api('/api/accounts'); } catch { state.accts = state.accts || {}; }
  paintBadge();
  return state.accts;
}
export const acct = id => (state.accts || {})[id] || {};
export const sendCount = () => SEND.filter(id => acct(id).connected).length;
export const readyCount = () => [...SEND, ...LINK].filter(id => acct(id).ready).length;
export const TOTAL = SEND.length + LINK.length;

export function paintBadge() {
  const b = $('#acct-btn');
  b.firstChild.textContent = t('hdr.accounts');
  const n = sendCount();
  b.lastChild.hidden = !n;
  b.lastChild.textContent = n;
}

export function initAccounts() {
  $('#acct-btn').addEventListener('click', () => emit('goto', 'accounts'));
  draw();
}

function card(id) {
  const a = acct(id), on = !!a.ready, send = SEND.includes(id);
  const status = send
    ? (on ? [el('div', { class: 'astat' }, el('span', { class: 'dot' }), el('span', { class: 'as' }, t('acct.connected_as', { as: a.as }))),
        el('div', { class: 'meter' }, el('span', { style: `width:${Math.min(100, Math.round(a.used / a.cap * 100))}%` })),
        el('small', {}, t('acct.used', { used: a.used, cap: a.cap }))]
      : [el('div', { class: 'astat off' }, t('acct.not_connected')), id === 'reddit' && el('small', {}, t('acct.warn_reddit', { cap: 5 }))])
    : [el('div', { class: 'astat' + (on ? '' : ' off') }, on && el('span', { class: 'dot' }), el('span', { class: 'as' }, on ? t('acct.on') : t('acct.off')))];
  const act = send
    ? (on ? el('button', { class: 'btn', onclick: e => disconnect(id, e.currentTarget) }, t('acct.disconnect'))
          : el('button', { class: 'btn primary', onclick: () => openConnect(id, () => { toast(t('acct.connected_toast', { name: platName(id) })); redraw(); }) }, t('acct.connect')))
    : el('button', { class: 'sw', role: 'switch', 'aria-checked': on, 'aria-label': platName(id), onclick: () => toggle(id, !on) });
  return el('article', { class: 'acct' + (on ? ' on' : '') }, el('div', { class: 'ai' }, platIcon(id)),
    el('div', { class: 'ab' }, el('h3', {}, platName(id)), el('p', { class: 'ad' }, t('acct.d.' + id)), status), el('div', { class: 'aact' }, act));
}

function draw() {
  root.replaceChildren(el('div', { class: 'page' }, el('div', { class: 'wrap', style: 'display:block' },
    el('button', { class: 'btn ghost', style: 'margin-inline-start:-14px', onclick: () => emit('goto', 'today') }, icon('back'), t('acct.back')),
    el('div', { class: 'acct-title' }, el('div', { class: 'eyebrow' }, t('hdr.accounts')), el('h2', {}, t('acct.title')), el('p', {}, t('acct.text'))),
    el('ul', { class: 'trust' }, [['lock', 'acct.trust1'], ['check', 'acct.trust2'], ['gauge', 'acct.trust3']].map(([i, k]) => el('li', {}, icon(i), el('span', {}, t(k))))),
    el('h4', { class: 'sec' }, t('acct.sec_link')), el('div', { class: 'agrid' }, LINK.map(card)),
    el('h4', { class: 'sec' }, t('acct.sec_send'), ' ', proTag()), el('div', { class: 'agrid' }, SEND.map(card)),
    el('p', { class: 'demo' }, t('acct.where', { path: state.meta.config_path.replace(/[^/\\]*$/, '') + 'accounts.json' })))));
}
export const redraw = () => { paintBadge(); draw(); emit('accounts-changed'); };

async function toggle(id, on) {
  try { state.accts[id] = await api('/api/accounts/' + id, { action: 'toggle', on }); redraw(); } catch (e) { toast(e.message, 'err'); }
}

function disconnect(id, btn) {
  if (!btn.dataset.sure) {  // two clicks: the saved login is deleted and has to be typed again
    btn.dataset.sure = 1; btn.textContent = t('acct.sure');
    setTimeout(() => { if (btn.isConnected) { delete btn.dataset.sure; btn.textContent = t('acct.disconnect'); } }, 3500);
    return;
  }
  api('/api/accounts/' + id, { action: 'disconnect' }).then(r => { state.accts[id] = r; toast(t('acct.disconnected', { name: platName(id) })); redraw(); }).catch(e => toast(e.message, 'err'));
}

// ---------- connect dialog ----------
const FORMS = {
  email: { sub: 'sheet.email_sub', go: 'sheet.email_go', help: ['sheet.email_help_1', 'sheet.email_help_2', 'sheet.email_help_3'], helpTitle: 'sheet.email_help' },
  mastodon: { sub: 'sheet.mast_sub', go: 'sheet.connect', help: ['sheet.mast_help_1', 'sheet.mast_help_2', 'sheet.mast_help_3'], helpTitle: 'sheet.how_token',
    fields: [['instance', 'f.server', 'text', 'mastodon.social'], ['token', 'f.token', 'password', '']] },
  github: { sub: 'sheet.gh_sub', go: 'sheet.connect', help: ['sheet.gh_help_1', 'sheet.gh_help_2', 'sheet.gh_help_3'], helpTitle: 'sheet.how_token',
    fields: [['token', 'f.token', 'password', '']] },
  reddit: { sub: 'sheet.rd_sub', go: 'sheet.connect', help: ['sheet.rd_help_1', 'sheet.rd_help_2', 'sheet.rd_help_3'], helpTitle: 'sheet.how_app', warn: true,
    fields: [['client_id', 'f.client_id', 'text', ''], ['client_secret', 'f.client_secret', 'password', ''], ['username', 'f.username', 'text', ''], ['password', 'f.reddit_pw', 'password', '']] },
};

export function openConnect(id, done) {
  if (!isPro()) return openPlan();  // sending through your own account is a Pro feature
  const d = $('#sheet'), spec = FORMS[id], title = t('sheet.title', { name: platName(id) });
  let provider = 'gmail';
  const vals = {};  // what was typed, kept when the provider switch redraws the form
  const head = (sub = spec.sub) => el('div', { class: 'sheet-h' }, el('div', { class: 'ai' }, platIcon(id)),
    el('div', {}, el('h3', {}, title), el('p', {}, t(sub))), el('button', { class: 'x', 'aria-label': t('sheet.close'), onclick: () => d.close() }, icon('x')));
  const input = (key, label, type, ph, extra = {}) => el('label', { class: 'field' }, t(label), el('input', { id: 'f-' + key, type, placeholder: ph, autocomplete: 'off', spellcheck: false, ...extra, value: vals[key] ?? extra.value ?? '' }));
  const draw = () => {
    const fields = id === 'email' ? [
      el('div', { class: 'seg', role: 'radiogroup', 'aria-label': t('f.provider') }, ['gmail', 'outlook', 'other'].map(p =>
        el('button', { type: 'button', role: 'radio', 'aria-checked': p === provider, onclick: () => { save(); provider = p; draw(); } }, p === 'gmail' ? 'Gmail' : p === 'outlook' ? 'Outlook' : t('f.other')))),
      input('address', 'f.address', 'email', provider === 'outlook' ? 'you@outlook.com' : provider === 'gmail' ? 'you@gmail.com' : 'you@yourdomain.com', { inputMode: 'email' }),
      provider === 'other' && el('div', { class: 'two2' }, input('host', 'f.host', 'text', 'smtp.yourdomain.com'), input('port', 'f.port', 'text', '587', { value: '587', inputMode: 'numeric' })),
      input('password', 'f.password', 'password', ''),
    ] : spec.fields.map(([k, l, ty, ph]) => input(k, l, ty, ph));
    const go = el('button', { class: 'cta sm', type: 'submit' }, t(spec.go));
    const err = el('p', { class: 'err', role: 'alert' });
    const form = el('form', { onsubmit: async e => {
      e.preventDefault();
      const values = Object.fromEntries([...form.querySelectorAll('input')].map(i => [i.id.slice(2), i.value.trim()]));
      go.disabled = true; go.replaceChildren(el('span', { class: 'spin' }), t('sheet.checking')); err.textContent = '';
      try {
        const r = await api('/api/accounts/' + id, { action: 'connect', fields: id === 'email' ? { ...values, provider } : values });
        state.accts[id] = r;
        success(r.as);
      } catch (ex) { err.textContent = ex.message; go.disabled = false; go.replaceChildren(t(spec.go)); }
    } },
      fields, el('details', { class: 'how' }, el('summary', {}, t(spec.helpTitle)), el('ol', {}, spec.help.map(k => el('li', {}, t(k))))),
      spec.warn && el('p', { class: 'warnb' }, t('acct.warn_reddit', { cap: 5 })), err,
      el('div', { class: 'sheet-f' }, el('button', { class: 'btn ghost', type: 'button', onclick: () => d.close() }, t('sheet.cancel')), go),
      el('p', { class: 'demo', style: 'text-align:end;margin-top:18px' }, t('sheet.local_note')));
    d.replaceChildren(el('div', { class: 'sheet' }, head(), form));
    form.querySelector('input')?.focus();
  };
  const save = () => $('#sheet').querySelectorAll('input').forEach(i => { vals[i.id.slice(2)] = i.value; });
  const success = as => {
    d.replaceChildren(el('div', { class: 'sheet' }, head('sheet.ok_sub'),
      el('div', { class: 'okmark' }, icon('check')), el('p', { class: 'okt' }, t('sheet.connected', { as }), id === 'email' ? ' ' + t('sheet.email_ok') : ''),
      el('div', { class: 'sheet-f' }, el('button', { class: 'cta sm', onclick: () => { d.close(); done && done(); } }, t('sheet.done')))));
  };
  draw();
  d.showModal();
}
