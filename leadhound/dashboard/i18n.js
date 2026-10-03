// Interface translations. UI text lives in /static/locales/<lang>.json; score reasons and website
// findings come from the server catalog (/api/i18n/<lang>) so drafts and app use the same words.
import { api, store } from './util.js';

export let LANG = 'en';
let EN = {}, UI = {}, SERVER = {};

async function json(url) {
  const r = await fetch(url);
  return r.ok ? r.json() : {};
}

export async function initI18n(languages) {
  const saved = store.get('lh-lang');
  const nav = (navigator.language || 'en').slice(0, 2).toLowerCase();
  LANG = languages[saved] ? saved : languages[nav] ? nav : 'en';
  [EN, UI, SERVER] = await Promise.all([json('/static/locales/en.json'),
    LANG === 'en' ? {} : json(`/static/locales/${LANG}.json`), api(`/api/i18n/${LANG}`).catch(() => ({}))]);
  document.documentElement.lang = LANG;
  document.documentElement.dir = LANG === 'ar' ? 'rtl' : 'ltr';
}

export function t(key, params = {}) {
  let s = UI[key] ?? EN[key] ?? SERVER[key] ?? key;
  for (const [k, v] of Object.entries(params)) s = s.split(`{${k}}`).join(String(v));
  return s;
}

export const has = key => key in UI || key in EN || key in SERVER;

export function setLang(code) {
  store.set('lh-lang', code);
  location.reload();
}

// One score reason: [points, key, args] -> "+15 budget stated: $500"
export function whyText(item) {
  const [pts, key, args = {}] = item;
  let text = t('why.' + key, args);
  if (key === 'critical' && args.codes) text += ': ' + args.codes.split(',').map(c => t('t.' + c)).join(', ');
  return pts == null ? text : `${pts >= 0 ? '+' : ''}${pts} ${text}`;
}

// A website finding in the interface language (falls back to the English text stored with it)
export function findingText(f) {
  const title = has('t.' + f.code) ? t('t.' + f.code, f.args || {}) : f.title;
  const pitch = has('f.' + f.code) ? t('f.' + f.code, f.args || {}) : f.pitch;
  return { title, pitch };
}

export const catName = c => (has('cat.' + c) ? t('cat.' + c) : String(c).replace(/_/g, ' '));
