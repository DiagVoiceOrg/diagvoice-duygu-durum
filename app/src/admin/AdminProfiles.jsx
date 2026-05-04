import { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../context/useAuth';
import { CARD_REGISTRY, getCardRegistryEntry } from '../lib/cardRegistry';
import * as cmsApi from '../services/cmsApi';

/** API satırı → form satırı */
function apiCardToForm(c) {
  return {
    id: c.id,
    displayTitle: c.displayTitle ?? '',
    subtitle: c.subtitle ?? '',
    footnote: c.footnote ?? '',
    badge: c.badge ?? '',
    periodLabel: c.period?.label ?? '',
    periodFrom: c.period?.from ?? '',
    periodTo: c.period?.to ?? '',
  };
}

/** Form → API gövdesi (boş alanları at) */
function formCardsToPayload(rows) {
  return rows.map((c) => {
    const out = { id: c.id };
    const t = (v) => (typeof v === 'string' ? v.trim() : '');
    if (t(c.displayTitle)) out.displayTitle = t(c.displayTitle);
    if (t(c.subtitle)) out.subtitle = t(c.subtitle);
    if (t(c.footnote)) out.footnote = t(c.footnote);
    if (t(c.badge)) out.badge = t(c.badge);
    const pl = t(c.periodLabel);
    const pf = t(c.periodFrom);
    const pt = t(c.periodTo);
    if (pl || pf || pt) {
      out.period = {};
      if (pl) out.period.label = pl;
      if (pf) out.period.from = pf;
      if (pt) out.period.to = pt;
    }
    return out;
  });
}

function defaultCreateCards() {
  return ['transcript', 'audio_emotion'].map((id) => {
    const r = getCardRegistryEntry(id);
    return apiCardToForm({ id, displayTitle: r?.defaultTitle ?? id });
  });
}

function ProfileCardsEditor({ cards, setCards }) {
  const usedIds = useMemo(() => new Set(cards.map((c) => c.id)), [cards]);
  const addable = CARD_REGISTRY.filter((r) => !usedIds.has(r.id));

  function move(index, delta) {
    setCards((prev) => {
      const j = index + delta;
      if (j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[j]] = [next[j], next[index]];
      return next;
    });
  }

  function removeAt(index) {
    setCards((prev) => prev.filter((_, i) => i !== index));
  }

  function patchRow(index, patch) {
    setCards((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function addByRegistryId(id) {
    const r = getCardRegistryEntry(id);
    if (!r || usedIds.has(id)) return;
    setCards((prev) => [...prev, apiCardToForm({ id, displayTitle: r.defaultTitle })]);
  }

  return (
    <div className="profile-cards-editor">
      <div className="profile-cards-editor-head">
        <span className="profile-cards-editor-title">Kartlar (sıra demo sayfasına yansır)</span>
        {addable.length > 0 ? (
          <label className="profile-cards-add">
            <span>Kart ekle</span>
            <select
              defaultValue=""
              onChange={(e) => {
                const v = e.target.value;
                e.target.value = '';
                if (v) addByRegistryId(v);
              }}
            >
              <option value="">Seçin…</option>
              {addable.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.defaultTitle} ({r.id})
                </option>
              ))}
            </select>
          </label>
        ) : (
          <span className="profile-cards-hint">Tüm kayıtlı kart tipleri eklendi.</span>
        )}
      </div>

      {cards.length === 0 ? (
        <p className="profile-cards-empty">Henüz kart yok. Yukarıdan “Kart ekle” ile ekleyin.</p>
      ) : (
        <ul className="profile-cards-list">
          {cards.map((row, index) => {
            const reg = getCardRegistryEntry(row.id);
            return (
              <li key={row.id} className="profile-card-block">
                <div className="profile-card-block-top">
                  <div className="profile-card-id">
                    <strong>{reg ? reg.defaultTitle : row.id}</strong>
                    <code className="profile-card-id-code">{row.id}</code>
                    {!reg ? (
                      <span className="profile-card-unknown" title="cardRegistry.js listesinde yok">
                        Kayıtsız tip
                      </span>
                    ) : null}
                  </div>
                  <div className="profile-card-order">
                    <button type="button" className="tab-button secondary" disabled={index === 0} onClick={() => move(index, -1)} aria-label="Yukarı taşı">
                      ↑
                    </button>
                    <button
                      type="button"
                      className="tab-button secondary"
                      disabled={index === cards.length - 1}
                      onClick={() => move(index, 1)}
                      aria-label="Aşağı taşı"
                    >
                      ↓
                    </button>
                    <button type="button" className="tab-button secondary btn-danger" onClick={() => removeAt(index)}>
                      Kaldır
                    </button>
                  </div>
                </div>
                {reg?.description ? <p className="profile-card-desc">{reg.description}</p> : null}
                <div className="profile-card-fields">
                  <label>
                    Başlık (displayTitle)
                    <input
                      type="text"
                      value={row.displayTitle}
                      onChange={(e) => patchRow(index, { displayTitle: e.target.value })}
                      placeholder={reg?.defaultTitle ?? row.id}
                    />
                  </label>
                  <label>
                    Alt başlık
                    <input type="text" value={row.subtitle} onChange={(e) => patchRow(index, { subtitle: e.target.value })} placeholder="İsteğe bağlı" />
                  </label>
                  <label>
                    Dipnot
                    <input type="text" value={row.footnote} onChange={(e) => patchRow(index, { footnote: e.target.value })} placeholder="İsteğe bağlı" />
                  </label>
                  <label>
                    Rozet (badge)
                    <input type="text" value={row.badge} onChange={(e) => patchRow(index, { badge: e.target.value })} placeholder="örn. v2" />
                  </label>
                  <div className="profile-card-period">
                    <span className="profile-card-period-label">Sürüm / dönem</span>
                    <label>
                      Etiket
                      <input
                        type="text"
                        value={row.periodLabel}
                        onChange={(e) => patchRow(index, { periodLabel: e.target.value })}
                        placeholder="örn. v2 · 2026–"
                      />
                    </label>
                    <label>
                      Başlangıç (ISO)
                      <input type="text" value={row.periodFrom} onChange={(e) => patchRow(index, { periodFrom: e.target.value })} placeholder="2026-01-01" />
                    </label>
                    <label>
                      Bitiş (ISO)
                      <input type="text" value={row.periodTo} onChange={(e) => patchRow(index, { periodTo: e.target.value })} placeholder="İsteğe bağlı" />
                    </label>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export default function AdminProfiles() {
  const { token, logout } = useAuth();
  const [profiles, setProfiles] = useState([]);
  const [err, setErr] = useState('');
  const [mode, setMode] = useState(null);
  const [label, setLabel] = useState('');
  const [key, setKey] = useState('');
  const [cards, setCards] = useState([]);

  async function load() {
    setErr('');
    try {
      const prof = await cmsApi.listAdminProfiles(token);
      setProfiles(prof);
    } catch (e) {
      if (e.response?.status === 401) logout();
      setErr(e.response?.data?.detail || e.message || 'Yükleme hatası');
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  function startEdit(p) {
    setMode({ type: 'edit', id: p.id });
    setKey(p.key);
    setLabel(p.label);
    setCards((p.cards || []).map(apiCardToForm));
  }

  function startCreate() {
    setMode({ type: 'create' });
    setKey('');
    setLabel('Yeni profil');
    setCards(defaultCreateCards());
  }

  function validateCards() {
    const ids = cards.map((c) => c.id).filter(Boolean);
    if (ids.length === 0) return 'En az bir kart ekleyin.';
    const dup = ids.filter((id, i) => ids.indexOf(id) !== i);
    if (dup.length) return `Aynı kart iki kez: ${[...new Set(dup)].join(', ')}`;
    return '';
  }

  async function saveCreate(e) {
    e.preventDefault();
    setErr('');
    const v = validateCards();
    if (v) {
      setErr(v);
      return;
    }
    const payload = formCardsToPayload(cards);
    try {
      await cmsApi.createProfile(token, { key, label, cards: payload });
      setMode(null);
      await load();
    } catch (e2) {
      if (e2.response?.status === 401) logout();
      setErr(
        typeof e2.response?.data?.detail === 'string'
          ? e2.response.data.detail
          : JSON.stringify(e2.response?.data) || e2.message || 'Kayıt hatası',
      );
    }
  }

  async function saveEdit(e, id) {
    e.preventDefault();
    setErr('');
    const v = validateCards();
    if (v) {
      setErr(v);
      return;
    }
    const payload = formCardsToPayload(cards);
    try {
      await cmsApi.updateProfile(token, id, { label, cards: payload });
      setMode(null);
      await load();
    } catch (e2) {
      if (e2.response?.status === 401) logout();
      setErr(
        typeof e2.response?.data?.detail === 'string'
          ? e2.response.data.detail
          : JSON.stringify(e2.response?.data) || e2.message || 'Kayıt hatası',
      );
    }
  }

  async function remove(id) {
    if (!window.confirm('Bu profili silmek istediğinize emin misiniz? Bağlı sayfa varsa silinmez.')) return;
    setErr('');
    try {
      await cmsApi.deleteProfile(token, id);
      await load();
    } catch (e2) {
      if (e2.response?.status === 401) logout();
      setErr(e2.response?.data?.detail || e2.message || 'Silme hatası');
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>Kart profilleri</h2>
        <button type="button" className="tab-button active" onClick={startCreate}>
          Yeni profil
        </button>
      </div>
      <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)', marginTop: '0.5rem' }}>
        Kart tipleri <code>app/src/lib/cardRegistry.js</code> içinde tanımlı; yeni model eklemek için oraya bir satır eklemen yeterli. Sıra oklarla değişir; başlık ve dipnotlar buradan düzenlenir.
      </p>
      {err ? <div className="error" style={{ marginTop: '1rem' }}>{err}</div> : null}

      {mode?.type === 'create' && (
        <form className="admin-form admin-form-wide" style={{ marginTop: '1.25rem' }} onSubmit={saveCreate}>
          <h3>Yeni profil</h3>
          <label>
            Anahtar (benzersiz)
            <input value={key} onChange={(e) => setKey(e.target.value)} placeholder="ornek-profil" required />
          </label>
          <label>
            Etiket
            <input value={label} onChange={(e) => setLabel(e.target.value)} required />
          </label>
          <ProfileCardsEditor cards={cards} setCards={setCards} />
          <div className="admin-actions">
            <button type="submit" className="tab-button active">
              Oluştur
            </button>
            <button type="button" className="tab-button secondary" onClick={() => setMode(null)}>
              İptal
            </button>
          </div>
        </form>
      )}

      {mode?.type === 'edit' && (
        <form className="admin-form admin-form-wide" style={{ marginTop: '1.25rem' }} onSubmit={(e) => saveEdit(e, mode.id)}>
          <h3>
            Profili düzenle — <code>{key}</code>
          </h3>
          <label>
            Etiket
            <input value={label} onChange={(e) => setLabel(e.target.value)} required />
          </label>
          <ProfileCardsEditor cards={cards} setCards={setCards} />
          <div className="admin-actions">
            <button type="submit" className="tab-button active">
              Kaydet
            </button>
            <button type="button" className="tab-button secondary" onClick={() => setMode(null)}>
              İptal
            </button>
          </div>
        </form>
      )}

      <div className="admin-table-wrap" style={{ marginTop: '1.25rem' }}>
        <table className="admin-table">
          <thead>
            <tr>
              <th>Anahtar</th>
              <th>Etiket</th>
              <th>Kart sayısı</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {profiles.map((p) => (
              <tr key={p.id}>
                <td>{p.key}</td>
                <td>{p.label}</td>
                <td>{Array.isArray(p.cards) ? p.cards.length : 0}</td>
                <td>
                  <button type="button" className="tab-button secondary" onClick={() => startEdit(p)}>
                    Düzenle
                  </button>{' '}
                  <button type="button" className="tab-button secondary btn-danger" onClick={() => remove(p.id)}>
                    Sil
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
