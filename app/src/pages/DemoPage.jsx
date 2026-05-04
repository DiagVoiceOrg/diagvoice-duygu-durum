import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import DemoHome from '../demo/DemoHome';
import {
  demoT,
  normalizeDemoLang,
  readStoredDemoLang,
  syncDocumentDemoLang,
  writeStoredDemoLang,
} from '../i18n/demoUi';
import { getPublicPageBySlug, listPublicPages } from '../services/cmsApi';

/** Slug yayında değil (çok dilli görüntüleme için sabit kod) */
const ERR_CMS404 = '__diagvoice_err_cms404__';
/** CMS uyarısı: ana sayfa / genel yükleme hatası */
const WARN_CMS_HOME = '__diagvoice_warn_cms_home__';
const WARN_CMS_PAGE = '__diagvoice_warn_cms_page__';

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
  const [demoLang, setDemoLangState] = useState(() => readStoredDemoLang());

  useEffect(() => {
    syncDocumentDemoLang(demoLang);
  }, [demoLang]);

  const setDemoLang = (lng) => {
    const n = normalizeDemoLang(lng);
    writeStoredDemoLang(n);
    setDemoLangState(n);
    syncDocumentDemoLang(n);
  };

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
          setPageError(ERR_CMS404);
          setProfileCards(null);
          setPageTitle('');
        } else {
          console.warn('CMS sayfa yüklenemedi:', e?.message || e);
          setProfileCards(null);
          setPageTitle('');
          setPageError(null);
          setCmsWarning(cmsSlug === '/' ? WARN_CMS_HOME : WARN_CMS_PAGE);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [cmsSlug]);

  const cmsBannerText =
    cmsWarning === null
      ? null
      : cmsWarning === WARN_CMS_HOME
        ? demoT(demoLang, 'cmsWarnHome')
        : cmsWarning === WARN_CMS_PAGE
          ? demoT(demoLang, 'cmsWarnPage')
          : cmsWarning;

  const pageErrorText = pageError === ERR_CMS404 ? demoT(demoLang, 'cms404Error') : pageError;

  if (loading) {
    return (
      <div className={`app-container${demoLang === 'ar' ? ' demo-rtl' : ''}`} style={{ padding: '2rem', textAlign: 'center' }}>
        <p style={{ color: 'var(--text-muted)' }}>{demoT(demoLang, 'pageLoading')}</p>
      </div>
    );
  }

  return (
    <DemoHome
      navPages={navPages}
      pageTitle={pageTitle}
      profileCards={profileCards}
      cmsWarning={cmsBannerText}
      pageError={pageErrorText}
      demoLang={demoLang}
      onDemoLangChange={setDemoLang}
    />
  );
}
