import { useCallback, useMemo, useState } from 'react';
import * as cmsApi from '../services/cmsApi';
import { AuthContext } from './authContext';

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => cmsApi.getStoredToken());
  const [user, setUser] = useState(null);

  const login = useCallback(async (email, password) => {
    const t = await cmsApi.login(email, password);
    cmsApi.setStoredToken(t);
    setToken(t);
    const me = await cmsApi.fetchMe(t);
    setUser(me);
    return me;
  }, []);

  const logout = useCallback(() => {
    cmsApi.setStoredToken(null);
    setToken(null);
    setUser(null);
  }, []);

  const refreshMe = useCallback(async () => {
    const t = cmsApi.getStoredToken();
    if (!t) {
      setUser(null);
      return null;
    }
    try {
      const me = await cmsApi.fetchMe(t);
      setUser(me);
      return me;
    } catch {
      logout();
      return null;
    }
  }, [logout]);

  const value = useMemo(
    () => ({
      token,
      user,
      login,
      logout,
      refreshMe,
      isAuthenticated: Boolean(token),
    }),
    [token, user, login, logout, refreshMe],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
