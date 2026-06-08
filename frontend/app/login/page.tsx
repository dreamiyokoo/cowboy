"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ACCESS_TOKEN_KEY, getValidAccessToken } from "@/app/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (getValidAccessToken()) {
      router.replace("/dashboard");
    }
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) {
        const json = await res.json().catch(() => ({}));
        const detail = json?.detail;
        const msg =
          typeof detail === "string"
            ? detail
            : Array.isArray(detail)
            ? detail.map((d: { msg?: string }) => d.msg ?? "").join(", ")
            : "ログインに失敗しました";
        setError(msg);
        return;
      }
      const { access_token } = await res.json();
      localStorage.setItem(ACCESS_TOKEN_KEY, access_token);
      router.replace("/dashboard");
    } catch {
      setError("サーバーへの接続に失敗しました");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950">
      <div className="w-full max-w-sm bg-gray-900 rounded-xl shadow-xl p-8">
        <h1 className="text-2xl font-bold text-center mb-6 text-yellow-400">
          🤠 Cowboy Dashboard
        </h1>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">ユーザー名</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoComplete="username"
              className="w-full px-4 py-2 rounded-lg bg-gray-800 border border-gray-700
                         text-gray-100 focus:outline-none focus:border-yellow-500"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">パスワード</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              className="w-full px-4 py-2 rounded-lg bg-gray-800 border border-gray-700
                         text-gray-100 focus:outline-none focus:border-yellow-500"
            />
          </div>
          {error && (
            <p className="text-red-400 text-sm">{error}</p>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 rounded-lg bg-yellow-500 hover:bg-yellow-400
                       text-gray-950 font-bold transition disabled:opacity-50"
          >
            {loading ? "ログイン中…" : "ログイン"}
          </button>
        </form>
      </div>
    </div>
  );
}
