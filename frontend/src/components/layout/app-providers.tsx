'use client';

import React from 'react';
import { SidebarProvider, SidebarInset } from '@/components/ui/sidebar';
import { SidebarLeft } from '@/components/sidebar/sidebar-left';

interface AppProvidersProps {
  children: React.ReactNode;
  showSidebar?: boolean;
  sidebarSiblings?: React.ReactNode;
}

export function AppProviders({ 
  children, 
  showSidebar = true,
  sidebarSiblings
}: AppProvidersProps) {

  if (!showSidebar) {
    return <>{children}</>;
  }

  return (
    <SidebarProvider>
      <SidebarLeft />
      <SidebarInset>
        {children}
      </SidebarInset>
      {sidebarSiblings}
    </SidebarProvider>
  );
}
