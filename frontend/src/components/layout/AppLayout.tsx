import { useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import ConfirmHost from '../common/ConfirmHost';
import ToastHost from '../common/ToastHost';
import { initApp } from '../../stores/actions';

export default function AppLayout() {
  useEffect(() => {
    void initApp();
  }, []);

  return (
    <div className="flex h-full overflow-hidden">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Outlet />
      </div>
      <ConfirmHost />
      <ToastHost />
    </div>
  );
}
