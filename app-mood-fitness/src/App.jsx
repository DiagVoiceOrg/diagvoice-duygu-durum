import { useState, useCallback, useEffect } from 'react';
import './App.css';
import AudioRecorder from './components/AudioRecorder';
import AudioFilePicker from './components/AudioFilePicker';
import { runFullAnalysis } from './services/analysis';
import { UI_LANGUAGES, getStrings, interpolate, htmlLangAttribute } from './i18n';

const EMOTION_ORDER = ['anger', 'fear', 'happiness', 'sadness'];

const EMOTION_COLORS = {
  anger: '#ef4444',
  fear: '#8b5cf6',
  happiness: '#10b981',
  sadness: '#6366f1',
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

function hasServiceOutcome(result, error) {
  return !!result || !!error;
}

export default function App() {
  const [speechLang, setSpeechLang] = useState('turkish');
  const [isLoading, setIsLoading] = useState(false);
  const [currentAnalysisSource, setCurrentAnalysisSource] = useState('');
  const [fatalError, setFatalError] = useState('');
  const [emotionV2, setEmotionV2] = useState(null);
  const [emotionV2Error, setEmotionV2Error] = useState(null);

  const m = getStrings(speechLang);

  useEffect(() => {
    document.documentElement.lang = htmlLangAttribute(speechLang);
    document.documentElement.dir = 'ltr';
    document.title = m.pageTitle;
  }, [speechLang, m.pageTitle]);

  const resetResults = () => {
    setFatalError('');
    setEmotionV2(null);
    setEmotionV2Error(null);
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
        setEmotionV2(out.emotionV2);
        setEmotionV2Error(out.emotionV2Error);
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

  const showResults = !isLoading && hasServiceOutcome(emotionV2, emotionV2Error);

  const predictionKey = emotionV2?.prediction;
  const confidence =
    typeof emotionV2?.confidence === 'number' ? emotionV2.confidence : null;
  const probabilities = emotionV2?.probabilities || {};
  const transcript = emotionV2?.transcript;

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="brand-name">DiagVoice</div>
        <div className="title">{m.headerSubtitle}</div>
      </header>

      <section
        className="notice-banner card"
        role="region"
        aria-label={m.legalNoticeTitle}
      >
        <h2 className="notice-banner-title">{m.legalNoticeTitle}</h2>
        <ul className="notice-banner-list">
          {m.legalNoticePoints.map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      </section>

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
            {emotionV2Error && <p className="err">{emotionV2Error}</p>}
            {!emotionV2Error && emotionV2 && (
              <>
                <p className="lead">
                  {m.prediction}:{' '}
                  <strong style={{ color: EMOTION_COLORS[predictionKey] || '#334155' }}>
                    {m.emotions[predictionKey] || predictionKey}
                  </strong>
                  {confidence != null && (
                    <>
                      {' · '}
                      {m.confidence}: {(confidence * 100).toFixed(0)}%
                    </>
                  )}
                </p>
                {EMOTION_ORDER.map((key) => (
                  <ProbBar
                    key={key}
                    label={m.emotions[key] || key}
                    value={probabilities[key] ?? 0}
                    color={EMOTION_COLORS[key]}
                  />
                ))}
                {typeof emotionV2.processing_time_ms === 'number' && (
                  <p className="meta-small">
                    {m.processingTime}: {Math.round(emotionV2.processing_time_ms)} ms
                  </p>
                )}
              </>
            )}
            {!emotionV2Error && !emotionV2 && <p className="muted">{m.noComponentResult}</p>}
          </article>

          <article className="card result-block">
            <h2>{m.transcriptionSectionTitle}</h2>
            {emotionV2Error && <p className="muted">{m.noComponentResult}</p>}
            {!emotionV2Error && emotionV2 && (
              <div className="transcript-box" dir="auto">
                {transcript || <span className="muted">{m.emptyTranscript}</span>}
              </div>
            )}
            {!emotionV2Error && !emotionV2 && <p className="muted">{m.noComponentResult}</p>}
          </article>
        </section>
      )}
    </div>
  );
}
