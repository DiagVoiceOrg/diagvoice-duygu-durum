import axios from 'axios';

// Fusion ile aynı host (varsayılan 8085).
const base = () => import.meta.env.VITE_CMS_API_URL || 'http://localhost:8085';

const TOKEN_KEY = 'diagvoice_cms_token';

export function getStoredToken() {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token) {
  if (token) sessionStorage.setItem(TOKEN_KEY, token);
  else sessionStorage.removeItem(TOKEN_KEY);
}

export async function getPublicPageBySlug(slug = '/') {
  const { data } = await axios.get(`${base()}/public/pages/by-slug`, { params: { slug } });
  return data;
}

/** Navbar: yayındaki sayfalar (sortOrder’a göre sunucu sıralar). */
export async function listPublicPages() {
  const { data } = await axios.get(`${base()}/public/pages`);
  return data;
}

export async function login(email, password) {
  const { data } = await axios.post(`${base()}/auth/login`, { email, password });
  return data.access_token;
}

export async function fetchMe(token) {
  const { data } = await axios.get(`${base()}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

export async function listAdminPages(token) {
  const { data } = await axios.get(`${base()}/admin/pages`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

export async function listAdminProfiles(token) {
  const { data } = await axios.get(`${base()}/admin/profiles`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

export async function createPage(token, body) {
  const { data } = await axios.post(`${base()}/admin/pages`, body, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

export async function updatePage(token, pageId, body) {
  const { data } = await axios.put(`${base()}/admin/pages/${pageId}`, body, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

export async function deletePage(token, pageId) {
  await axios.delete(`${base()}/admin/pages/${pageId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function createProfile(token, body) {
  const { data } = await axios.post(`${base()}/admin/profiles`, body, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

export async function updateProfile(token, profileId, body) {
  const { data } = await axios.put(`${base()}/admin/profiles/${profileId}`, body, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return data;
}

export async function deleteProfile(token, profileId) {
  await axios.delete(`${base()}/admin/profiles/${profileId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}
