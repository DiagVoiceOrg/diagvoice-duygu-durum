import React from 'react';
import Tooltip from './Tooltip';

const SentimentVisualizer = ({
  sentiment,
  score,
  displayTitle = 'Analiz Sonucu',
  subtitle,
  footnote,
  badge,
  periodLabel,
}) => {
  if (sentiment === null || score === null) {
    return null;
  }

  const getSentimentStyle = () => {
    let color;
    let icon;
    let bgClass;

    if (sentiment.toLowerCase() === 'positive') {
      color = '#059669';
      icon = 'P';
      bgClass = 'sentiment-positive';
    } else if (sentiment.toLowerCase() === 'negative') {
      color = '#DC2626';
      icon = 'N';
      bgClass = 'sentiment-negative';
    } else {
      color = '#78716C';
      icon = 'N';
      bgClass = 'sentiment-neutral';
    }
    return { color, icon, bgClass };
  };
  
  const { color, icon, bgClass } = getSentimentStyle();
  const percentage = (score * 100).toFixed(1);

  return (
    <div className={`card sentiment-card ${bgClass}`}>
      <div className="card-header-text sentiment-card-heading">
        <div className="card-title-row">
          <h2>{displayTitle}</h2>
          {badge ? <span className="card-badge">{badge}</span> : null}
        </div>
        {subtitle ? <p className="card-subtitle">{subtitle}</p> : null}
        {periodLabel ? <p className="card-period">{periodLabel}</p> : null}
      </div>
      <div className="sentiment-content">
        <span className="sentiment-icon">{icon}</span>
        <p className="sentiment-label" style={{ color }}>
          {sentiment.charAt(0).toUpperCase() + sentiment.slice(1)}
        </p>
        <p className="sentiment-score">
          Skor:{' '}
          <Tooltip text="Metin duygu analizinin güven skoru. Yüzde ne kadar yüksekse, model o kadar emin.">
            {percentage}%
          </Tooltip>
        </p>
      </div>
      {footnote ? <p className="card-footnote">{footnote}</p> : null}
    </div>
  );
};

export default SentimentVisualizer;
