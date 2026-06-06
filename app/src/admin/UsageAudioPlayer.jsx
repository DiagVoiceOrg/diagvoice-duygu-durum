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
    <div className="usage-audio-panel">
      <div className="usage-audio-panel-title">Ses kaydı</div>
      <div className="usage-audio-panel-meta">
        {label}
        {meta ? ` (${meta})` : ''}
      </div>
      {loading ? <div className="usage-audio-loading">Ses yükleniyor…</div> : null}
      {loadErr ? <div className="error">{loadErr}</div> : null}
      {src ? (
        <audio controls preload="metadata" src={src} className="usage-audio-element">
          Tarayıcınız ses oynatmayı desteklemiyor.
        </audio>
      ) : null}
    </div>
  );
}
