// AI through the user's own key: Gemini / Groq (free keys), Claude, OpenAI, OpenRouter or any OpenAI-compatible server.
import { settings } from './settings.js';

export const PROVIDERS = {
  'Google Gemini': { kind: 'openai', base: 'https://generativelanguage.googleapis.com/v1beta/openai', model: 'gemini-2.5-flash', keyUrl: 'https://aistudio.google.com/apikey' },
  Groq: { kind: 'openai', base: 'https://api.groq.com/openai/v1', model: 'llama-3.3-70b-versatile', keyUrl: 'https://console.groq.com/keys' },
  'Claude (Anthropic)': { kind: 'anthropic', base: 'https://api.anthropic.com/v1', model: 'claude-haiku-4-5', keyUrl: 'https://console.anthropic.com/settings/keys' },
  OpenAI: { kind: 'openai', base: 'https://api.openai.com/v1', model: 'gpt-4o-mini', keyUrl: 'https://platform.openai.com/api-keys' },
  OpenRouter: { kind: 'openai', base: 'https://openrouter.ai/api/v1', model: 'openai/gpt-4o-mini', keyUrl: 'https://openrouter.ai/keys' },
  'Custom (OpenAI-compatible)': { kind: 'openai', base: '', model: '', keyUrl: '' },
};

export function aiConfig() {
  const s = settings();
  const p = PROVIDERS[s.provider];
  if (!p) return null;
  const key = (s.keys || {})[s.provider] || '';
  const base = (s.provider.startsWith('Custom') ? s.baseUrl : p.base || '').replace(/\/$/, '');
  const model = s.model || p.model;
  if (!base || !model || (!key && !s.provider.startsWith('Custom'))) return null;
  return { kind: p.kind, base, model, key, provider: s.provider };
}
export const aiReady = () => aiConfig() !== null;

export async function chat(messages, { maxTokens = 900, temperature = 0.4 } = {}) {
  const c = aiConfig();
  if (!c) throw new Error('Add your AI key in Settings first (Google Gemini and Groq give free keys).');
  let res, data;
  try {
    if (c.kind === 'anthropic') {
      const system = messages.filter((m) => m.role === 'system').map((m) => m.content).join('\n\n');
      res = await fetch(`${c.base}/messages`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'x-api-key': c.key, 'anthropic-version': '2023-06-01',
          'anthropic-dangerous-direct-browser-access': 'true' },
        body: JSON.stringify({ model: c.model, max_tokens: maxTokens, temperature, system: system || undefined,
          messages: messages.filter((m) => m.role !== 'system') }),
      });
      data = await res.json();
      if (!res.ok) throw new Error(data?.error?.message || `HTTP ${res.status}`);
      return strip((data.content || []).map((b) => b.text || '').join(''));
    }
    const headers = { 'content-type': 'application/json' };
    if (c.key) headers.authorization = `Bearer ${c.key}`;
    res = await fetch(`${c.base}/chat/completions`, {
      method: 'POST', headers,
      body: JSON.stringify({ model: c.model, messages, max_tokens: maxTokens, temperature }),
    });
    data = await res.json();
    if (!res.ok) throw new Error(data?.error?.message || (Array.isArray(data) && data[0]?.error?.message) || `HTTP ${res.status}`);
    return strip(data.choices?.[0]?.message?.content || '');
  } catch (e) {
    if (e instanceof TypeError) throw new Error("Can't reach the AI - check your internet connection.");
    throw e;
  }
}

const strip = (t) => String(t).replace(/<think>[\s\S]*?<\/think>/g, '').trim();

function chunks(text, limit = 20000) {
  const out = [];
  let cur = '';
  for (const p of text.split(/\n+/)) {
    if (cur.length + p.length > limit && cur) { out.push(cur); cur = ''; }
    cur += `${p}\n`;
  }
  if (cur.trim()) out.push(cur);
  return out;
}

const SYS = 'You are an expert analyst who writes accurate, concise summaries. Never invent facts. Use Markdown.';

export async function summarize(text, { length = 'Medium', language = 'Same as document', focus = '' } = {}, onProgress) {
  if (!text.trim()) throw new Error('No text found. If it is a scan, run OCR first.');
  const shape = { Short: '5 bullet points', Medium: '8-12 bullet points', Detailed: 'a detailed structured summary with headings and bullet points' }[length];
  const lang = language.startsWith('Same') ? 'in the same language as the document' : `in ${language}`;
  const extra = focus ? ` Focus on: ${focus}.` : '';
  let body = text;
  const parts = chunks(text);
  if (parts.length > 1) {
    const notes = [];
    for (let k = 0; k < parts.length; k++) {
      onProgress && onProgress(k / parts.length, `Reading part ${k + 1} of ${parts.length}`);
      notes.push(await chat([{ role: 'system', content: SYS }, { role: 'user', content: `Write compact notes (key facts, numbers, names, conclusions) of this part of a document.${extra}\n\n---\n${parts[k]}` }], { maxTokens: 600, temperature: 0.2 }));
    }
    body = notes.join('\n\n');
  }
  onProgress && onProgress(0.9, 'Writing summary');
  return chat([{ role: 'system', content: SYS }, { role: 'user', content: `Summarize the document below as ${shape}, ${lang}. Start with a one-sentence overview in bold.${extra}\n\n---\n${body.slice(0, 24000)}` }], { maxTokens: length === 'Detailed' ? 1400 : 800, temperature: 0.3 });
}

export async function askDoc(text, question, history = []) {
  const doc = text.length > 24000 ? text.slice(0, 24000) : text;
  return chat([{ role: 'system', content: `Answer using only this document. If the answer isn't there, say so.\n\n${doc}` }, ...history.slice(-6), { role: 'user', content: question }], { maxTokens: 700, temperature: 0.2 });
}

export async function quiz(text, n = 5) {
  const r = await chat([{ role: 'system', content: 'You write multiple-choice quizzes. Reply ONLY with JSON.' },
    { role: 'user', content: `Make ${n} multiple-choice questions about this text. JSON array of {"question","options":[4 strings],"answer":index,"explanation"}.\n\n${text.slice(0, 16000)}` }], { maxTokens: 1500, temperature: 0.3 });
  const m = r.match(/\[[\s\S]*\]/);
  if (!m) throw new Error('The AI did not return a quiz. Try again.');
  return JSON.parse(m[0]);
}

export async function translate(text, language, onProgress) {
  const parts = chunks(text, 5000);
  const out = [];
  for (let k = 0; k < parts.length; k++) {
    onProgress && onProgress(k / parts.length, `Translating ${k + 1} of ${parts.length}`);
    out.push(await chat([{ role: 'system', content: `You are a professional translator. Translate into ${language}. Keep numbers, names, links and paragraph breaks. Reply with the translation only.` }, { role: 'user', content: parts[k] }], { maxTokens: 4000, temperature: 0.1 }));
  }
  return out.join('\n\n');
}

export const LANGUAGES = ['English', 'French', 'Spanish', 'Portuguese', 'German', 'Italian', 'Swahili', 'Luganda', 'Kinyarwanda',
  'Amharic', 'Somali', 'Yoruba', 'Hausa', 'Igbo', 'Zulu', 'Afrikaans', 'Arabic', 'Turkish', 'Russian', 'Hindi', 'Bengali',
  'Urdu', 'Chinese (Simplified)', 'Japanese', 'Korean', 'Vietnamese', 'Indonesian', 'Dutch', 'Polish', 'Greek'];
