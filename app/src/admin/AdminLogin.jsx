import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/useAuth';

export default function AdminLogin() {
  const { login, token } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState('');
  const [loading, setLoading] = useState(false);

  if (token) {
    const to = loc.state?.from || '/admin';
    return <Navigate to={to} replace />;
  }

  async function onSubmit(e) {
    e.preventDefault();
    setErr('');
    setLoading(true);
    try {
      await login(email, password);
      nav(loc.state?.from || '/admin', { replace: true });
    } catch {
      setErr('Giriş başarısız. E-posta veya şifre hatalı.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="admin-shell">
      <h1 style={{ marginBottom: '1rem' }}>Admin girişi</h1>
      <form className="admin-form" onSubmit={onSubmit}>
        <label>
          E-posta
          <input
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label>
          Şifre
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {err ? <div className="error">{err}</div> : null}
        <div className="admin-actions">
          <button type="submit" className="tab-button active" disabled={loading}>
            {loading ? 'Giriş…' : 'Giriş yap'}
          </button>
          <Link to="/" className="tab-button secondary">
            Ana sayfa
          </Link>
        </div>
      </form>
    </div>
  );
}
