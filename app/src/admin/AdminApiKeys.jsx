import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../context/useAuth';
import * as cmsApi from '../services/cmsApi';

const TYPE_LABELS = { sk: 'Sunucu (gizli)', pk: 'Tarayıcı' };

const EMPTY_CLIENT_FORM = { name: '', contact_email: '', notes: '' };

const EMPTY_KEY_FORM = {
  type: 'sk',
  name: '',
  scopes: [],
  origins: '',
  rpm: '120',
  max_concurrent: '5',
  monthly_quota: '0',
  expires: '',
};

const fieldStyle = {
  font: 'inherit',
  padding: '0.5rem 0.65rem',
  borderRadius: 'var(--radius-md)',
  border: '1px solid var(--border)',
  background: 'var(--surface)',
  color: 'var(--text-main)',
};

const mutedText = { fontSize: '0.8rem', color: 'var(--text-muted)' };

/** FastAPI hata gövdesini okunur metne çevirir (`detail` string veya 422 listesi). */
function errMsg(e, fallback) {
  const detail = e?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((d) => {
      const loc = Array.isArray(d?.loc) ? d.loc.filter((p) => p !== 'body').join('.') : '';
      return loc ? `${loc}: ${d?.msg ?? ''}` : String(d?.msg ?? JSON.stringify(d));
    });
    if (parts.length) return parts.join(' · ');
  }
  return e?.message || fallback;
}

function fmtTime(v) {
  return v ? String(v).replace('T', ' ').slice(0, 16) : '—';
}

function limitText(v) {
  const n = Number(v);
  return !n ? 'sınırsız' : String(n);
}

function scopeLabel(scope, scopes) {
  if (scope === '*') return 'Tüm analizler';
  return scopes.find((s) => s.scope === scope)?.title || scope;
}

/* ---------- Tek seferlik anahtar gösterimi ---------- */

function RevealedKeyModal({ revealed, onClose }) {
  const [copyState, setCopyState] = useState('');

  async function copy() {
    try {
      await navigator.clipboard.writeText(revealed.apiKey);
      setCopyState('Kopyalandı');
    } catch {
      setCopyState('Kopyalanamadı — anahtarı elle seçip kopyalayın.');
    }
  }

  return (
    <div className="usage-log-overlay" role="dialog" aria-modal aria-labelledby="revealed-key-title">
      <div className="usage-log-modal" style={{ width: 'min(40rem, 100%)' }}>
        <header className="usage-log-modal-head">
          <div>
            <h2 id="revealed-key-title">{revealed.title}</h2>
            <p className="usage-log-modal-sub">
              {revealed.keyName ? <span>{revealed.keyName}</span> : null}
              {revealed.clientName ? <span>· {revealed.clientName}</span> : null}
            </p>
          </div>
        </header>
        <div className="usage-log-modal-body" style={{ paddingTop: '1rem' }}>
          <div className="error" style={{ marginTop: 0 }}>
            Bu anahtar yalnızca şimdi gösterilir. Pencereyi kapattıktan sonra tekrar görüntülenemez; kopyalayıp
            müşteriye güvenli bir kanaldan iletin.
            {revealed.warning ? <div style={{ marginTop: '0.35rem', fontSize: '0.85rem' }}>{revealed.warning}</div> : null}
          </div>
          <code
            style={{
              display: 'block',
              marginTop: '1rem',
              padding: '0.75rem',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border)',
              background: 'var(--surface)',
              fontSize: '0.9rem',
              wordBreak: 'break-all',
              userSelect: 'all',
            }}
          >
            {revealed.apiKey}
          </code>
          <div className="admin-actions" style={{ marginTop: '1rem', alignItems: 'center' }}>
            <button type="button" className="tab-button active" onClick={copy}>
              Kopyala
            </button>
            <button type="button" className="tab-button secondary" onClick={onClose}>
              Kaydettim, kapat
            </button>
            {copyState ? <span style={mutedText}>{copyState}</span> : null}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------- Kullanım ---------- */

function KeyUsageModal({ apiKey, token, logout, onClose }) {
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    setErr('');
    setLoading(true);
    try {
      const json = await cmsApi.fetchApiKeyUsage(token, apiKey.key_id, days);
      setData(json);
    } catch (e) {
      if (e.response?.status === 401) logout();
      setErr(errMsg(e, 'Kullanım yüklenemedi'));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [token, apiKey.key_id, days, logout]);

  useEffect(() => {
    load();
  }, [load]);

  const daily = data?.daily || [];

  return (
    <div className="usage-log-overlay" role="dialog" aria-modal onClick={onClose}>
      <div className="usage-log-modal" style={{ width: 'min(44rem, 100%)' }} onClick={(e) => e.stopPropagation()}>
        <header className="usage-log-modal-head">
          <div>
            <h2>Kullanım — {apiKey.name}</h2>
            <p className="usage-log-modal-sub">
              <code>{apiKey.masked}</code>
              {apiKey.client_name ? <span>· {apiKey.client_name}</span> : null}
            </p>
          </div>
          <button type="button" className="tab-button secondary" onClick={onClose}>
            Kapat
          </button>
        </header>
        <div className="usage-log-modal-body" style={{ paddingTop: '1rem' }}>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <select value={days} onChange={(e) => setDays(Number(e.target.value))} style={fieldStyle}>
              <option value={7}>Son 7 gün</option>
              <option value={30}>Son 30 gün</option>
              <option value={90}>Son 90 gün</option>
            </select>
            <button type="button" className="tab-button secondary" disabled={loading} onClick={() => load()}>
              {loading ? 'Yükleniyor…' : 'Yenile'}
            </button>
          </div>

          {err ? <div className="error" style={{ marginTop: '1rem' }}>{err}</div> : null}

          {data ? (
            <>
              <div className="model-health-summary" style={{ padding: '0.75rem 1rem', marginTop: '1rem', maxWidth: '16rem' }}>
                <div style={mutedText}>Bu ay ({data.month})</div>
                <div style={{ fontSize: '1.35rem', fontWeight: 600 }}>
                  {data.month_total ?? 0}
                  {Number(data.key?.limits?.monthly_quota) ? (
                    <span style={{ ...mutedText, fontWeight: 400 }}> / {data.key.limits.monthly_quota}</span>
                  ) : null}
                </div>
              </div>
              <div className="admin-table-wrap" style={{ marginTop: '1rem' }}>
                <table className="admin-table" style={{ fontSize: '0.85rem' }}>
                  <thead>
                    <tr>
                      <th>Tarih</th>
                      <th>Yol</th>
                      <th>İstek</th>
                      <th>Hata</th>
                    </tr>
                  </thead>
                  <tbody>
                    {daily.length ? (
                      daily.map((row) => (
                        <tr key={`${row.date}-${row.route}`}>
                          <td>{row.date}</td>
                          <td>
                            <code>{row.route}</code>
                          </td>
                          <td>{row.count}</td>
                          <td style={row.errors ? { color: '#b91c1c', fontWeight: 600 } : undefined}>{row.errors}</td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={4} style={mutedText}>
                          Bu aralıkta kullanım yok.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/* ---------- Anahtar oluşturma formu ---------- */

function KeyCreateForm({ token, logout, clients, scopes, defaultClientId, onCreated, onCancel }) {
  const [clientId, setClientId] = useState(defaultClientId || '');
  const [form, setForm] = useState(EMPTY_KEY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState('');

  const activeClients = clients.filter((c) => c.status === 'active');
  const isPk = form.type === 'pk';

  function patch(p) {
    setForm((f) => ({ ...f, ...p }));
  }

  function toggleScope(scope) {
    setForm((f) => ({
      ...f,
      scopes: f.scopes.includes(scope) ? f.scopes.filter((s) => s !== scope) : [...f.scopes, scope],
    }));
  }

  async function submit(e) {
    e.preventDefault();
    setErr('');
    const name = form.name.trim();
    const origins = form.origins
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (!clientId) return setErr('Önce bir müşteri seçin.');
    if (name.length < 2 || name.length > 120) return setErr('Anahtar adı 2–120 karakter olmalı.');
    if (!form.scopes.length) return setErr('En az bir kapsam seçin.');
    if (isPk && !origins.length) return setErr('Tarayıcı anahtarı için en az bir izinli origin girin.');

    const limits = {};
    for (const k of ['rpm', 'max_concurrent', 'monthly_quota']) {
      const raw = String(form[k]).trim();
      if (raw === '') continue;
      const n = Number(raw);
      if (!Number.isInteger(n) || n < 0) return setErr('Limitler 0 veya pozitif tam sayı olmalı.');
      limits[k] = n;
    }

    const body = {
      type: form.type,
      name,
      scopes: form.scopes,
      allowed_origins: isPk ? origins : [],
      limits,
      expires_at: form.expires ? `${form.expires}T23:59:59Z` : null,
    };

    setSubmitting(true);
    try {
      const res = await cmsApi.createApiKey(token, clientId, body);
      setForm(EMPTY_KEY_FORM);
      onCreated(res);
    } catch (e2) {
      if (e2.response?.status === 401) logout();
      setErr(errMsg(e2, 'Anahtar oluşturulamadı'));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      className="admin-form admin-form-wide"
      onSubmit={submit}
      style={{
        marginTop: '1rem',
        padding: '1rem',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border)',
        background: 'var(--surface-elevated, var(--surface))',
      }}
    >
      <h3 style={{ margin: 0 }}>Anahtar oluştur</h3>
      {err ? <div className="error" style={{ marginTop: 0 }}>{err}</div> : null}

      <div style={{ display: 'flex', gap: '0.85rem', flexWrap: 'wrap' }}>
        <label style={{ flex: '1 1 14rem' }}>
          Müşteri
          <select value={clientId} onChange={(e) => setClientId(e.target.value)} required>
            <option value="">Seçin…</option>
            {activeClients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label style={{ flex: '1 1 14rem' }}>
          Tür
          <select value={form.type} onChange={(e) => patch({ type: e.target.value })}>
            <option value="sk">Sunucu (gizli) — sk</option>
            <option value="pk">Tarayıcı — pk</option>
          </select>
        </label>
      </div>
      <span style={{ ...mutedText, marginTop: '-0.5rem' }}>
        {isPk
          ? 'Tarayıcı anahtarı yalnızca aşağıdaki origin’lerden gelen isteklerde geçerlidir; ön yüz koduna gömülebilir.'
          : 'Sunucu anahtarı gizlidir; yalnızca müşterinin arka ucunda kullanılmalı, tarayıcıya konmamalıdır.'}
      </span>

      <label>
        Anahtar adı
        <input
          type="text"
          value={form.name}
          onChange={(e) => patch({ name: e.target.value })}
          placeholder="ör. TOGG üretim"
          minLength={2}
          maxLength={120}
          required
        />
      </label>

      <fieldset style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', padding: '0.65rem 0.85rem' }}>
        <legend style={{ fontSize: '0.875rem', fontWeight: 600, padding: '0 0.25rem' }}>Kapsamlar</legend>
        {scopes.length ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(15rem, 1fr))', gap: '0.4rem 1rem' }}>
            {scopes.map((s) => (
              <label
                key={s.scope}
                style={{ flexDirection: 'row', alignItems: 'flex-start', gap: '0.45rem', fontWeight: 400 }}
              >
                <input
                  type="checkbox"
                  checked={form.scopes.includes(s.scope)}
                  onChange={() => toggleScope(s.scope)}
                  style={{ marginTop: '0.2rem' }}
                />
                <span>
                  <span style={{ fontWeight: s.scope === '*' ? 700 : 600 }}>{scopeLabel(s.scope, scopes)}</span>
                  <br />
                  <code style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{s.path || s.scope}</code>
                </span>
              </label>
            ))}
          </div>
        ) : (
          <span style={mutedText}>Kapsam listesi yüklenemedi.</span>
        )}
      </fieldset>

      {isPk ? (
        <label>
          İzinli origin’ler (her satıra bir tane)
          <textarea
            value={form.origins}
            onChange={(e) => patch({ origins: e.target.value })}
            placeholder={'https://app.ornek.com\nhttps://staging.ornek.com'}
            style={{ minHeight: '6rem' }}
            required
          />
        </label>
      ) : null}

      <div style={{ display: 'flex', gap: '0.85rem', flexWrap: 'wrap' }}>
        <label style={{ flex: '1 1 9rem' }}>
          Dakikada istek (rpm)
          <input type="number" min={0} step={1} value={form.rpm} onChange={(e) => patch({ rpm: e.target.value })} style={fieldStyle} />
        </label>
        <label style={{ flex: '1 1 9rem' }}>
          Eşzamanlı istek
          <input
            type="number"
            min={0}
            step={1}
            value={form.max_concurrent}
            onChange={(e) => patch({ max_concurrent: e.target.value })}
            style={fieldStyle}
          />
        </label>
        <label style={{ flex: '1 1 9rem' }}>
          Aylık kota
          <input
            type="number"
            min={0}
            step={1}
            value={form.monthly_quota}
            onChange={(e) => patch({ monthly_quota: e.target.value })}
            style={fieldStyle}
          />
        </label>
        <label style={{ flex: '1 1 9rem' }}>
          Son kullanma (isteğe bağlı)
          <input type="date" value={form.expires} onChange={(e) => patch({ expires: e.target.value })} style={fieldStyle} />
        </label>
      </div>
      <span style={{ ...mutedText, marginTop: '-0.5rem' }}>0 = sınırsız. Son kullanma tarihi boşsa anahtar süresizdir.</span>

      <div className="admin-actions">
        <button type="submit" className="tab-button active" disabled={submitting}>
          {submitting ? 'Oluşturuluyor…' : 'Anahtar oluştur'}
        </button>
        <button type="button" className="tab-button secondary" disabled={submitting} onClick={onCancel}>
          Vazgeç
        </button>
      </div>
    </form>
  );
}

/* ---------- Sayfa ---------- */

export default function AdminApiKeys() {
  const { token, logout } = useAuth();

  const [scopes, setScopes] = useState([]);
  const [clients, setClients] = useState([]);
  const [clientsLoading, setClientsLoading] = useState(false);
  const [clientsErr, setClientsErr] = useState('');

  const [selectedClientId, setSelectedClientId] = useState('');
  const [keys, setKeys] = useState([]);
  const [keysLoading, setKeysLoading] = useState(false);
  const [keysErr, setKeysErr] = useState('');

  const [clientForm, setClientForm] = useState(EMPTY_CLIENT_FORM);
  const [clientSubmitting, setClientSubmitting] = useState(false);
  const [clientFormErr, setClientFormErr] = useState('');
  const [busyClientId, setBusyClientId] = useState('');

  const [showKeyForm, setShowKeyForm] = useState(false);
  const [busyKeyId, setBusyKeyId] = useState('');
  const [actionErr, setActionErr] = useState('');

  /** Tam anahtar yalnızca bu state'te, modal kapanınca silinir. */
  const [revealed, setRevealed] = useState(null);
  const [usageKey, setUsageKey] = useState(null);

  const loadClients = useCallback(async () => {
    setClientsErr('');
    setClientsLoading(true);
    try {
      const [clientsRes, scopesRes] = await Promise.all([cmsApi.listApiClients(token), cmsApi.listApiScopes(token)]);
      setClients(clientsRes?.items || []);
      setScopes(scopesRes?.scopes || []);
    } catch (e) {
      if (e.response?.status === 401) logout();
      setClientsErr(errMsg(e, 'Müşteriler yüklenemedi'));
    } finally {
      setClientsLoading(false);
    }
  }, [token, logout]);

  const loadKeys = useCallback(async () => {
    setKeysErr('');
    setKeysLoading(true);
    try {
      const res = await cmsApi.listApiKeys(token, selectedClientId || undefined);
      setKeys(res?.items || []);
    } catch (e) {
      if (e.response?.status === 401) logout();
      setKeysErr(errMsg(e, 'Anahtarlar yüklenemedi'));
      setKeys([]);
    } finally {
      setKeysLoading(false);
    }
  }, [token, logout, selectedClientId]);

  useEffect(() => {
    loadClients();
  }, [loadClients]);

  useEffect(() => {
    loadKeys();
  }, [loadKeys]);

  async function submitClient(e) {
    e.preventDefault();
    setClientFormErr('');
    const name = clientForm.name.trim();
    if (name.length < 2 || name.length > 120) {
      setClientFormErr('Müşteri adı 2–120 karakter olmalı.');
      return;
    }
    const body = { name };
    if (clientForm.contact_email.trim()) body.contact_email = clientForm.contact_email.trim();
    if (clientForm.notes.trim()) body.notes = clientForm.notes.trim();
    setClientSubmitting(true);
    try {
      const created = await cmsApi.createApiClient(token, body);
      setClientForm(EMPTY_CLIENT_FORM);
      await loadClients();
      if (created?.id) setSelectedClientId(created.id);
    } catch (e2) {
      if (e2.response?.status === 401) logout();
      setClientFormErr(errMsg(e2, 'Müşteri oluşturulamadı'));
    } finally {
      setClientSubmitting(false);
    }
  }

  async function toggleClient(c) {
    const next = c.status === 'active' ? 'disabled' : 'active';
    if (
      next === 'disabled' &&
      !window.confirm(`"${c.name}" devre dışı bırakılsın mı? Bu müşterinin tüm anahtarları istek kabul etmez.`)
    ) {
      return;
    }
    setActionErr('');
    setBusyClientId(c.id);
    try {
      const updated = await cmsApi.updateApiClient(token, c.id, { status: next });
      setClients((list) => list.map((x) => (x.id === c.id ? { ...x, ...updated } : x)));
    } catch (e) {
      if (e.response?.status === 401) logout();
      setActionErr(errMsg(e, 'Müşteri güncellenemedi'));
    } finally {
      setBusyClientId('');
    }
  }

  async function onKeyCreated(res) {
    setShowKeyForm(false);
    setRevealed({
      title: 'Yeni API anahtarı',
      apiKey: res.api_key,
      warning: res.warning,
      keyName: res.key?.name,
      clientName: res.key?.client_name,
    });
    await loadKeys();
  }

  async function rotateKey(k) {
    if (
      !window.confirm(
        `"${k.name}" anahtarı yenilensin mi?\n\nMevcut anahtar hemen iptal edilir ve yeni bir anahtar üretilir. Müşterinin yeni anahtarı kullanması gerekir.`,
      )
    ) {
      return;
    }
    setActionErr('');
    setBusyKeyId(k.key_id);
    try {
      const res = await cmsApi.rotateApiKey(token, k.key_id);
      setRevealed({
        title: 'Yenilenen API anahtarı',
        apiKey: res.api_key,
        warning: res.warning,
        keyName: res.key?.name,
        clientName: res.key?.client_name,
      });
      await loadKeys();
    } catch (e) {
      if (e.response?.status === 401) logout();
      setActionErr(errMsg(e, 'Anahtar yenilenemedi'));
    } finally {
      setBusyKeyId('');
    }
  }

  async function revokeKey(k) {
    if (
      !window.confirm(
        `"${k.name}" (${k.masked}) iptal edilsin mi?\n\nBu işlem geri alınamaz; anahtarla yapılan tüm istekler hemen reddedilir.`,
      )
    ) {
      return;
    }
    setActionErr('');
    setBusyKeyId(k.key_id);
    try {
      const updated = await cmsApi.revokeApiKey(token, k.key_id);
      setKeys((list) => list.map((x) => (x.key_id === k.key_id ? { ...x, ...updated } : x)));
    } catch (e) {
      if (e.response?.status === 401) logout();
      setActionErr(errMsg(e, 'Anahtar iptal edilemedi'));
    } finally {
      setBusyKeyId('');
    }
  }

  const selectedClient = clients.find((c) => c.id === selectedClientId) || null;

  return (
    <div className="admin-shell-inner">
      <div className="admin-page-head">
        <h1>API Anahtarları</h1>
        <p style={{ margin: '0.35rem 0 0', color: 'var(--text-muted)', maxWidth: '52rem' }}>
          Dış müşteriler (ör. TOGG) için müşteri kaydı ve <code>/v1</code> API anahtarları. Tam anahtar yalnızca
          oluşturma veya yenileme anında bir kez gösterilir; listede yalnızca maskelenmiş hali görünür.
        </p>
      </div>

      {actionErr ? <div className="error" style={{ marginTop: '1rem' }}>{actionErr}</div> : null}

      <div
        style={{
          marginTop: '1.25rem',
          display: 'flex',
          flexWrap: 'wrap',
          gap: '1.5rem',
          alignItems: 'flex-start',
        }}
      >
        {/* Müşteriler */}
        <section style={{ flex: '1 1 16rem', maxWidth: '22rem', minWidth: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.5rem' }}>
            <h2 style={{ fontSize: '1rem', margin: 0 }}>Müşteriler</h2>
            <button type="button" className="tab-button secondary" disabled={clientsLoading} onClick={() => loadClients()}>
              {clientsLoading ? 'Yükleniyor…' : 'Yenile'}
            </button>
          </div>
          {clientsErr ? <div className="error" style={{ marginTop: '0.75rem' }}>{clientsErr}</div> : null}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', marginTop: '0.75rem' }}>
            <button
              type="button"
              className={`tab-button ${selectedClientId === '' ? 'active' : 'secondary'}`}
              style={{ textAlign: 'left' }}
              onClick={() => setSelectedClientId('')}
            >
              Tüm müşteriler
            </button>
            {clients.map((c) => (
              <div
                key={c.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                }}
              >
                <button
                  type="button"
                  className={`tab-button ${selectedClientId === c.id ? 'active' : 'secondary'}`}
                  style={{ flex: 1, textAlign: 'left', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}
                  title={[c.contact_email, c.notes].filter(Boolean).join(' · ') || c.name}
                  onClick={() => setSelectedClientId(c.id)}
                >
                  {c.name}
                  {c.status !== 'active' ? ' (pasif)' : ''}
                </button>
                <button
                  type="button"
                  className={`tab-button secondary${c.status === 'active' ? ' btn-danger' : ''}`}
                  disabled={busyClientId === c.id}
                  onClick={() => toggleClient(c)}
                  style={{ whiteSpace: 'nowrap' }}
                >
                  {busyClientId === c.id ? '…' : c.status === 'active' ? 'Devre dışı' : 'Etkinleştir'}
                </button>
              </div>
            ))}
            {!clientsLoading && !clientsErr && clients.length === 0 ? (
              <span style={mutedText}>Henüz müşteri yok.</span>
            ) : null}
          </div>

          <form className="admin-form" style={{ marginTop: '1.25rem' }} onSubmit={submitClient}>
            <h3 style={{ margin: 0, fontSize: '0.95rem' }}>Yeni müşteri</h3>
            {clientFormErr ? <div className="error" style={{ marginTop: 0 }}>{clientFormErr}</div> : null}
            <label>
              Ad
              <input
                type="text"
                value={clientForm.name}
                onChange={(e) => setClientForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="ör. TOGG"
                minLength={2}
                maxLength={120}
                required
              />
            </label>
            <label>
              E-posta
              <input
                type="email"
                value={clientForm.contact_email}
                onChange={(e) => setClientForm((f) => ({ ...f, contact_email: e.target.value }))}
                placeholder="iletisim@ornek.com"
              />
            </label>
            <label>
              Not
              <textarea
                value={clientForm.notes}
                onChange={(e) => setClientForm((f) => ({ ...f, notes: e.target.value }))}
                style={{ minHeight: '4rem', fontFamily: 'inherit', fontSize: '0.875rem' }}
              />
            </label>
            <div className="admin-actions">
              <button type="submit" className="tab-button active" disabled={clientSubmitting}>
                {clientSubmitting ? 'Kaydediliyor…' : 'Müşteri ekle'}
              </button>
            </div>
          </form>
        </section>

        {/* Anahtarlar */}
        <section style={{ flex: '3 1 30rem', minWidth: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
            <h2 style={{ fontSize: '1rem', margin: 0 }}>
              Anahtarlar{selectedClient ? ` — ${selectedClient.name}` : ''}
            </h2>
            <div className="admin-actions">
              <button type="button" className="tab-button secondary" disabled={keysLoading} onClick={() => loadKeys()}>
                {keysLoading ? 'Yükleniyor…' : 'Yenile'}
              </button>
              <button
                type="button"
                className="tab-button active"
                disabled={showKeyForm || clients.every((c) => c.status !== 'active')}
                onClick={() => setShowKeyForm(true)}
              >
                Anahtar oluştur
              </button>
            </div>
          </div>

          {showKeyForm ? (
            <KeyCreateForm
              key={selectedClientId || 'all'}
              token={token}
              logout={logout}
              clients={clients}
              scopes={scopes}
              defaultClientId={selectedClient?.status === 'active' ? selectedClientId : ''}
              onCreated={onKeyCreated}
              onCancel={() => setShowKeyForm(false)}
            />
          ) : null}

          {keysErr ? <div className="error" style={{ marginTop: '1rem' }}>{keysErr}</div> : null}

          <div className="admin-table-wrap" style={{ marginTop: '1rem' }}>
            <table className="admin-table" style={{ fontSize: '0.85rem' }}>
              <thead>
                <tr>
                  <th>Anahtar</th>
                  <th>Tür</th>
                  <th>Kapsamlar</th>
                  <th>Limitler</th>
                  <th>Durum</th>
                  <th>Son kullanım</th>
                  <th>Oluşturma</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => {
                  const active = k.status === 'active';
                  const busy = busyKeyId === k.key_id;
                  return (
                    <tr key={k.key_id} style={active ? undefined : { opacity: 0.65 }}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{k.name}</div>
                        <code style={{ fontSize: '0.78rem' }}>{k.masked}</code>
                        {!selectedClientId && k.client_name ? <div style={mutedText}>{k.client_name}</div> : null}
                      </td>
                      <td>
                        <span className={`usage-badge ${k.type === 'sk' ? 'usage-badge--warn' : 'usage-badge--neutral'}`}>
                          {TYPE_LABELS[k.type] || k.type}
                        </span>
                        {k.type === 'pk' && k.allowed_origins?.length ? (
                          <div style={{ ...mutedText, marginTop: '0.25rem' }} title={k.allowed_origins.join('\n')}>
                            {k.allowed_origins.length} origin
                          </div>
                        ) : null}
                      </td>
                      <td style={{ maxWidth: '14rem' }}>
                        {(k.scopes || []).map((s) => scopeLabel(s, scopes)).join(', ') || '—'}
                      </td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        <div>rpm: {limitText(k.limits?.rpm)}</div>
                        <div>eşzamanlı: {limitText(k.limits?.max_concurrent)}</div>
                        <div>aylık: {limitText(k.limits?.monthly_quota)}</div>
                      </td>
                      <td>
                        <span className={`usage-badge ${active ? 'usage-badge--success' : 'usage-badge--error'}`}>
                          {active ? 'Aktif' : 'İptal'}
                        </span>
                        {k.expires_at ? <div style={{ ...mutedText, marginTop: '0.25rem' }}>bitiş: {fmtTime(k.expires_at)}</div> : null}
                        {k.revoked_at ? <div style={{ ...mutedText, marginTop: '0.25rem' }}>{fmtTime(k.revoked_at)}</div> : null}
                      </td>
                      <td style={{ whiteSpace: 'nowrap' }}>{fmtTime(k.last_used_at)}</td>
                      <td style={{ whiteSpace: 'nowrap' }}>{fmtTime(k.created_at)}</td>
                      <td>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                          <button type="button" className="tab-button secondary" onClick={() => setUsageKey(k)}>
                            Kullanım
                          </button>
                          {active ? (
                            <>
                              <button type="button" className="tab-button secondary" disabled={busy} onClick={() => rotateKey(k)}>
                                {busy ? '…' : 'Yenile'}
                              </button>
                              <button
                                type="button"
                                className="tab-button secondary btn-danger"
                                disabled={busy}
                                onClick={() => revokeKey(k)}
                              >
                                İptal et
                              </button>
                            </>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {!keysLoading && !keysErr && keys.length === 0 ? (
                  <tr>
                    <td colSpan={8} style={mutedText}>
                      {selectedClient ? 'Bu müşterinin henüz anahtarı yok.' : 'Henüz anahtar yok.'}
                    </td>
                  </tr>
                ) : null}
                {keysLoading && keys.length === 0 ? (
                  <tr>
                    <td colSpan={8} style={mutedText}>
                      Yükleniyor…
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      {usageKey ? (
        <KeyUsageModal apiKey={usageKey} token={token} logout={logout} onClose={() => setUsageKey(null)} />
      ) : null}

      {revealed ? <RevealedKeyModal revealed={revealed} onClose={() => setRevealed(null)} /> : null}
    </div>
  );
}
