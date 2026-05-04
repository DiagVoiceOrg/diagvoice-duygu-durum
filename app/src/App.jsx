import { Navigate, Route, Routes } from 'react-router-dom';
import AdminLayout from './admin/AdminLayout';
import AdminLogin from './admin/AdminLogin';
import AdminModelHealth from './admin/AdminModelHealth';
import AdminPages from './admin/AdminPages';
import AdminProfiles from './admin/AdminProfiles';
import ProtectedRoute from './admin/ProtectedRoute';
import DemoPage from './pages/DemoPage';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<DemoPage />} />
      <Route path="/:slug" element={<DemoPage />} />
      <Route path="/admin/login" element={<AdminLogin />} />
      <Route
        path="/admin"
        element={
          <ProtectedRoute>
            <AdminLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/admin/pages" replace />} />
        <Route path="pages" element={<AdminPages />} />
        <Route path="profiles" element={<AdminProfiles />} />
        <Route path="models-health" element={<AdminModelHealth />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
