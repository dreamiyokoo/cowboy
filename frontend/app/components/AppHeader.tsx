"use client";
import Link from "next/link";

export type AppPage = "dashboard" | "predictions" | "card-stats" | "admin";

const NAV: { href: string; label: string; page: AppPage }[] = [
  { href: "/dashboard",   label: "🏠 ダッシュボード", page: "dashboard" },
  { href: "/predictions", label: "🔮 AI予測",         page: "predictions" },
  { href: "/card-stats",  label: "📊 勝率統計",       page: "card-stats" },
  { href: "/admin",       label: "⚙️ 管理画面",       page: "admin" },
];

interface Props {
  currentPage: AppPage;
  onLogout: () => void;
  onRefresh?: () => void;
  lastUpdated?: Date | null;
}

export default function AppHeader({ currentPage, onLogout, onRefresh, lastUpdated }: Props) {
  return (
    <header className="sticky top-0 z-10 flex items-center justify-between bg-gray-900/80 backdrop-blur border-b border-gray-800 px-6 py-3">
      <span className="text-xl font-bold text-yellow-400 tracking-tight">🤠 Cowboy</span>
      <nav className="flex items-center gap-2">
        {NAV.map(({ href, label, page }) => {
          const active = currentPage === page;
          return active ? (
            <span
              key={page}
              className="text-sm px-3 py-1 rounded font-semibold bg-yellow-500/15 text-yellow-300 border border-yellow-500/30 cursor-default"
            >
              {label}
            </span>
          ) : (
            <Link
              key={page}
              href={href}
              className="text-sm px-3 py-1 rounded font-medium bg-gray-800 hover:bg-gray-700 text-gray-300 transition"
            >
              {label}
            </Link>
          );
        })}
        {lastUpdated && (
          <span className="text-xs text-gray-500 ml-1 tabular-nums">
            {lastUpdated.toLocaleTimeString("ja-JP")}
          </span>
        )}
        {onRefresh && (
          <button
            onClick={onRefresh}
            className="text-sm px-3 py-1 rounded bg-gray-800 hover:bg-gray-700 text-gray-300 transition"
          >
            更新
          </button>
        )}
        <button
          onClick={onLogout}
          className="text-sm px-3 py-1 rounded bg-red-950/80 hover:bg-red-900 border border-red-900/50 text-red-300 transition"
        >
          ログアウト
        </button>
      </nav>
    </header>
  );
}
