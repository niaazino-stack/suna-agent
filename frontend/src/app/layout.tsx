import { ThemeProvider } from '@/components/home/theme-provider';
import { siteConfig } from '@/lib/site';
import type { Metadata, Viewport } from 'next';
import './globals.css';
import { ReactQueryProvider } from './react-query-provider';
import { Toaster } from '@/components/ui/sonner';
import '@/lib/polyfills';
import { roobert } from './fonts/roobert';
import { roobertMono } from './fonts/roobert-mono';
import { Suspense } from 'react';
import { I18nProvider } from '@/components/i18n-provider';


export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: 'white' },
    { media: '(prefers-color-scheme: dark)', color: 'black' }
  ],
  width: 'device-width',
  initialScale: 1,
  maximumScale: 5,
};

export const metadata: Metadata = {
  metadataBase: new URL(siteConfig.url),
  title: {
    default: siteConfig.name,
    template: `%s | ${siteConfig.name}`,
  },
  description: siteConfig.description,
  keywords: [
    'AI assistant',
    'open source AI',
    'artificial intelligence',
    'AI worker',
    'browser automation',
    'web scraping',
    'file management',
    'research assistant',
    'data analysis',
    'task automation',
    'Kortix',
    'generalist AI',
  ],
  authors: [
    { 
      name: 'Kortix Team', 
      url: 'https://kortix.com' 
    }
  ],
  creator: 'Kortix Team',
  publisher: 'Kortix Team',
  category: 'Technology',
  applicationName: 'Kortix',
  formatDetection: {
    telephone: false,
    email: false,
    address: false,
  },
  robots: {
    index: true,
    follow: true,
    nocache: false,
    googleBot: {
      index: true,
      follow: true,
      'max-video-preview': -1,
      'max-image-preview': 'large',
      'max-snippet': -1,
    },
  },
  openGraph: {
    type: 'website',
    title: 'Kortix - Open Source Generalist AI Worker',
    description: siteConfig.description,
    url: siteConfig.url,
    siteName: 'Kortix',
    locale: 'en_US',
    images: [
      {
        url: '/banner.png',
        width: 1200,
        height: 630,
        alt: 'Kortix - Open Source Generalist AI Worker',
        type: 'image/png',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Kortix - Open Source Generalist AI Worker',
    description: siteConfig.description,
    creator: '@kortix',
    site: '@kortix',
    images: ['/banner.png'],
  },
  icons: {
    icon: [
      { url: '/favicon.png', sizes: 'any' },
      { url: '/favicon-light.png', sizes: 'any', media: '(prefers-color-scheme: dark)' },
    ],
    shortcut: '/favicon.png',
    apple: '/favicon.png',
  },
  manifest: '/manifest.json',
  alternates: {
    canonical: siteConfig.url,
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning className={`${roobert.variable} ${roobertMono.variable}`}>
      <body className="antialiased font-sans bg-background">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <I18nProvider>
            <ReactQueryProvider>
              {children}
              <Toaster />
              <Suspense fallback={null}>
              </Suspense>
            </ReactQueryProvider>
          </I18nProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
