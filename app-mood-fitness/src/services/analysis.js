import { getFusionOrigin } from './fusionOrigin';

const FUSION = () => getFusionOrigin();
const EMOTION_V2_URL = () => `${FUSION()}/analyze-emotion-v2`;

const TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS || 600000);
const REQUEST_MS = Number.isFinite(TIMEOUT_MS) ? TIMEOUT_MS : 600000;

/** UI (turkish|english) → fusion `speech_language` (tr|en) */
export function normalizeSpeechLanguageForStt(raw) {
  const s = String(raw ?? 'turkish').trim().toLowerCase();
  const map = {
    turkish: 'tr',
    english: 'en',
    tr: 'tr',
    en: 'en',
  };
  return map[s] || 'tr';
}

function formatFetchError(err) {
  if (!err) return 'Unknown error';
  return err.message || String(err);
}

const extFromMime = (mime) => {
  const m = (mime || '').toLowerCase();
  if (m.includes('webm')) return 'webm';
  if (m.includes('wav')) return 'wav';
  if (m.includes('mpeg') || m.includes('mp3')) return 'mp3';
  if (m.includes('mp4')) return 'm4a';
  if (m.includes('ogg')) return 'ogg';
  return 'webm';
};

async function postFormJson(url, formData) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_MS);
  try {
    const res = await fetch(url, {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    });
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      throw new Error(text?.slice(0, 500) || res.statusText || 'Geçersiz JSON yanıt');
    }
    if (!res.ok) {
      const detail = data && typeof data === 'object' && 'detail' in data ? data.detail : data;
      const msg =
        typeof detail === 'string' ? detail : detail != null ? JSON.stringify(detail) : res.statusText;
      throw new Error(msg);
    }
    return data;
  } catch (e) {
    if (e.name === 'AbortError') {
      throw new Error(`İstek zaman aşımı (${REQUEST_MS} ms)`);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export async function analyzeEmotionV2(audioBlob, languageCode) {
  const formData = new FormData();
  const name =
    audioBlob && typeof audioBlob.name === 'string' && audioBlob.name.length > 0
      ? audioBlob.name
      : `recording.${extFromMime(audioBlob?.type)}`;
  formData.append('file', audioBlob, name);
  formData.append('speech_language', normalizeSpeechLanguageForStt(languageCode));

  return postFormJson(EMOTION_V2_URL(), formData);
}

/** @deprecated use analyzeEmotionV2 — tek uç nokta STT + emosyon v2 döner */
export async function runFullAnalysis(audioBlob, sttLanguage) {
  try {
    const result = await analyzeEmotionV2(audioBlob, sttLanguage);
    return {
      emotionV2: result,
      emotionV2Error: null,
    };
  } catch (err) {
    return {
      emotionV2: null,
      emotionV2Error: formatFetchError(err),
    };
  }
}
