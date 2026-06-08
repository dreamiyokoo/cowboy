"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  buildChartData,
  CowboyBullDiffChart,
  CumulPnlChart,
  PayoutChart,
  BetTotalChart,
} from "./Charts";
import {
  getValidAccessToken,
  clearAccessToken,
} from "@/app/lib/auth";
import {
  fetchStats,
  fetchGames,
  fetchCapturePreview,
  fmtAmount,
  RESULT_LABEL,
  RESULT_COLOR,
  BET_COLUMNS,
  WIN_COLUMNS,
  WIN_ODDS,
  WIN_COL_MAP,
  WINNING_HAND_ROW_KEYS,
  WINNING_HAND_ROW_LABELS,
  calcBetTotal,
  calcPayout,
  type Game,
  type StatsResponse,
  type GamesResponse,
  type GameResult,
  type CapturePreview,
} from "@/app/lib/api";

const REFRESH_INTERVAL = 30_000;
const PREVIEW_INTERVAL = 3_000;

export default function DashboardPage() {
  const router = useRouter();
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [gamesData, setGamesData] = useState<GamesResponse | null>(null);
  const [preview, setPreview] = useState<CapturePreview | null>(null);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [showCapture, setShowCapture] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const previewTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function logout() {
    clearAccessToken();
    router.replace("/login");
  }

  async function load() {
    const token = getValidAccessToken();
    if (!token) { router.replace("/login"); return; }
    try {
      const [s, g] = await Promise.all([
        fetchStats(token),
        fetchGames(token, 100, 0),
      ]);
      setStats(s);
      setGamesData(g);
      setLastUpdated(new Date());
      setError("");
    } catch (e: unknown) {
      if (e instanceof Error && "status" in e && (e as {status:number}).status === 401) {
        logout();
      } else {
        setError("データの取得に失敗しました");
      }
    }
  }

  async function loadPreview() {
    const token = getValidAccessToken();
    if (!token) return;
    try {
      const p = await fetchCapturePreview(token);
      setPreview(p);
    } catch {
      // プレビュー取得失敗は無視
    }
  }

  useEffect(() => {
    if (!getValidAccessToken()) { router.replace("/login"); return; }
    load();
    loadPreview();
    timerRef.current = setInterval(load, REFRESH_INTERVAL);
    previewTimerRef.current = setInterval(loadPreview, PREVIEW_INTERVAL);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (previewTimerRef.current) clearInterval(previewTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const games = gamesData?.games ?? [];

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      {/* ヘッダー */}
      <header className="sticky top-0 z-10 flex items-center justify-between
                         bg-gray-900/80 backdrop-blur border-b border-gray-800 px-6 py-3">
        <h1 className="text-xl font-bold text-yellow-400">🤠 Cowboy Dashboard</h1>
        <div className="flex items-center gap-4">
          {lastUpdated && (
            <span className="text-xs text-gray-500">
              更新: {lastUpdated.toLocaleTimeString("ja-JP")}
            </span>
          )}
          <button
            onClick={load}
            className="text-sm px-3 py-1 rounded bg-gray-800 hover:bg-gray-700 transition"
          >
            更新
          </button>
          <button
            onClick={logout}
            className="text-sm px-3 py-1 rounded bg-red-900 hover:bg-red-800 transition"
          >
            ログアウト
          </button>
        </div>
      </header>

      <main className="p-4 md:p-6 space-y-6">
        {error && (
          <div className="rounded-lg bg-red-900/60 border border-red-700 px-4 py-3 text-red-300">
            {error}
          </div>
        )}

        {/* ライブキャプチャプレビュー */}
        <section className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
          <div
            className="flex items-center justify-between px-4 py-3 cursor-pointer select-none"
            onClick={() => setShowCapture(v => !v)}
          >
            <h2 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
              <span className={`text-xs transition-transform ${showCapture ? "rotate-90" : ""}`}>▶</span>
              📷 ライブキャプチャ
              {preview && !showCapture && (
                <span className="text-xs text-gray-500 space-x-2 ml-1">
                  {preview.round_number != null && <span>R{preview.round_number}</span>}
                  {preview.game_state === "result" && <span className="text-green-400">✓ 結果表示</span>}
                  {preview.game_state === "betting" && <span className="text-yellow-400">投票中</span>}
                  {preview.result && <span className={RESULT_COLOR[preview.result as GameResult]?.split(" ")[1]}>{RESULT_LABEL[preview.result as GameResult]}</span>}
                </span>
              )}
            </h2>
            <div className="flex items-center gap-3" onClick={e => e.stopPropagation()}>
              {/* ラウンド番号 */}
              {showCapture && preview?.round_number != null && (
                <span className="px-2 py-0.5 rounded text-xs font-semibold bg-gray-800 text-gray-300">
                  R {preview.round_number}
                </span>
              )}
              {/* ゲーム状態表示 */}
              {showCapture && preview?.game_state && (
                <span className={`px-2 py-0.5 rounded text-xs font-semibold ${
                  preview.game_state === "result"
                    ? "bg-green-900 text-green-300"
                    : preview.game_state === "betting"
                    ? "bg-yellow-900 text-yellow-300"
                    : "bg-gray-700 text-gray-300"
                }`}>
                  {preview.game_state === "result"
                    ? "✓ 結果表示"
                    : preview.game_state === "betting"
                    ? `🗳️ 投票中${preview.remaining_seconds != null ? ` (残り${Math.round(preview.remaining_seconds)}s)` : ""}`
                    : "待機中"}
                </span>
              )}
              {/* 結果ラベル */}
              {showCapture && preview?.result && (
                <span className={`px-2 py-0.5 rounded text-xs font-semibold ${RESULT_COLOR[preview.result as GameResult] ?? ""}`}>
                  {RESULT_LABEL[preview.result as GameResult] ?? preview.result}
                </span>
              )}
            </div>
          </div>
          {showCapture && (
          <><div className="border-t border-gray-800" />
          <div className="flex gap-4 p-4 items-start flex-wrap">
            {/* スクリーンショット */}
            <div className="shrink-0">
              {preview?.screen_image ? (
                <a href={preview.screen_image} target="_blank" rel="noreferrer" title="クリックで拡大">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={preview.screen_image}
                    alt="キャプチャ画面"
                    className="rounded-lg border border-gray-700 cursor-zoom-in hover:opacity-90 transition"
                    style={{ width: 220 }}
                  />
                </a>
              ) : (
                <div className="w-[220px] h-[390px] rounded-lg bg-gray-800 flex items-center justify-center text-gray-600 text-xs">
                  待機中…
                </div>
              )}
              <p className="text-xs text-gray-600 text-center mt-1">クリックで拡大</p>
            </div>
            {/* 検出情報 */}
            <div className="flex-1 flex gap-4 min-w-[260px]">
              {/* テキスト情報 */}
              <div className="space-y-2 text-sm shrink-0">
                <InfoRow label="状態" value={
                  preview?.game_state === "result" ? "結果表示"
                  : preview?.game_state === "betting" ? "投票中"
                  : "—"
                } />
                <InfoRow label="ラウンド" value={preview?.round_number != null ? String(preview.round_number) : "—"} highlight />
                <InfoRow label="オープンカード" value={preview?.open_card ?? "—"} highlight />
                <InfoRow label="検出結果" value={preview?.result ? (RESULT_LABEL[preview.result as GameResult] ?? preview.result) : "—"} />
                <InfoRow label="JPストック" value={preview?.jackpot_stock != null ? fmtAmount(preview.jackpot_stock) : "—"} />
                {!preview && (
                  <p className="text-gray-600 text-xs">プレビューデータがありません</p>
                )}
              </div>

              {/* 主要クロップ画像（コンパクト） */}
              <div className="flex-1 grid grid-cols-2 md:grid-cols-4 gap-2">
                <CropPreview
                  label="ラウンド"
                  image={preview?.round_image}
                  ocr={preview?.round_number != null ? String(preview.round_number) : null}
                  maxW="max-w-[120px]"
                />
                <CropPreview
                  label="オープンカード"
                  image={preview?.open_card_image}
                  ocr={preview?.open_card ?? null}
                  maxW="max-w-[120px]"
                />
                <CropPreview
                  label="JPストック"
                  image={preview?.jackpot_stock_image}
                  ocr={preview?.jackpot_stock != null ? fmtAmount(preview.jackpot_stock) : null}
                  maxW="max-w-[180px]"
                />
                <CropPreview
                  label="結果ボタン行"
                  image={preview?.result_image}
                  ocr={
                    preview?.result_scores
                      ? Object.entries(preview.result_scores)
                          .map(([k, v]) => `${k[0]}:${v.toFixed(2)}`)
                          .join(" ")
                      : (preview?.result ? (RESULT_LABEL[preview.result as GameResult] ?? preview.result) : null)
                  }
                  maxW="max-w-[200px]"
                />
              </div>
            </div>
          </div>

          {/* ベット領域 + 検出額 */}
          {preview?.bet_images && (
            <div className="border-t border-gray-800 px-4 py-3">
              <h3 className="text-xs font-semibold text-gray-400 mb-3">ベット検出結果</h3>
              <div className="grid grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
                {Object.entries(preview.bet_images).map(([key, img]) => {
                  const val = preview.bet_values?.[key];
                  return (
                    <CropPreview
                      key={`bet-${key}`}
                      label={key}
                      image={img}
                      ocr={val != null ? fmtAmount(val) : null}
                    />
                  );
                })}
              </div>
            </div>
          )}

          {/* WIN判定領域 + ペイアウト */}
          {preview?.win_images && (
            <div className="border-t border-gray-800 px-4 py-3">
              <h3 className="text-xs font-semibold text-gray-400 mb-3">WIN判定</h3>
              <div className="grid grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
                {Object.entries(preview.win_images).map(([key, img]) => {
                  const score = preview.win_scores?.[key] ?? null;
                  const isWin = score != null && score >= 0.30;
                  const bet = preview.bet_values?.[key] ?? null;
                  const odds = WIN_ODDS[key] ?? null;
                  const payout = bet != null && odds != null ? Math.floor(bet * odds) : null;
                  const ocrText = isWin && payout != null
                    ? `${fmtAmount(bet)} × ${odds} = ${fmtAmount(payout)} WIN`
                    : bet != null && odds != null
                    ? `${fmtAmount(bet)} × ${odds}倍`
                    : odds != null ? `× ${odds}倍` : null;
                  return (
                    <CropPreview
                      key={`win-${key}`}
                      label={key}
                      image={img}
                      ocr={ocrText}
                      valueColor={isWin ? "text-green-300" : "text-gray-500"}
                    />
                  );
                })}
              </div>
            </div>
          )}

          {/* 勝利ハンド行（FL/CN / 1ペア / Aペア） */}
          {preview?.winning_hand_images && (
            <div className="border-t border-gray-800 px-4 py-3">
              <h3 className="text-xs font-semibold text-gray-400 mb-3">勝利ハンド行</h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {preview.winning_hand_images.map((img, idx) => {
                  const key = WINNING_HAND_ROW_KEYS[idx];
                  const label = WINNING_HAND_ROW_LABELS[idx];
                  const score = preview.win_scores?.[key] ?? preview.winning_hand_scores?.[idx] ?? null;
                  const isWin = score != null && score >= 0.30;
                  const bet = key ? (preview.bet_values?.[key] ?? null) : null;
                  const odds = key ? (WIN_ODDS[key] ?? null) : null;
                  const payout = bet != null && odds != null ? Math.floor(bet * odds) : null;
                  const ocrText = isWin && payout != null
                    ? `${fmtAmount(bet)} × ${odds} = ${fmtAmount(payout)} WIN`
                    : bet != null && odds != null
                    ? `${fmtAmount(bet)} × ${odds}倍`
                    : odds != null ? `× ${odds}倍` : null;
                  return (
                    <CropPreview
                      key={`hand-${idx}`}
                      label={label ?? `ハンド ${idx + 1}`}
                      image={img}
                      ocr={ocrText}
                      valueColor={isWin ? "text-green-300" : "text-gray-500"}
                      maxW="max-w-[320px]"
                    />
                  );
                })}
              </div>
            </div>
          )}
          </>)}
        </section>

        {/* 統計カード */}
        {stats && (
          <>
            <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <StatCard label="総ゲーム数" value={stats.total} />
              <StatCard
                label="カウボーイ"
                value={`${stats.result_counts.cowboy} (${(stats.result_rates.cowboy * 100).toFixed(1)}%)`}
                className="border-red-800"
              />
              <StatCard
                label="ブル"
                value={`${stats.result_counts.bull} (${(stats.result_rates.bull * 100).toFixed(1)}%)`}
                className="border-blue-800"
              />
              <StatCard
                label="抽選"
                value={`${stats.result_counts.draw} (${(stats.result_rates.draw * 100).toFixed(1)}%)`}
                className="border-green-800"
              />
            </section>

            {stats.total_bet_sum > 0 && (
              <section className="grid grid-cols-3 gap-3">
                <StatCard label="ベット合計" value={fmtAmount(stats.total_bet_sum)} />
                <StatCard label="払い出し" value={fmtAmount(stats.total_payout)} />
                <StatCard
                  label="ユーザー収支"
                  value={(stats.user_pnl >= 0 ? "+" : "") + fmtAmount(stats.user_pnl)}
                  className={stats.user_pnl >= 0 ? "border-green-800" : "border-red-800"}
                />
              </section>
            )}
          </>
        )}

        {/* 結果分布バー */}
        {stats && stats.total > 0 && (
          <section className="bg-gray-900 rounded-xl p-4 space-y-2">
            <h2 className="text-sm font-semibold text-gray-400 mb-3">結果分布</h2>
            <ResultBar label="カウボーイ" count={stats.result_counts.cowboy} total={stats.total} color="bg-red-600" />
            <ResultBar label="ブル"       count={stats.result_counts.bull}   total={stats.total} color="bg-blue-600" />
            <ResultBar label="抽選"       count={stats.result_counts.draw}   total={stats.total} color="bg-green-600" />
          </section>
        )}

        {/* グラフ */}
        {games.length >= 2 && (() => {
          const chartData = buildChartData(games);
          return (
            <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <CowboyBullDiffChart data={chartData} />
              <CumulPnlChart data={chartData} />
              <PayoutChart data={chartData} />
              <BetTotalChart data={chartData} />
            </section>
          );
        })()}

        {/* ゲーム履歴テーブル */}
        {games.length > 0 && (
          <section>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-gray-400">
                ゲーム履歴 (最新 {games.length} 件 / 全 {gamesData?.total} 件)
              </h2>
            </div>
            <div className="overflow-x-auto rounded-xl border border-gray-800">
              <table className="min-w-full text-xs">
                <thead className="bg-gray-900 text-gray-400">
                  <tr>
                    <Th>#</Th>
                    <Th>結果</Th>
                    <Th>R</Th>
                    <Th>オープン</Th>
                    <Th>JP</Th>
                    {BET_COLUMNS.map((c) => <Th key={c.key}>{c.label}</Th>)}
                    {WIN_COLUMNS.map((c) => <Th key={c.key}>{c.label} W</Th>)}
                    <Th>ベット合計</Th>
                    <Th>払い出し</Th>
                    <Th>収支</Th>
                    <Th>記録日時</Th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800">
                  {games.map((g) => (
                    <GameRow key={g.id} game={g} />
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {!stats && !error && (
          <div className="text-center text-gray-500 py-16">読み込み中…</div>
        )}
      </main>
    </div>
  );
}

// ── サブコンポーネント ─────────────────────────────────

function InfoRow({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-gray-500 text-xs w-28 shrink-0">{label}</span>
      <span className={`font-mono font-semibold ${highlight ? "text-yellow-300 text-base" : "text-gray-200"}`}>
        {value}
      </span>
    </div>
  );
}

function CropPreview({
  label,
  image,
  ocr,
  valueColor,
  maxW = "max-w-[120px]",
}: {
  label: string;
  image?: string | null;
  ocr?: string | null;
  valueColor?: string;
  maxW?: string;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1 gap-1">
        <span className="text-gray-500 text-xs truncate">{label}</span>
        <span className={`font-mono text-xs shrink-0 ${valueColor ?? "text-yellow-300"}`}>
          {ocr ?? "—"}
        </span>
      </div>
      {image ? (
        <a href={image} target="_blank" rel="noreferrer" title="クリックで拡大">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={image}
            alt={label}
            className={`rounded border border-gray-700 cursor-zoom-in hover:opacity-90 transition w-full ${maxW} bg-gray-800`}
          />
        </a>
      ) : (
        <div className="h-8 rounded border border-gray-800 bg-gray-800/50 flex items-center justify-center text-gray-600 text-xs">
          —
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  className = "",
}: {
  label: string;
  value: string | number;
  className?: string;
}) {
  return (
    <div
      className={`bg-gray-900 rounded-xl p-4 border border-gray-800 ${className}`}
    >
      <p className="text-xs text-gray-400 mb-1">{label}</p>
      <p className="text-lg font-bold">{value}</p>
    </div>
  );
}

function ResultBar({
  label,
  count,
  total,
  color,
}: {
  label: string;
  count: number;
  total: number;
  color: string;
}) {
  const pct = total > 0 ? ((count / total) * 100).toFixed(1) : "0.0";
  const w = total > 0 ? (count / total) * 100 : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="w-24 text-xs text-gray-300 shrink-0">{label}</span>
      <div className="flex-1 h-4 bg-gray-800 rounded-full overflow-hidden">
        <div
          className={`h-full ${color} transition-all`}
          style={{ width: `${w}%` }}
        />
      </div>
      <span className="w-20 text-right text-xs text-gray-400">
        {count} ({pct}%)
      </span>
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-3 py-2 text-left font-medium whitespace-nowrap">{children}</th>
  );
}

function GameRow({ game }: { game: Game }) {
  const colorCls = RESULT_COLOR[game.result as GameResult] ?? "bg-gray-800 text-gray-300";
  const dt = new Date(game.recorded_at);
  const dtStr = `${dt.getMonth() + 1}/${dt.getDate()} ${dt.getHours().toString().padStart(2,"0")}:${dt.getMinutes().toString().padStart(2,"0")}`;

  return (
    <tr className="hover:bg-gray-800/50 transition">
      <td className="px-3 py-1.5 text-gray-500">{game.id}</td>
      <td className="px-3 py-1.5">
        <span className={`px-2 py-0.5 rounded text-xs font-semibold ${colorCls}`}>
          {RESULT_LABEL[game.result as GameResult] ?? game.result}
        </span>
      </td>
      <td className="px-3 py-1.5 text-gray-400">{game.round_number ?? "—"}</td>
      <td className="px-3 py-1.5 font-mono text-yellow-300">{game.open_card ?? "—"}</td>
      <td className="px-3 py-1.5 text-right text-amber-400 font-mono text-xs">{game.jackpot_stock != null ? fmtAmount(game.jackpot_stock) : "—"}</td>
      {BET_COLUMNS.map((c) => (
        <td key={c.key} className="px-3 py-1.5 text-right text-gray-300">
          {fmtAmount(game[c.key] as number | null)}
        </td>
      ))}
      {WIN_COLUMNS.map((c) => {
        const map = WIN_COL_MAP[c.key as string];
        const isWin = game[c.key] === true;
        const bet = map ? (game[map.betKey] as number | null) : null;
        const odds = map ? (WIN_ODDS[map.oddsKey] ?? null) : null;
        const payout = isWin && bet != null && odds != null
          ? Math.floor(bet * odds) : null;
        return (
          <td key={c.key} className="px-3 py-1.5 text-right">
            {game[c.key] == null ? (
              <span className="text-gray-700">—</span>
            ) : isWin ? (
              payout != null && payout < 10_000_000 ? (
                <span className="text-green-400 font-semibold text-xs">{fmtAmount(payout)}</span>
              ) : (
                <span className="text-green-600 text-xs">✓</span>
              )
            ) : (
              <span className="text-gray-700">—</span>
            )}
          </td>
        );
      })}
      {(() => {
        const betTotal = calcBetTotal(game);
        const payout = calcPayout(game);
        const balance = payout - betTotal;
        return (
          <>
            <td className="px-3 py-1.5 text-right text-gray-300">{fmtAmount(betTotal || null)}</td>
            <td className="px-3 py-1.5 text-right text-gray-300">{fmtAmount(payout || null)}</td>
            <td className={`px-3 py-1.5 text-right font-semibold ${balance > 0 ? "text-green-400" : balance < 0 ? "text-red-400" : "text-gray-500"}`}>
              {betTotal === 0 ? "—" : (balance > 0 ? "+" : "") + fmtAmount(balance)}
            </td>
          </>
        );
      })()}
      <td className="px-3 py-1.5 text-gray-500 whitespace-nowrap">{dtStr}</td>
    </tr>
  );
}
