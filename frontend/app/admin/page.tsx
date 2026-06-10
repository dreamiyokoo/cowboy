"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

interface LogFile {
  filename: string;
  size: number;
  mtime: number;
}

export default function AdminPage() {
  const router = useRouter();
  const [adminPassword, setAdminPassword] = useState("");
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [logs, setLogs] = useState<LogFile[]>([]);
  const [selectedLogText, setSelectedLogText] = useState<string | null>(null);
  const [selectedLogTitle, setSelectedLogTitle] = useState("");
  const [isLogModalOpen, setIsLogModalOpen] = useState(false);
  const [error, setError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

  // 初期ロード時に localStorage からパスワードを取得してログイン試行
  useEffect(() => {
    const saved = localStorage.getItem("admin_password");
    if (saved) {
      setAdminPassword(saved);
      verifyPassword(saved);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function verifyPassword(passwordToVerify: string) {
    setIsLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_URL}/api/v1/admin/login`, {
        method: "POST",
        headers: {
          "X-Admin-Password": passwordToVerify,
        },
      });
      if (res.ok) {
        setIsAuthenticated(true);
        localStorage.setItem("admin_password", passwordToVerify);
        fetchLogs(passwordToVerify);
      } else {
        setError("管理者パスワードが正しくありません");
        setIsAuthenticated(false);
        localStorage.removeItem("admin_password");
      }
    } catch (err) {
      setError("接続エラーが発生しました");
    } finally {
      setIsLoading(false);
    }
  }

  async function fetchLogs(pwd: string) {
    try {
      const res = await fetch(`${API_URL}/api/v1/admin/logs`, {
        headers: {
          "X-Admin-Password": pwd,
        },
      });
      if (res.ok) {
        const data = await res.json();
        setLogs(data.logs || []);
      }
    } catch (err) {
      console.error("Failed to fetch logs", err);
    }
  }

  async function handleViewLog(filename: string) {
    setError("");
    try {
      const res = await fetch(`${API_URL}/api/v1/admin/logs/${filename}`, {
        headers: {
          "X-Admin-Password": adminPassword,
        },
      });
      if (!res.ok) throw new Error("ログの取得に失敗しました");
      const text = await res.text();
      setSelectedLogText(text);
      setSelectedLogTitle(filename);
      setIsLogModalOpen(true);
    } catch (err: any) {
      setError(err.message || "ログファイルの取得に失敗しました");
    }
  }

  async function handleReset() {
    const confirm1 = window.confirm(
      "【警告】すべてのゲーム履歴データ、およびラウンドログファイルを削除します。よろしいですか？"
    );
    if (!confirm1) return;

    const confirm2 = window.confirm(
      "本当に実行しますか？この操作は取り消せません。"
    );
    if (!confirm2) return;

    setIsLoading(true);
    setError("");
    setSuccessMessage("");
    try {
      const res = await fetch(`${API_URL}/api/v1/admin/games/reset`, {
        method: "DELETE",
        headers: {
          "X-Admin-Password": adminPassword,
        },
      });
      if (res.ok) {
        setSuccessMessage("データベースおよびログファイルを全消去しました。");
        setLogs([]);
      } else {
        const data = await res.json();
        setError(data.detail || "リセット処理に失敗しました");
      }
    } catch (err) {
      setError("通信エラーが発生しました");
    } finally {
      setIsLoading(false);
    }
  }

  function handleLogout() {
    localStorage.removeItem("admin_password");
    setAdminPassword("");
    setIsAuthenticated(false);
    setLogs([]);
  }

  function formatBytes(bytes: number) {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const dm = 2;
    const sizes = ["Bytes", "KB", "MB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i];
  }

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-gray-950 text-gray-100 flex items-center justify-center p-4">
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-8 max-w-md w-full shadow-2xl">
          <div className="text-center mb-6">
            <h1 className="text-2xl font-bold text-yellow-400 mb-2 font-mono">
              ⚙️ Cowboy Admin Panel
            </h1>
            <p className="text-xs text-gray-400">
              管理画面にアクセスするには管理者パスワードを入力してください
            </p>
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              verifyPassword(adminPassword);
            }}
            className="space-y-4"
          >
            <div>
              <label className="block text-xs text-gray-400 mb-1 font-semibold">
                パスワード
              </label>
              <input
                type="password"
                value={adminPassword}
                onChange={(e) => setAdminPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full bg-gray-950 border border-gray-800 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-yellow-400 text-yellow-300 font-mono transition"
                required
              />
            </div>

            {error && (
              <p className="text-xs text-red-400 bg-red-950/40 border border-red-900 rounded p-2 text-center">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-2.5 rounded-lg bg-yellow-500 hover:bg-yellow-400 text-gray-950 text-sm font-semibold transition active:scale-95 disabled:opacity-50"
            >
              {isLoading ? "検証中..." : "ログイン"}
            </button>

            <div className="text-center pt-2">
              <Link
                href="/dashboard"
                className="text-xs text-gray-500 hover:text-gray-400 transition"
              >
                ← ダッシュボードに戻る
              </Link>
            </div>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      {/* ヘッダー */}
      <header className="sticky top-0 z-10 flex items-center justify-between bg-gray-900/80 backdrop-blur border-b border-gray-800 px-6 py-3">
        <div className="flex items-center gap-2">
          <span className="text-lg">⚙️</span>
          <h1 className="text-lg font-bold text-yellow-400 font-mono">
            Cowboy Admin Panel
          </h1>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/dashboard"
            className="text-xs px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 transition"
          >
            ← ダッシュボード
          </Link>
          <Link
            href="/predictions"
            className="text-xs px-3 py-1.5 rounded bg-yellow-950/40 hover:bg-yellow-900/60 border border-yellow-900/30 text-yellow-300 transition"
          >
            🔮 AI予測
          </Link>
          <button
            onClick={handleLogout}
            className="text-xs px-3 py-1.5 rounded bg-red-950 hover:bg-red-900 text-red-300 transition"
          >
            ログアウト
          </button>
        </div>
      </header>

      <main className="p-4 md:p-6 max-w-6xl mx-auto space-y-6">
        {error && (
          <div className="rounded-lg bg-red-950/60 border border-red-700 px-4 py-3 text-red-300 text-sm">
            {error}
          </div>
        )}
        {successMessage && (
          <div className="rounded-lg bg-green-950/60 border border-green-700 px-4 py-3 text-green-300 text-sm">
            {successMessage}
          </div>
        )}

        {/* メンテナンスアクション */}
        <section className="bg-gray-900 border border-gray-800 rounded-xl p-6">
          <h2 className="text-sm font-semibold text-gray-300 mb-1">
            システムメンテナンス
          </h2>
          <p className="text-xs text-gray-500 mb-4">
            データベースおよびローカルのOCRデバッグログファイルを一括削除できます。通常、この操作は取り消せません。
          </p>

          <div className="flex items-center">
            <button
              onClick={handleReset}
              disabled={isLoading}
              className="px-4 py-2 bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white rounded-lg text-xs font-semibold shadow transition active:scale-95 flex items-center gap-1.5"
            >
              ⚠️ データベースとログの全消去
            </button>
          </div>
        </section>

        {/* ログ一覧 */}
        <section className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
          <div className="flex items-center justify-between border-b border-gray-800 px-4 py-3 bg-gray-900/50">
            <h2 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
              📂 OCR/システムログファイル ({logs.length}件)
            </h2>
            <button
              onClick={() => fetchLogs(adminPassword)}
              className="text-xs px-2 py-1 rounded bg-gray-800 hover:bg-gray-700 transition"
            >
              更新
            </button>
          </div>

          <div className="overflow-x-auto">
            {logs.length === 0 ? (
              <div className="text-center text-gray-500 py-12 text-xs">
                ログファイルが見つかりません。
              </div>
            ) : (
              <table className="min-w-full text-xs text-left">
                <thead className="bg-gray-950 text-gray-400">
                  <tr>
                    <th className="px-4 py-2.5">ファイル名</th>
                    <th className="px-4 py-2.5">サイズ</th>
                    <th className="px-4 py-2.5">最終更新日時</th>
                    <th className="px-4 py-2.5 text-right">アクション</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800">
                  {logs.map((log) => {
                    const date = new Date(log.mtime * 1000);
                    const isErrorLog = log.filename.startsWith("error_");
                    return (
                      <tr
                        key={log.filename}
                        className="hover:bg-gray-800/40 transition"
                      >
                        <td className="px-4 py-2 font-mono flex items-center gap-1.5">
                          {isErrorLog ? (
                            <span className="text-red-400" title="エラー/タイムアウトによるログ">⚠️</span>
                          ) : (
                            <span className="text-gray-500">📄</span>
                          )}
                          <span className={isErrorLog ? "text-red-300 font-semibold" : "text-gray-300"}>
                            {log.filename}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-gray-400">
                          {formatBytes(log.size)}
                        </td>
                        <td className="px-4 py-2 text-gray-400">
                          {date.toLocaleString("ja-JP")}
                        </td>
                        <td className="px-4 py-2 text-right">
                          <button
                            onClick={() => handleViewLog(log.filename)}
                            className="px-2.5 py-1 bg-gray-850 border border-gray-800 hover:bg-gray-800 rounded font-mono text-[11px] text-yellow-400 active:scale-95 transition"
                          >
                            表示
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </section>
      </main>

      {/* ログモーダル */}
      {isLogModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm">
          <div className="bg-gray-950 border border-gray-800 rounded-xl max-w-4xl w-full max-h-[85vh] flex flex-col p-6 shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-800 pb-3">
              <h3 className="text-sm font-semibold text-yellow-400 font-mono">
                📄 Log Viewer: {selectedLogTitle}
              </h3>
              <button
                onClick={() => setIsLogModalOpen(false)}
                className="text-gray-500 hover:text-gray-300 transition text-xs font-semibold px-2.5 py-1 bg-gray-900 rounded border border-gray-800"
              >
                閉じる
              </button>
            </div>
            <pre className="overflow-auto text-xs text-gray-300 font-mono bg-black/50 p-4 rounded border border-gray-900/50 mt-4 flex-1 whitespace-pre-wrap select-text">
              {selectedLogText || "ログの内容がありません"}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
