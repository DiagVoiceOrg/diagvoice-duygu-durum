import { useState } from 'react';
import { Link, NavLink } from 'react-router-dom';
import '../App.css';
import AudioRecorder from '../components/AudioRecorder';
import SampleAudioPlayer from '../components/SampleAudioPlayer';
import AudioFilePicker from '../components/AudioFilePicker';
import SentimentVisualizer from '../components/SentimentVisualizer';
import CardChrome from '../components/CardChrome';
import { analyzeByProfileCards } from '../services/analyzePartial';
import logo from '../logo.jpg';
import ModelDetailsPage from '../components/ModelDetailsPage';
import { mergeCardCopy, resolveCardOrder } from '../lib/cardCopy';

function ProbBar({ label, value, color }) {
  const percentage = Math.round(value * 100);
  return (
    <div className="prob-bar-row">
      <span className="prob-label">{label}</span>
      <div className="prob-bar-container">
        <div
          className="prob-bar-fill"
          style={{ width: `${percentage}%`, backgroundColor: color }}
        />
        <span className="prob-value">{percentage}%</span>
      </div>
    </div>
  );
}

const EMOTION_LABELS = {
  sadness: { tr: 'Üzüntü', color: '#6366f1' },
  fear: { tr: 'Korku', color: '#8b5cf6' },
  happiness: { tr: 'Mutluluk', color: '#10b981' },
  anger: { tr: 'Öfke', color: '#ef4444' },
  happy: { tr: 'Mutlu', color: '#10b981' },
  sad: { tr: 'Üzgün', color: '#6366f1' },
  angry: { tr: 'Sinirli', color: '#ef4444' },
  fearful: { tr: 'Korkulu', color: '#8b5cf6' },
};

function getEmotionLabel(pred_label) {
  return EMOTION_LABELS[pred_label]?.tr || pred_label;
}

function getEmotionColor(pred_label) {
  return EMOTION_LABELS[pred_label]?.color || '#6b7280';
}

const BENCHMARK_POSITIVE_UI_THRESHOLD = 0.5;

const DEPRESSION_RISK_TR = { dusuk: 'Düşük', orta: 'Orta', yuksek: 'Yüksek' };
const DEPRESSION_RISK_COLOR = { dusuk: '#10b981', orta: '#f59e0b', yuksek: '#ef4444' };

/** CMS’deki slug → React Router path (tek segment). */
function cmsSlugToPath(slug) {
  if (!slug || slug === '/') return '/';
  const s = String(slug).trim();
  const inner = s.replace(/^\/+|\/+$/g, '');
  return inner ? `/${inner}` : '/';
}

export default function DemoHome({
  profileCards,
  cmsWarning,
  navPages = [],
  pageTitle = '',
  pageError = null,
}) {
  const [isLoading, setIsLoading] = useState(false);
  const [transcribedText, setTranscribedText] = useState('');
  const [sentimentResult, setSentimentResult] = useState({ sentiment: null, score: null });
  const [audioEmotionResult, setAudioEmotionResult] = useState(null);
  const [diseaseResult, setDiseaseResult] = useState(null);
  const [depressionResult, setDepressionResult] = useState(null);
  const [mentalFitnessResult, setMentalFitnessResult] = useState(null);
  const [ageGenderResult, setAgeGenderResult] = useState(null);
  const [ageGenderError, setAgeGenderError] = useState(null);
  const [valenceResult, setValenceResult] = useState({ text: null, audio: null, fused: null });
  const [confidenceResult, setConfidenceResult] = useState(null);
  const [benchmarkV2Result, setBenchmarkV2Result] = useState(null);
  const [benchmarkV2Error, setBenchmarkV2Error] = useState(null);
  const [error, setError] = useState('');
  const [currentAnalysisSource, setCurrentAnalysisSource] = useState('');
  const [activePage, setActivePage] = useState('summary');

  const handleAudioAnalysis = async (audioBlob, sourceName) => {
    setIsLoading(true);
    setError('');
    setTranscribedText('');
    setSentimentResult({ sentiment: null, score: null });
    setAudioEmotionResult(null);
    setDiseaseResult(null);
    setDepressionResult(null);
    setMentalFitnessResult(null);
    setAgeGenderResult(null);
    setAgeGenderError(null);
    setValenceResult({ text: null, audio: null, fused: null });
    setConfidenceResult(null);
    setBenchmarkV2Result(null);
    setBenchmarkV2Error(null);
    setCurrentAnalysisSource(sourceName);

    try {
      const result = await analyzeByProfileCards(audioBlob, profileCards);
      setTranscribedText(result.text || '');

      if (result.text_sentiment) {
        setSentimentResult({
          sentiment: result.text_sentiment.sentiment ?? null,
          score: result.text_sentiment.score ?? null,
        });
      }

      if (result.audio) {
        setAudioEmotionResult(result.audio);
      }

      if (result.disease) {
        setDiseaseResult(result.disease);
      }

      if (result.depression) {
        setDepressionResult(result.depression);
      }

      if (result.mental_fitness) {
        setMentalFitnessResult(result.mental_fitness);
      }

      if (result.age_gender) {
        setAgeGenderResult(result.age_gender);
      }
      if (typeof result.age_gender_error === 'string') {
        setAgeGenderError(result.age_gender_error);
      } else {
        setAgeGenderError(null);
      }

      setValenceResult({
        text: result.valence_text ?? null,
        audio: result.valence_audio ?? null,
        fused: result.fused ?? null,
      });

      if (result.confidence) {
        setConfidenceResult(result.confidence);
      }

      if (result.benchmark_v2) {
        setBenchmarkV2Result(result.benchmark_v2);
      }
      if (typeof result.benchmark_v2_error === 'string') {
        setBenchmarkV2Error(result.benchmark_v2_error);
      }
    } catch (err) {
      const errorMessage = err.message || 'Bilinmeyen bir hata oluştu';
      console.error(`Analysis failed for ${sourceName}:`, err);
      setError(`"${sourceName}" analizi sırasında bir hata oluştu: ${errorMessage}`);
    } finally {
      setIsLoading(false);
    }
  };

  const order = resolveCardOrder(profileCards);

  function renderSummaryCard(cardId) {
    const copy = mergeCardCopy(cardId, profileCards);

    switch (cardId) {
      case 'transcript':
        if (!transcribedText) return null;
        return (
          <div className="card transcribed-text" key={cardId}>
            <h2>{copy.displayTitle}</h2>
            {copy.subtitle ? <p className="card-subtitle">{copy.subtitle}</p> : null}
            {copy.periodLabel ? <p className="card-period">{copy.periodLabel}</p> : null}
            <p>&quot;{transcribedText}&quot;</p>
            {copy.badge ? <span className="card-badge-inline">{copy.badge}</span> : null}
            {copy.footnote ? <p className="card-footnote">{copy.footnote}</p> : null}
          </div>
        );

      case 'audio_emotion':
        if (!audioEmotionResult) return null;
        return (
          <div className="card emotion-card" key={cardId}>
            <CardChrome
              copy={copy}
              indicator={
                <div
                  className="emotion-indicator"
                  style={{ backgroundColor: getEmotionColor(audioEmotionResult.pred_label) }}
                />
              }
            >
              <div className="main-result">
                <span
                  className="result-highlight"
                  style={{ color: getEmotionColor(audioEmotionResult.pred_label) }}
                >
                  {getEmotionLabel(audioEmotionResult.pred_label)}
                </span>
                <span className="confidence-badge">
                  Güven: {Math.round((audioEmotionResult.intensity || 0) * 100)}%
                </span>
              </div>
            </CardChrome>
          </div>
        );

      case 'disease':
        if (!diseaseResult) return null;
        return (
          <div className="card health-card" key={cardId}>
            <CardChrome
              copy={copy}
              indicator={
                <div
                  className={`health-indicator ${diseaseResult.pred_label === 'healthy' ? 'healthy' : 'sick'}`}
                />
              }
            >
              <div className="main-result">
                <span
                  className={`result-highlight ${diseaseResult.pred_label === 'healthy' ? 'healthy-text' : 'sick-text'}`}
                >
                  {diseaseResult.pred_label === 'healthy' ? 'Sağlıklı' : 'Hasta'}
                </span>
              </div>
              <div className="prob-section compact">
                <ProbBar label="Sağlıklı" value={diseaseResult.probs?.[0] || 0} color="#10b981" />
                <ProbBar label="Hasta" value={diseaseResult.probs?.[1] || 0} color="#ef4444" />
              </div>
            </CardChrome>
          </div>
        );

      case 'benchmark_v2':
        if (!benchmarkV2Result && !benchmarkV2Error) return null;
        return (
          <div className="card health-card" key={cardId}>
            <CardChrome
              copy={copy}
              indicator={
                <div
                  className="profile-indicator"
                  style={{
                    background: (() => {
                      if (benchmarkV2Error || benchmarkV2Result?.error) return '#94a3b8';
                      const p = benchmarkV2Result?.positive_class_probability;
                      if (typeof p !== 'number') return '#94a3b8';
                      return p >= BENCHMARK_POSITIVE_UI_THRESHOLD ? '#f59e0b' : '#10b981';
                    })(),
                  }}
                />
              }
            >
              {benchmarkV2Error && (
                <div className="error" style={{ marginTop: 0 }}>
                  {benchmarkV2Error}
                </div>
              )}
              {benchmarkV2Result?.error && (
                <div className="error" style={{ marginTop: 0 }}>
                  {typeof benchmarkV2Result.error === 'string'
                    ? benchmarkV2Result.error
                    : JSON.stringify(benchmarkV2Result.error)}
                </div>
              )}
              {benchmarkV2Result &&
                typeof benchmarkV2Result.positive_class_probability === 'number' &&
                !benchmarkV2Result.error &&
                (() => {
                  const pTan = benchmarkV2Result.positive_class_probability ?? 0;
                  const uiTanili = pTan >= BENCHMARK_POSITIVE_UI_THRESHOLD;
                  return (
                    <>
                      <div className="main-result">
                        <span
                          className={`result-highlight ${uiTanili ? 'sick-text' : 'healthy-text'}`}
                        >
                          {uiTanili ? 'Tanılı riski' : 'Sağlıklı profil'}
                        </span>
                        <span className="confidence-badge">
                          Eşik: %{Math.round(BENCHMARK_POSITIVE_UI_THRESHOLD * 100)}
                        </span>
                      </div>
                      <div className="score-section">
                        <div className="score-label">P(tanılı)</div>
                        <div className="score-bar-container">
                          <div
                            className="score-bar"
                            style={{
                              width: `${Math.max(0, Math.min(100, pTan * 100))}%`,
                              backgroundColor:
                                pTan >= BENCHMARK_POSITIVE_UI_THRESHOLD ? '#f59e0b' : '#10b981',
                            }}
                          />
                        </div>
                        <div className="score-value">%{Math.round(pTan * 100)}</div>
                      </div>
                      {benchmarkV2Result.mode && (
                        <div className="profile-confidence" style={{ marginTop: '0.5rem' }}>
                          Model modu: {benchmarkV2Result.mode}
                        </div>
                      )}
                    </>
                  );
                })()}
            </CardChrome>
          </div>
        );

      case 'mental_fitness':
        if (!mentalFitnessResult) return null;
        return (
          <div className="card wellness-card" key={cardId}>
            <CardChrome copy={copy} indicator={<div className="wellness-indicator" />}>
              <div className="main-result">
                <span className="result-highlight">
                  {mentalFitnessResult.pred_label === 'healthy'
                    ? 'Sağlıklı Profil'
                    : 'Değerlendirme Gerekli'}
                </span>
              </div>
              {typeof mentalFitnessResult.mental_fitness_score === 'number' && (
                <div className="score-section">
                  <div className="score-label">Ses Sağlığı Skoru</div>
                  <div className="score-bar-container">
                    <div
                      className="score-bar"
                      style={{
                        width: `${mentalFitnessResult.mental_fitness_score}%`,
                        backgroundColor:
                          mentalFitnessResult.mental_fitness_score > 70
                            ? '#10b981'
                            : mentalFitnessResult.mental_fitness_score > 40
                              ? '#f59e0b'
                              : '#ef4444',
                      }}
                    />
                  </div>
                  <div className="score-value">
                    {mentalFitnessResult.mental_fitness_score.toFixed(0)}%
                  </div>
                </div>
              )}
            </CardChrome>
          </div>
        );

      case 'depression':
        if (!depressionResult) return null;
        {
          const rl = depressionResult.risk_level;
          const riskTr = (rl && DEPRESSION_RISK_TR[rl]) || '—';
          const riskColor = (rl && DEPRESSION_RISK_COLOR[rl]) || '#6b7280';
          const depressionStatus =
            depressionResult.pred_label === 'depresyon' ? 'Depresyon Riski' : 'Sağlıklı';
          const showRiskLevel = depressionResult.pred_label === 'depresyon';
          const finalProb =
            typeof depressionResult.final_prob_depression === 'number'
              ? Math.max(0, Math.min(1, depressionResult.final_prob_depression))
              : null;
          return (
            <div className="card health-card" key={cardId}>
              <CardChrome
                copy={copy}
                indicator={<div className="profile-indicator" style={{ background: riskColor }} />}
              >
                <div
                  className="main-result"
                  style={{
                    flexDirection: 'column',
                    alignItems: 'flex-start',
                    gap: '0.25rem',
                  }}
                >
                  <span className="result-highlight" style={{ color: riskColor }}>
                    Durum: {depressionStatus}
                  </span>
                  {showRiskLevel && (
                    <span className="result-highlight" style={{ color: riskColor }}>
                      Risk seviyesi: {riskTr}
                    </span>
                  )}
                  {finalProb !== null && (
                    <div className="score-section" style={{ width: '100%' }}>
                      <div className="score-label">Skor</div>
                      <div className="score-bar-container">
                        <div
                          className="score-bar"
                          style={{
                            width: `${Math.round(finalProb * 100)}%`,
                            backgroundColor: riskColor,
                          }}
                        />
                      </div>
                      <div className="score-value">%{Math.round(finalProb * 100)}</div>
                    </div>
                  )}
                </div>
              </CardChrome>
            </div>
          );
        }

      case 'sentiment':
        if (!sentimentResult.sentiment) return null;
        return (
          <SentimentVisualizer
            key={cardId}
            sentiment={sentimentResult.sentiment}
            score={sentimentResult.score}
            displayTitle={copy.displayTitle}
            subtitle={copy.subtitle}
            footnote={copy.footnote}
            badge={copy.badge}
            periodLabel={copy.periodLabel}
          />
        );

      default:
        return null;
    }
  }

  return (
    <div className="app-container">
      <header className="app-header">
        <img src={logo} alt="DiagVoice Logo" className="logo" />
        <div className="brand-name">DiagVoice</div>
        {pageTitle ? <div className="demo-page-title">{pageTitle}</div> : null}
        <Link className="admin-link" to="/admin">
          Admin
        </Link>
      </header>

      {navPages.length > 0 ? (
        <nav className="demo-site-nav" aria-label="Sayfalar">
          {navPages.map((p) => (
            <NavLink
              key={p.id}
              to={cmsSlugToPath(p.slug)}
              className={({ isActive }) => `demo-site-nav-link${isActive ? ' active' : ''}`}
              end={p.slug === '/' || !p.slug}
            >
              {p.title || p.slug}
            </NavLink>
          ))}
        </nav>
      ) : null}

      {cmsWarning ? <div className="cms-banner">{cmsWarning}</div> : null}
      {pageError ? <div className="error demo-page-error">{pageError}</div> : null}

      <div className="page-tabs">
        <button
          className={`tab-button ${activePage === 'summary' ? 'active' : 'secondary'}`}
          onClick={() => setActivePage('summary')}
          type="button"
          disabled={isLoading}
        >
          Özet
        </button>
        <button
          className={`tab-button ${activePage === 'details' ? 'active' : 'secondary'}`}
          onClick={() => setActivePage('details')}
          type="button"
          disabled={isLoading}
        >
          Model Detayları
        </button>
      </div>

      <div className={`main-grid${pageError ? ' main-grid-disabled' : ''}`}>
        <AudioRecorder onRecordingComplete={(blob) => handleAudioAnalysis(blob, 'Yeni Kayıt')} disabled={!!pageError} />
        <SampleAudioPlayer onSampleSelect={handleAudioAnalysis} disabled={!!pageError} />
        <AudioFilePicker onFileSelect={handleAudioAnalysis} disabled={!!pageError} />
      </div>

      {isLoading && (
        <div className="loading">
          &quot;{currentAnalysisSource}&quot; için analiz yapılıyor… Lütfen bekleyin.
        </div>
      )}

      {error && <div className="error">{error}</div>}

      <section className="results-section">
        {activePage === 'summary' && <>{order.map((id) => renderSummaryCard(id))}</>}

        {activePage === 'details' && (
          <ModelDetailsPage
            audioEmotionResult={audioEmotionResult}
            ageGenderResult={ageGenderResult}
            ageGenderError={ageGenderError}
            valenceResult={valenceResult}
            confidenceResult={confidenceResult}
          />
        )}
      </section>
    </div>
  );
}
