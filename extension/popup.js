// Opens the leadhound app (running on this computer) with the current page filled in. The app asks you to confirm.
const portBox = document.getElementById('port');
let tab = null;

chrome.storage.local.get({ port: 8787 }, v => { portBox.value = v.port; });
portBox.addEventListener('change', () => {
  const p = Math.max(1, Math.min(65535, parseInt(portBox.value, 10) || 8787));
  portBox.value = p;
  chrome.storage.local.set({ port: p });
});

async function selectedText() {
  try {
    const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => String(window.getSelection() || '') });
    return (res && res.result || '').trim().slice(0, 4000);
  } catch { return ''; }  // pages the browser does not let extensions read (settings, stores)
}

async function open(route) {
  if (!tab || !/^https?:\/\//.test(tab.url || '')) return;
  const q = new URLSearchParams({ url: tab.url });
  if (route === 'add') {
    q.set('title', (tab.title || '').slice(0, 200));
    const text = await selectedText();
    if (text) q.set('text', text);
  }
  chrome.tabs.create({ url: `http://127.0.0.1:${parseInt(portBox.value, 10) || 8787}/#${route}?${q}` });
  window.close();
}

chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
  tab = tabs[0];
  const ok = tab && /^https?:\/\//.test(tab.url || '');
  document.getElementById('page').textContent = ok ? (tab.title || tab.url) : 'Open a web page first.';
  document.getElementById('save').disabled = document.getElementById('check').disabled = !ok;
});
document.getElementById('save').addEventListener('click', () => open('add'));
document.getElementById('check').addEventListener('click', () => open('check'));
