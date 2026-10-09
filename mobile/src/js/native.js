// Native features through Capacitor plugins, with browser fallbacks (so the app also runs in a browser).
import { Capacitor, registerPlugin } from '@capacitor/core';

export const isNative = () => !!(Capacitor && Capacitor.isNativePlatform && Capacitor.isNativePlatform());
const NativeTTS = registerPlugin('TextToSpeech');
const Filesystem = registerPlugin('Filesystem');
const Share = registerPlugin('Share');

// ------------------------------------------------------------------ text to speech
export const tts = {
  async voices() {
    if (isNative()) {
      try { return (await NativeTTS.getSupportedVoices()).voices || []; } catch { return []; }
    }
    const synth = window.speechSynthesis;
    if (!synth) return [];
    let v = synth.getVoices();
    if (!v.length) {
      await new Promise((r) => { synth.onvoiceschanged = r; setTimeout(r, 1200); });
      v = synth.getVoices();
    }
    return v.map((x) => ({ name: x.name, lang: x.lang, voiceURI: x.voiceURI, default: x.default }));
  },
  /** Resolves when the text has been spoken (or stop() was called). */
  async speak(text, { rate = 1, pitch = 1, voice = null, lang = undefined } = {}) {
    if (isNative()) {
      const opts = { text, rate, pitch, volume: 1, category: 'playback' };
      if (lang) opts.lang = lang;
      if (voice !== null && voice !== undefined && voice >= 0) opts.voice = voice;
      return NativeTTS.speak(opts);
    }
    const synth = window.speechSynthesis;
    if (!synth) throw new Error('This browser cannot speak text');
    return new Promise((resolve) => {
      const u = new SpeechSynthesisUtterance(text);
      u.rate = rate; u.pitch = pitch;
      const vs = synth.getVoices();
      if (voice !== null && voice >= 0 && vs[voice]) u.voice = vs[voice];
      else if (lang) u.lang = lang;
      u.onend = u.onerror = () => resolve();
      synth.speak(u);
    });
  },
  async stop() {
    if (isNative()) { try { await NativeTTS.stop(); } catch { /* ignore */ } return; }
    window.speechSynthesis && window.speechSynthesis.cancel();
  },
  async installVoices() {
    if (isNative()) { try { await NativeTTS.openInstall(); } catch { /* ignore */ } }
  },
};

// ------------------------------------------------------------------ files
export function bytesToBase64(bytes) {
  let s = '';
  const CH = 0x8000;
  for (let i = 0; i < bytes.length; i += CH) s += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
  return btoa(s);
}

/** Save a file. Android: Documents/RushSuite/<name> (falls back to app storage). Browser: download. */
export async function saveFile(name, bytes, mime = 'application/octet-stream') {
  if (!(bytes instanceof Uint8Array)) bytes = new Uint8Array(bytes);
  if (isNative()) {
    const data = bytesToBase64(bytes);
    for (const directory of ['DOCUMENTS', 'EXTERNAL', 'DATA']) {
      try {
        const r = await Filesystem.writeFile({ path: `RushSuite/${name}`, data, directory, recursive: true });
        return { uri: r.uri, where: directory === 'DOCUMENTS' ? `Documents/RushSuite/${name}` : name };
      } catch { /* try the next location */ }
    }
    throw new Error('Could not save the file on this phone');
  }
  const url = URL.createObjectURL(new Blob([bytes], { type: mime }));
  const a = document.createElement('a');
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
  window.__lastSaved = (window.__lastSaved || []).concat([{ name, size: bytes.length }]);
  return { uri: url, where: `Downloads/${name}` };
}

export async function shareFile(uri, title = 'Share') {
  if (isNative()) {
    try { await Share.share({ title, url: uri, dialogTitle: title }); } catch { /* cancelled */ }
    return;
  }
  window.open(uri, '_blank');
}

export async function shareText(text, title = 'Share') {
  if (isNative()) { try { await Share.share({ title, text, dialogTitle: title }); } catch { /* cancelled */ } return; }
  if (navigator.share) { try { await navigator.share({ title, text }); } catch { /* cancelled */ } return; }
  await navigator.clipboard?.writeText(text);
}
