const TRANSCRIBE_URL =
  import.meta.env.VITE_TRANSCRIBE_URL || 'http://localhost:8001/transcribe';
const VOICE_EMOTION_URL =
  import.meta.env.VITE_VOICE_EMOTION_URL || 'http://localhost:8002/analyze-audio';
const MENTAL_FITNESS_URL =
  import.meta.env.VITE_MENTAL_FITNESS_URL || 'http://localhost:8005/analyze-mental';
const TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS || 600000);

const REQUEST_MS = Number.isFinite(TIMEOUT_MS) ? TIMEOUT_MS : 600000;

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

/**
 * POST multipart/form-data; JSON body. Tarayıcı boundary’yi kendisi ekler (Content-Type elle verilmez).
 */
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

/**
 * Whisper / backend expects: turkish | english | arabic (or tr|en|ar via mapping on server)
 */
export async function transcribeAudio(audioBlob, languageCode) {
  const formData = new FormData();
  const name =
    audioBlob && typeof audioBlob.name === 'string' && audioBlob.name.length > 0
      ? audioBlob.name
      : `recording.${extFromMime(audioBlob?.type)}`;
  formData.append('file', audioBlob, name);
  formData.append('language', languageCode);

  return postFormJson(TRANSCRIBE_URL, formData);
}

export async function analyzeVoiceEmotion(audioBlob) {
  const formData = new FormData();
  const name =
    audioBlob && typeof audioBlob.name === 'string' && audioBlob.name.length > 0
      ? audioBlob.name
      : `recording.${extFromMime(audioBlob?.type)}`;
  formData.append('file', audioBlob, name);

  return postFormJson(VOICE_EMOTION_URL, formData);
}

export async function analyzeMentalFitness(audioBlob) {
  const formData = new FormData();
  const name =
    audioBlob && typeof audioBlob.name === 'string' && audioBlob.name.length > 0
      ? audioBlob.name
      : `recording.${extFromMime(audioBlob?.type)}`;
  formData.append('file', audioBlob, name);

  return postFormJson(MENTAL_FITNESS_URL, formData);
}

export async function runFullAnalysis(audioBlob, sttLanguage) {
  const [stt, emotion, mental] = await Promise.allSettled([
    transcribeAudio(audioBlob, sttLanguage),
    analyzeVoiceEmotion(audioBlob),
    analyzeMentalFitness(audioBlob),
  ]);

  return {
    stt: stt.status === 'fulfilled' ? stt.value : null,
    sttError: stt.status === 'rejected' ? formatFetchError(stt.reason) : null,
    emotion: emotion.status === 'fulfilled' ? emotion.value : null,
    emotionError: emotion.status === 'rejected' ? formatFetchError(emotion.reason) : null,
    mental: mental.status === 'fulfilled' ? mental.value : null,
    mentalError: mental.status === 'rejected' ? formatFetchError(mental.reason) : null,
  };
}
