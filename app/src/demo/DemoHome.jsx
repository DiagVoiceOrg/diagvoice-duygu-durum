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
import {
  DEMO_LANGS,
  demoT,
  depressionRiskUiLabel,
  emotionUiLabel,
  normalizeDemoLang,
} from '../i18n/demoUi';

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

const EMOTION_COLORS = {
  sadness: '#6366f1',
  fear: '#8b5cf6',
  happiness: '#10b981',
  anger: '#ef4444',
  happy: '#10b981',
  sad: '#6366f1',
  angry: '#ef4444',
  fearful: '#8b5cf6',
};

function getEmotionColor(pred_label) {
  return EMOTION_COLORS[pred_label] || '#6b7280';
}

const BENCHMARK_POSITIVE_UI_THRESHOLD = 0.5;

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
  demoLang = 'tr',
  onDemoLangChange = () => {},
}) {
  const lang = normalizeDemoLang(demoLang);

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
  const [textSttError, setTextSttError] = useState(null);
  const [sentimentPipelineError, setSentimentPipelineError] = useState(null);
  const [audioEmotionError, setAudioEmotionError] = useState(null);
  const [diseaseError, setDiseaseError] = useState(null);
  const [mentalFitnessError, setMentalFitnessError] = useState(null);
  const [depressionError, setDepressionError] = useState(null);
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
    setTextSttError(null);
    setSentimentPipelineError(null);
    setAudioEmotionError(null);
    setDiseaseError(null);
    setMentalFitnessError(null);
    setDepressionError(null);
    setCurrentAnalysisSource(sourceName);

    try {
      const result = await analyzeByProfileCards(audioBlob, profileCards, lang);
      setTranscribedText(result.text || '');
      setTextSttError(typeof result.text_error === 'string' ? result.text_error : null);
      setSentimentPipelineError(typeof result.text_sentiment_error === 'string' ? result.text_sentiment_error : null);
      setAudioEmotionError(typeof result.audio_error === 'string' ? result.audio_error : null);
      setDiseaseError(typeof result.disease_error === 'string' ? result.disease_error : null);
      setMentalFitnessError(typeof result.mental_fitness_error === 'string' ? result.mental_fitness_error : null);
      setDepressionError(typeof result.depression_error === 'string' ? result.depression_error : null);

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
      const errorMessage = err.message || demoT(lang, 'errorUnknown');
      console.error(`Analysis failed for ${sourceName}:`, err);
      setError(demoT(lang, 'errorAnalyzing', { source: sourceName, message: errorMessage }));
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
                  {emotionUiLabel(lang, audioEmotionResult.pred_label)}
                </span>
                <span className="confidence-badge">
                  {demoT(lang, 'confidenceBadge')}: {Math.round((audioEmotionResult.intensity || 0) * 100)}%
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
                  {diseaseResult.pred_label === 'healthy'
                    ? demoT(lang, 'diseaseHealthy')
                    : demoT(lang, 'diseaseSick')}
                </span>
              </div>
              <div className="prob-section compact">
                <ProbBar
                  label={demoT(lang, 'probHealthy')}
                  value={diseaseResult.probs?.[0] || 0}
                  color="#10b981"
                />
                <ProbBar
                  label={demoT(lang, 'probSick')}
                  value={diseaseResult.probs?.[1] || 0}
                  color="#ef4444"
                />
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
                          {uiTanili ? demoT(lang, 'diagRiskUi') : demoT(lang, 'diagHealthyProf')}
                        </span>
                        <span className="confidence-badge">
                          {demoT(lang, 'thresholdLabel')}: %{Math.round(BENCHMARK_POSITIVE_UI_THRESHOLD * 100)}
                        </span>
                      </div>
                      <div className="score-section">
                        <div className="score-label">{demoT(lang, 'pDiagLabel')}</div>
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
                          {demoT(lang, 'modelModeLabel')}: {benchmarkV2Result.mode}
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
                    ? demoT(lang, 'mentalOk')
                    : demoT(lang, 'mentalReview')}
                </span>
              </div>
              {typeof mentalFitnessResult.mental_fitness_score === 'number' && (
                <div className="score-section">
                  <div className="score-label">{demoT(lang, 'vocalHealthScore')}</div>
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
          const riskLabel = rl ? depressionRiskUiLabel(lang, rl) : '—';
          const riskColor = (rl && DEPRESSION_RISK_COLOR[rl]) || '#6b7280';
          const depressionStatus =
            depressionResult.pred_label === 'depresyon'
              ? demoT(lang, 'depRisk')
              : demoT(lang, 'depOk');
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
                    {demoT(lang, 'statusPrefix')} {depressionStatus}
                  </span>
                  {showRiskLevel && (
                    <span className="result-highlight" style={{ color: riskColor }}>
                      {demoT(lang, 'riskLevelPrefix')} {riskLabel}
                    </span>
                  )}
                  {finalProb !== null && (
                    <div className="score-section" style={{ width: '100%' }}>
                      <div className="score-label">{demoT(lang, 'scoreLabel')}</div>
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
    <div className={`app-container${lang === 'ar' ? ' demo-rtl' : ''}`}>
      <header className="app-header">
        <img src={logo} alt={demoT(lang, 'logoAlt')} className="logo" />
        <div className="brand-name">DiagVoice</div>
        {pageTitle ? <div className="demo-page-title">{pageTitle}</div> : null}
        <div
          className="app-header-controls"
          role="toolbar"
          aria-label={demoT(lang, 'languageSwitchAria')}
        >
          <div className="lang-switch" role="group">
            {DEMO_LANGS.map((L) => (
              <button
                key={L.id}
                type="button"
                className={`lang-pill-btn${L.id === 'ar' ? ' lang-pill-btn--arabic' : ''}${
                  lang === L.id ? ' is-active' : ''
                }`}
                lang={L.id === 'tr' ? 'tr' : L.id === 'ar' ? 'ar' : 'en'}
                onClick={() => onDemoLangChange(L.id)}
                aria-pressed={lang === L.id}
                aria-label={L.label}
              >
                {L.label}
              </button>
            ))}
          </div>
          <Link className="admin-link" to="/admin">
            {demoT(lang, 'headerAdmin')}
          </Link>
        </div>
      </header>

      {navPages.length > 0 ? (
        <nav className="demo-site-nav" aria-label={demoT(lang, 'navPagesAria')}>
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
          {demoT(lang, 'tabSummary')}
        </button>
        <button
          className={`tab-button ${activePage === 'details' ? 'active' : 'secondary'}`}
          onClick={() => setActivePage('details')}
          type="button"
          disabled={isLoading}
        >
          {demoT(lang, 'tabDetails')}
        </button>
      </div>

      <div className={`main-grid${pageError ? ' main-grid-disabled' : ''}`}>
        <AudioRecorder
          micDeniedMessage={demoT(lang, 'recorderMicDenied')}
          labels={{
            title: demoT(lang, 'recorderTitle'),
            start: demoT(lang, 'recorderStart'),
            stop: demoT(lang, 'recorderStop'),
            play: demoT(lang, 'recorderPlay'),
            pause: demoT(lang, 'recorderPause'),
          }}
          onRecordingComplete={(blob) => handleAudioAnalysis(blob, demoT(lang, 'sourceNewRecording'))}
          disabled={!!pageError}
        />
        <SampleAudioPlayer
          onSampleSelect={handleAudioAnalysis}
          disabled={!!pageError}
          labels={{
            title: demoT(lang, 'sampleTitle'),
            hint: demoT(lang, 'sampleHint'),
            listAria: demoT(lang, 'sampleListAria'),
            analyzeSep: demoT(lang, 'sampleAnalyzeSep'),
            fetchError: demoT(lang, 'sampleLoadError'),
            noAudio: demoT(lang, 'browserNoAudio'),
          }}
        />
        <AudioFilePicker
          onFileSelect={handleAudioAnalysis}
          disabled={!!pageError}
          labels={{
            title: demoT(lang, 'filePickTitle'),
            selected: demoT(lang, 'fileSelected'),
            noAudio: demoT(lang, 'browserNoAudio'),
          }}
        />
      </div>

      {isLoading && (
        <div className="loading">
          {demoT(lang, 'loadingAnalyzing', { source: `"${currentAnalysisSource}"` })}
        </div>
      )}

      {error && <div className="error">{error}</div>}

      <section className="results-section">
        {activePage === 'summary' && <>{order.map((id) => renderSummaryCard(id))}</>}

        {activePage === 'details' && (
          <ModelDetailsPage
            demoLang={lang}
            profileCards={profileCards}
            orderedCardIds={order}
            transcribedText={transcribedText}
            textSttError={textSttError}
            audioEmotionError={audioEmotionError}
            diseaseError={diseaseError}
            benchmarkV2Error={benchmarkV2Error}
            mentalFitnessError={mentalFitnessError}
            depressionError={depressionError}
            sentimentPipelineError={sentimentPipelineError}
            audioEmotionResult={audioEmotionResult}
            diseaseResult={diseaseResult}
            benchmarkV2Result={benchmarkV2Result}
            mentalFitnessResult={mentalFitnessResult}
            depressionResult={depressionResult}
            sentimentResult={sentimentResult}
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
