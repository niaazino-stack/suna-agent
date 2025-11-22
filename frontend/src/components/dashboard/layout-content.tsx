'use client';

import { FloatingMobileMenuButton } from '@/components/sidebar/sidebar-left';
import { useApiHealth } from '@/hooks/usage/use-health';
import { MaintenancePage } from '@/components/maintenance/maintenance-page';

import { useIsMobile } from '@/hooks/utils';
import { PresentationViewerWrapper } from '@/stores/presentation-viewer-store';
import { AppProviders } from '@/components/layout/app-providers';

interface DashboardLayoutContentProps {
  children: React.ReactNode;
}

export default function DashboardLayoutContent({
  children,
}: DashboardLayoutContentProps) {
  const isMobile = useIsMobile();
  const { data: healthData, isLoading: isCheckingHealth, error: healthError } = useApiHealth();

  const isApiHealthy = healthData?.status === 'ok' && !healthError;

  // Render maintenance page if API is not healthy
  if (isCheckingHealth) return null;
  if (!isApiHealthy) {
    return <MaintenancePage />;
  }

  return (
    <AppProviders 
      showSidebar={true}
      sidebarSiblings={
        <>
            <FloatingMobileMenuButton />
        </>
      }
    >
        <div className="bg-background">{children}</div>
        <PresentationViewerWrapper />
    </AppProviders>
  );
}
