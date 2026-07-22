import { getFusionOrigin } from './fusionOrigin';

const FUSION = () => getFusionOrigin();
const TRANSCRIBE_URL = () => `${FUSION()}/analyze-voice-to-text`;
const VOICE_EMOTION_URL = () => `${FUSION()}/analyze-voice-sentiment`;

const TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS || 600000);
const REQUEST_MS = Number.isFinite(TIMEOUT_MS) ? TIMEOUT_MS : 600000;

/** UI (turkish|english|arabic|auto) → fusion STT Form `speech_language` (tr|en|ar|auto) */
export function normalizeSpeechLanguageForStt(raw) {
  const s = String(raw ?? 'turkish').trim().toLowerCase();
  const map = {
    turkish: 'tr',
    english: 'en',
    arabic: 'ar',
    auto: 'auto',
    tr: 'tr',
    en: 'en',
    ar: 'ar',
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

export async function transcribeAudio(audioBlob, languageCode) {
  const formData = new FormData();
  const name =
    audioBlob && typeof audioBlob.name === 'string' && audioBlob.name.length > 0
      ? audioBlob.name
      : `recording.${extFromMime(audioBlob?.type)}`;
  formData.append('file', audioBlob, name);
  formData.append('speech_language', normalizeSpeechLanguageForStt(languageCode));

  return postFormJson(TRANSCRIBE_URL(), formData);
}

export async function analyzeVoiceEmotion(audioBlob) {
  const formData = new FormData();
  const name =
    audioBlob && typeof audioBlob.name === 'string' && audioBlob.name.length > 0
      ? audioBlob.name
      : `recording.${extFromMime(audioBlob?.type)}`;
  formData.append('file', audioBlob, name);

  return postFormJson(VOICE_EMOTION_URL(), formData);
}

export async function runFullAnalysis(audioBlob, sttLanguage) {
  const [sttResult, emotionResult] = await Promise.allSettled([
    transcribeAudio(audioBlob, sttLanguage),
    analyzeVoiceEmotion(audioBlob),
  ]);

  return {
    stt: sttResult.status === 'fulfilled' ? sttResult.value : null,
    sttError: sttResult.status === 'rejected' ? formatFetchError(sttResult.reason) : null,
    emotion: emotionResult.status === 'fulfilled' ? emotionResult.value : null,
    emotionError:
      emotionResult.status === 'rejected' ? formatFetchError(emotionResult.reason) : null,
  };
}
