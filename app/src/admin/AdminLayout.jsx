import { useEffect } from 'react';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/useAuth';

export default function AdminLayout() {
  const { logout, refreshMe, user } = useAuth();
  const nav = useNavigate();

  useEffect(() => {
    refreshMe();
  }, [refreshMe]);

  return (
    <div className="admin-shell">
      <nav className="admin-nav">
        <NavLink to="/admin/pages">Sayfalar</NavLink>
        <NavLink to="/admin/profiles">Kart profilleri</NavLink>
        <NavLink to="/admin/models-health">Model durumu</NavLink>
        <NavLink to="/admin/usage">API kullanımı</NavLink>
        <span className="admin-nav-spacer" />
        {user?.email ? (
          <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>{user.email}</span>
        ) : null}
        <Link to="/">Demo</Link>
        <button
          type="button"
          className="tab-button secondary"
          onClick={() => {
            logout();
            nav('/', { replace: true });
          }}
        >
          Çıkış
        </button>
      </nav>
      <Outlet />
    </div>
  );
}
