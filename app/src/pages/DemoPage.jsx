import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import DemoHome from '../demo/DemoHome';
import { getPublicPageBySlug, listPublicPages } from '../services/cmsApi';

/** React route `/:slug` → CMS slug (örn. depresyon-emosyon → /depresyon-emosyon) */
export function routeParamToCmsSlug(slugParam) {
  if (!slugParam) return '/';
  const clean = String(slugParam).replace(/^\/+|\/+$/g, '');
  return clean ? `/${clean}` : '/';
}

export default function DemoPage() {
  const { slug: slugParam } = useParams();
  const cmsSlug = useMemo(() => routeParamToCmsSlug(slugParam), [slugParam]);

  const [loading, setLoading] = useState(true);
  const [navPages, setNavPages] = useState([]);
  const [profileCards, setProfileCards] = useState(null);
  const [pageTitle, setPageTitle] = useState('');
  const [cmsWarning, setCmsWarning] = useState(null);
  const [pageError, setPageError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setPageError(null);
      try {
        const list = await listPublicPages();
        if (!cancelled) setNavPages(Array.isArray(list) ? list : []);
      } catch {
        if (!cancelled) setNavPages([]);
      }
      try {
        const page = await getPublicPageBySlug(cmsSlug);
        if (cancelled) return;
        setProfileCards(page?.profile?.cards ?? null);
        setPageTitle(page?.title ?? '');
        setCmsWarning(null);
        setPageError(null);
      } catch (e) {
        if (cancelled) return;
        if (e.response?.status === 404) {
          setPageError('Bu slug için yayımlanmış bir sayfa yok. Admin’den slug ve “Yayında” alanını kontrol et.');
          setProfileCards(null);
          setPageTitle('');
        } else {
          console.warn('CMS sayfa yüklenemedi:', e?.message || e);
          setProfileCards(null);
          setPageTitle('');
          setPageError(null);
          setCmsWarning(
            cmsSlug === '/'
              ? 'Demo ayarları yüklenemedi (CMS kapalı olabilir); varsayılan kart sırası kullanılıyor.'
              : 'Sayfa ayarları yüklenemedi; varsayılan davranış kullanılıyor.',
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [cmsSlug]);

  if (loading) {
    return (
      <div className="app-container" style={{ padding: '2rem', textAlign: 'center' }}>
        <p style={{ color: 'var(--text-muted)' }}>Sayfa yükleniyor…</p>
      </div>
    );
  }

  return (
    <DemoHome
      navPages={navPages}
      pageTitle={pageTitle}
      profileCards={profileCards}
      cmsWarning={cmsWarning}
      pageError={pageError}
    />
  );
}
