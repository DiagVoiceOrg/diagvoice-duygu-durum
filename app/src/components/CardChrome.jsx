/**
 * Özet kartları için ortak başlık / rozet / alt not alanı.
 * indicator: React node (renkli nokta vb.)
 */
export default function CardChrome({ copy, indicator, titleAddon, children }) {
  const title = copy?.displayTitle ?? '';
  return (
    <>
      <div className="card-header">
        {indicator}
        <div className="card-header-text">
          <div className="card-title-row">
            <h2>{title}</h2>
            {copy?.badge ? <span className="card-badge">{copy.badge}</span> : null}
            {titleAddon}
          </div>
          {copy?.subtitle ? <p className="card-subtitle">{copy.subtitle}</p> : null}
          {copy?.periodLabel ? <p className="card-period">{copy.periodLabel}</p> : null}
        </div>
      </div>
      {children}
      {copy?.footnote ? <p className="card-footnote">{copy.footnote}</p> : null}
    </>
  );
}
