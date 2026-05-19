import { getFusionOrigin } from './fusionOrigin';

/** Fusion proxy kökü; /analyze-fused burada yok — sadece mood-fitness için gerekli uçlar. */
const FUSION = () => getFusionOrigin();
const TRANSCRIBE_URL = () => `${FUSION()}/analyze-voice-to-text`;
const VOICE_EMOTION_URL = () => `${FUSION()}/analyze-voice-sentiment`;
const MENTAL_FITNESS_URL = () => `${FUSION()}/analyze-mental-fitness`;
const VALIDATE_TRANSCRIPT_URL = () =>
  `${FUSION()}/analyze-mental-fitness/validate-transcript-meaning`;

const TRANSCRIPT_VALIDATE_MS = Number(import.meta.env.VITE_TRANSCRIPT_VALIDATE_MS || 90000);
const TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS || 600000);

const REQUEST_MS = Number.isFinite(TIMEOUT_MS) ? TIMEOUT_MS : 600000;
const VALIDATION_MS = Number.isFinite(TRANSCRIPT_VALIDATE_MS) ? TRANSCRIPT_VALIDATE_MS : 90000;

/** UI (turkish|english|arabic) → fusion STT Form `speech_language` (tr|en|ar) */
export function normalizeSpeechLanguageForStt(raw) {
  const s = String(raw ?? 'turkish').trim().toLowerCase();
  const map = { turkish: 'tr', english: 'en', arabic: 'ar', tr: 'tr', en: 'en', ar: 'ar' };
  return map[s] || 'tr';
}

/** UI / validate JSON `language` — mental_fitness bekler: turkish | english | arabic */
export function normalizeLanguageForValidate(raw) {
  const s = String(raw ?? 'turkish').trim().toLowerCase();
  const map = {
    turkish: 'turkish',
    english: 'english',
    arabic: 'arabic',
    tr: 'turkish',
    en: 'english',
    ar: 'arabic',
  };
  return map[s] || 'turkish';
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

async function postJson(url, jsonBody, timeoutMs = VALIDATION_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(jsonBody),
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
      throw new Error(`Transkript doğrulama zaman aşımı (${timeoutMs} ms)`);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

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

export async function analyzeMentalFitness(audioBlob) {
  const formData = new FormData();
  const name =
    audioBlob && typeof audioBlob.name === 'string' && audioBlob.name.length > 0
      ? audioBlob.name
      : `recording.${extFromMime(audioBlob?.type)}`;
  formData.append('file', audioBlob, name);

  return postFormJson(MENTAL_FITNESS_URL(), formData);
}

/** Transkript seçilen dilde anlamlı mı (fusion → mental_fitness validate). */
export async function validateTranscriptForMental(text, languageCode) {
  return postJson(VALIDATE_TRANSCRIPT_URL(), {
    text: text ?? '',
    language: normalizeLanguageForValidate(languageCode),
  });
}

function formatValidationFailure(reason) {
  const r = (reason || '').trim();
  const byCode = {
    high_repetition_low_word_diversity:
      'Metin çoğunlukla aynı kelimelerin tekrarından oluşuyor; mental fitness çalıştırılmadı.',
    single_word_dominated:
      'Metinde tek bir kelime belirgin şekilde tekrarlanıyor; mental fitness çalıştırılmadı.',
    tiny_phrase_looped:
      'Metin aynı kısa ifadenin üst üste tekrarı gibi; mental fitness çalıştırılmadı.',
    bigram_loop_low_diversity:
      'Metin aynı iki kelimelik kalıbın sık döngüsüne sıkışmış; mental fitness çalıştırılmadı.',
  };
  if (byCode[r]) return byCode[r];
  if (/^[a-z][a-z0-9_]*$/i.test(r)) return `${r}. Mental fitness bu kayıt için atlandı.`;
  return `${r} Mental fitness bu kayıt için atlandı.`;
}

export async function runFullAnalysis(audioBlob, sttLanguage) {
  const [sttResult, emotionResult] = await Promise.allSettled([
    transcribeAudio(audioBlob, sttLanguage),
    analyzeVoiceEmotion(audioBlob),
  ]);

  const stt = sttResult.status === 'fulfilled' ? sttResult.value : null;
  const sttError = sttResult.status === 'rejected' ? formatFetchError(sttResult.reason) : null;

  let mental = null;
  let mentalError = null;

  if (sttError) {
    mentalError = 'STT başarısız olduğu için mental fitness çalıştırılmadı.';
  } else {
    const transcript = typeof stt?.text === 'string' ? stt.text.trim() : '';
    if (!transcript) {
      try {
        mental = await analyzeMentalFitness(audioBlob);
      } catch (e) {
        mentalError = formatFetchError(e);
      }
    } else {
      try {
        const verdict = await validateTranscriptForMental(transcript, sttLanguage);
        if (verdict?.meaningful === true) {
          try {
            mental = await analyzeMentalFitness(audioBlob);
          } catch (e) {
            mentalError = formatFetchError(e);
          }
        } else {
          const why =
            typeof verdict?.reason === 'string' && verdict.reason.trim()
              ? verdict.reason.trim()
              : 'Model transkripti seçilen dilde tutarlı konuşma olarak görmedi';
          mentalError = formatValidationFailure(why);
        }
      } catch (e) {
        mentalError = `Transkript doğrulaması başarısız: ${formatFetchError(e)}`;
      }
    }
  }

  return {
    stt,
    sttError,
    emotion: emotionResult.status === 'fulfilled' ? emotionResult.value : null,
    emotionError: emotionResult.status === 'rejected' ? formatFetchError(emotionResult.reason) : null,
    mental,
    mentalError,
  };
}
