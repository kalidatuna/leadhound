// Settings form, update panel and first-run wizard.
import { $, api, el, emit, state, toast, openModal, closeModal } from './util.js';
import { t, LANG, setLang, catName } from './i18n.js';
import { runQueue, rememberPlace, startJob } from './find.js';

const root = $('#view-settings');
const list = v => (v || []).join(', ');
const field = (label, hint, input) => el('label', { class: 'f' }, label, hint && el('small', {}, hint), input);
const options = (pairs, cur) => pairs.map(([v, l]) => el('option', { value: v, selected: String(v) === String(cur) }, l));

export async function initSettings() {
  draw();
}

function draw() {
  const cfg = state.cfg;
  const i = (id, type = 'text', extra = {}) => el('input', { id: 's-' + id, type, value: cfg[id] ?? '', ...extra });
  const check = (id, label, hint) => el('label', { class: 'check' }, el('input', { type: 'checkbox', id: 's-' + id, checked: !!cfg[id] }),
    el('span', {}, label, hint && el('small', {}, hint)));
  const key = (name, ok) => el('span', { class: ok ? '' : 'mut' }, ok ? t('set.key_found', { name }) : t('set.key_missing', { name }));
  const langs = Object.entries(state.meta.languages);
  root.replaceChildren(el('div', { class: 'page' }, el('div', { class: 'wrap' },
    el('div', { class: 'card' }, el('h2', {}, t('set.language')),
      el('div', { class: 'two' },
        field(t('set.app_language'), '', el('select', { onchange: e => setLang(e.target.value) }, options(langs, LANG))),
        field(t('set.draft_language'), t('set.draft_language_hint'), el('select', { id: 's-draft_language' }, options([['auto', t('set.draft_auto')], ...langs], cfg.draft_language))))),
    el('div', { class: 'card' }, el('h2', {}, t('set.about')), el('p', {}, t('set.about_desc')),
      el('div', { class: 'row' },
        el('select', { id: 's-profession', style: 'flex:1;min-width:200px' }, options([['', t('set.profession_none')], ...state.meta.professions.map(p => [p.id, t('prof.' + p.id)])], cfg.profession)),
        el('button', { class: 'btn', onclick: applyProfession }, t('set.apply_defaults'))),
      el('p', { class: 'mut sm' }, t('set.profession_hint')),
      el('div', { class: 'two' }, field(t('set.name'), '', i('name')), field(t('set.signature'), t('set.signature_hint'), i('signature'))),
      field(t('set.pitch'), t('set.pitch_hint'), i('pitch')),
      field(t('set.skills'), t('set.skills_hint'), i('skills', 'text', { value: list(cfg.skills) })),
      field(t('set.avoid'), t('set.avoid_hint'), i('avoid', 'text', { value: list(cfg.avoid) })),
      el('div', { class: 'three' },
        field(t('set.currency'), '', el('select', { id: 's-currency' }, options(state.meta.currencies.map(c => [c, c]), cfg.currency))),
        field(t('set.min_budget'), t('set.zero_hint'), i('min_budget', 'number', { min: 0 })),
        field(t('set.min_rate'), t('set.zero_hint'), i('min_rate', 'number', { min: 0 }))),
      field(t('set.portfolio'), t('set.portfolio_hint'), i('portfolio'))),
    el('div', { class: 'card' }, el('h2', {}, t('set.where')),
      check('freelancer', 'Freelancer.com', t('set.freelancer_hint')),
      field(t('set.freelancer_cats'), t('set.freelancer_cats_hint'), i('freelancer_categories', 'text', { value: list(cfg.freelancer_categories) })),
      field('Reddit', t('set.reddit_hint'), i('reddit_subreddits', 'text', { value: list(cfg.reddit_subreddits) })),
      check('hn', 'Hacker News', ''), check('github', 'GitHub', t('set.github_hint')),
      el('div', { class: 'two' }, field(t('set.gh_labels'), '', i('github_labels', 'text', { value: list(cfg.github_labels) })),
        field(t('set.gh_langs'), t('set.gh_langs_hint'), i('github_languages', 'text', { value: list(cfg.github_languages) }))),
      check('mastodon', 'Mastodon', t('set.mastodon_hint')),
      el('div', { class: 'two' }, field(t('set.mastodon_servers'), '', i('mastodon_instances', 'text', { value: list(cfg.mastodon_instances) })),
        field(t('set.mastodon_tags'), '', i('mastodon_tags', 'text', { value: list(cfg.mastodon_tags) }))),
      field(t('set.rss'), t('set.rss_hint'), el('textarea', { id: 's-rss_feeds', rows: 3, value: (cfg.rss_feeds || []).join('\n') })),
      el('div', { class: 'two' },
        field(t('set.max_age'), '', el('select', { id: 's-max_age_days' }, options([7, 14, 21, 30, 60].map(d => [d, t('set.days', { n: d })]), cfg.max_age_days))),
        field(t('set.auto'), t('set.auto_hint'), el('select', { id: 's-auto_scan_hours' }, options([[0, t('set.auto_off')], [6, t('set.auto_every', { n: 6 })], [12, t('set.auto_every', { n: 12 })], [24, t('set.auto_daily')]], cfg.auto_scan_hours)))),
      el('p', { class: 'mut' }, key('GitHub', cfg.keys.github), ' · ', t('set.gh_token_hint'))),
    el('div', { class: 'card' }, el('h2', {}, t('set.ai')), el('p', {}, t('set.ai_desc')),
      field(t('set.provider'), '', el('select', { id: 's-llm_provider' }, options([['none', t('prov.none')], ['anthropic', t('prov.anthropic')], ['openai', t('prov.openai')]], cfg.llm_provider))),
      el('div', { class: 'two' }, field(t('set.model'), t('set.model_hint'), i('llm_model')), field(t('set.server'), t('set.server_hint'), i('llm_base_url'))),
      el('p', { class: 'mut' }, key('Anthropic', cfg.keys.anthropic), ' · ', key('OpenAI', cfg.keys.openai), ' · ', t('set.keys_hint'))),
    el('div', { class: 'card' }, el('h2', {}, t('set.local')),
      el('div', { class: 'two' }, field(t('set.max_biz'), '', i('max_businesses', 'number', { min: 1, max: 300 })), field(t('set.radius'), '', i('radius_m', 'number', { min: 100, max: 20000 })))),
    updateCard(),
    el('div', { class: 'savebar' }, el('button', { class: 'btn primary', onclick: save }, t('set.save')),
      state.meta.cloud && el('button', { class: 'btn', onclick: () => api('/api/logout', {}).finally(() => location.reload()) }, t('set.logout')),
      el('span', { class: 'mut' }, t('set.stored_at'), ' ', state.meta.config_path)))));
}

function collect() {
  const v = id => $('#s-' + id).value;
  const c = id => $('#s-' + id).checked;
  return {
    name: v('name'), signature: v('signature'), pitch: v('pitch'), skills: v('skills'), avoid: v('avoid'), profession: v('profession'),
    currency: v('currency'), min_budget: v('min_budget'), min_rate: v('min_rate'), portfolio: v('portfolio'), draft_language: v('draft_language'),
    freelancer: c('freelancer'), freelancer_categories: v('freelancer_categories'), reddit_subreddits: v('reddit_subreddits'),
    hn: c('hn'), github: c('github'), github_labels: v('github_labels'), github_languages: v('github_languages'),
    mastodon: c('mastodon'), mastodon_instances: v('mastodon_instances'), mastodon_tags: v('mastodon_tags'), rss_feeds: v('rss_feeds'),
    max_age_days: +v('max_age_days'), auto_scan_hours: +v('auto_scan_hours'), llm_provider: v('llm_provider'), llm_model: v('llm_model'),
    llm_base_url: v('llm_base_url'), max_businesses: +v('max_businesses'), radius_m: +v('radius_m'),
  };
}

async function persist(body) {
  state.cfg = await api('/api/config', body);
  state.meta = await api('/api/meta');
  draw();
}

async function save() {
  try { await persist(collect()); emit('profile-changed'); toast(t('set.saved')); } catch (e) { toast(e.message, 'err'); }
}

async function applyProfession() {
  const pid = $('#s-profession').value;
  if (!pid) return;
  try { await persist({ ...collect(), profession_defaults: pid }); emit('profile-changed'); toast(t('set.applied', { name: t('prof.' + pid) })); } catch (e) { toast(e.message, 'err'); }
}

// ---- updates ----
function updateCard() {
  const box = el('div', { class: 'card', id: 'upd' }, el('h2', {}, t('set.update')), el('p', { class: 'mut' }, t('set.version', { v: state.meta.version })));
  const status = el('div', { class: 'row' }, el('button', { class: 'btn', onclick: () => checkUpdate(status, true) }, t('set.check_updates')));
  box.append(status);
  checkUpdate(status, false);
  return box;
}

export async function checkUpdate(target, force) {
  let u;
  try { u = await api('/api/update' + (force ? '?force=1' : '')); } catch { return null; }
  if (!target) return u;
  if (!u.newer) { target.replaceChildren(el('span', { class: 'mut' }, t('upd.latest')), el('button', { class: 'btn sm', onclick: () => checkUpdate(target, true) }, t('set.check_updates'))); return u; }
  const acts = [el('b', {}, t('upd.available', { v: u.latest }))];
  if (u.mode === 'pip') acts.push(el('button', { class: 'btn primary', onclick: () => installUpdate(target) }, t('upd.install')));
  else if (u.mode === 'cloud') acts.push(el('span', { class: 'mut' }, t('upd.cloud')));
  else acts.push(el('a', { class: 'btn primary', href: u.url, target: '_blank', rel: 'noopener noreferrer' }, t('upd.download')));
  target.replaceChildren(...acts);
  return u;
}

async function installUpdate(target) {
  target.replaceChildren(el('span', {}, el('span', { class: 'spin' }), ' ', t('upd.installing')));
  if (!await startJob('update', {})) return;
  const off = setInterval(async () => {
    const j = await api('/api/jobs/current').catch(() => null);
    if (!j || j.status === 'running') return;
    clearInterval(off);
    if (j.status !== 'done') { target.replaceChildren(el('span', { class: 'bad' }, t('upd.failed')), el('pre', { class: 'log' }, j.log.slice(-8).join('\n'))); return; }
    target.replaceChildren(el('span', {}, t('upd.restarting')));
    await api('/api/restart', {}).catch(() => {});
    const wait = setInterval(() => fetch('/', { cache: 'no-store' }).then(r => { if (r.ok) { clearInterval(wait); location.reload(); } }).catch(() => {}), 1000);
  }, 1000);
}

// ---- first-run wizard ----
export function showWizard() {
  const data = { profession: '', name: '', city: '', cats: new Set() };
  const step1 = () => {
    const cards = el('div', { class: 'profs' }, state.meta.professions.map(p => el('button', { class: 'prof' + (data.profession === p.id ? ' on' : ''), type: 'button',
      onclick: () => { data.profession = p.id; data.name = $('#w-name').value; data.cats = new Set(p.categories); step1(); } }, t('prof.' + p.id))));
    openModal([
      el('div', { class: 'steps' }, t('wiz.step', { n: 1 })), el('h2', {}, t('wiz.welcome')), el('p', { class: 'mut' }, t('wiz.welcome_text')),
      el('div', { class: 'row', style: 'margin:6px 0 2px' }, el('span', { class: 'mut' }, t('set.app_language')),
        el('select', { onchange: e => setLang(e.target.value) }, options(Object.entries(state.meta.languages), LANG))),
      el('label', { class: 'f' }, t('wiz.what')), cards,
      field(t('wiz.name'), '', el('input', { id: 'w-name', value: data.name })),
      el('div', { class: 'row', style: 'margin-top:18px' }, el('button', { class: 'btn primary', onclick: () => {
        if (!data.profession) return toast(t('wiz.pick_one'), 'err');
        data.name = $('#w-name').value.trim(); step2();
      } }, t('wiz.next')), el('button', { class: 'btn ghost', onclick: skip }, t('wiz.skip'))),
    ]);
  };
  const step2 = () => {
    const prof = state.meta.professions.find(p => p.id === data.profession);
    const cats = [...new Set([...(prof?.categories || []), 'restaurant', 'cafe', 'dentist', 'hairdresser', 'gym', 'hotel'])].slice(0, 12);
    const draw = () => $('#w-cats').replaceChildren(...cats.map(c => el('button', { class: 'chip' + (data.cats.has(c) ? ' on' : ''), type: 'button',
      onclick: () => { data.cats.has(c) ? data.cats.delete(c) : data.cats.add(c); draw(); } }, catName(c))));
    openModal([
      el('div', { class: 'steps' }, t('wiz.step', { n: 2 })), el('h2', {}, t('wiz.first')), el('p', { class: 'mut' }, t('wiz.first_text')),
      field(t('wiz.city'), t('wiz.city_hint'), el('input', { id: 'w-city', placeholder: t('find.city_ph') })),
      el('label', { class: 'f' }, t('wiz.which_biz')), el('div', { class: 'chips', id: 'w-cats' }),
      el('div', { class: 'row', style: 'margin-top:18px' }, el('button', { class: 'btn primary', onclick: finish }, t('wiz.start')),
        el('button', { class: 'btn ghost', onclick: step1 }, t('wiz.back'))),
    ]);
    draw();
  };
  const save = extra => persist({ name: data.name, signature: data.name, ...(data.profession ? { profession_defaults: data.profession } : {}), ...extra });
  const skip = async () => { try { await save({}); } catch (e) { toast(e.message, 'err'); } closeModal(); emit('profile-changed'); };
  const finish = async () => {
    const city = $('#w-city').value.trim();
    try { await save(data.cats.size ? { categories: [...data.cats] } : {}); } catch (e) { return toast(e.message, 'err'); }
    closeModal();
    emit('profile-changed');
    if (city) rememberPlace(city);
    const jobs = [{ kind: 'scan', params: {} }];
    if (city && data.cats.size) jobs.push({ kind: 'local', params: { place: city, categories: [...data.cats], website: 'no', audit: false, limit: 40 } });
    runQueue(jobs);
  };
  step1();
}
