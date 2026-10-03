// Cloud mode sign-in. Kept separate from the app: no token exists until you are signed in.
const $ = id => document.getElementById(id);
let lang = 'en';
try { lang = localStorage.getItem('lh-lang') || (navigator.language || 'en').slice(0, 2); } catch { /* private mode */ }

async function texts() {
  for (const l of [lang, 'en']) {
    const r = await fetch(`/static/locales/${l}.json`).catch(() => null);
    if (r && r.ok) return r.json();
  }
  return {};
}

texts().then(T => {
  const t = (k, d) => T[k] || d;
  document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
  $('l-title').textContent = t('login.title', 'Sign in');
  $('l-label').textContent = t('login.password', 'Password');
  $('go').textContent = t('login.btn', 'Sign in');
  const go = async () => {
    $('go').disabled = true;
    const r = await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: $('pw').value }) });
    $('go').disabled = false;
    if (r.ok) return location.reload();
    const e = await r.json().catch(() => ({}));
    $('err').hidden = false;
    $('err').textContent = r.status === 401 ? t('login.wrong', 'Wrong password') : (e.error || 'Error');
  };
  $('go').addEventListener('click', go);
  $('pw').addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
});
