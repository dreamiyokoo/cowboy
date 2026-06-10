"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  getValidAccessToken,
  clearAccessToken,
} from "@/app/lib/auth";
import {
  fetchCardStats,
  type CardStatsItem,
  type CardStatsRates,
} from "@/app/lib/api";

type SortKey = "card" | "total" | keyof CardStatsRates;
type SortOrder = "asc" | "desc";

const rankOrder = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"];
const suitOrder = ["S", "H", "D", "C"]; // Spade, Heart, Diamond, Club

const getCardSortValue = (cardStr: string) => {
  if (!cardStr) return { suitIdx: 99, rankIdx: -1 };
  const suit = cardStr.slice(-1);
  const rank = cardStr.slice(0, -1);
  const suitIdx = suitOrder.indexOf(suit);
  const rankIdx = rankOrder.indexOf(rank);
  return { suitIdx: suitIdx >= 0 ? suitIdx : 99, rankIdx };
};

export default function CardStatsPage() {
  const router = useRouter();
  const [stats, setStats] = useState<CardStatsItem[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>("card");
  const [sortOrder, setSortOrder] = useState<SortOrder>("asc");
  const [selectedSuits, setSelectedSuits] = useState<string[]>(["S", "H", "D", "C"]);
  const [selectedRanks, setSelectedRanks] = useState<string[]>(rankOrder);

  function logout() {
    clearAccessToken();
    router.replace("/login");
  }

  async function loadData() {
    const token = getValidAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    try {
      setLoading(true);
      const res = await fetchCardStats(token);
      setStats(res.card_stats);
      setError("");
    } catch (e: any) {
      if (e.status === 401) {
        logout();
      } else {
        setError("データの取得に失敗しました");
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!getValidAccessToken()) {
      router.replace("/login");
      return;
    }
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortOrder(sortOrder === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortOrder("desc"); // デフォルトは降順
    }
  };

  const toggleSuit = (suit: string) => {
    if (selectedSuits.includes(suit)) {
      setSelectedSuits(selectedSuits.filter((s) => s !== suit));
    } else {
      setSelectedSuits([...selectedSuits, suit]);
    }
  };

  const toggleAllSuits = () => {
    if (selectedSuits.length === 4) {
      setSelectedSuits([]);
    } else {
      setSelectedSuits(["S", "H", "D", "C"]);
    }
  };

  const toggleRank = (rank: string) => {
    if (selectedRanks.includes(rank)) {
      setSelectedRanks(selectedRanks.filter((r) => r !== rank));
    } else {
      setSelectedRanks([...selectedRanks, rank]);
    }
  };

  const toggleAllRanks = () => {
    if (selectedRanks.length === rankOrder.length) {
      setSelectedRanks([]);
    } else {
      setSelectedRanks([...rankOrder]);
    }
  };

  const filteredStats = stats.filter((item) => {
    if (!item.card) return false;
    const suit = item.card.slice(-1);
    const rank = item.card.slice(0, -1);

    const suitMatch = selectedSuits.includes(suit);
    const rankMatch = selectedRanks.includes(rank);

    return suitMatch && rankMatch;
  });

  const sortedStats = [...filteredStats].sort((a, b) => {
    const aVal = getCardSortValue(a.card);
    const bVal = getCardSortValue(b.card);

    // 第一ソートルールは常にスート (S -> H -> D -> C)
    if (aVal.suitIdx !== bVal.suitIdx) {
      return sortOrder === "asc"
        ? aVal.suitIdx - bVal.suitIdx
        : bVal.suitIdx - aVal.suitIdx;
    }

    // 第二ソートルール (同じスート内での比較)
    if (sortKey === "card") {
      // 2〜10KAの降順 (Aが一番上、2が一番下)
      return sortOrder === "asc"
        ? bVal.rankIdx - aVal.rankIdx
        : aVal.rankIdx - bVal.rankIdx;
    }

    let valA = sortKey === "total" ? a.total : a.rates[sortKey];
    let valB = sortKey === "total" ? b.total : b.rates[sortKey];

    if (valA !== valB) {
      return sortOrder === "asc"
        ? valA - valB
        : valB - valA;
    }

    // 最終的な安定ソート (ランク降順)
    return bVal.rankIdx - aVal.rankIdx;
  });

  const columns: { key: SortKey; label: string; tooltip?: string }[] = [
    { key: "card", label: "カード" },
    { key: "total", label: "抽選回数" },
    { key: "cowboy", label: "カウボーイ" },
    { key: "draw", label: "抽選 (Draw)" },
    { key: "bull", label: "ブル" },
    { key: "any_flash", label: "FL/CN", tooltip: "フラッシュ/コネクト/フラッシュコネクト" },
    { key: "any_pair", label: "1ペア" },
    { key: "any_ace", label: "Aペア" },
    { key: "win_high", label: "ハイ/1P" },
    { key: "win_two", label: "2ペア" },
    { key: "win_sf", label: "3K/ST/FL", tooltip: "スリーカード/ストレート/フラッシュ" },
    { key: "win_fh", label: "FH", tooltip: "フルハウス" },
    { key: "win_four", label: "4K+", tooltip: "フォーオブアカインド以上" },
  ];

  // スートの絵文字を付与するヘルパー
  const formatCard = (cardStr: string) => {
    if (!cardStr) return "";
    // スート文字 (S, H, D, C) を絵文字にする
    const suit = cardStr.slice(-1);
    const rank = cardStr.slice(0, -1);
    let suitEmoji = "";
    let suitColor = "text-gray-400";
    if (suit === "H") { suitEmoji = "♥"; suitColor = "text-red-500"; }
    else if (suit === "D") { suitEmoji = "♦"; suitColor = "text-red-400"; }
    else if (suit === "S") { suitEmoji = "♠"; suitColor = "text-blue-500"; }
    else if (suit === "C") { suitEmoji = "♣"; suitColor = "text-green-500"; }
    
    return (
      <span className="font-bold">
        {rank}
        <span className={`ml-1 ${suitColor}`}>{suitEmoji}</span>
      </span>
    );
  };

  const getSortIcon = (key: SortKey) => {
    if (sortKey !== key) return "↕";
    return sortOrder === "asc" ? "▲" : "▼";
  };

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      {/* ヘッダー */}
      <header className="sticky top-0 z-10 flex items-center justify-between
                         bg-gray-900/80 backdrop-blur border-b border-gray-800 px-6 py-3">
        <h1 className="text-xl font-bold text-yellow-400">📊 カード別 WIN確率</h1>
        <div className="flex items-center gap-4">
          <Link
            href="/dashboard"
            className="text-sm px-3 py-1 rounded bg-gray-800 hover:bg-gray-700 transition text-gray-300 font-medium"
          >
            🏠 ダッシュボード
          </Link>
          <Link
            href="/predictions"
            className="text-sm px-3 py-1 rounded bg-yellow-950/40 hover:bg-yellow-900/60 border border-yellow-900/30 transition text-yellow-300 font-medium"
          >
            🔮 AI予測
          </Link>
          <Link
            href="/admin"
            className="text-sm px-3 py-1 rounded bg-gray-800 hover:bg-gray-700 transition text-gray-300 font-medium"
          >
            ⚙️ 管理画面
          </Link>
          <button
            onClick={logout}
            className="text-sm px-3 py-1 rounded bg-red-950/80 hover:bg-red-900 border border-red-900/50 text-red-300 transition"
          >
            ログアウト
          </button>
        </div>
      </header>

      {/* メインコンテンツ */}
      <main className="p-6 max-w-7xl mx-auto space-y-6">
        <div className="flex flex-col gap-4 bg-gray-900/30 border border-gray-800/80 rounded p-4">
          <div className="flex flex-col lg:flex-row gap-6 justify-between">
            {/* スート選択 */}
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-4">
                <span className="text-xs font-semibold text-yellow-500/95">♠♥♦♣ スート絞り込み</span>
                <button
                  onClick={toggleAllSuits}
                  className="text-[10px] text-gray-400 hover:text-yellow-400 transition"
                >
                  {selectedSuits.length === 4 ? "全解除" : "全選択"}
                </button>
              </div>
              <div className="flex flex-wrap gap-4 bg-gray-950/40 px-3 py-2 rounded border border-gray-800/60">
                {[
                  { key: "S", label: "♠ Spade", color: "text-blue-500" },
                  { key: "H", label: "♥ Heart", color: "text-red-500" },
                  { key: "D", label: "♦ Diamond", color: "text-red-400" },
                  { key: "C", label: "♣ Club", color: "text-green-500" }
                ].map((s) => (
                  <label key={s.key} className="flex items-center gap-1.5 cursor-pointer text-xs select-none hover:text-gray-200">
                    <input
                      type="checkbox"
                      checked={selectedSuits.includes(s.key)}
                      onChange={() => toggleSuit(s.key)}
                      className="accent-yellow-500 rounded border-gray-700 bg-gray-800 w-3.5 h-3.5"
                    />
                    <span className={`font-semibold ${s.color}`}>{s.label}</span>
                  </label>
                ))}
              </div>
            </div>

            {/* ランク選択 */}
            <div className="space-y-2 flex-1">
              <div className="flex items-center justify-between gap-4">
                <span className="text-xs font-semibold text-yellow-500/95">🔢 ランク絞り込み</span>
                <button
                  onClick={toggleAllRanks}
                  className="text-[10px] text-gray-400 hover:text-yellow-400 transition"
                >
                  {selectedRanks.length === rankOrder.length ? "全解除" : "全選択"}
                </button>
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-2 bg-gray-950/40 px-3 py-2 rounded border border-gray-800/60">
                {rankOrder.slice().reverse().map((r) => (
                  <label key={r} className="flex items-center gap-1.5 cursor-pointer text-xs select-none hover:text-gray-200">
                    <input
                      type="checkbox"
                      checked={selectedRanks.includes(r)}
                      onChange={() => toggleRank(r)}
                      className="accent-yellow-500 rounded border-gray-700 bg-gray-800 w-3.5 h-3.5"
                    />
                    <span className="text-gray-300 font-semibold">{r}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>
        </div>

        {error && (
          <div className="p-4 bg-red-950/50 border border-red-900/50 rounded text-sm text-red-400">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center h-64">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-yellow-500"></div>
          </div>
        ) : sortedStats.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 bg-gray-900/40 rounded border border-gray-800 p-6">
            <p className="text-gray-400 text-sm">統計データがありません</p>
          </div>
        ) : (
          <div className="overflow-x-auto rounded border border-gray-800 bg-gray-900/20 backdrop-blur">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-gray-900 border-b border-gray-800 text-gray-400 font-medium">
                  {columns.map((col) => (
                    <th
                      key={col.key}
                      onClick={() => handleSort(col.key)}
                      className="px-4 py-3 cursor-pointer hover:bg-gray-800 hover:text-gray-200 select-none"
                      title={col.tooltip}
                    >
                      <div className="flex items-center gap-1">
                        <span>{col.label}</span>
                        <span className="text-gray-600 text-[10px]">{getSortIcon(col.key)}</span>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/60">
                {sortedStats.map((item, idx) => (
                  <tr key={idx} className="hover:bg-gray-800/30 transition">
                    <td className="px-4 py-3 whitespace-nowrap bg-gray-950/30 font-semibold border-r border-gray-800/40">
                      {formatCard(item.card)}
                    </td>
                    <td className="px-4 py-3 text-gray-400 font-medium border-r border-gray-800/40">
                      {item.total}
                    </td>
                    {/* カウボーイ */}
                    <td className={`px-4 py-3 font-medium ${item.rates.cowboy > 0.5 ? "text-red-400 font-bold" : "text-gray-300"}`}>
                      {(item.rates.cowboy * 100).toFixed(1)}%
                    </td>
                    {/* 抽選 */}
                    <td className="px-4 py-3 text-gray-300">
                      {(item.rates.draw * 100).toFixed(1)}%
                    </td>
                    {/* ブル */}
                    <td className={`px-4 py-3 font-medium ${item.rates.bull > 0.5 ? "text-blue-400 font-bold" : "text-gray-300"}`}>
                      {(item.rates.bull * 100).toFixed(1)}%
                    </td>
                    {/* FL/CN */}
                    <td className="px-4 py-3 text-gray-300">
                      {(item.rates.any_flash * 100).toFixed(1)}%
                    </td>
                    {/* 1ペア */}
                    <td className="px-4 py-3 text-gray-300">
                      {(item.rates.any_pair * 100).toFixed(1)}%
                    </td>
                    {/* Aペア */}
                    <td className="px-4 py-3 text-gray-300">
                      {(item.rates.any_ace * 100).toFixed(1)}%
                    </td>
                    {/* ハイ/1P */}
                    <td className="px-4 py-3 text-gray-300">
                      {(item.rates.win_high * 100).toFixed(1)}%
                    </td>
                    {/* 2ペア */}
                    <td className="px-4 py-3 text-gray-300">
                      {(item.rates.win_two * 100).toFixed(1)}%
                    </td>
                    {/* 3K/ST/FL */}
                    <td className="px-4 py-3 text-gray-300">
                      {(item.rates.win_sf * 100).toFixed(1)}%
                    </td>
                    {/* FH */}
                    <td className="px-4 py-3 text-gray-300">
                      {(item.rates.win_fh * 100).toFixed(1)}%
                    </td>
                    {/* 4K+ */}
                    <td className="px-4 py-3 text-gray-300">
                      {(item.rates.win_four * 100).toFixed(1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}
