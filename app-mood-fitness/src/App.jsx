import { useState, useCallback, useEffect } from 'react';
import './App.css';
import AudioRecorder from './components/AudioRecorder';
import AudioFilePicker from './components/AudioFilePicker';
import { runFullAnalysis } from './services/analysis';
import { UI_LANGUAGES, getStrings, interpolate, htmlLangAttribute } from './i18n';

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

  const m = getStrings(speechLang);
  const isRtl = speechLang === 'arabic';

  useEffect(() => {
    document.documentElement.lang = htmlLangAttribute(speechLang);
    document.documentElement.dir = isRtl ? 'rtl' : 'ltr';
    document.title = m.pageTitle;
  }, [speechLang, isRtl, m.pageTitle]);

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
      const loc = getStrings(speechLang);
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
        const msg = err?.message || loc.unknownError;
        console.error(`Analysis failed for ${sourceName}:`, err);
        setFatalError(`${interpolate(loc.fatalErrorPrefix, { source: sourceName })} ${msg}`);
      } finally {
        setIsLoading(false);
      }
    },
    [speechLang],
  );

  const onRecordingComplete = useCallback(
    (blob) => {
      analyzeAudio(blob, getStrings(speechLang).sourceNewRecording);
    },
    [analyzeAudio, speechLang],
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

  const whisperLangLabel =
    stt?.language &&
    m.whisperLangDisplay[String(stt.language).toLowerCase()]
      ? m.whisperLangDisplay[String(stt.language).toLowerCase()]
      : stt?.language;

  return (
    <div className={`app-container${isRtl ? ' app-rtl' : ''}`}>
      <header className="app-header">
        <div className="brand-name">DiagVoice</div>
        <div className="title">{m.headerSubtitle}</div>
      </header>

      <section className="lang-strip card" aria-label={m.langSectionTitle}>
        <div className="lang-strip-head">
          <span className="lang-strip-title">{m.langSectionTitle}</span>
          <span className="hint">{m.langSectionHint}</span>
        </div>
        <div className="lang-toggle" role="group" aria-label={m.langSectionTitle}>
          {UI_LANGUAGES.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`lang-toggle-btn${speechLang === opt.value ? ' lang-toggle-btn--active' : ''}`}
              onClick={() => setSpeechLang(opt.value)}
              disabled={isLoading}
              aria-pressed={speechLang === opt.value}
              lang={htmlLangAttribute(opt.value)}
            >
              {opt.nativeLabel}
            </button>
          ))}
        </div>
      </section>

      <div className="main-grid">
        <AudioRecorder
          onRecordingComplete={onRecordingComplete}
          disabled={isLoading}
          labels={{
            title: m.micCardTitle,
            start: m.startRecord,
            stop: m.stopRecord,
            play: m.play,
            pause: m.pause,
            micDenied: m.micDenied,
          }}
        />
        <AudioFilePicker
          onFileSelect={onFileSelect}
          disabled={isLoading}
          labels={{
            title: m.fileCardTitle,
            selected: m.selectedFile,
            audioUnsupported: m.audioUnsupported,
          }}
        />
      </div>

      {isLoading && (
        <div className="loading">
          {interpolate(m.analyzingLoading, { source: currentAnalysisSource })}
        </div>
      )}

      {fatalError && <div className="error">{fatalError}</div>}

      {showResults && (
        <section className="results-section">
          <article className="card result-block">
            <h2>{m.emotionSectionTitle}</h2>
            {emotionError && <p className="err">{emotionError}</p>}
            {!emotionError && emotion && (
              <>
                <p className="lead">
                  {m.prediction}:{' '}
                  <strong>{m.emotions[emotion.pred_label] || emotion.pred_label}</strong>
                  {' · '}
                  {m.intensity}: {(Number(emotion.intensity) * 100).toFixed(0)}%
                </p>
                {emotion.probs &&
                  labelsOrder.map((idx) => {
                    const key = emotion.labels[idx];
                    return (
                      <ProbBar
                        key={idx}
                        label={m.emotions[key] || key}
                        value={emotion.probs[Number(idx)]}
                        color={emotionColors[Number(idx) % emotionColors.length]}
                      />
                    );
                  })}
              </>
            )}
            {!emotionError && !emotion && <p className="muted">{m.noComponentResult}</p>}
          </article>

          <article className="card result-block">
            <h2>{m.mentalSectionTitle}</h2>
            <h3 className="h3">{m.transcriptionTitle}</h3>
            {sttError && <p className="err">{sttError}</p>}
            {!sttError && stt && (
              <div className="transcript-box" dir="auto">
                {stt.text || <span className="muted">{m.emptyTranscript}</span>}
                {whisperLangLabel && (
                  <p className="meta-small">
                    {m.transcriptLangLabel}: {whisperLangLabel}
                  </p>
                )}
              </div>
            )}
            {!sttError && !stt && <p className="muted">{m.noComponentResult}</p>}

            <h3 className="h3">{m.mentalFitnessHeading}</h3>
            <p className="meta-small muted">{m.mentalHint}</p>
            {mentalError && <p className="err">{mentalError}</p>}
            {!mentalError && mental && (
              <div>
                <p className="lead">
                  {m.mentalClass}:{' '}
                  <strong>{m.mentalLabels[mental.pred_label] || mental.pred_label}</strong>
                  {mental.mental_fitness_score != null && (
                    <>
                      {' · '}
                      {m.score}: <strong>{mental.mental_fitness_score}</strong>
                    </>
                  )}
                </p>
                {mental.probs && mental.probs.length > 0 && (
                  <p className="muted small">
                    {m.probsLabel}: {mental.probs.map((p) => p.toFixed(3)).join(', ')}
                  </p>
                )}
              </div>
            )}
            {!mentalError && !mental && <p className="muted">{m.noComponentResult}</p>}
          </article>
        </section>
      )}
    </div>
  );
}
