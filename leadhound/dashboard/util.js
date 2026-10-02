// Shared helpers: API calls, tiny DOM builder, toasts, clipboard, event bus.
export const TOKEN = document.querySelector('meta[name="lh-token"]').content;
export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];
export const state = { meta: null };

const bus = new EventTarget();
export const emit = (name, detail) => bus.dispatchEvent(new CustomEvent(name, { detail }));
export const on = (name, fn) => bus.addEventListener(name, e => fn(e.detail));

export async function api(path, body) {
  const opt = { headers: { 'X-Leadhound-Token': TOKEN } };
  if (body !== undefined) {
    opt.method = 'POST';
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(path, opt);
  const isJson = (r.headers.get('content-type') || '').includes('json');
  const data = isJson ? await r.json() : await r.blob();
  if (!r.ok) throw new Error((isJson && data.error) || `Request failed (${r.status})`);
  return data;
}

// el('div', {class:'x', onclick:fn, disabled:true}, 'text', childNode, [more]) -> element. Text is never parsed as HTML.
export function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else if (k === 'value') e.value = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k in e && typeof v !== 'string') e[k] = v;
    else e.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    e.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return e;
}

export function toast(msg, kind = '', action = null) {
  const t = el('div', { class: 'toast ' + kind }, msg);
  if (action) t.append(el('button', { onclick: () => { action.fn(); t.remove(); } }, action.label));
  $('#toasts').append(t);
  setTimeout(() => t.remove(), action ? 7000 : 3500);
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = el('textarea', { value: text });
    document.body.append(ta);
    ta.select();
    const ok = document.execCommand('copy');
    ta.remove();
    return ok;
  }
}

export function ageText(ts) {
  if (!ts) return '';
  const h = (Date.now() / 1000 - ts) / 3600;
  if (h < 1) return 'just now';
  return h < 48 ? `${Math.round(h)}h ago` : `${Math.round(h / 24)}d ago`;
}

export const scoreClass = s => (s >= 60 ? 'hi' : s >= 35 ? 'mid' : 'lo');
export const safeUrl = u => (/^https?:\/\//i.test(u || '') ? u : null);
export const pretty = s => String(s).replace(/_/g, ' ');
export const SOURCE_NAMES = { reddit: 'Reddit', hn: 'Hacker News', github: 'GitHub', rss: 'Job board', osm: 'Local business', manual: 'Website check' };

export function openModal(content) {
  const m = $('#modal');
  m.textContent = '';
  m.append(el('div', { class: 'dialog', role: 'dialog' }, content));
  m.hidden = false;
}
export function closeModal() { $('#modal').hidden = true; $('#modal').textContent = ''; }
export const modalOpen = () => !$('#modal').hidden;
