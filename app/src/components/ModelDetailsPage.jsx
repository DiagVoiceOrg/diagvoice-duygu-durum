import React from 'react';
import { mergeCardCopy } from '../lib/cardCopy';
import {
  demoT,
  agreementUiLabel,
  depressionRiskUiLabel,
  emotionUiLabel,
  genderUiLabel,
  normalizeDemoLang,
} from '../i18n/demoUi';

function formatPct01(v, digits = 0) {
  if (typeof v !== 'number' || Number.isNaN(v)) return null;
  return `${(v * 100).toFixed(digits)}%`;
}

function formatPct01FromUnit(v, digits = 2) {
  if (typeof v !== 'number' || Number.isNaN(v)) return null;
  if (v > 1.000001) return `${v.toFixed(digits)}%`;
  return `${(v * 100).toFixed(digits)}%`;
}

function maxIndex(arr) {
  if (!Array.isArray(arr) || arr.length === 0) return { idx: -1, value: null };
  let bestIdx = 0;
  let bestVal = arr[0];
  for (let i = 1; i < arr.length; i += 1) {
    if (arr[i] > bestVal) {
      bestVal = arr[i];
      bestIdx = i;
    }
  }
  return { idx: bestIdx, value: bestVal };
}

function ProbBarRow({ label, value, color }) {
  const percentage = Math.round((value || 0) * 100);
  return (
    <div className="prob-bar-row">
      <span className="prob-label">{label}</span>
      <div className="prob-bar-container">
        <div className="prob-bar-fill" style={{ width: `${percentage}%`, backgroundColor: color }} />
        <span className="prob-value">{percentage}%</span>
      </div>
    </div>
  );
}

function DetailKv({ label, value }) {
  if (value === null || value === undefined || value === '') return null;
  return (
    <div className="result-row md-detail-row">
      <span className="result-label">{label}</span>
      <span className="result-value md-detail-pre-wrap">{String(value)}</span>
    </div>
  );
}

function DetailCard({ title, subtitle, chromaIndicator, warn, footnote, children }) {
  return (
    <div className="card health-card md-detail-card">
      <div className="card-header">
        {chromaIndicator && <div className="fusion-indicator" style={chromaIndicator} />}
        <h2>{title}</h2>
      </div>
      {subtitle ? (
        <div className="profile-confidence md-detail-sub">{subtitle}</div>
      ) : null}
      {warn ? <div className="error md-detail-error">{warn}</div> : null}
      {children}
      {footnote ? <p className="card-footnote md-detail-foot">{footnote}</p> : null}
    </div>
  );
}

const GENDER_COLOR = {
  male: '#3b82f6',
  female: '#ec4899',
};
const EMOTION_DETAIL_COLORS = {
  sadness: '#6366f1',
  fear: '#8b5cf6',
  happiness: '#10b981',
  anger: '#ef4444',
};

function getEmotionColor(predLabel) {
  return EMOTION_DETAIL_COLORS[predLabel] || '#6b7280';
}
const AGEBIN_LABELS = ['15-24', '25-34', '35-44', '45-54', '55-64'];
const AGE_DISPLAY_SHIFT_BINS = 1;

/**
 * @param {object} props
 * @param {string} props.demoLang
 * @param {Array<{ id: string }>|null} props.profileCards
 * @param {string[]} props.orderedCardIds
 * @param {string} [props.transcribedText]
 * @param {string|null} [props.textSttError]
 * @param {string|null} [props.audioEmotionError]
 * @param {string|null} [props.diseaseError]
 * @param {string|null} [props.benchmarkV2Error]
 * @param {string|null} [props.mentalFitnessError]
 * @param {string|null} [props.depressionError]
 * @param {string|null} [props.sentimentPipelineError]
 * @param {object|null} [props.audioEmotionResult]
 * @param {object|null} [props.diseaseResult]
 * @param {object|null} [props.benchmarkV2Result]
 * @param {object|null} [props.mentalFitnessResult]
 * @param {object|null} [props.depressionResult]
 * @param {{ sentiment: string|null, score: number|null }} [props.sentimentResult]
 * @param {object|null} [props.unifiedEmotionResult]
 */
export default function ModelDetailsPage({
  demoLang = 'tr',
  profileCards,
  orderedCardIds = [],
  transcribedText = '',
  textSttError = null,
  audioEmotionError = null,
  diseaseError = null,
  benchmarkV2Error = null,
  mentalFitnessError = null,
  depressionError = null,
  sentimentPipelineError = null,
  audioEmotionResult,
  diseaseResult,
  benchmarkV2Result,
  mentalFitnessResult,
  depressionResult,
  sentimentResult = { sentiment: null, score: null },
  ageGenderResult,
  ageGenderError,
  valenceResult,
  confidenceResult,
  unifiedEmotionResult = null,
}) {
  const lang = normalizeDemoLang(demoLang);

  const order = orderedCardIds.length ? orderedCardIds : [];

  const gender = ageGenderResult?.gender;
  const agebin = ageGenderResult?.agebin;

  const genderBest = maxIndex(gender?.probs);
  const agebinBest = maxIndex(agebin?.probs);

  const genderTop2 = Array.isArray(gender?.probs)
    ? gender.probs.map((p, i) => ({ p, i })).sort((a, b) => b.p - a.p).slice(0, 2)
    : [];
  const agebinTop2 = Array.isArray(agebin?.probs)
    ? agebin.probs.map((p, i) => ({ p, i })).sort((a, b) => b.p - a.p).slice(0, 2)
    : [];

  const fused = valenceResult?.fused;
  const fusedValence = typeof fused?.valence === 'number' ? fused.valence : null;
  const fusedLabel = fused?.label;

  const valenceText = typeof valenceResult?.text === 'number' ? valenceResult.text : null;
  const valenceAudio = typeof valenceResult?.audio === 'number' ? valenceResult.audio : null;

  const confidenceText = confidenceResult?.text;
  const confidenceAudio = confidenceResult?.audio;
  const disagreement = confidenceResult?.disagreement;
  const dynamicFusion = confidenceResult?.dynamic_fusion;

  const fusedAccentColor =
    fusedLabel?.toLowerCase() === 'positive'
      ? '#10b981'
      : fusedLabel?.toLowerCase() === 'negative'
        ? '#ef4444'
        : '#6b7280';
  const emotionLabels = [
    demoT(lang, 'emotionSadness'),
    demoT(lang, 'emotionFear'),
    demoT(lang, 'emotionHappiness'),
    demoT(lang, 'emotionAnger'),
  ];
  const emotionColors = ['#6366f1', '#8b5cf6', '#10b981', '#ef4444'];

  const classLabelForIndex = (idx) =>
    demoT(lang, 'classN', {
      n: String(idx + 1),
    });

  const hasFusionPanels =
    valenceText !== null ||
    valenceAudio !== null ||
    fusedValence !== null ||
    typeof confidenceText === 'number' ||
    typeof confidenceAudio === 'number' ||
    typeof disagreement === 'number' ||
    (Array.isArray(unifiedEmotionResult?.probs) && unifiedEmotionResult.probs.length > 0);

  const showFusionExtras =
    order.includes('unified_emotion') &&
    order.includes('sentiment') &&
    order.includes('audio_emotion') &&
    hasFusionPanels;

  /** @returns {React.ReactElement | null} */
  function detailBlockFor(cardId) {
    const copy = mergeCardCopy(cardId, profileCards);

    switch (cardId) {
      case 'transcript': {
        const hasTxt = !!(transcribedText && transcribedText.trim());
        const hasErr = !!(textSttError && textSttError.trim());
        if (!hasTxt && !hasErr) {
          return (
            <DetailCard key={cardId} title={copy.displayTitle}>
              <p className="md-detail-muted">{demoT(lang, 'mdEmptyPrompt')}</p>
            </DetailCard>
          );
        }
        return (
          <DetailCard
            key={cardId}
            title={`${copy.displayTitle}`}
            subtitle={demoT(lang, 'mdSttIntro')}
            warn={hasErr ? `${demoT(lang, 'mdSttErrorTitle')}: ${textSttError}` : null}
            footnote={copy.footnote ?? undefined}
          >
            <div className="md-transcript-block">
              {hasTxt ? <blockquote className="md-transcript-quote">&ldquo;{transcribedText}&rdquo;</blockquote> : null}
            </div>
          </DetailCard>
        );
      }

      case 'audio_emotion': {
        if (!audioEmotionResult && !audioEmotionError) {
          return (
            <DetailCard key={cardId} title={`${copy.displayTitle}`}>
              <p className="md-detail-muted">{demoT(lang, 'mdEmptyPrompt')}</p>
            </DetailCard>
          );
        }
        return (
          <DetailCard
            key={cardId}
            title={`${copy.displayTitle}`}
            subtitle={demoT(lang, 'mdAudioMetaTitle')}
            warn={audioEmotionError || null}
          >
            <h4 className="md-detail-h4">{demoT(lang, 'mdPredSummary')}</h4>
            <DetailKv label={demoT(lang, 'mdPredLabel')} value={emotionUiLabel(lang, audioEmotionResult?.pred_label)} />
            <DetailKv
              label={demoT(lang, 'mdPredId')}
              value={
                typeof audioEmotionResult?.pred_id === 'number' ? String(audioEmotionResult.pred_id) : undefined
              }
            />
            <DetailKv
              label={demoT(lang, 'mdIntensityPct')}
              value={
                typeof audioEmotionResult?.intensity === 'number'
                  ? formatPct01FromUnit(audioEmotionResult.intensity, 1)
                  : undefined
              }
            />

            <h4 className="md-detail-h4">{demoT(lang, 'mdClassProbsFull')}</h4>
            {Array.isArray(audioEmotionResult?.probs) && audioEmotionResult.probs.length > 0 ? (
              <div className="prob-section">
                {audioEmotionResult.probs.map((prob, idx) => (
                  <ProbBarRow
                    key={`${emotionLabels[idx] || classLabelForIndex(idx)}-${idx}`}
                    label={emotionLabels[idx] || classLabelForIndex(idx)}
                    value={prob}
                    color={emotionColors[idx] || '#94a3b8'}
                  />
                ))}
              </div>
            ) : (
              <p className="md-detail-muted">{demoT(lang, 'mdEmptyPrompt')}</p>
            )}
          </DetailCard>
        );
      }

      case 'unified_emotion': {
        if (!unifiedEmotionResult?.probs?.length) {
          return (
            <DetailCard key={cardId} title={copy.displayTitle}>
              <p className="md-detail-muted">{demoT(lang, 'mdEmptyPrompt')}</p>
            </DetailCard>
          );
        }
        const textProbs = unifiedEmotionResult.sources?.text?.probs;
        const audioProbs = unifiedEmotionResult.sources?.audio?.probs;
        return (
          <DetailCard
            key={cardId}
            title={copy.displayTitle}
            subtitle={demoT(lang, 'mdUnifiedIntro')}
            chromaIndicator={{ background: getEmotionColor(unifiedEmotionResult.pred_label) }}
          >
            <h4 className="md-detail-h4">{demoT(lang, 'mdPredSummary')}</h4>
            <DetailKv
              label={demoT(lang, 'mdPredLabel')}
              value={emotionUiLabel(lang, unifiedEmotionResult.pred_label)}
            />
            <DetailKv
              label={demoT(lang, 'mdPredId')}
              value={
                typeof unifiedEmotionResult.pred_id === 'number'
                  ? String(unifiedEmotionResult.pred_id)
                  : undefined
              }
            />
            {unifiedEmotionResult.agreement ? (
              <DetailKv
                label={demoT(lang, 'mdUnifiedAgreement')}
                value={agreementUiLabel(lang, unifiedEmotionResult.agreement)}
              />
            ) : null}
            {typeof unifiedEmotionResult.disagreement === 'number' ? (
              <DetailKv
                label={demoT(lang, 'disagreementLbl')}
                value={unifiedEmotionResult.disagreement.toFixed(3)}
              />
            ) : null}
            {typeof unifiedEmotionResult.w_text === 'number' ? (
              <div className="profile-confidence">
                {demoT(lang, 'textWeight', { p: `${Math.round(unifiedEmotionResult.w_text * 100)}` })}
              </div>
            ) : null}

            <h4 className="md-detail-h4">{demoT(lang, 'mdUnifiedFused')}</h4>
            <div className="prob-section">
              {unifiedEmotionResult.probs.map((prob, idx) => (
                <ProbBarRow
                  key={`fused-${idx}`}
                  label={emotionLabels[idx] || classLabelForIndex(idx)}
                  value={prob}
                  color={emotionColors[idx] || '#94a3b8'}
                />
              ))}
            </div>

            {Array.isArray(textProbs) && textProbs.length >= 4 ? (
              <>
                <h4 className="md-detail-h4">{demoT(lang, 'mdUnifiedTextSrc')}</h4>
                <div className="prob-section">
                  {textProbs.slice(0, 4).map((prob, idx) => (
                    <ProbBarRow
                      key={`text-${idx}`}
                      label={emotionLabels[idx] || classLabelForIndex(idx)}
                      value={prob}
                      color="#3b82f6"
                    />
                  ))}
                </div>
              </>
            ) : null}

            {Array.isArray(audioProbs) && audioProbs.length >= 4 ? (
              <>
                <h4 className="md-detail-h4">{demoT(lang, 'mdUnifiedAudioSrc')}</h4>
                <div className="prob-section">
                  {audioProbs.slice(0, 4).map((prob, idx) => (
                    <ProbBarRow
                      key={`audio-${idx}`}
                      label={emotionLabels[idx] || classLabelForIndex(idx)}
                      value={prob}
                      color="#8b5cf6"
                    />
                  ))}
                </div>
              </>
            ) : null}
          </DetailCard>
        );
      }

      case 'disease': {
        if (!diseaseResult && !diseaseError) {
          return (
            <DetailCard key={cardId} title={`${copy.displayTitle}`}>
              <p className="md-detail-muted">{demoT(lang, 'mdEmptyPrompt')}</p>
            </DetailCard>
          );
        }
        return (
          <DetailCard key={cardId} title={`${copy.displayTitle}`} warn={diseaseError || null}>
            <DetailKv label={demoT(lang, 'mdPredLabel')} value={diseaseResult?.pred_label} />
            <DetailKv label={demoT(lang, 'mdPredId')} value={diseaseResult?.pred_id ?? undefined} />

            <h4 className="md-detail-h4">{demoT(lang, 'mdDiseaseRow')}</h4>
            {Array.isArray(diseaseResult?.probs) && diseaseResult.probs.length >= 2 ? (
              <div className="prob-section">
                <ProbBarRow label={demoT(lang, 'probHealthy')} value={diseaseResult.probs[0]} color="#10b981" />
                <ProbBarRow label={demoT(lang, 'probSick')} value={diseaseResult.probs[1]} color="#ef4444" />
              </div>
            ) : (
              <p className="md-detail-muted">{demoT(lang, 'mdEmptyPrompt')}</p>
            )}
          </DetailCard>
        );
      }

      case 'benchmark_v2': {
        if (!benchmarkV2Result && !benchmarkV2Error) {
          return (
            <DetailCard key={cardId} title={`${copy.displayTitle}`}>
              <p className="md-detail-muted">{demoT(lang, 'mdEmptyPrompt')}</p>
            </DetailCard>
          );
        }

        const r = benchmarkV2Result;
        const apiErr =
          benchmarkV2Error ||
          (r?.error ? (typeof r.error === 'string' ? r.error : JSON.stringify(r.error)) : null);

        return (
          <DetailCard key={cardId} title={`${copy.displayTitle}`} subtitle={demoT(lang, 'mdBenchFull')} warn={apiErr}>
            {r && !r.error ? (
              <>
                {typeof r.positive_class_probability === 'number' ? (
                  <DetailKv
                    label={demoT(lang, 'mdBenchPositiveP')}
                    value={formatPct01FromUnit(r.positive_class_probability, 2)}
                  />
                ) : null}
                <DetailKv label={demoT(lang, 'mdBenchPredClass')} value={r.predicted_class ?? undefined} />
                <DetailKv label={demoT(lang, 'mdBenchThrTuned')} value={r.threshold_tuned ?? undefined} />
                <DetailKv label={demoT(lang, 'mdBenchThrObj')} value={r.threshold_objective ?? undefined} />
                <DetailKv label={demoT(lang, 'modelModeLabel')} value={r.mode ?? undefined} />
                <DetailKv label={demoT(lang, 'mdBenchHint')} value={r.class_names_hint ?? undefined} />
              </>
            ) : null}
          </DetailCard>
        );
      }

      case 'mental_fitness': {
        if (!mentalFitnessResult && !mentalFitnessError) {
          return (
            <DetailCard key={cardId} title={`${copy.displayTitle}`}>
              <p className="md-detail-muted">{demoT(lang, 'mdEmptyPrompt')}</p>
            </DetailCard>
          );
        }
        const m = mentalFitnessResult;
        return (
          <DetailCard key={cardId} title={`${copy.displayTitle}`} subtitle={demoT(lang, 'mdMentalFull')} warn={mentalFitnessError || null}>
            <DetailKv label={demoT(lang, 'mdPredLabel')} value={m?.pred_label} />
            <DetailKv label={demoT(lang, 'mdPredId')} value={m?.pred_id ?? undefined} />
            <DetailKv
              label={demoT(lang, 'mdMentalScore')}
              value={typeof m?.mental_fitness_score === 'number' ? `${Number(m.mental_fitness_score).toFixed(1)}%` : undefined}
            />
            {Array.isArray(m?.probs) && m.probs.length > 0 ? (
              <>
                <h4 className="md-detail-h4">{demoT(lang, 'mdClassProbsFull')}</h4>
                <div className="prob-section">
                  {m.probs.map((p, idx) => (
                    <ProbBarRow
                      key={`mf-${idx}`}
                      label={classLabelForIndex(idx)}
                      value={p}
                      color={idx === 0 ? '#10b981' : '#94a3b8'}
                    />
                  ))}
                </div>
              </>
            ) : null}
          </DetailCard>
        );
      }

      case 'depression': {
        if (!depressionResult && !depressionError) {
          return (
            <DetailCard key={cardId} title={`${copy.displayTitle}`}>
              <p className="md-detail-muted">{demoT(lang, 'mdEmptyPrompt')}</p>
            </DetailCard>
          );
        }
        const d = depressionResult;
        return (
          <DetailCard key={cardId} title={`${copy.displayTitle}`} subtitle={demoT(lang, 'mdDepFull')} warn={depressionError || null}>
            <DetailKv label={demoT(lang, 'mdPredLabel')} value={d?.pred_label} />
            <DetailKv label={demoT(lang, 'mdPredId')} value={d?.pred_id ?? undefined} />
            <DetailKv label={demoT(lang, 'mdDepRisk')} value={d?.risk_level ? depressionRiskUiLabel(lang, d.risk_level) : undefined} />
            <DetailKv
              label={demoT(lang, 'mdDepProbFinal')}
              value={
                typeof d?.final_prob_depression === 'number' ? formatPct01FromUnit(d.final_prob_depression, 2) : undefined
              }
            />
            <DetailKv label={demoT(lang, 'mdDepMean')} value={typeof d?.mean_prob_depression === 'number' ? formatPct01FromUnit(d.mean_prob_depression, 3) : undefined} />
            <DetailKv label={demoT(lang, 'mdDepMedian')} value={typeof d?.median_prob_depression === 'number' ? formatPct01FromUnit(d.median_prob_depression, 3) : undefined} />
            <DetailKv label={demoT(lang, 'mdDepTrim')} value={typeof d?.trimmed_mean_prob_depression === 'number' ? formatPct01FromUnit(d.trimmed_mean_prob_depression, 3) : undefined} />
            <DetailKv label={demoT(lang, 'mdDepStd')} value={typeof d?.std_prob_depression === 'number' ? d.std_prob_depression.toFixed(4) : undefined} />
            <DetailKv label={demoT(lang, 'mdDepSpan')} value={typeof d?.min_prob_depression === 'number' && typeof d?.max_prob_depression === 'number' ? `[${formatPct01FromUnit(d.min_prob_depression, 2)}, ${formatPct01FromUnit(d.max_prob_depression, 2)}]` : undefined} />
            <DetailKv label={demoT(lang, 'mdDepSegCount')} value={d?.segment_count ?? undefined} />
            <DetailKv label={demoT(lang, 'mdDepReliability')} value={d?.reliability} />
            <DetailKv label={demoT(lang, 'mdDepThreshold')} value={typeof d?.threshold === 'number' ? String(d.threshold) : undefined} />
            <DetailKv label={demoT(lang, 'mdDepInstability')} value={typeof d?.is_unstable === 'boolean' ? (d.is_unstable ? 'true' : 'false') : undefined} />

            {Array.isArray(d?.segment_probs) && d.segment_probs.length > 0 ? (
              <details className="md-detail-details">
                <summary>{demoT(lang, 'mdDepSegPreview')}</summary>
                <pre className="md-detail-pre">{d.segment_probs.slice(0, 24).map((x) => x.toFixed(4)).join(', ')}</pre>
              </details>
            ) : null}
          </DetailCard>
        );
      }

      case 'sentiment': {
        if (!sentimentResult?.sentiment && sentimentResult?.score === null && !sentimentPipelineError) {
          return (
            <DetailCard key={cardId} title={`${copy.displayTitle}`}>
              <p className="md-detail-muted">{demoT(lang, 'mdEmptyPrompt')}</p>
            </DetailCard>
          );
        }

        const sc = sentimentResult?.score;

        return (
          <DetailCard
            key={cardId}
            title={`${copy.displayTitle}`}
            subtitle={`${demoT(lang, 'mdSentAnalysis')} · ${demoT(lang, 'mdSentPipelineTitle')}`}
            warn={sentimentPipelineError || null}
          >
            <DetailKv label={demoT(lang, 'mdSentLabel')} value={sentimentResult?.sentiment ?? undefined} />
            <DetailKv label={demoT(lang, 'mdSentScore')} value={sc !== null && sc !== undefined ? String(sc) : undefined} />
          </DetailCard>
        );
      }

      default:
        return null;
    }
  }

  const renderAgeGender = () => {
    if (!gender && !agebin) return null;
    const genderPred = gender?.pred_label;
    const agebinPred = agebin?.pred_label;
    const genderPredId = typeof gender?.pred_id === 'number' ? gender.pred_id : null;
    const agebinPredId = typeof agebin?.pred_id === 'number' ? agebin.pred_id : null;

    const genderColor = genderPred && GENDER_COLOR[genderPred] ? GENDER_COLOR[genderPred] : '#3b82f6';

    const agebinColor = '#f59e0b';
    const trGender = (label) => genderUiLabel(lang, label);
    const oppositeGender = genderPred === 'female' ? 'male' : genderPred === 'male' ? 'female' : null;

    const getGenderLabelByIndex = (idx) => {
      if (genderPredId !== null && idx === genderPredId) return trGender(genderPred);
      if (Array.isArray(gender?.probs) && gender.probs.length === 2 && oppositeGender) {
        return trGender(oppositeGender);
      }
      return classLabelForIndex(idx);
    };

    const getAgebinLabelByIndex = (idx) => {
      const shiftedIdx = Math.max(
        0,
        Math.min(AGEBIN_LABELS.length - 1, idx - AGE_DISPLAY_SHIFT_BINS),
      );
      return AGEBIN_LABELS[shiftedIdx] || classLabelForIndex(shiftedIdx);
    };
    const agebinPredDisplay = (() => {
      if (agebinPredId !== null) return getAgebinLabelByIndex(agebinPredId);
      const inferredIdx = AGEBIN_LABELS.indexOf(agebinPred || '');
      if (inferredIdx >= 0) return getAgebinLabelByIndex(inferredIdx);
      return agebinPred || '-';
    })();

    return (
      <DetailCard title={demoT(lang, 'mdAgeGender')} chromaIndicator={{ background: '#f59e0b' }} warn={ageGenderError || null}>
        {gender && (
          <div className="profile-grid">
            <div className="profile-item">
              <div className="profile-label">{demoT(lang, 'mdGenderGuess')}</div>
              <div className="profile-value" style={{ color: genderColor }}>
                {genderUiLabel(lang, gender.pred_label)}
              </div>
              {typeof genderBest.value === 'number' && (
                <div className="profile-confidence">
                  {demoT(lang, 'confidenceBadge')}: {formatPct01(genderBest.value, 0)}
                </div>
              )}
            </div>

            <div className="profile-item">
              <div className="profile-label">{demoT(lang, 'mdAgeGroupGuess')}</div>
              <div className="profile-value" style={{ color: agebinColor }}>
                {agebinPredDisplay}
              </div>
              {typeof agebinBest.value === 'number' && (
                <div className="profile-confidence">
                  {demoT(lang, 'confidenceBadge')}: {formatPct01(agebinBest.value, 0)}
                </div>
              )}
            </div>
          </div>
        )}

        <div className="prob-section">
          <h4>{demoT(lang, 'mdDistribution')}</h4>
          {Array.isArray(gender?.probs) && gender.probs.length > 0 && (
            <>
              <ProbBarRow
                label={getGenderLabelByIndex(genderTop2[0]?.i ?? genderBest.idx)}
                value={genderTop2[0]?.p ?? genderBest.value}
                color={genderColor}
              />
              {genderTop2.length > 1 && (
                <ProbBarRow
                  label={getGenderLabelByIndex(genderTop2[1].i)}
                  value={genderTop2[1].p}
                  color="#94a3b8"
                />
              )}
            </>
          )}

          {Array.isArray(agebin?.probs) && agebin.probs.length > 0 && (
            <>
              <ProbBarRow
                label={getAgebinLabelByIndex(agebinTop2[0]?.i ?? agebinBest.idx)}
                value={agebinTop2[0]?.p ?? agebinBest.value}
                color={agebinColor}
              />
              {agebinTop2.length > 1 && (
                <ProbBarRow
                  label={getAgebinLabelByIndex(agebinTop2[1].i)}
                  value={agebinTop2[1].p}
                  color="#94a3b8"
                />
              )}
            </>
          )}
        </div>
      </DetailCard>
    );
  };

  const renderValence = () => {
    const hasAnyValence = valenceText !== null || valenceAudio !== null || fusedValence !== null;
    if (!hasAnyValence) return null;

    const unifiedLabel = unifiedEmotionResult?.pred_label;
    const fusedDisplay = unifiedLabel
      ? emotionUiLabel(lang, unifiedLabel)
      : fusedLabel
        ? fusedLabel.charAt(0).toUpperCase() + fusedLabel.slice(1).toLowerCase()
        : '-';

    const accentColor = unifiedLabel
      ? getEmotionColor(unifiedLabel)
      : fusedAccentColor;

    return (
      <div className="card fusion-result">
        <div>
          <div
            className={`fusion-label ${
              unifiedLabel
                ? 'neutral'
                : fusedLabel?.toLowerCase() === 'positive'
                  ? 'positive'
                  : fusedLabel?.toLowerCase() === 'negative'
                    ? 'negative'
                    : 'neutral'
            }`}
            style={unifiedLabel ? { color: accentColor } : undefined}
          >
            {demoT(lang, 'fusedEmotionPrefix')} {fusedDisplay}
          </div>
          <div className="fusion-confidence">
            {typeof fusedValence === 'number'
              ? demoT(lang, 'valencePct', { p: `${(fusedValence * 100).toFixed(1)}` })
              : demoT(lang, 'valenceUnavailable')}
          </div>
          {typeof fused?.w_text === 'number' && (
            <div className="fusion-confidence">
              {demoT(lang, 'textWeight', { p: `${Math.round(fused.w_text * 100)}` })}
            </div>
          )}
        </div>

        <div style={{ width: 160 }}>
          <div className="source-bar-container" style={{ height: 14, borderRadius: 10, marginBottom: 8 }}>
            <div
              className="source-fill"
              style={{
                width: `${typeof fusedValence === 'number' ? fusedValence * 100 : 0}%`,
                background: accentColor,
                height: '100%',
              }}
            />
          </div>
          <div className="source-value" style={{ textAlign: 'right' }}>
            {typeof fusedValence === 'number' ? `${(fusedValence * 100).toFixed(0)}%` : '-'}
          </div>
        </div>
      </div>
    );
  };

  const renderValenceBars = () => {
    if (valenceText === null && valenceAudio === null) return null;
    return (
      <div className="card health-card md-detail-card" style={{ paddingTop: 18 }}>
        <div className="card-header">
          <div className="fusion-indicator" />
          <h2>{demoT(lang, 'mdValenceCompare')}</h2>
        </div>
        <div className="profile-confidence" style={{ marginBottom: '0.75rem' }}>
          {demoT(lang, 'mdValenceCompareSrc')}
        </div>
        <div className="prob-section">
          {valenceText !== null && (
            <ProbBarRow label={demoT(lang, 'labelTextShort')} value={valenceText} color="#3b82f6" />
          )}
          {valenceAudio !== null && (
            <ProbBarRow label={demoT(lang, 'labelAudioShort')} value={valenceAudio} color="#8b5cf6" />
          )}
        </div>
      </div>
    );
  };

  const renderConfidence = () => {
    const has =
      typeof confidenceText === 'number' ||
      typeof confidenceAudio === 'number' ||
      typeof disagreement === 'number';
    if (!has) return null;

    return (
      <div className="card health-card md-detail-card">
        <div className="card-header">
          <div className="fusion-indicator" />
          <h2>{demoT(lang, 'mdFusionConfTitle')}</h2>
        </div>
        <div className="profile-confidence" style={{ marginBottom: '0.75rem' }}>
          {demoT(lang, 'mdFusionConfSrc')}
        </div>

        <div className="profile-grid">
          <div className="profile-item">
            <div className="profile-label">{demoT(lang, 'confTextLbl')}</div>
            <div className="profile-value">{formatPct01(confidenceText, 0) || '-'}</div>
            <div className="profile-confidence">{demoT(lang, 'confTextSub')}</div>
          </div>
          <div className="profile-item">
            <div className="profile-label">{demoT(lang, 'confAudioLbl')}</div>
            <div className="profile-value">{formatPct01(confidenceAudio, 0) || '-'}</div>
            <div className="profile-confidence">{demoT(lang, 'confAudioSub')}</div>
          </div>
        </div>

        <div className="prob-section">
          <h4>{demoT(lang, 'mdMismatchHeading')}</h4>
          {typeof disagreement === 'number' && (
            <div className="result-row">
              <span className="result-label">{demoT(lang, 'disagreementLbl')}</span>
              <span className="result-value">{disagreement.toFixed(3)}</span>
            </div>
          )}
          <div className="result-row">
            <span className="result-label">{demoT(lang, 'dynamicFusionLbl')}</span>
            <span className="result-value">{dynamicFusion ? demoT(lang, 'on') : demoT(lang, 'off')}</span>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="model-details-stack">
      {order.map((cid) => detailBlockFor(cid))}

      {ageGenderResult || ageGenderError ? renderAgeGender() : null}

      {showFusionExtras ? (
        <DetailCard title={demoT(lang, 'mdFusionExtrasTitle')} subtitle={demoT(lang, 'mdFusionExtrasHint')}>
          {renderValence()}
          {renderValenceBars()}
          {renderConfidence()}
        </DetailCard>
      ) : null}
    </div>
  );
}
