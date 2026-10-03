// Step 3: read the message, choose how to send it, send it. leadhound never sends without a click here.
import { api, el, toast, copyText } from './util.js';
import { t } from './i18n.js';
import { icon } from './icons.js';
import { srcName, ageText, reasonLine } from './leads.js';
import { acct, openConnect, platIcon, platName, redraw } from './accounts.js';

const VERB = { email: 'act.email', mastodon: 'act.mastodon', github: 'act.github', reddit: 'act.reddit' };
const NOTE = { gmail: 'note.gmail', outlook: 'note.outlook', whatsapp: 'note.whatsapp', telegram: 'note.telegram', freelancer: 'note.copy_page', page: 'note.copy_page', email: 'note.mailto', reddit: 'note.copy_page' };
const SUBJECT = /^[^\n:]{1,20}: (.*)\n\n?/;  // drafts for local businesses start with "Subject: ..."
const ratePips = n => [1, 2, 3, 4, 5].map(i => el('i', { class: i <= n ? 'on' : '' }));

/** Only web and mail links ever get opened, whatever the server sends. */
function openLink(url) {
  if (!/^(https?:|mailto:)/i.test(url || '')) return;
  const a = el('a', { href: url, target: '_blank', rel: 'noopener noreferrer' });
  document.body.append(a);
  a.click();
  a.remove();
}

/**
 * Draw the compose step into `box` for lead `l`.
 * cb.onBack(), cb.onSent({via, as}) after leadhound sent it or the user confirmed they did.
 */
export async function renderCompose(box, l, cb) {
  if (!l.draft) {
    try { l.draft = (await api(`/api/leads/${l.id}/draft`, { llm: false })).draft; } catch (e) { return toast(e.message, 'err'); }
  }
  let chans = [];
  try { chans = await api(`/api/leads/${l.id}/channels`); } catch (e) { toast(e.message, 'err'); }
  const pickDefault = () => chans.findIndex(c => c.mode === 'send' && c.ready) >= 0 ? chans.findIndex(c => c.mode === 'send' && c.ready) : Math.max(chans.findIndex(c => c.ready), 0);
  let sel = chans.length ? pickDefault() : -1, opened = false, saveTimer = null;

  const ta = el('textarea', { spellcheck: false, value: l.draft, oninput: () => { l.draft = ta.value; clearTimeout(saveTimer); saveTimer = setTimeout(() => api('/api/leads/' + l.id, { draft: l.draft }).catch(() => {}), 600); } });
  const via = el('div', { class: 'via' });
  const prim = el('span', { class: 'prim' });
  const parts = () => { const m = SUBJECT.exec(ta.value); return { subject: m ? m[1] : l.title, body: m ? ta.value.slice(m[0].length) : ta.value }; };
  const cur = () => chans[sel];

  const markSent = async (viaId, info) => {
    try { await api('/api/leads/' + l.id, { status: 'contacted', draft: ta.value, via: viaId }); } catch (e) { return toast(e.message, 'err'); }
    cb.onSent(info || { via: null });
  };

  async function act() {
    const c = cur(), name = platName(c.id), { subject, body } = parts();
    if (c.mode === 'send' && c.ready) {  // send through the connected account
      const btn = prim.querySelector('[data-act]');
      btn.disabled = true; btn.replaceChildren(el('span', { class: 'spin' }), t('compose.sending'));
      try {
        const r = await api(`/api/leads/${l.id}/send`, { channel: c.id, to: c.to, subject, body });
        acct(c.id).used = r.used;
        cb.onSent({ via: name, as: r.as });
      } catch (e) { toast(e.message, 'err'); draw(); }
    } else if (c.mode === 'send') {  // not connected yet
      openConnect(c.id, async () => { chans = await api(`/api/leads/${l.id}/channels`); redraw(); draw(); });
    } else if (!c.ready) {  // link app turned off
      try { await api('/api/accounts/' + c.id, { action: 'toggle', on: true }); chans = await api(`/api/leads/${l.id}/channels`); redraw(); draw(); } catch (e) { toast(e.message, 'err'); }
    } else {
      openVia(c, subject, body);
    }
  }

  async function openVia(c, subject, body) {
    const name = platName(c.id), text = body.trim();
    let url = c.link || '';
    const q = encodeURIComponent;
    if (c.id === 'email') url += `?subject=${q(subject)}&body=${q(text)}`;
    else if (c.id === 'gmail') url += `&su=${q(subject)}&body=${q(text)}`;
    else if (c.id === 'outlook') url += `&subject=${q(subject)}&body=${q(text)}`;
    else if (c.text_param) url += `?${c.text_param}=${q(text)}`;
    if (url.length > 6000) { url = c.link; c = { ...c, copy: true }; }  // too long for a link: open the app empty and paste instead
    if (c.copy) toast(await copyText(text) ? t('compose.copied_open', { name }) : t('copy_blocked'));
    else toast(t('compose.opened', { name }));
    openLink(url);
    opened = true;
    draw();
  }

  function note() {
    if (!chans.length) return t('note.none');
    const c = cur(), name = platName(c.id), a = acct(c.id);
    let s;
    if (c.mode === 'send') s = c.ready ? t('note.send', { as: a.as, used: a.used, cap: a.cap }) : c.link ? t(NOTE[c.id] || 'note.copy_page') : t('note.connect', { name });
    else s = c.ready ? t(NOTE[c.id] || 'note.copy_page') : t('note.off', { name });
    return s + ' ' + t('note.tail');
  }

  function draw() {
    via.replaceChildren(...[el('div', { class: 'via-h' }, t('compose.via')),
      chans.length > 0 && el('div', { class: 'opts', role: 'radiogroup', 'aria-label': t('compose.via') }, chans.map((c, i) => {
        const [cls, label] = c.mode === 'send' ? (c.ready ? ['ok', t('compose.st_connected')] : ['', t('compose.st_not')]) : (c.ready ? ['ok', t('compose.st_opens')] : ['', t('compose.st_off')]);
        return el('button', { type: 'button', class: 'opt' + (i === sel ? ' on' : ''), role: 'radio', 'aria-checked': i === sel, onclick: () => { sel = i; opened = false; draw(); } },
          el('span', { class: 'oi' }, platIcon(c.id)), el('span', { class: 'ot' }, el('b', {}, platName(c.id)), el('small', {}, c.to)), el('span', { class: 'os ' + cls }, label));
      })),
      el('p', { class: 'via-note' }, note())].filter(Boolean));
    const manual = el('button', { class: 'btn ghost', onclick: () => markSent('manual') }, t('compose.sent_other'));
    const gold = (label, ic, attrs = {}) => el('button', { class: 'cta sm', 'data-act': 1, onclick: act, ...attrs }, ic && icon(ic), label);
    const c = cur();
    let kids;
    if (!c) kids = [el('button', { class: 'cta sm', onclick: () => markSent('manual') }, icon('check'), t('compose.i_sent'))];
    else if (c.mode === 'send' && c.ready) {
      const a = acct(c.id), full = a.used >= a.cap;
      kids = [manual, gold(full ? t('compose.limit') : t(VERB[c.id]), 'send', { disabled: full })];
    } else if (c.mode === 'send') {
      const connect = () => openConnect(c.id, async () => { chans = await api(`/api/leads/${l.id}/channels`); redraw(); draw(); });
      // not connected: opening it yourself works right away, connecting is the optional upgrade
      kids = c.link ? [manual, el('button', { class: 'btn', onclick: connect }, t('compose.connect', { name: platName(c.id) })), !opened ? gold(t('compose.open', { name: platName(c.id) }), 'arrow', { onclick: () => { const { subject, body } = parts(); openVia({ ...c, copy: c.id !== 'email' }, subject, body); } }) : el('button', { class: 'cta sm', onclick: () => markSent(c.id, { via: null }) }, icon('check'), t('compose.i_sent'))]
        : [manual, gold(t('compose.connect', { name: platName(c.id) }))];
    } else if (!c.ready) kids = [manual, gold(t('compose.turn_on', { name: platName(c.id) }))];
    else if (!opened) kids = [manual, gold(t('compose.open', { name: platName(c.id) }), 'arrow')];
    else kids = [el('button', { class: 'btn', onclick: act }, t('compose.open_again')), el('button', { class: 'cta sm', onclick: () => markSent(c.id, { via: null }) }, icon('check'), t('compose.i_sent'))];
    prim.replaceChildren(...kids.filter(Boolean));
  }

  const n = Math.max(1, Math.min(5, Math.round(l.score / 20)));
  const facts = el('dl', { class: 'facts' },
    !!l.budget && el('div', {}, el('dt', {}, t('compose.budget')), el('dd', { class: 'num' }, l.budget)),
    l.created_at > 0 && el('div', {}, el('dt', {}, t('compose.posted')), el('dd', {}, ageText(l.created_at))),
    el('div', {}, el('dt', {}, t('compose.match')), el('dd', {}, el('span', { class: 'rate' }, ratePips(n)), el('span', { class: 'num' }, l.score))));
  box.replaceChildren(el('div', { class: 'compose' },
    el('div', { class: 'mini' }, el('div', {}, el('span', { class: 'src' }, srcName(l.source))), el('h3', {}, l.title), facts,
      el('p', {}, reasonLine(l)),
      el('div', { class: 'tips' }, el('h5', {}, t('compose.tips')), el('ul', {}, ['compose.tip1', 'compose.tip2', 'compose.tip3'].map(k => el('li', {}, icon('check'), t(k)))))),
    el('div', { class: 'paper' }, via, ta,
      el('div', { class: 'foot' }, el('button', { class: 'btn', onclick: async () => toast(await copyText(parts().body.trim()) ? t('copied') : t('copy_blocked')) }, icon('copy'), t('today.copy_btn')),
        el('button', { class: 'btn ghost', onclick: cb.onBack }, t('compose.back')), prim))));
  draw();
  ta.focus({ preventScroll: true });
}
