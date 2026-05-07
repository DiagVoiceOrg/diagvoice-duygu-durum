import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../context/useAuth';
import * as cmsApi from '../services/cmsApi';

function statusBadgeClass(status) {
  switch (status) {
    case 'ok':
      return 'model-health-status model-health-status--ok';
    case 'warn':
      return 'model-health-status model-health-status--warn';
    case 'skipped':
      return 'model-health-status model-health-status--muted';
    case 'fail':
    default:
      return 'model-health-status model-health-status--fail';
  }
}

function statusLabelTr(status) {
  switch (status) {
    case 'ok':
      return 'Tamam';
    case 'warn':
      return 'Uyarı';
    case 'skipped':
      return 'Kapalı';
    case 'fail':
      return 'Hata';
    default:
      return status || '—';
  }
}

export default function AdminModelHealth() {
  const { token, logout } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    setErr('');
    setLoading(true);
    try {
      const json = await cmsApi.fetchModelsHealth(token);
      setData(json);
    } catch (e) {
      if (e.response?.status === 401) logout();
      setErr(
        typeof e.response?.data?.detail === 'string'
          ? e.response.data.detail
          : e.message || 'Kontrol isteği başarısız',
      );
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [token, logout]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="admin-shell-inner">
      <div className="admin-page-head">
        <h1>Model durumu</h1>
        <p style={{ margin: '0.35rem 0 0', color: 'var(--text-muted)', maxWidth: '52rem' }}>
          Dahili çıkarım servislerinin sunucuda ayağa kalkıp yanıt verdiğini kontrol eder (Docker içinden
          8050–8058 ve iş sağlığı Flask <code>/health</code>; Türkçe psik HF için ayrıca{' '}
          <code>/health</code>). Bu sonuç <strong>klinik doğrulama değildir</strong>
          — yalnızca servis yaşam döngüsü, benchmark ve HF ağırlık yükünü bildirir.
        </p>
      </div>

      <div style={{ marginTop: '1.25rem', display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
        <button type="button" className="tab-button secondary" disabled={loading} onClick={() => load()}>
          {loading ? 'Kontrol ediliyor…' : 'Yeniden kontrol et'}
        </button>
        {data?.checked_at ? (
          <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            Son tarama: {new Date(data.checked_at).toLocaleString()}
          </span>
        ) : null}
      </div>

      {err ? (
        <div className="error" style={{ marginTop: '1rem' }}>
          {err}
        </div>
      ) : null}

      {data?.summary ? (
        <div
          className="model-health-summary"
          style={{
            marginTop: '1.25rem',
            display: 'flex',
            flexWrap: 'wrap',
            gap: '0.65rem',
            alignItems: 'center',
          }}
        >
          <span className="model-health-chip model-health-chip--ok">{data.summary.ok} tamam</span>
          {data.summary.warn > 0 ? (
            <span className="model-health-chip model-health-chip--warn">{data.summary.warn} uyarı</span>
          ) : null}
          {data.summary.fail > 0 ? (
            <span className="model-health-chip model-health-chip--fail">{data.summary.fail} hata</span>
          ) : null}
          {data.summary.skipped > 0 ? (
            <span className="model-health-chip">{data.summary.skipped} kapalı</span>
          ) : null}
        </div>
      ) : null}

      {data?.hint ? (
        <div className="cms-banner" style={{ marginTop: '1rem' }}>
          {data.hint}
        </div>
      ) : null}

      {data?.services?.length ? (
        <div className="admin-table-wrap" style={{ marginTop: '1.25rem' }}>
          <table className="admin-table">
            <thead>
              <tr>
                <th>Servis</th>
                <th>Durum</th>
                <th style={{ whiteSpace: 'nowrap' }}>HTTP</th>
                <th style={{ whiteSpace: 'nowrap' }}>Süre (ms)</th>
                <th>İstek URL</th>
                <th>Açıklama / özet</th>
              </tr>
            </thead>
            <tbody>
              {data.services.map((row) => (
                <tr key={row.id}>
                  <td>
                    <strong>{row.label}</strong>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{row.id}</div>
                  </td>
                  <td>
                    <span className={statusBadgeClass(row.status)}>{statusLabelTr(row.status)}</span>
                  </td>
                  <td>{row.http_status != null ? row.http_status : '—'}</td>
                  <td>{row.latency_ms != null ? row.latency_ms : '—'}</td>
                  <td>
                    <code style={{ fontSize: '0.78rem', wordBreak: 'break-all' }}>
                      {row.probe_url || '—'}
                    </code>
                  </td>
                  <td>
                    {row.detail ? <span style={{ fontSize: '0.875rem' }}>{row.detail}</span> : '—'}
                    {row.preview != null ? (
                      <details style={{ marginTop: '0.4rem', fontSize: '0.8rem' }}>
                        <summary>Yanıt özeti</summary>
                        <pre
                          style={{
                            marginTop: '0.35rem',
                            maxHeight: '9rem',
                            overflow: 'auto',
                            background: 'var(--surface-elevated)',
                            padding: '0.45rem',
                            borderRadius: 'var(--radius-md)',
                          }}
                        >
                          {typeof row.preview === 'string'
                            ? row.preview
                            : JSON.stringify(row.preview, null, 2)}
                        </pre>
                      </details>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        !loading &&
        !err && (
          <p style={{ marginTop: '1.5rem', color: 'var(--text-muted)' }}>
            Kontrol etmek için &quot;Yeniden kontrol et&quot;e basın.
          </p>
        )
      )}
    </div>
  );
}
