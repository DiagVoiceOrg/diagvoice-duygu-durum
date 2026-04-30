import { useState, useCallback } from 'react';
import './App.css';
import AudioRecorder from './components/AudioRecorder';
import AudioFilePicker from './components/AudioFilePicker';
import { runFullAnalysis } from './services/analysis';

/** Backend Whisper alan değerleri (voice_to_text resolve_whisper_language) */
const SPEECH_LANGUAGES = [
  { value: 'turkish', label: 'Türkçe' },
  { value: 'english', label: 'English' },
  { value: 'arabic', label: 'العربية' },
];

const EMOTION_TR = {
  sadness: 'Üzüntü',
  fear: 'Korku',
  happiness: 'Mutluluk',
  anger: 'Öfke',
};

const MENTAL_TR = {
  healthy: 'Healthy (olumlu)',
  depression: 'Depression (risk)',
};

function ProbBar({ label, value, color }) {
  const v = Math.min(100, Math.max(0, Number(value) * 100));
  return (
    <div className="prob-bar">
      <div className="prob-bar-head">
        <span>{label}</span>
        <span className="prob-pct">{v.toFixed(1)}%</span>
      </div>
      <div className="prob-track">
        <div className="prob-fill" style={{ width: `${v}%`, background: color }} />
      </div>
    </div>
  );
}

function hasServiceOutcome(stt, sttErr, emotion, emotionErr, mental, mentalErr) {
  return (
    !!(stt || emotion || mental) ||
    !!(sttErr || emotionErr || mentalErr)
  );
}

export default function App() {
  const [speechLang, setSpeechLang] = useState('turkish');
  const [isLoading, setIsLoading] = useState(false);
  const [currentAnalysisSource, setCurrentAnalysisSource] = useState('');
  const [fatalError, setFatalError] = useState('');
  const [stt, setStt] = useState(null);
  const [sttError, setSttError] = useState(null);
  const [emotion, setEmotion] = useState(null);
  const [emotionError, setEmotionError] = useState(null);
  const [mental, setMental] = useState(null);
  const [mentalError, setMentalError] = useState(null);

  const resetResults = () => {
    setFatalError('');
    setStt(null);
    setSttError(null);
    setEmotion(null);
    setEmotionError(null);
    setMental(null);
    setMentalError(null);
  };

  const analyzeAudio = useCallback(
    async (blob, sourceName) => {
      if (!blob) return;
      resetResults();
      setIsLoading(true);
      setCurrentAnalysisSource(sourceName);
      try {
        const out = await runFullAnalysis(blob, speechLang);
        setStt(out.stt);
        setSttError(out.sttError);
        setEmotion(out.emotion);
        setEmotionError(out.emotionError);
        setMental(out.mental);
        setMentalError(out.mentalError);
      } catch (err) {
        const msg = err?.message || 'Bilinmeyen bir hata oluştu';
        console.error(`Analysis failed for ${sourceName}:`, err);
        setFatalError(`"${sourceName}" analizi sırasında bir hata oluştu: ${msg}`);
      } finally {
        setIsLoading(false);
      }
    },
    [speechLang],
  );

  const onRecordingComplete = useCallback(
    (blob) => {
      analyzeAudio(blob, 'Yeni kayıt');
    },
    [analyzeAudio],
  );

  const onFileSelect = useCallback(
    (file) => {
      if (file) analyzeAudio(file, file.name);
    },
    [analyzeAudio],
  );

  const showResults =
    !isLoading && hasServiceOutcome(stt, sttError, emotion, emotionError, mental, mentalError);

  const emotionColors = ['#6366f1', '#f59e0b', '#10b981', '#ef4444'];
  const labelsOrder = emotion?.labels
    ? Object.keys(emotion.labels).sort((a, b) => Number(a) - Number(b))
    : [];

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="brand-name">DiagVoice</div>
        <div className="title">Duygu durumu &amp; mental fitness</div>
      </header>

      <section className="lang-strip card">
        <label htmlFor="speech-lang">
          Konuşma dili <span className="hint">(STT çıktısı bu dilde yazılır)</span>
        </label>
        <select
          id="speech-lang"
          value={speechLang}
          onChange={(e) => setSpeechLang(e.target.value)}
          disabled={isLoading}
        >
          {SPEECH_LANGUAGES.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </section>

      <div className="main-grid">
        <AudioRecorder onRecordingComplete={onRecordingComplete} disabled={isLoading} />
        <AudioFilePicker onFileSelect={onFileSelect} disabled={isLoading} />
      </div>

      {isLoading && (
        <div className="loading">
          &quot;{currentAnalysisSource}&quot; için analiz yapılıyor... Lütfen bekleyin.
        </div>
      )}

      {fatalError && <div className="error">{fatalError}</div>}

      {showResults && (
        <section className="results-section">
          <article className="card result-block">
            <h2>Ses duygu durumu</h2>
            {emotionError && <p className="err">{emotionError}</p>}
            {!emotionError && emotion && (
              <>
                <p className="lead">
                  Tahmin: <strong>{EMOTION_TR[emotion.pred_label] || emotion.pred_label}</strong>
                  {' · '}
                  Yoğunluk: {(Number(emotion.intensity) * 100).toFixed(0)}%
                </p>
                {emotion.probs &&
                  labelsOrder.map((idx) => {
                    const key = emotion.labels[idx];
                    return (
                      <ProbBar
                        key={idx}
                        label={EMOTION_TR[key] || key}
                        value={emotion.probs[Number(idx)]}
                        color={emotionColors[Number(idx) % emotionColors.length]}
                      />
                    );
                  })}
              </>
            )}
            {!emotionError && !emotion && <p className="muted">Bu bileşen için sonuç dönmedi.</p>}
          </article>

          <article className="card result-block">
            <h2>Mental fitness ve konuşma metni</h2>
            <h3 className="h3">Transkripsiyon (STT)</h3>
            {sttError && <p className="err">{sttError}</p>}
            {!sttError && stt && (
              <div className="transcript-box" dir="auto">
                {stt.text || <span className="muted">(boş)</span>}
                {stt.language && (
                  <p className="meta-small">Algılanan / seçilen dil: {stt.language}</p>
                )}
              </div>
            )}
            {!sttError && !stt && <p className="muted">Bu bileşen için sonuç dönmedi.</p>}

            <h3 className="h3">Mental fitness</h3>
            {mentalError && <p className="err">{mentalError}</p>}
            {!mentalError && mental && (
              <div>
                <p className="lead">
                  Sınıf: <strong>{MENTAL_TR[mental.pred_label] || mental.pred_label}</strong>
                  {mental.mental_fitness_score != null && (
                    <>
                      {' · '}
                      Skor: <strong>{mental.mental_fitness_score}</strong>
                    </>
                  )}
                </p>
                {mental.probs && mental.probs.length > 0 && (
                  <p className="muted small">
                    Olasılıklar: {mental.probs.map((p) => p.toFixed(3)).join(', ')}
                  </p>
                )}
              </div>
            )}
            {!mentalError && !mental && <p className="muted">Bu bileşen için sonuç dönmedi.</p>}
          </article>
        </section>
      )}
    </div>
  );
}
