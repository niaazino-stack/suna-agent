'use client';

import { useEffect, useState, useRef } from 'react';
import {
  Loader2,
} from "lucide-react"
import { ThreadIcon } from "./thread-icon"
import { usePathname, useRouter } from "next/navigation"
import { SpotlightCard } from '@/components/ui/spotlight-card';
import { cn } from '@/lib/utils';

import Link from "next/link"
import { useSidebar, } from '@/components/ui/sidebar';
import { formatDateForList } from '@/lib/utils/date-formatting';
import { useThreads } from '@/hooks/threads/use-threads';
import { useTranslations } from 'next-intl';
import { useMemo } from 'react';

const ThreadItem: React.FC<{
  thread: any;
  isActive: boolean;
  isThreadLoading: boolean;
  handleThreadClick: (e: React.MouseEvent<HTMLAnchorElement>, threadId: string, url: string) => void;
}> = ({
  thread,
  isActive,
  isThreadLoading,
  handleThreadClick,
}) => {
    const url = `/agents/${thread.thread_id}`;
    return (
      <SpotlightCard
        className={cn(
          "transition-colors cursor-pointer",
          isActive ? "bg-muted" : "bg-transparent"
        )}
      >
        <Link
          href={url}
          onClick={(e) => handleThreadClick(e, thread.thread_id, url)}
          prefetch={false}
          className="block"
        >
          <div
            className="flex items-center gap-3 p-2.5 text-sm"
          >
            <div
              className="relative flex items-center justify-center w-10 h-10 rounded-2xl bg-card border-[1.5px] border-border flex-shrink-0 group/icon"
            >
              {isThreadLoading ? (
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              ) : (
                <ThreadIcon
                    iconName={thread.iconName || 'bot'}
                    className={cn(
                      "text-muted-foreground transition-opacity"
                    )}
                    size={14}
                  />
              )}
            </div>
            <span className="flex-1 truncate">{thread.name}</span>
            <div className="flex-shrink-0 relative">
              <span
                className={cn(
                  "text-xs text-muted-foreground transition-opacity"
                )}
              >
                {formatDateForList(thread.updated_at)}
              </span>
            </div>
          </div>
        </Link>
      </SpotlightCard>
    );
  };

export function NavAgents() {
  const t = useTranslations('sidebar');
  const { isMobile, state, setOpenMobile } = useSidebar()
  const [loadingThreadId, setLoadingThreadId] = useState<string | null>(null)
  const pathname = usePathname()

  const {
    data: threadsResponse,
    isLoading: isThreadsLoading,
    error: threadsError
  } = useThreads({});
  
  const threads = threadsResponse?.threads || [];

  const handleThreadClick = (e: React.MouseEvent<HTMLAnchorElement>, threadId: string, url: string) => {
    if (!e.metaKey) {
      setLoadingThreadId(threadId);
    }

    if (isMobile) {
      setOpenMobile(false);
    }
  }

  const isLoading = isThreadsLoading && threads.length === 0;

  return (
    <div>
      <div className="overflow-y-auto max-h-[calc(100vh-280px)] [&::-webkit-scrollbar]:hidden [-ms-overflow-style:'none'] [scrollbar-width:'none'] pb-16">
        {(state !== 'collapsed' || isMobile) && (
          <>
            {isLoading ? (
              <div className="space-y-1">
                {Array.from({ length: 3 }).map((_, index) => (
                  <div key={`skeleton-${index}`} className="flex items-center gap-3 px-2 py-2">
                    <div className="h-10 w-10 bg-muted/10 border-[1.5px] border-border rounded-2xl animate-pulse"></div>
                    <div className="h-4 bg-muted rounded flex-1 animate-pulse"></div>
                    <div className="h-3 w-8 bg-muted rounded animate-pulse"></div>
                  </div>
                ))}
              </div>
            ) : threads.length > 0 ? (
              <>
                {threads.map((thread) => {
                      const isActive = pathname?.includes(thread.thread_id) || false;
                      const isThreadLoading = loadingThreadId === thread.thread_id;
                      return (
                        <ThreadItem
                          key={thread.thread_id}
                          thread={thread}
                          isActive={isActive}
                          isThreadLoading={isThreadLoading}
                          handleThreadClick={handleThreadClick}
                        />
                      );
                    })}
              </>
            ) : (
              <div className="py-2 pl-2.5 text-sm text-muted-foreground">
                {t('noConversations')}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}