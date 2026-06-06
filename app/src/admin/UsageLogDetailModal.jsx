import { useState } from 'react';
import JsonBlock from './JsonBlock';
import UsageAudioPlayer from './UsageAudioPlayer';
import {
  formatLogTime,
  highlightFields,
  outcomeLabel,
  parseUsageLogDetail,
} from './usageLogDetail';

function MetaChip({ label, value }) {
  if (value == null || value === '') return null;
  return (
    <div className="usage-meta-chip">
      <span className="usage-meta-chip-label">{label}</span>
      <span className="usage-meta-chip-value">{value}</span>
    </div>
  );
}

function ModelSectionCard({ section }) {
  const highlights = highlightFields(section.data);
  const isError = section.kind === 'error' || Boolean(section.error);

  return (
    <article className={`usage-model-card${isError ? ' usage-model-card--error' : ''}`}>
      <header className="usage-model-card-head">
        <h3>{section.title}</h3>
        {section.error ? <span className="usage-badge usage-badge--error">Hata</span> : null}
      </header>
      {section.error ? <p className="usage-model-error">{String(section.error)}</p> : null}
      {highlights.length ? (
        <dl className="usage-highlight-dl">
          {highlights.map(({ key, value }) => (
            <div key={key} className="usage-highlight-row">
              <dt>{key}</dt>
              <dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {section.data != null ? (
        <JsonBlock value={section.data} title="Tam model yanıtı (JSON)" defaultOpen={!highlights.length} />
      ) : null}
    </article>
  );
}

export default function UsageLogDetailModal({ log, token, onClose }) {
  const [tab, setTab] = useState('models');
  const parsed = parseUsageLogDetail(log);
  const badge = outcomeLabel(parsed.meta.outcome, parsed.meta.http_status);
  const hasModels = parsed.models.length > 0;
  const hasErrors = parsed.errors.length > 0;

  return (
    <div className="usage-log-overlay" role="dialog" aria-modal onClick={onClose}>
      <div className="usage-log-modal" onClick={(e) => e.stopPropagation()}>
        <header className="usage-log-modal-head">
          <div>
            <h2>Log detayı</h2>
            <p className="usage-log-modal-sub">
              <code>{parsed.meta.path}</code>
              <span className={`usage-badge ${badge.className}`}>{badge.text}</span>
            </p>
          </div>
          <button type="button" className="tab-button secondary" onClick={onClose}>
            Kapat
          </button>
        </header>

        <div className="usage-meta-grid">
          <MetaChip label="Zaman (UTC)" value={formatLogTime(parsed.meta.created_at)} />
          <MetaChip label="Süre" value={parsed.meta.duration_ms != null ? `${parsed.meta.duration_ms} ms` : null} />
          <MetaChip label="HTTP" value={parsed.meta.http_status} />
          <MetaChip label="IP" value={parsed.meta.client_ip} />
          <MetaChip label="Dosya" value={parsed.meta.filename} />
          <MetaChip label="Boyut" value={parsed.meta.file_bytes != null ? `${parsed.meta.file_bytes} B` : null} />
          <MetaChip label="Upstream HTTP" value={parsed.meta.upstream_http} />
          <MetaChip label="Dil" value={parsed.meta.speech_language} />
        </div>

        {log.has_audio || log.audio_recording ? (
          <UsageAudioPlayer token={token} logId={log.id} recording={log.audio_recording || { id: log.id }} />
        ) : null}

        <div className="usage-log-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'models'}
            className={tab === 'models' ? 'usage-log-tab usage-log-tab--active' : 'usage-log-tab'}
            onClick={() => setTab('models')}
          >
            Model cevapları
            {hasModels ? ` (${parsed.models.length})` : ''}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'json'}
            className={tab === 'json' ? 'usage-log-tab usage-log-tab--active' : 'usage-log-tab'}
            onClick={() => setTab('json')}
          >
            Ham JSON
          </button>
        </div>

        <div className="usage-log-modal-body">
          {tab === 'models' ? (
            <div className="usage-models-panel">
              {hasErrors ? (
                <section className="usage-errors-panel">
                  <h3 className="usage-section-title">Hatalar</h3>
                  {parsed.errors.map((err) => (
                    <article key={err.id} className="usage-error-card">
                      <strong>{err.title}</strong>
                      {err.summary ? <p>{err.summary}</p> : null}
                      {err.detail != null && err.detail !== err.summary ? (
                        <JsonBlock value={err.detail} title="Hata detayı" defaultOpen={false} maxHeight="12rem" />
                      ) : null}
                    </article>
                  ))}
                </section>
              ) : null}

              {hasModels ? (
                parsed.models.map((section) => <ModelSectionCard key={section.id} section={section} />)
              ) : (
                <p className="usage-empty-hint">
                  Bu kayıtta yapılandırılmış model yanıtı yok. Eski proxy logları yalnızca metadata içerebilir;
                  yeni isteklerde model cevabı burada görünür. Ham veri için <strong>Ham JSON</strong> sekmesine
                  bakın.
                </p>
              )}
            </div>
          ) : (
            <JsonBlock value={log} title="Tüm log kaydı" defaultOpen maxHeight="min(50vh, 28rem)" />
          )}
        </div>
      </div>
    </div>
  );
}
