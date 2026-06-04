import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";
import Nav from "@/components/nav";
import Providers from "@/components/providers";

export const metadata: Metadata = {
  title: "PearScarf",
  description: "Operational dashboard for pearscarf — intents, reality, and self-improvement.",
};

// Runs before paint so we never flash the wrong theme / nav-width on first load.
const uiBootstrap = `
(function () {
  try {
    var theme = localStorage.getItem('pearscarf-ui:theme');
    if (theme !== 'dark' && theme !== 'light') {
      theme = (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
    }
    document.documentElement.setAttribute('data-theme', theme);
    if (localStorage.getItem('pearscarf-ui:nav-collapsed') === 'true') {
      document.documentElement.setAttribute('data-nav-collapsed', 'true');
    }
  } catch (e) {}
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: uiBootstrap }} />
      </head>
      <body className="antialiased">
        <Providers>
          <div className="flex min-h-screen">
            <Nav />
            <main className="flex-1 min-w-0">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
