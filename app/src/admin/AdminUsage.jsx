import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../context/useAuth';
import * as cmsApi from '../services/cmsApi';
import UsageLogDetailModal from './UsageLogDetailModal';

function defaultDateRange() {
  const to = new Date();
  const from = new Date(to.getTime() - 7 * 24 * 60 * 60 * 1000);
  return {
    from: from.toISOString().slice(0, 10),
    to: to.toISOString().slice(0, 10),
  };
}

function auditErrorSummary(row) {
  const d = row?.details;
  if (!d || typeof d !== 'object') return '—';
  if (d.error_summary) return String(d.error_summary);
  if (d.upstream_errors && typeof d.upstream_errors === 'object') {
    const parts = Object.entries(d.upstream_errors).map(
      ([k, v]) => `${k}: ${String(v).slice(0, 80)}`,
    );
    if (parts.length) return parts.join(' · ');
  }
  if (d.upstream_error) return String(d.upstream_error);
  if (d.error_message) return String(d.error_message);
  if (d.detail) return typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail);
  return '—';
}

export default function AdminUsage() {
  const { token, logout } = useAuth();
  const [range, setRange] = useState(defaultDateRange);
  const [summary, setSummary] = useState(null);
  const [logsRes, setLogsRes] = useState(null);
  /** Sunucuya giden filtreler (yazarken tetiklenmez). */
  const [applied, setApplied] = useState({ path: '', min_status: '', outcome: '', skip: 0, limit: 30 });
  const [draftPath, setDraftPath] = useState('');
  const [draftMinStatus, setDraftMinStatus] = useState('');
  const [draftOutcome, setDraftOutcome] = useState('');
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  const fromIso = range.from ? `${range.from}T00:00:00.000Z` : undefined;
  const toIso = range.to ? `${range.to}T23:59:59.999Z` : undefined;

  const loadSummary = useCallback(async () => {
    const json = await cmsApi.fetchUsageSummary(token, { from: fromIso, to: toIso });
    setSummary(json);
  }, [token, fromIso, toIso]);

  const loadLogs = useCallback(async () => {
    const params = {
      skip: applied.skip,
      limit: applied.limit,
      ...(applied.path ? { path: applied.path } : {}),
      ...(applied.min_status !== '' && applied.min_status != null
        ? { min_status: Number(applied.min_status) }
        : {}),
      ...(applied.outcome ? { outcome: applied.outcome } : {}),
      ...(fromIso ? { from: fromIso } : {}),
      ...(toIso ? { to: toIso } : {}),
    };
    const json = await cmsApi.fetchUsageLogs(token, params);
    setLogsRes(json);
  }, [token, applied, fromIso, toIso]);

  const loadAll = useCallback(async () => {
    setErr('');
    setLoading(true);
    try {
      await Promise.all([loadSummary(), loadLogs()]);
    } catch (e) {
      if (e.response?.status === 401) logout();
      setErr(
        typeof e.response?.data?.detail === 'string'
          ? e.response.data.detail
          : e.message || 'Yükleme başarısız',
      );
      setSummary(null);
      setLogsRes(null);
    } finally {
      setLoading(false);
    }
  }, [loadSummary, loadLogs, logout]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  async function openDetail(id) {
    setErr('');
    try {
      const row = await cmsApi.fetchUsageLogDetail(token, id);
      setDetail(row);
    } catch (e) {
      if (e.response?.status === 401) logout();
      setErr(e.response?.data?.detail || e.message || 'Detay yüklenemedi');
    }
  }

  const total = summary?.total ?? 0;
  const byOutcome = summary?.by_outcome || {};
  const success = byOutcome.success ?? 0;
  const clientErr = byOutcome.client_error ?? 0;
  const serverErr = byOutcome.server_error ?? 0;
  const byPath = summary?.by_path || [];
  const maxPathCount = Math.max(1, ...byPath.map((p) => p.count));

  return (
    <div className="admin-shell-inner">
      <div className="admin-page-head">
        <h1>API kullanımı</h1>
        <p style={{ margin: '0.35rem 0 0', color: 'var(--text-muted)', maxWidth: '52rem' }}>
          Fusion (8085) üzerinden kaydedilen istekler: yol, HTTP durumu, süre ve özet ayrıntılar. Hata
          kayıtlarında <code>error_summary</code>, <code>upstream_errors</code> veya doğrulama mesajları
          görünür. Ses içeren istekler <code>data/audio_recordings</code> volume’unda saklanır; detay
          ekranından dinleyebilirsiniz. Tam STT metni varsayılan olarak saklanmaz; sunucuda{' '}
          <code>AUDIT_LOG_INCLUDE_TRANSCRIPT=1</code> ile açılabilir.
        </p>
      </div>

      <div
        style={{
          marginTop: '1rem',
          display: 'flex',
          flexWrap: 'wrap',
          gap: '0.75rem',
          alignItems: 'flex-end',
        }}
      >
        <label style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', fontSize: '0.85rem' }}>
          Başlangıç
          <input
            type="date"
            value={range.from}
            onChange={(e) => setRange((r) => ({ ...r, from: e.target.value }))}
            className="tab-button secondary"
            style={{ padding: '0.35rem 0.5rem' }}
          />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', fontSize: '0.85rem' }}>
          Bitiş
          <input
            type="date"
            value={range.to}
            onChange={(e) => setRange((r) => ({ ...r, to: e.target.value }))}
            className="tab-button secondary"
            style={{ padding: '0.35rem 0.5rem' }}
          />
        </label>
        <button type="button" className="tab-button secondary" disabled={loading} onClick={() => loadAll()}>
          {loading ? 'Yükleniyor…' : 'Yenile'}
        </button>
      </div>

      {err ? (
        <div className="error" style={{ marginTop: '1rem' }}>
          {err}
        </div>
      ) : null}

      {summary ? (
        <div
          style={{
            marginTop: '1.25rem',
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(9rem, 1fr))',
            gap: '0.65rem',
          }}
        >
          <div className="model-health-summary" style={{ padding: '0.75rem 1rem' }}>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Toplam</div>
            <div style={{ fontSize: '1.35rem', fontWeight: 600 }}>{total}</div>
          </div>
          <div className="model-health-summary" style={{ padding: '0.75rem 1rem' }}>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Başarılı (2xx–3xx)</div>
            <div style={{ fontSize: '1.35rem', fontWeight: 600 }}>{success}</div>
          </div>
          <div className="model-health-summary" style={{ padding: '0.75rem 1rem' }}>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>İstemci hatası (4xx)</div>
            <div style={{ fontSize: '1.35rem', fontWeight: 600 }}>{clientErr}</div>
          </div>
          <div className="model-health-summary" style={{ padding: '0.75rem 1rem' }}>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Sunucu hatası (5xx)</div>
            <div style={{ fontSize: '1.35rem', fontWeight: 600 }}>{serverErr}</div>
          </div>
        </div>
      ) : null}

      {byPath.length ? (
        <div style={{ marginTop: '1.25rem' }}>
          <h2 style={{ fontSize: '1rem', marginBottom: '0.5rem' }}>En çok çağrılan yollar</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
            {byPath.map((row) => (
              <div key={row.path} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <div
                  style={{
                    height: '0.55rem',
                    borderRadius: 4,
                    background: 'var(--accent, #3b82f6)',
                    width: `${Math.round((row.count / maxPathCount) * 100)}%`,
                    maxWidth: '100%',
                    minWidth: '4%',
                  }}
                />
                <span style={{ fontSize: '0.8rem', whiteSpace: 'nowrap' }}>
                  {row.count}× {row.path}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div style={{ marginTop: '1.5rem' }}>
        <h2 style={{ fontSize: '1rem', marginBottom: '0.5rem' }}>Loglar</h2>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.75rem' }}>
          <input
            placeholder="path öneki (ör. /analyze)"
            value={draftPath}
            onChange={(e) => setDraftPath(e.target.value)}
            style={{ minWidth: '12rem', padding: '0.35rem 0.5rem' }}
          />
          <input
            placeholder="min HTTP status"
            value={draftMinStatus}
            onChange={(e) => setDraftMinStatus(e.target.value)}
            style={{ width: '8rem', padding: '0.35rem 0.5rem' }}
          />
          <select
            value={draftOutcome}
            onChange={(e) => setDraftOutcome(e.target.value)}
            style={{ padding: '0.35rem 0.5rem' }}
          >
            <option value="">tüm sonuçlar</option>
            <option value="success">success</option>
            <option value="client_error">client_error</option>
            <option value="server_error">server_error</option>
          </select>
          <button
            type="button"
            className="tab-button secondary"
            onClick={() => {
              setApplied((a) => ({
                ...a,
                path: draftPath.trim(),
                min_status: draftMinStatus.trim(),
                outcome: draftOutcome.trim(),
                skip: 0,
              }));
            }}
          >
            Filtrele
          </button>
        </div>

        <div style={{ overflowX: 'auto' }}>
          <table className="admin-table" style={{ width: '100%', fontSize: '0.85rem' }}>
            <thead>
              <tr>
                <th>Zaman (UTC)</th>
                <th>Yol</th>
                <th>Metod</th>
                <th>HTTP</th>
                <th>ms</th>
                <th>Hata özeti</th>
                <th>Ses</th>
                <th>IP</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(logsRes?.items || []).map((row) => (
                <tr key={row.id}>
                  <td>{row.created_at ? String(row.created_at).replace('T', ' ').slice(0, 19) : '—'}</td>
                  <td>
                    <code>{row.path}</code>
                  </td>
                  <td>{row.method}</td>
                  <td>{row.http_status}</td>
                  <td>{row.duration_ms}</td>
                  <td
                    title={auditErrorSummary(row)}
                    style={{ maxWidth: '18rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  >
                    {auditErrorSummary(row)}
                  </td>
                  <td>
                    {row.has_audio || row.audio_recording ? (
                      <span style={{ fontSize: '0.8rem', color: 'var(--accent, #3b82f6)' }}>Kayıt var</span>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td title={row.client_ip || ''}>{(row.client_ip || '').slice(0, 24) || '—'}</td>
                  <td>
                    <button type="button" className="tab-button secondary" onClick={() => openDetail(row.id)}>
                      {row.has_audio || row.audio_recording ? 'Detay / Dinle' : 'Detay'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div style={{ marginTop: '0.75rem', display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <button
            type="button"
            className="tab-button secondary"
            disabled={!logsRes || applied.skip <= 0}
            onClick={() => setApplied((f) => ({ ...f, skip: Math.max(0, f.skip - f.limit) }))}
          >
            Önceki
          </button>
          <button
            type="button"
            className="tab-button secondary"
            disabled={!logsRes || applied.skip + applied.limit >= (logsRes.total || 0)}
            onClick={() => setApplied((f) => ({ ...f, skip: f.skip + f.limit }))}
          >
            Sonraki
          </button>
          <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            {logsRes
              ? `${applied.skip + 1}–${Math.min(applied.skip + applied.limit, logsRes.total)} / ${logsRes.total}`
              : ''}
          </span>
        </div>
      </div>

      {detail ? (
        <UsageLogDetailModal log={detail} token={token} onClose={() => setDetail(null)} />
      ) : null}
    </div>
  );
}
