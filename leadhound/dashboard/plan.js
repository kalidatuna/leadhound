// Plans: Free, a Pro trial, Pro by license key. The pill in the header and the "leadhound Pro" dialog.
import { $, api, el, emit, on, state, toast } from './util.js';
import { t, LANG } from './i18n.js';
import { icon } from './icons.js';

export const plan = () => state.plan || { plan: 'pro', configured: false };
export const isPro = () => plan().plan !== 'free';
const fmtDate = ts => new Intl.DateTimeFormat(LANG, { year: 'numeric', month: 'long', day: 'numeric' }).format(new Date(ts * 1000));
const safe = u => (/^https:\/\//i.test(u || '') ? u : '');

export async function loadPlan() {
  try { state.plan = await api('/api/plan'); } catch { /* keep the last known plan */ }
  paintPill();
  return state.plan;
}

export function paintPill() {
  const b = $('#plan-btn'), p = plan();
  if (!p.configured) { b.hidden = true; return; }  // licensing is off in this build: nothing to sell
  b.hidden = false;
  b.textContent = p.plan === 'trial' ? t('plan.pill_trial', { n: p.trial_left }) : p.plan === 'taste' ? t('plan.pill_taste', { n: p.uses_left })
    : p.plan === 'pro' ? t('plan.pill_pro') : p.need_signup ? t('plan.pill_signup') : t('plan.pill_free');
  b.classList.toggle('upgrade', p.plan === 'free');
}

export function initPlan() {
  $('#plan-btn').addEventListener('click', openPlan);
  on('pro-required', openPlan);
  on('plan-changed', () => document.querySelectorAll('.protag').forEach(x => x.remove()));
  paintPill();
}

/** A small "Pro" label for headings of paid features. Empty when the user already has Pro. */
export const proTag = () => (isPro() ? null : el('button', { class: 'protag', type: 'button', onclick: openPlan }, t('plan.badge')));

export function openPlan() {
  const d = $('#plan-dialog'), p = plan();
  const status = p.plan === 'trial' ? t('plan.st_trial', { n: p.trial_left })
    : p.plan === 'taste' ? t('plan.st_taste', { n: p.uses_left, days: p.trial_days })
    : p.need_signup ? t('plan.st_signup', { days: p.trial_days }) : p.trial_used && p.plan === 'free' ? t('plan.st_trial_ended')
    : p.plan === 'pro' ? (p.configured ? t('plan.st_pro', { date: fmtDate(p.expires) }) : t('plan.st_off'))
    : p.key_state === 'expired' ? t('plan.st_expired', { date: fmtDate(p.expires) }) : t('plan.st_free');
  const buy = safe(p.buy_url);
  const err = el('p', { class: 'err', role: 'alert' });
  const input = el('input', { placeholder: t('plan.key_ph'), autocomplete: 'off', spellcheck: false, 'aria-label': t('plan.key_label') });
  const email = el('input', { type: 'email', placeholder: t('plan.email_ph'), autocomplete: 'email', 'aria-label': t('plan.signup_btn') });
  const signup = el('form', { class: 'keyrow', onsubmit: async e => {
    e.preventDefault();
    if (!email.value.trim()) return;
    serr.textContent = '';
    try { state.plan = await api('/api/plan', { action: 'signup', email: email.value.trim() }); paintPill(); emit('plan-changed'); d.close(); toast(t('plan.signed_up')); }
    catch (ex) { serr.textContent = ex.message; }
  } }, email, el('button', { class: 'btn primary', type: 'submit' }, t('plan.signup_btn')));
  const serr = el('p', { class: 'err', role: 'alert' });
  const form = el('form', { class: 'keyrow', onsubmit: async e => {
    e.preventDefault();
    if (!input.value.trim()) return;
    err.textContent = '';
    try { state.plan = await api('/api/plan', { action: 'activate', key: input.value.trim() }); paintPill(); emit('plan-changed'); d.close(); toast(t('plan.activated')); }
    catch (ex) { err.textContent = ex.message; }
  } }, input, el('button', { class: 'btn primary', type: 'submit' }, t('plan.activate')));
  d.replaceChildren(el('div', { class: 'sheet plan' },
    el('div', { class: 'sheet-h' }, el('div', { class: 'ai' }, icon('check')), el('div', {}, el('h3', {}, t('plan.title')), el('p', {}, status)),
      el('button', { class: 'x', 'aria-label': t('sheet.close'), onclick: () => d.close() }, icon('x'))),
    p.need_signup && el('div', { class: 'buy' }, signup, serr, el('p', { class: 'sd' }, t('plan.signup_note'))),
    el('ul', { class: 'perks' }, ['plan.f1', 'plan.f2', 'plan.f3', 'plan.f4', 'plan.f5'].map(k => el('li', {}, icon('check'), t(k)))),
    el('p', { class: 'sd' }, t('plan.free_note', { n: p.free_searches, m: p.free_max_leads })),
    p.configured && p.plan !== 'pro' && el('div', { class: 'buy' },
      el('div', { class: 'price' }, t('plan.price', { month: p.price_month, year: p.price_year })),
      buy ? el('a', { class: 'cta sm', href: buy, target: '_blank', rel: 'noopener noreferrer' }, t('plan.get'), icon('arrow')) : el('span', { class: 'sd' }, t('plan.not_for_sale')),
      buy && el('p', { class: 'sd' }, t('plan.after'))),
    p.configured && el('div', { class: 'keybox' }, el('label', { class: 'field' }, t('plan.key_label'), form), err,
      p.key_state === 'ok' && el('button', { class: 'btn ghost sm', onclick: async () => { state.plan = await api('/api/plan', { action: 'remove' }); paintPill(); emit('plan-changed'); d.close(); toast(t('plan.removed')); } }, t('plan.remove')))));
  d.showModal();
}
