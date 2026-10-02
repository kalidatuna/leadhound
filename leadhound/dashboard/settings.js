// Settings form and first-run wizard.
import { $, api, el, emit, state, toast, openModal, closeModal } from './util.js';
import { runQueue, rememberPlace } from './find.js';

const root = $('#view-settings');
let cfg = null;

const PRESETS = [
  ['Web developer', 'python, javascript, react, node, django, website, web app', 'I build fast, reliable websites and web apps for small businesses'],
  ['WordPress / Shopify', 'wordpress, woocommerce, shopify, elementor, php', 'I build and fix WordPress and Shopify stores that turn visitors into customers'],
  ['Mobile apps', 'flutter, react native, ios, android, swift, kotlin', 'I build mobile apps for iPhone and Android, from idea to the app stores'],
  ['Automation & data', 'python, automation, scraping, api, selenium, excel, data', 'I automate repetitive work and build data tools that save hours every week'],
  ['AI & chatbots', 'llm, chatbot, openai, rag, python, api', 'I build AI assistants and automations that handle real customer work'],
];

const list = v => (v || []).join(', ');
const field = (label, hint, input) => el('label', { class: 'f' }, label, hint && el('small', {}, hint), input);

export async function initSettings() {
  cfg = await api('/api/config');
  draw();
}

function draw() {
  const i = (id, type = 'text', extra = {}) => el('input', { id: 's-' + id, type, value: cfg[id] ?? '', ...extra });
  const keyNote = (name, ok) => el('span', { class: ok ? '' : 'mut' }, ok ? `${name} key found ✓` : `${name} key not set`);
  root.replaceChildren(el('div', { class: 'page' }, el('div', { class: 'wrap' },
    el('div', { class: 'card' }, el('h2', {}, 'About you'), el('p', {}, 'Used to rank leads and write your messages.'),
      el('div', { class: 'two' }, field('Your name', '', i('name')), field('Signature', 'How you sign messages, e.g. Name | website', i('signature'))),
      field('What you do, in one sentence', 'Appears in your messages', i('pitch')),
      field('Your skills', 'Comma separated. Leads that mention these rank higher.', i('skills', 'text', { value: list(cfg.skills) })),
      field('Words that mean "no thanks"', 'Leads with these are pushed down hard.', i('avoid', 'text', { value: list(cfg.avoid) })),
      el('div', { class: 'two' }, field('Smallest project (any currency)', '0 = no minimum', i('min_budget', 'number', { min: 0 })), field('Lowest hourly rate', '0 = no minimum', i('min_rate', 'number', { min: 0 }))),
      field('Portfolio link', 'Added to your messages', i('portfolio'))),
    el('div', { class: 'card' }, el('h2', {}, 'Where to look'),
      el('label', { class: 'check' }, el('input', { type: 'checkbox', id: 's-hn', checked: cfg.hn }), el('span', {}, 'Hacker News')),
      el('label', { class: 'check' }, el('input', { type: 'checkbox', id: 's-github', checked: cfg.github }), el('span', {}, 'GitHub issues')),
      field('Reddit communities', 'Comma separated, without r/', i('reddit_subreddits', 'text', { value: list(cfg.reddit_subreddits) })),
      el('div', { class: 'two' }, field('GitHub labels', '', i('github_labels', 'text', { value: list(cfg.github_labels) })), field('GitHub languages', 'Optional, e.g. python, javascript', i('github_languages', 'text', { value: list(cfg.github_languages) }))),
      field('Job board feeds (RSS)', 'One web address per line', el('textarea', { id: 's-rss_feeds', rows: 3, value: (cfg.rss_feeds || []).join('\n') })),
      field('Ignore posts older than', '', el('select', { id: 's-max_age_days' }, [7, 14, 21, 30, 60].map(d => el('option', { value: d, selected: cfg.max_age_days === d }, `${d} days`)))),
      el('p', { class: 'mut' }, keyNote('GitHub', cfg.keys.github), ' · set the GITHUB_TOKEN environment variable for higher limits')),
    el('div', { class: 'card' }, el('h2', {}, 'AI messages (optional)'),
      el('p', {}, 'Without this, messages come from smart templates. With it, an AI writes a draft from the lead\'s details. You still review and send it.'),
      field('Provider', '', el('select', { id: 's-llm_provider' }, [['none', 'None, use templates'], ['anthropic', 'Claude (Anthropic)'], ['openai', 'OpenAI or compatible (Ollama, ...)']].map(([v, l]) => el('option', { value: v, selected: cfg.llm_provider === v }, l)))),
      el('div', { class: 'two' }, field('Model', 'Needed for OpenAI/Ollama, e.g. llama3.1', i('llm_model')), field('Server address', 'Ollama: http://localhost:11434/v1', i('llm_base_url'))),
      el('p', { class: 'mut' }, keyNote('Anthropic', cfg.keys.anthropic), ' · ', keyNote('OpenAI', cfg.keys.openai), ' · keys are read from environment variables and never saved to disk')),
    el('div', { class: 'card' }, el('h2', {}, 'Local search defaults'),
      el('div', { class: 'two' }, field('Max businesses per search', '', i('max_businesses', 'number', { min: 1, max: 200 })), field('Default radius (meters)', '', i('radius_m', 'number', { min: 100, max: 20000 })))),
    el('div', { class: 'savebar' }, el('button', { class: 'btn primary', onclick: save }, 'Save settings'),
      el('span', { class: 'mut' }, 'Stored at ', state.meta.config_path)))));
}

function collect() {
  const v = id => $('#s-' + id).value;
  return {
    name: v('name'), signature: v('signature'), pitch: v('pitch'), skills: v('skills'), avoid: v('avoid'),
    min_budget: v('min_budget'), min_rate: v('min_rate'), portfolio: v('portfolio'),
    hn: $('#s-hn').checked, github: $('#s-github').checked, reddit_subreddits: v('reddit_subreddits'),
    github_labels: v('github_labels'), github_languages: v('github_languages'), rss_feeds: v('rss_feeds'),
    max_age_days: +v('max_age_days'), llm_provider: v('llm_provider'), llm_model: v('llm_model'), llm_base_url: v('llm_base_url'),
    max_businesses: +v('max_businesses'), radius_m: +v('radius_m'),
  };
}

async function save() {
  try {
    cfg = await api('/api/config', collect());
    state.meta = await api('/api/meta');
    draw();
    toast('Settings saved');
  } catch (e) { toast(e.message, 'err'); }
}

// ---- first-run wizard ----
export function showWizard() {
  const data = { name: '', skills: list(cfg.skills), pitch: cfg.pitch, city: '', cats: new Set(['restaurant', 'dentist']) };
  const step1 = () => {
    const presetBtns = PRESETS.map(([label, skills, pitch]) => el('button', { class: 'chip', type: 'button', onclick: () => { $('#w-skills').value = skills; $('#w-pitch').value = pitch; } }, label));
    openModal([
      el('div', { class: 'steps' }, 'Step 1 of 2'), el('h2', {}, 'Welcome to leadhound'),
      el('p', { class: 'mut' }, 'Tell it what you do, and it will find people and businesses that need exactly that.'),
      el('label', { class: 'f' }, 'What kind of work do you do? ', el('small', {}, 'Click one to fill the boxes below, then edit freely.')),
      el('div', { class: 'chips' }, presetBtns),
      field('Your name', '', el('input', { id: 'w-name', value: data.name })),
      field('Your skills', 'Comma separated', el('input', { id: 'w-skills', value: data.skills })),
      field('What you do, in one sentence', 'Used in your messages', el('input', { id: 'w-pitch', value: data.pitch })),
      el('div', { class: 'row', style: 'margin-top:18px' }, el('button', { class: 'btn primary', onclick: () => {
        data.name = $('#w-name').value.trim(); data.skills = $('#w-skills').value.trim(); data.pitch = $('#w-pitch').value.trim();
        if (!data.skills) return toast('Add at least one skill', 'err');
        step2();
      } }, 'Next'), el('button', { class: 'btn ghost', onclick: skip }, 'Skip setup')),
    ]);
  };
  const step2 = () => {
    const cats = ['restaurant', 'cafe', 'dentist', 'hairdresser', 'beauty', 'plumber', 'lawyer', 'hotel', 'gym', 'car_repair'];
    const draw = () => $('#w-cats').replaceChildren(...cats.map(c => el('button', { class: 'chip' + (data.cats.has(c) ? ' on' : ''), type: 'button', onclick: () => { data.cats.has(c) ? data.cats.delete(c) : data.cats.add(c); draw(); } }, c.replace(/_/g, ' '))));
    openModal([
      el('div', { class: 'steps' }, 'Step 2 of 2'), el('h2', {}, 'Find your first clients'),
      el('p', { class: 'mut' }, 'leadhound will look for people hiring right now. You can also search local businesses near you.'),
      field('Your city (optional)', 'Leave empty to only search for hiring posts', el('input', { id: 'w-city', placeholder: 'e.g. Tbilisi, Georgia' })),
      el('label', { class: 'f' }, 'Which businesses? '), el('div', { class: 'chips', id: 'w-cats' }),
      el('div', { class: 'row', style: 'margin-top:18px' }, el('button', { class: 'btn primary', onclick: finish }, 'Save and start searching'),
        el('button', { class: 'btn ghost', onclick: step1 }, 'Back')),
    ]);
    draw();
  };
  const persist = async extra => {
    cfg = await api('/api/config', { name: data.name, signature: data.name, skills: data.skills || list(cfg.skills), pitch: data.pitch || cfg.pitch, ...extra });
    state.meta = await api('/api/meta');
    draw();
  };
  const skip = async () => { try { await persist({}); } catch (e) { toast(e.message, 'err'); } closeModal(); };
  const finish = async () => {
    const city = $('#w-city').value.trim();
    try { await persist({ categories: [...data.cats] }); } catch (e) { return toast(e.message, 'err'); }
    closeModal();
    if (city) { rememberPlace(city); const p = $('#place'); if (p) p.value = city; }
    const jobs = [{ kind: 'scan', params: {} }];
    if (city && data.cats.size) jobs.push({ kind: 'local', params: { place: city, categories: [...data.cats], website: 'no', audit: false, limit: 40 } });
    runQueue(jobs);
    emit('goto', 'find');
  };
  step1();
}
