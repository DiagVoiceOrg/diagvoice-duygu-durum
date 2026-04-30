import axios from 'axios';

function formatAxiosError(err) {
  if (!err) return 'Unknown error';
  if (err.response?.data !== undefined) {
    const d = err.response.data;
    if (typeof d === 'object' && d !== null && 'detail' in d) {
      const detail = d.detail;
      return typeof detail === 'string' ? detail : JSON.stringify(detail);
    }
    return typeof d === 'string' ? d : JSON.stringify(d);
  }
  return err.message || String(err);
}

const TRANSCRIBE_URL =
  import.meta.env.VITE_TRANSCRIBE_URL || 'http://localhost:8001/transcribe';
const VOICE_EMOTION_URL =
  import.meta.env.VITE_VOICE_EMOTION_URL || 'http://localhost:8002/analyze-audio';
const MENTAL_FITNESS_URL =
  import.meta.env.VITE_MENTAL_FITNESS_URL || 'http://localhost:8005/analyze-mental';
const TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS || 600000);

const axiosAudio = axios.create({
  timeout: Number.isFinite(TIMEOUT_MS) ? TIMEOUT_MS : 600000,
  maxBodyLength: Infinity,
  maxContentLength: Infinity,
});

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

  const { data } = await axiosAudio.post(TRANSCRIBE_URL, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function analyzeVoiceEmotion(audioBlob) {
  const formData = new FormData();
  const name =
    audioBlob && typeof audioBlob.name === 'string' && audioBlob.name.length > 0
      ? audioBlob.name
      : `recording.${extFromMime(audioBlob?.type)}`;
  formData.append('file', audioBlob, name);

  const { data } = await axiosAudio.post(VOICE_EMOTION_URL, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function analyzeMentalFitness(audioBlob) {
  const formData = new FormData();
  const name =
    audioBlob && typeof audioBlob.name === 'string' && audioBlob.name.length > 0
      ? audioBlob.name
      : `recording.${extFromMime(audioBlob?.type)}`;
  formData.append('file', audioBlob, name);

  const { data } = await axiosAudio.post(MENTAL_FITNESS_URL, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function runFullAnalysis(audioBlob, sttLanguage) {
  const [stt, emotion, mental] = await Promise.allSettled([
    transcribeAudio(audioBlob, sttLanguage),
    analyzeVoiceEmotion(audioBlob),
    analyzeMentalFitness(audioBlob),
  ]);

  return {
    stt: stt.status === 'fulfilled' ? stt.value : null,
    sttError:
      stt.status === 'rejected' ? formatAxiosError(stt.reason) : null,
    emotion: emotion.status === 'fulfilled' ? emotion.value : null,
    emotionError:
      emotion.status === 'rejected' ? formatAxiosError(emotion.reason) : null,
    mental: mental.status === 'fulfilled' ? mental.value : null,
    mentalError:
      mental.status === 'rejected' ? formatAxiosError(mental.reason) : null,
  };
}
