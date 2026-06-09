import axios from 'axios';
import { analyzeFused, normalizeSpeechLanguageForStt } from './analyzeFused';
import { CARD_IDS, resolveCardOrder } from '../lib/cardCopy';
import { getFusionOrigin } from './fusionOrigin';

const API_TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS || 600000);

const extFromMime = (mime) => {
  const m = (mime || '').toLowerCase();
  if (m.includes('webm')) return 'webm';
  if (m.includes('wav')) return 'wav';
  if (m.includes('mpeg') || m.includes('mp3')) return 'mp3';
  if (m.includes('mp4')) return 'm4a';
  if (m.includes('ogg')) return 'ogg';
  return 'wav';
};

function buildFormData(audioData) {
  const formData = new FormData();
  const hasName = audioData && typeof audioData.name === 'string' && audioData.name.length > 0;
  const fileName = hasName ? audioData.name : `recording.${extFromMime(audioData?.type)}`;
  formData.append('file', audioData, fileName);
  return formData;
}

function buildFormDataWithTranscript(audioData, transcript) {
  const fd = buildFormData(audioData);
  fd.append('transcript', transcript ?? '');
  return fd;
}

async function postMultipart(path, audioData, speechLanguage) {
  const fd = buildFormData(audioData);
  if (path === '/analyze-voice-to-text' && speechLanguage != null && speechLanguage !== '') {
    fd.append('speech_language', normalizeSpeechLanguageForStt(speechLanguage));
  }
  const origin = getFusionOrigin();
  const { data } = await axios.post(`${origin}${path}`, fd, {
    timeout: Number.isFinite(API_TIMEOUT_MS) ? API_TIMEOUT_MS : 600000,
    maxBodyLength: Infinity,
    maxContentLength: Infinity,
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

async function postBenchmark(audioData, transcript) {
  const origin = getFusionOrigin();
  const { data } = await axios.post(`${origin}/analyze-benchmark-v2`, buildFormDataWithTranscript(audioData, transcript), {
    timeout: Number.isFinite(API_TIMEOUT_MS) ? API_TIMEOUT_MS : 600000,
    maxBodyLength: Infinity,
    maxContentLength: Infinity,
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

async function postTextSentiment(text) {
  const origin = getFusionOrigin();
  const { data } = await axios.post(`${origin}/analyze-text-sentiment`, { text: text ?? '' }, {
    timeout: Number.isFinite(API_TIMEOUT_MS) ? API_TIMEOUT_MS : 600000,
    headers: { 'Content-Type': 'application/json' },
  });
  return data;
}

async function postEmotionFusion(textSentiment, audio) {
  const origin = getFusionOrigin();
  const body = {};
  if (textSentiment && typeof textSentiment.score === 'number') {
    body.text_sentiment = {
      sentiment: textSentiment.sentiment ?? textSentiment.label ?? null,
      score: textSentiment.score,
    };
  }
  if (audio && Array.isArray(audio.probs) && audio.probs.length >= 4) {
    body.audio = {
      probs: audio.probs.slice(0, 4),
      intensity: typeof audio.intensity === 'number' ? audio.intensity : undefined,
      pred_label: audio.pred_label ?? undefined,
      pred_id: typeof audio.pred_id === 'number' ? audio.pred_id : undefined,
    };
  }
  if (!body.text_sentiment && !body.audio) {
    throw new Error('emotion fusion requires text_sentiment and/or audio');
  }
  const { data } = await axios.post(`${origin}/analyze-emotion-fusion`, body, {
    timeout: Number.isFinite(API_TIMEOUT_MS) ? API_TIMEOUT_MS : 600000,
    headers: { 'Content-Type': 'application/json' },
  });
  return data;
}

function normalizeTextSentiment(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const out = { ...raw };
  if (out.sentiment == null && out.label != null) {
    out.sentiment = out.label;
  }
  return out;
}

function canRunEmotionFusion(textSentiment, audio, textErr, audioErr) {
  const hasText =
    textSentiment &&
    typeof textSentiment.score === 'number' &&
    !textErr;
  const hasAudio =
    audio &&
    Array.isArray(audio.probs) &&
    audio.probs.length >= 4 &&
    !audioErr;
  return hasText || hasAudio;
}

/** Profilde unified_emotion kartı varsa POST /analyze-emotion-fusion ile doldurur. */
async function enrichWithUnifiedFusion(result, wantsUnifiedFusion, profileOrder) {
  if (!wantsUnifiedFusion) return result;

  if (!profileOrder.includes('sentiment') && !profileOrder.includes('audio_emotion')) {
    return {
      ...result,
      unified_emotion_error:
        'Birleşik emosyon için profilde sentiment (Metin Duygusu) ve audio_emotion (Ses Emosyonu) kartları da gerekli.',
    };
  }

  const textSentiment = normalizeTextSentiment(result.text_sentiment);
  const audio = result.audio;
  const textErr = result.text_sentiment_error;
  const audioErr = result.audio_error;

  const hasText =
    textSentiment && typeof textSentiment.score === 'number' && !textErr;
  const hasAudio =
    audio && Array.isArray(audio.probs) && audio.probs.length >= 4 && !audioErr;

  if (!canRunEmotionFusion(textSentiment, audio, textErr, audioErr)) {
    let unifiedEmotionError = null;
    if (textErr && !hasAudio) {
      unifiedEmotionError = textErr;
    } else if (audioErr) {
      unifiedEmotionError = audioErr;
    }
    return {
      ...result,
      unified_emotion: null,
      unified_emotion_error: unifiedEmotionError,
    };
  }

  try {
    const fusion = await postEmotionFusion(hasText ? textSentiment : null, hasAudio ? audio : null);
    return {
      ...result,
      text_sentiment: textSentiment ?? result.text_sentiment,
      valence_text: fusion.valence_text ?? null,
      valence_audio: fusion.valence_audio ?? null,
      confidence: fusion.confidence ?? null,
      fused: fusion.fused ?? null,
      unified_emotion: fusion.unified_emotion ?? null,
      unified_emotion_error: null,
    };
  } catch (e) {
    const msg = e.response?.data ? JSON.stringify(e.response.data) : e.message || 'Emotion fusion hatası';
    console.warn('POST /analyze-emotion-fusion failed:', msg);
    return {
      ...result,
      unified_emotion_error: msg,
    };
  }
}

const KNOWN_CARD_IDS = new Set(CARD_IDS);

/** Profildeki tüm bilinen kartlar varsa tek analyze-fused (valence/fusion dahil). */
function shouldUseAnalyzeFused(uniqueIds) {
  const s = new Set(uniqueIds.filter((id) => KNOWN_CARD_IDS.has(id)));
  return s.size === CARD_IDS.length && CARD_IDS.every((id) => s.has(id));
}

function needsVoiceToText(uniqueIds, wantsUnifiedFusion = false) {
  return (
    uniqueIds.includes('transcript') ||
    uniqueIds.includes('sentiment') ||
    uniqueIds.includes('benchmark_v2') ||
    wantsUnifiedFusion
  );
}

/**
 * CMS profilindeki kart id’lerine göre yalnızca gerekli fusion proxy uçlarına istek atar.
 * Tam kart listesi (registry ile aynı 7 id) ise tek POST /analyze-fused kullanılır.
 *
 * @param {Blob|File} audioData
 * @param {Array<{ id: string }>|null|undefined} profileCards
 * @param {string} [speechLanguage] Demo UI kodu tr|en|ar → Whisper diline proxy’den iletilir
 * @returns {Promise<Record<string, unknown>>} analyze-fused ile uyumlu gövde
 */
export async function analyzeByProfileCards(audioData, profileCards, speechLanguage = 'tr') {
  const sttLang = normalizeSpeechLanguageForStt(speechLanguage);
  const ordered = resolveCardOrder(profileCards);
  const uniqueIds = [...new Set(ordered.filter((id) => id && KNOWN_CARD_IDS.has(id)))];
  const wantsUnifiedFusion = ordered.includes('unified_emotion');

  if (uniqueIds.length === 0 || shouldUseAnalyzeFused(uniqueIds)) {
    const result = await analyzeFused(audioData, sttLang);
    return enrichWithUnifiedFusion(result, wantsUnifiedFusion, ordered);
  }

  let sttText = null;
  let sttErr = null;
  let audioResult = null;
  let audioErr = null;
  let diseaseResult = null;
  let diseaseErr = null;
  let mentalFitnessResult = null;
  let mentalFitnessErr = null;
  let depressionResult = null;
  let depressionErr = null;
  let benchmarkV2Result = null;
  let benchmarkV2Err = null;
  let textResult = null;
  let textErr = null;

  const sttNeeded = needsVoiceToText(uniqueIds, wantsUnifiedFusion);

  const phase1 = [];

  if (sttNeeded) {
    phase1.push(
      postMultipart('/analyze-voice-to-text', audioData, sttLang)
        .then((d) => {
          sttText = typeof d?.text === 'string' ? d.text : '';
        })
        .catch((e) => {
          sttErr = e.response?.data ? JSON.stringify(e.response.data) : e.message || 'STT hatası';
        }),
    );
  }
  if (uniqueIds.includes('audio_emotion') || wantsUnifiedFusion) {
    phase1.push(
      postMultipart('/analyze-voice-sentiment', audioData)
        .then((d) => {
          audioResult = d;
        })
        .catch((e) => {
          audioErr = e.response?.data ? JSON.stringify(e.response.data) : e.message || 'Ses emosyon hatası';
        }),
    );
  }
  if (uniqueIds.includes('disease')) {
    phase1.push(
      postMultipart('/analyze-disease', audioData)
        .then((d) => {
          diseaseResult = d;
        })
        .catch((e) => {
          diseaseErr = e.response?.data ? JSON.stringify(e.response.data) : e.message || 'WURSS hatası';
        }),
    );
  }
  if (uniqueIds.includes('mental_fitness')) {
    phase1.push(
      postMultipart('/analyze-mental-fitness', audioData)
        .then((d) => {
          mentalFitnessResult = d;
        })
        .catch((e) => {
          mentalFitnessErr = e.response?.data ? JSON.stringify(e.response.data) : e.message || 'Mental fitness hatası';
        }),
    );
  }
  if (uniqueIds.includes('depression')) {
    phase1.push(
      postMultipart('/analyze-depression', audioData)
        .then((d) => {
          depressionResult = d;
        })
        .catch((e) => {
          depressionErr = e.response?.data ? JSON.stringify(e.response.data) : e.message || 'Depresyon hatası';
        }),
    );
  }

  await Promise.all(phase1);

  const transcript = (sttText ?? '').trim();

  const phase2 = [];
  if (uniqueIds.includes('sentiment') || wantsUnifiedFusion) {
    if (!sttNeeded) {
      textErr = 'Metin duygusu için metin gerekir; profile transcript, benchmark veya sentiment ile STT tetikleyin.';
    } else if (sttErr) {
      textErr = `text_sentiment skipped: STT failed (${sttErr})`;
    } else if (!transcript) {
      if (uniqueIds.includes('sentiment')) {
        textErr = 'skipped: empty transcript after STT';
      }
    } else {
      phase2.push(
        postTextSentiment(transcript)
          .then((d) => {
            textResult = d;
          })
          .catch((e) => {
            textErr = e.response?.data ? JSON.stringify(e.response.data) : e.message || 'Metin duygusu hatası';
          }),
      );
    }
  }

  if (uniqueIds.includes('benchmark_v2')) {
    phase2.push(
      postBenchmark(audioData, transcript)
        .then((d) => {
          benchmarkV2Result = d;
        })
        .catch((e) => {
          benchmarkV2Err = e.response?.data ? JSON.stringify(e.response.data) : e.message || 'Benchmark hatası';
        }),
    );
  }

  await Promise.all(phase2);

  let textSentimentForResponse = normalizeTextSentiment(textResult);

  return enrichWithUnifiedFusion(
    {
      text: sttText,
      text_error: sttErr,
      audio: audioResult,
      audio_error: audioErr,
      disease: diseaseResult,
      disease_error: diseaseErr,
      mental_fitness: mentalFitnessResult,
      mental_fitness_error: mentalFitnessErr,
      age_gender: null,
      age_gender_error: null,
      depression: depressionResult,
      depression_error: depressionErr,
      benchmark_v2: benchmarkV2Result,
      benchmark_v2_error: benchmarkV2Err,
      text_sentiment: textSentimentForResponse,
      text_sentiment_error: textErr,
      valence_text: null,
      valence_audio: null,
      confidence: null,
      fused: null,
      unified_emotion: null,
    },
    wantsUnifiedFusion,
    ordered,
  );
}
