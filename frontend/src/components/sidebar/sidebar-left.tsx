'use client';

import * as React from 'react';
import Link from 'next/link';
import { Bot, Menu, Plus, Zap, ChevronRight, BookOpen, Code, Star, Package, Sparkle, Sparkles, X, MessageCircle, PanelLeftOpen, Settings, LogOut, User, CreditCard, Key, Plug, Shield, DollarSign, KeyRound, Sun, Moon, Book, Database, PanelLeftClose } from 'lucide-react';

import { NavAgents } from '@/components/sidebar/nav-agents';
import { KortixLogo } from '@/components/sidebar/kortix-logo';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarRail,
  SidebarTrigger,
  useSidebar,
} from '@/components/ui/sidebar';

import { useEffect, useState } from 'react';
import { useTheme } from 'next-themes';
import { useRouter } from 'next/navigation';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { Button } from '@/components/ui/button';
import { useIsMobile } from '@/hooks/utils';
import { cn } from '@/lib/utils';
import { usePathname, useSearchParams } from 'next/navigation';

function FloatingMobileMenuButton() {
  const { setOpenMobile, openMobile, setOpen } = useSidebar();
  const isMobile = useIsMobile();

  if (!isMobile || openMobile) return null;

  return (
    <div className="fixed top-6 left-4 z-50">
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            onClick={() => {
              setOpen(true);
              setOpenMobile(true);
            }}
            size="icon"
            className="h-10 w-10 rounded-full bg-primary text-primary-foreground shadow-lg hover:bg-primary/90 transition-all duration-200 hover:scale-105 active:scale-95 touch-manipulation"
            aria-label="Open menu"
          >
            <Menu className="h-5 w-5" />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="bottom">
          Open menu
        </TooltipContent>
      </Tooltip>
    </div>
  );
}

export function SidebarLeft({
  ...props
}: React.ComponentProps<typeof Sidebar>) {
  const { state, setOpen, setOpenMobile } = useSidebar();
  const isMobile = useIsMobile();
  const { theme, setTheme } = useTheme();
  const router = useRouter();

  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (isMobile) {
      setOpenMobile(false);
    }
  }, [pathname, searchParams, isMobile, setOpenMobile]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {

      if ((event.metaKey || event.ctrlKey) && event.key === 'b') {
        event.preventDefault();
        setOpen(!state.startsWith('expanded'));
        window.dispatchEvent(
          new CustomEvent('sidebar-left-toggled', {
            detail: { expanded: !state.startsWith('expanded') },
          }),
        );
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [state, setOpen, router, isMobile, setOpenMobile]);

  return (
    <Sidebar
      collapsible="icon"
      className="border-r border-border/50 bg-background [&::-webkit-scrollbar]:hidden [-ms-overflow-style:'none'] [scrollbar-width:'none']"
      {...props}
    >
      <SidebarHeader className={cn("px-6 pt-7 overflow-hidden", state === 'collapsed' && "px-6")}>
        <div className={cn("flex h-[32px] items-center justify-between min-w-[200px]")}>
          <div className="">
            {state === 'collapsed' ? (
              <div className="pl-2 relative flex items-center justify-center w-fit group/logo">
                <Link href="/dashboard" onClick={() => isMobile && setOpenMobile(false)}>
                  <KortixLogo size={20} className="flex-shrink-0 opacity-100 group-hover/logo:opacity-0 transition-opacity" />
                </Link>
                <Tooltip delayDuration={2000}>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 absolute opacity-0 group-hover/logo:opacity-100 transition-opacity"
                      onClick={() => setOpen(true)}
                    >
                      <PanelLeftOpen className="!h-5 !w-5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Expand sidebar (CMD+B)</TooltipContent>
                </Tooltip>
              </div>
            ) : (
              <div className="pl-2 relative flex items-center justify-center w-fit">
                <Link href="/dashboard" onClick={() => isMobile && setOpenMobile(false)}>
                  <KortixLogo size={20} className="flex-shrink-0" />
                </Link>
              </div>
            )}

          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => {
              if (isMobile) {
                setOpenMobile(false);
              } else {
                setOpen(false);
              }
            }}
          >
            <PanelLeftClose className="!h-5 !w-5" />
          </Button>
        </div>
      </SidebarHeader >
      <SidebarContent className="[&::-webkit-scrollbar]:hidden [-ms-overflow-style:'none'] [scrollbar-width:'none']">
          <div
            className="flex flex-col h-full"
          >
            <div className="px-6 pt-4 space-y-4">
              <div className="w-full">
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full shadow-none justify-between h-10 px-4"
                  asChild
                >
                  <Link
                    href="/dashboard"
                    onClick={() => {
                      if (isMobile) setOpenMobile(false);
                    }}
                  >
                    <div className="flex items-center gap-2">
                      <Plus className="h-4 w-4" />
                      New Chat
                    </div>
                  </Link>
                </Button>
              </div>
            </div>

            <div className="px-6 flex-1 overflow-hidden">
                <NavAgents />
            </div>
          </div>
      </SidebarContent>

      <div className={cn("pb-4", state === 'collapsed' ? "px-6" : "px-6")}>
        <SidebarMenu>
        <SidebarMenuButton hasSubmenu={false}>
        <div className="flex items-center w-full justify-between">
          <div className="flex items-center gap-2">
            <Settings className="h-4 w-4" />
            <span>Settings</span>
          </div>
        </div>
        </SidebarMenuButton>
        <SidebarMenuSub>
          <SidebarMenuSubItem onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
            <div className="flex items-center justify-between w-full">
              <span>Theme</span>
              <div className="flex items-center gap-2">
                <Sun className="h-4 w-4" /> / <Moon className="h-4 w-4" />
              </div>
            </div>
            </SidebarMenuSubItem>
        </SidebarMenuSub>
        </SidebarMenu>
      </div>
      <SidebarRail />
    </Sidebar >
  );
}

export { FloatingMobileMenuButton };
