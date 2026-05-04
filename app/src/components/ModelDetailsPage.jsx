import React from 'react';
import {
  demoT,
  genderUiLabel,
  normalizeDemoLang,
} from '../i18n/demoUi';

function formatPct01(v, digits = 0) {
  if (typeof v !== 'number' || Number.isNaN(v)) return null;
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

const GENDER_COLOR = {
  male: '#3b82f6',
  female: '#ec4899',
};
const AGEBIN_LABELS = ['15-24', '25-34', '35-44', '45-54', '55-64'];
const AGE_DISPLAY_SHIFT_BINS = 1;

export default function ModelDetailsPage({
  demoLang = 'tr',
  audioEmotionResult,
  ageGenderResult,
  ageGenderError,
  valenceResult,
  confidenceResult,
}) {
  const lang = normalizeDemoLang(demoLang);

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

  const renderEmotionDistribution = () => {
    if (!Array.isArray(audioEmotionResult?.probs) || audioEmotionResult.probs.length === 0) {
      return null;
    }

    return (
      <div className="card health-card" style={{ paddingTop: 18 }}>
        <div className="card-header">
          <div className="fusion-indicator" />
          <h2>{demoT(lang, 'mdEmotionDistrib')}</h2>
        </div>
        <div className="profile-confidence" style={{ marginBottom: '0.75rem' }}>
          {demoT(lang, 'mdEmotionDistribSrc')}
        </div>
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
      </div>
    );
  };

  const renderAgeGender = () => {
    if (!gender && !agebin) return null;
    const genderPred = gender?.pred_label;
    const agebinPred = agebin?.pred_label;
    const genderPredId = typeof gender?.pred_id === 'number' ? gender.pred_id : null;
    const agebinPredId = typeof agebin?.pred_id === 'number' ? agebin.pred_id : null;

    const genderColor = genderPred && GENDER_COLOR[genderPred] ? GENDER_COLOR[genderPred] : '#3b82f6';

    const agebinColor = '#f59e0b';
    const trGender = (label) => genderUiLabel(lang, label);
    const oppositeGender =
      genderPred === 'female' ? 'male' : genderPred === 'male' ? 'female' : null;

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
      <div className="card wellness-card">
        <div className="card-header">
          <div className="profile-indicator" style={{ background: '#f59e0b' }} />
          <h2>{demoT(lang, 'mdAgeGender')}</h2>
        </div>

        {ageGenderError && (
          <div className="error" style={{ marginBottom: '1rem' }}>
            {ageGenderError}
          </div>
        )}

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
      </div>
    );
  };

  const renderValence = () => {
    const hasAnyValence = valenceText !== null || valenceAudio !== null || fusedValence !== null;
    if (!hasAnyValence) return null;

    const fusedDisplay = fusedLabel
      ? fusedLabel.charAt(0).toUpperCase() + fusedLabel.slice(1).toLowerCase()
      : '-';

    return (
      <div className="card fusion-result">
        <div>
          <div
            className={`fusion-label ${
              fusedLabel?.toLowerCase() === 'positive'
                ? 'positive'
                : fusedLabel?.toLowerCase() === 'negative'
                  ? 'negative'
                  : 'neutral'
            }`}
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
                background: fusedAccentColor,
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
      <div className="card health-card" style={{ paddingTop: 18 }}>
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
      <div className="card health-card">
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
      {renderEmotionDistribution()}
      {renderAgeGender()}
      {renderValence()}
      {renderValenceBars()}
      {renderConfidence()}
    </div>
  );
}
