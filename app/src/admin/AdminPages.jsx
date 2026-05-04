import { useEffect, useState } from 'react';
import { useAuth } from '../context/useAuth';
import * as cmsApi from '../services/cmsApi';

export default function AdminPages() {
  const { token, logout } = useAuth();
  const [pages, setPages] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [err, setErr] = useState('');
  const [mode, setMode] = useState(null);
  const [form, setForm] = useState({
    slug: '/',
    title: '',
    description: '',
    published: true,
    sortOrder: 0,
    profileKey: 'default-demo',
    layout: 'demo_default',
  });

  async function load() {
    setErr('');
    try {
      const [p, prof] = await Promise.all([
        cmsApi.listAdminPages(token),
        cmsApi.listAdminProfiles(token),
      ]);
      setPages(p);
      setProfiles(prof);
    } catch (e) {
      if (e.response?.status === 401) logout();
      setErr(e.response?.data?.detail || e.message || 'Yükleme hatası');
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- token/load stable enough for MVP
  }, [token]);

  async function saveCreate(e) {
    e.preventDefault();
    setErr('');
    try {
      await cmsApi.createPage(token, form);
      setMode(null);
      await load();
    } catch (e2) {
      if (e2.response?.status === 401) logout();
      setErr(e2.response?.data?.detail || e2.message || 'Kayıt hatası');
    }
  }

  async function saveEdit(e, id) {
    e.preventDefault();
    setErr('');
    try {
      await cmsApi.updatePage(token, id, {
        title: form.title,
        description: form.description || null,
        published: form.published,
        sortOrder: Number(form.sortOrder),
        profileKey: form.profileKey,
        layout: form.layout,
      });
      setMode(null);
      await load();
    } catch (e2) {
      if (e2.response?.status === 401) logout();
      setErr(e2.response?.data?.detail || e2.message || 'Kayıt hatası');
    }
  }

  async function remove(id) {
    if (!window.confirm('Bu sayfayı silmek istediğinize emin misiniz?')) return;
    setErr('');
    try {
      await cmsApi.deletePage(token, id);
      await load();
    } catch (e2) {
      if (e2.response?.status === 401) logout();
      setErr(e2.response?.data?.detail || e2.message || 'Silme hatası');
    }
  }

  function startEdit(p) {
    setMode({ type: 'edit', id: p.id });
    setForm({
      slug: p.slug,
      title: p.title,
      description: p.description || '',
      published: p.published,
      sortOrder: p.sortOrder,
      profileKey: p.profileKey,
      layout: p.layout,
    });
  }

  function startCreate() {
    setMode({ type: 'create' });
    setForm({
      slug: '/demo-extra',
      title: 'Yeni sayfa',
      description: '',
      published: false,
      sortOrder: 10,
      profileKey: profiles[0]?.key || 'default-demo',
      layout: 'demo_default',
    });
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>Sayfalar</h2>
        <button type="button" className="tab-button active" onClick={startCreate}>
          Yeni sayfa
        </button>
      </div>
      {err ? <div className="error" style={{ marginTop: '1rem' }}>{err}</div> : null}

      {mode?.type === 'create' && (
        <form className="admin-form" style={{ marginTop: '1.25rem' }} onSubmit={saveCreate}>
          <h3>Yeni sayfa</h3>
          <label>
            Slug (örn. / veya /demo)
            <input value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} />
          </label>
          <label>
            Başlık
            <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </label>
          <label>
            Açıklama
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </label>
          <label>
            Profil
            <select value={form.profileKey} onChange={(e) => setForm({ ...form, profileKey: e.target.value })}>
              {profiles.map((pr) => (
                <option key={pr.id} value={pr.key}>
                  {pr.label} ({pr.key})
                </option>
              ))}
            </select>
          </label>
          <label>
            Sıra
            <input type="number" value={form.sortOrder} onChange={(e) => setForm({ ...form, sortOrder: e.target.value })} />
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: '0.5rem' }}>
            <input type="checkbox" checked={form.published} onChange={(e) => setForm({ ...form, published: e.target.checked })} />
            Yayında
          </label>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', margin: 0 }}>
            Hangi API’lerin çağrılacağı <strong>profilde seçilen kartlara</strong> göre otomatik belirlenir. Slug tek
            segment olmalı (örn. <code>/depresyon-emosyon</code>).
          </p>
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
        <form className="admin-form" style={{ marginTop: '1.25rem' }} onSubmit={(e) => saveEdit(e, mode.id)}>
          <h3>Sayfayı düzenle ({form.slug})</h3>
          <label>
            Başlık
            <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </label>
          <label>
            Açıklama
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </label>
          <label>
            Profil
            <select value={form.profileKey} onChange={(e) => setForm({ ...form, profileKey: e.target.value })}>
              {profiles.map((pr) => (
                <option key={pr.id} value={pr.key}>
                  {pr.label} ({pr.key})
                </option>
              ))}
            </select>
          </label>
          <label>
            Sıra
            <input type="number" value={form.sortOrder} onChange={(e) => setForm({ ...form, sortOrder: e.target.value })} />
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: '0.5rem' }}>
            <input type="checkbox" checked={form.published} onChange={(e) => setForm({ ...form, published: e.target.checked })} />
            Yayında
          </label>
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
              <th>Slug</th>
              <th>Başlık</th>
              <th>Profil</th>
              <th>Yayın</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {pages.map((p) => (
              <tr key={p.id}>
                <td>{p.slug}</td>
                <td>{p.title}</td>
                <td>{p.profileKey}</td>
                <td>{p.published ? 'Evet' : 'Hayır'}</td>
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
