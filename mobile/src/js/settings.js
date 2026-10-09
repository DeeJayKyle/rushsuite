// App settings (stored on the phone only).
const KEY = 'rushsuite.settings';
const DEFAULTS = {
  provider: 'Google Gemini', keys: {}, model: '', baseUrl: '',
  voice: -1, rate: 1.0, pitch: 1.0, readerFont: 19, readerTheme: 'Dark',
};
let cache = null;
export function settings() {
  if (!cache) {
    try { cache = { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || '{}') }; } catch { cache = { ...DEFAULTS }; }
  }
  return cache;
}
export function saveSettings(patch = {}) {
  Object.assign(settings(), patch);
  try { localStorage.setItem(KEY, JSON.stringify(cache)); } catch { /* storage full */ }
}
