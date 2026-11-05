// Runs before the page draws so a chosen light or dark theme never flashes. "auto" follows the computer.
try { const t = localStorage.getItem('lh-theme'); if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t; } catch { /* storage blocked */ }
