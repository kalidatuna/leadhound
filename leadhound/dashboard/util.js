// Shared helpers: API calls, tiny DOM builder, toasts, clipboard, event bus.
export const TOKEN = document.querySelector('meta[name="lh-token"]').content;
export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];
export const state = { meta: null };

// localStorage that never throws (private mode, blocked storage)
export const store = {
  get: k => { try { return localStorage.getItem(k) || ''; } catch { return ''; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* ignore */ } },
};

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
  if (r.status === 401 && path !== '/api/login') { location.reload(); throw new Error('signed out'); }
  const isJson = (r.headers.get('content-type') || '').includes('json');
  const data = isJson ? await r.json() : await r.blob();
  if (r.status === 402) { emit('pro-required'); const e = new Error(''); e.status = 402; throw e; }  // the plan dialog explains it
  if (!r.ok) { const e = new Error((isJson && data.error) || `Request failed (${r.status})`); e.status = r.status; throw e; }
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
  if (!msg) return;  // empty message: the error was already shown some other way
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


export const scoreClass = s => (s >= 60 ? 'hi' : s >= 35 ? 'mid' : 'lo');
export const safeUrl = u => (/^https?:\/\//i.test(u || '') ? u : null);
export const BRANDS = { reddit: 'Reddit', hn: 'Hacker News', github: 'GitHub', freelancer: 'Freelancer.com', mastodon: 'Mastodon' };

export function openModal(content) {
  const m = $('#modal');
  m.textContent = '';
  m.append(el('div', { class: 'dialog', role: 'dialog' }, content));
  m.hidden = false;
}
export function closeModal() { $('#modal').hidden = true; $('#modal').textContent = ''; }
export const modalOpen = () => !$('#modal').hidden;
