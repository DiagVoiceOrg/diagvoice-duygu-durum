import { useEffect, useState } from 'react';
import * as cmsApi from '../services/cmsApi';

function formatBytes(n) {
  if (n == null || Number.isNaN(Number(n))) return '';
  const v = Number(n);
  if (v < 1024) return `${v} B`;
  if (v < 1024 * 1024) return `${(v / 1024).toFixed(1)} KB`;
  return `${(v / (1024 * 1024)).toFixed(1)} MB`;
}

export default function UsageAudioPlayer({ token, logId, recording }) {
  const [src, setSrc] = useState(null);
  const [loadErr, setLoadErr] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!token || !logId || !recording) {
      setSrc(null);
      return undefined;
    }

    let objectUrl;
    let cancelled = false;
    setLoading(true);
    setLoadErr('');

    cmsApi
      .fetchUsageLogAudio(token, logId)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      })
      .catch((e) => {
        if (cancelled) return;
        setLoadErr(
          typeof e.response?.data?.detail === 'string'
            ? e.response.data.detail
            : e.message || 'Ses yüklenemedi',
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [token, logId, recording]);

  if (!recording) return null;

  const label = recording.original_filename || 'Ses kaydı';
  const meta = [formatBytes(recording.bytes), recording.content_type].filter(Boolean).join(' · ');

  return (
    <div
      style={{
        marginTop: '0.75rem',
        padding: '0.75rem',
        borderRadius: 6,
        border: '1px solid rgba(255,255,255,0.12)',
        background: 'rgba(255,255,255,0.04)',
      }}
    >
      <div style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.25rem' }}>Ses kaydı</div>
      <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
        {label}
        {meta ? ` (${meta})` : ''}
      </div>
      {loading ? <div style={{ fontSize: '0.85rem' }}>Ses yükleniyor…</div> : null}
      {loadErr ? <div className="error">{loadErr}</div> : null}
      {src ? (
        <audio controls preload="metadata" src={src} style={{ width: '100%' }}>
          Tarayıcınız ses oynatmayı desteklemiyor.
        </audio>
      ) : null}
    </div>
  );
}
