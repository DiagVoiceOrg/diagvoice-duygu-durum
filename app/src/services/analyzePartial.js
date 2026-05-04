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

const KNOWN_CARD_IDS = new Set(CARD_IDS);

/** Profildeki tüm bilinen kartlar varsa tek analyze-fused (valence/fusion dahil). */
function shouldUseAnalyzeFused(uniqueIds) {
  const s = new Set(uniqueIds.filter((id) => KNOWN_CARD_IDS.has(id)));
  return s.size === CARD_IDS.length && CARD_IDS.every((id) => s.has(id));
}

function needsVoiceToText(uniqueIds) {
  return (
    uniqueIds.includes('transcript') ||
    uniqueIds.includes('sentiment') ||
    uniqueIds.includes('benchmark_v2')
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

  if (uniqueIds.length === 0 || shouldUseAnalyzeFused(uniqueIds)) {
    return analyzeFused(audioData, sttLang);
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

  const sttNeeded = needsVoiceToText(uniqueIds);

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
  if (uniqueIds.includes('audio_emotion')) {
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
  if (uniqueIds.includes('sentiment')) {
    if (!sttNeeded) {
      textErr = 'Metin duygusu için metin gerekir; profile transcript, benchmark veya sentiment ile STT tetikleyin.';
    } else if (sttErr) {
      textErr = `text_sentiment skipped: STT failed (${sttErr})`;
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

  let textSentimentForResponse = null;
  if (textResult) {
    textSentimentForResponse = { ...textResult };
    if (textSentimentForResponse.sentiment == null && textSentimentForResponse.label != null) {
      textSentimentForResponse.sentiment = textSentimentForResponse.label;
    }
  }

  return {
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
  };
}
