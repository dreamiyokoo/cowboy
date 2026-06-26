"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import AppHeader from "@/app/components/AppHeader";
import GameProgressBar from "@/app/components/GameProgressBar";
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
  fetchCardStatSingle,
  fetchGameIntervals,
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
  type CardStatsItem,
  type GameIntervalsResponse,
} from "@/app/lib/api";

const REFRESH_INTERVAL = 30_000;
const PREVIEW_INTERVAL = 3_000;
const PREVIEW_INTERVAL_BETTING = 1_000;

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
  const lastFetchedCardRef = useRef<string | null>(null);
  const lastSoundResultRef = useRef<string | null>(null);

  const [limit, setLimit] = useState(500);
  const [historyLimit, setHistoryLimit] = useState(10);
  const [selectedLogText, setSelectedLogText] = useState<string | null>(null);
  const [selectedLogTitle, setSelectedLogTitle] = useState("");
  const [isLogModalOpen, setIsLogModalOpen] = useState(false);
  const [isLoadingLog, setIsLoadingLog] = useState(false);
  const [selectedCaptureUrl, setSelectedCaptureUrl] = useState<string | null>(null);
  const [selectedCaptureTitle, setSelectedCaptureTitle] = useState("");
  const [isCaptureModalOpen, setIsCaptureModalOpen] = useState(false);
  const [isLoadingCapture, setIsLoadingCapture] = useState(false);
  const [cardStat, setCardStat] = useState<CardStatsItem | null>(null);
  const [gameIntervals, setGameIntervals] = useState<GameIntervalsResponse | null>(null);

  function logout() {
    clearAccessToken();
    router.replace("/login");
  }

  async function load() {
    const token = getValidAccessToken();
    if (!token) { router.replace("/login"); return; }
    try {
      const [s, g, iv] = await Promise.all([
        fetchStats(token),
        fetchGames(token, limit, 0),
        fetchGameIntervals(token),
      ]);
      setStats(s);
      setGamesData(g);
      setGameIntervals(iv);
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
      // 投票中にオープンカードが検出されたとき、統計データを取得する
      if (p && p.open_card && p.open_card !== lastFetchedCardRef.current) {
        lastFetchedCardRef.current = p.open_card;
        try {
          const stat = await fetchCardStatSingle(token, p.open_card);
          setCardStat(stat);
        } catch {
          setCardStat(null);
        }
      }
      // カードが消えたらリセット
      if (!p || !p.open_card) {
        lastFetchedCardRef.current = null;
        setCardStat(null);
      }
    } catch {
      // プレビュー取得失敗は無視
    }
  }

  async function handleViewLog(logFileName: string) {
    const token = getValidAccessToken();
    if (!token) return;
    setIsLoadingLog(true);
    setSelectedLogTitle(logFileName);
    try {
      const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
      const res = await fetch(`${API_URL}/api/v1/games/logs/${logFileName}`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
      if (!res.ok) throw new Error("ログの取得に失敗しました");
      const text = await res.text();
      setSelectedLogText(text);
      setIsLogModalOpen(true);
    } catch (err: any) {
      alert(err.message || "ログファイルの取得に失敗しました");
    } finally {
      setIsLoadingLog(false);
    }
  }

  async function handleViewCapture(gameId: number) {
    const token = getValidAccessToken();
    if (!token) return;
    setIsLoadingCapture(true);
    setSelectedCaptureTitle(`Game #${gameId} Result Capture`);
    
    if (selectedCaptureUrl) {
      URL.revokeObjectURL(selectedCaptureUrl);
      setSelectedCaptureUrl(null);
    }

    try {
      const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
      const res = await fetch(`${API_URL}/api/v1/games/captures/${gameId}`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
      if (!res.ok) throw new Error("キャプチャの取得に失敗しました");
      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      setSelectedCaptureUrl(objectUrl);
      setIsCaptureModalOpen(true);
    } catch (err: any) {
      alert(err.message || "キャプチャの取得に失敗しました");
    } finally {
      setIsLoadingCapture(false);
    }
  }

  function handleCloseCaptureModal() {
    setIsCaptureModalOpen(false);
    if (selectedCaptureUrl) {
      URL.revokeObjectURL(selectedCaptureUrl);
      setSelectedCaptureUrl(null);
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
  }, [limit]);

  // 結果確定時にサウンドを再生（result_detected_at をキーにして1回だけ）
  useEffect(() => {
    const result = preview?.result;
    const detectedAt = preview?.result_detected_at;
    if (!result || !detectedAt || result === "error") return;
    if (detectedAt === lastSoundResultRef.current) return;
    lastSoundResultRef.current = detectedAt;
    const audio = new Audio(`/sound/${result}.wav`);
    audio.play().catch(() => {});
  }, [preview?.result, preview?.result_detected_at]);

  // BETTING中はポーリングを1秒に短縮してベットスキャン後の更新予測を即時反映
  useEffect(() => {
    if (previewTimerRef.current) clearInterval(previewTimerRef.current);
    const interval = preview?.game_state === "betting" ? PREVIEW_INTERVAL_BETTING : PREVIEW_INTERVAL;
    previewTimerRef.current = setInterval(loadPreview, interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview?.game_state]);

  const games = gamesData?.games ?? [];

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <AppHeader
        currentPage="dashboard"
        onLogout={logout}
        onRefresh={load}
        lastUpdated={lastUpdated}
      />
      <GameProgressBar preview={preview} />

      <main className="p-4 md:p-6 space-y-6">
        {error && (
          <div className="rounded-lg bg-red-900/60 border border-red-700 px-4 py-3 text-red-300">
            {error}
          </div>
        )}

        {/* AI予測カード（常時表示） */}
        {preview?.prediction && (
          <AIPredictionCard
            prediction={preview.prediction}
            sideBet={preview.side_bet_prediction}
            roundNumber={preview.round_number}
            gameState={preview.game_state}
            openCard={preview.open_card}
            gaps={gameIntervals ? Object.fromEntries(
              Object.entries(gameIntervals.categories).map(([k, v]) => [k, (v as { current_gap: number }).current_gap] as [string, number])
            ) : undefined}
          />
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
                  {preview.game_state === "preparing" && <span className="text-blue-400">準備中</span>}
                  {preview.game_state === "cooldown" && <span className="text-gray-400">待機中</span>}
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
                    : preview.game_state === "preparing"
                    ? "bg-blue-900 text-blue-300"
                    : "bg-gray-800 text-gray-400"
                }`}>
                  {preview.game_state === "result"
                    ? "✓ 結果表示"
                    : preview.game_state === "betting"
                    ? `🗳️ 投票中${preview.remaining_seconds != null ? ` (残り${Math.round(preview.remaining_seconds)}s)` : ""}`
                    : preview.game_state === "preparing"
                    ? "🔄 準備中 (シャッフル)"
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
                  : preview?.game_state === "betting" ? (
                      preview.remaining_seconds != null
                        ? `🗳️ 投票中 (残り ${Math.round(preview.remaining_seconds)}s)`
                        : "🗳️ 投票中"
                    )
                  : preview?.game_state === "preparing" ? "🔄 準備中"
                  : preview?.game_state === "cooldown" ? (
                      preview.remaining_seconds != null
                        ? `💤 待機中 (残り ${Math.round(preview.remaining_seconds)}s)`
                        : "💤 待機中"
                    )
                  : "—"
                } />
                {preview?.open_detected_at && (
                  <InfoRow
                    label="オープン検出"
                    value={(() => {
                      const t = new Date(preview.open_detected_at);
                      const diff = Math.max(0, Math.round((new Date().getTime() - t.getTime()) / 1000));
                      return `${t.toLocaleTimeString("ja-JP")} (${diff}s経過)`;
                    })()}
                  />
                )}
                {preview?.result_detected_at && (
                  <InfoRow
                    label="結果検出"
                    value={(() => {
                      const t = new Date(preview.result_detected_at);
                      const diff = Math.max(0, Math.round((new Date().getTime() - t.getTime()) / 1000));
                      return `${t.toLocaleTimeString("ja-JP")} (${diff}s経過)`;
                    })()}
                  />
                )}
                <InfoRow label="ラウンド" value={preview?.round_number != null ? String(preview.round_number) : "—"} highlight />
                <InfoRow label="オープンカード" value={preview?.open_card ?? "—"} highlight />
                <InfoRow label="タイマー" value={preview?.timer_value != null ? `${preview.timer_value}s` : "—"} highlight />
                <InfoRow label="検出結果" value={preview?.result ? (RESULT_LABEL[preview.result as GameResult] ?? preview.result) : "—"} />
                <InfoRow label="JPストック" value={preview?.jackpot_stock != null ? fmtAmount(preview.jackpot_stock) : "—"} />
                {!preview && (
                  <p className="text-gray-600 text-xs">プレビューデータがありません</p>
                )}
                {preview?.prediction && (
                  <PredictionGauge
                    prediction={preview.prediction}
                    sideBet={preview.side_bet_prediction}
                    gaps={gameIntervals ? Object.fromEntries(
                      Object.entries(gameIntervals.categories).map(([k, v]) => [k, v.current_gap] as [string, number])
                    ) : undefined}
                  />
                )}
              </div>

              {/* 主要クロップ画像（コンパクト） */}
              <div className="flex-1 grid grid-cols-2 md:grid-cols-5 gap-2">
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
                  label="タイマー"
                  image={preview?.timer_image}
                  ocr={preview?.timer_value != null ? String(preview.timer_value) : null}
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

        {/* オープンカード統計パネル */}
        {cardStat && (
          <section className="bg-gray-900 rounded-xl border border-amber-800/50 overflow-hidden">
            <div className="flex items-center gap-3 px-4 py-2.5 bg-amber-900/20 border-b border-amber-800/40">
              <span className="text-amber-400 text-sm font-bold">📊 オープンカード統計</span>
              <span className="text-2xl font-black text-white tracking-wider">{cardStat.card}</span>
              <span className="text-xs text-gray-400 ml-auto">{cardStat.total}ゲーム分</span>
            </div>
            <div className="p-3 space-y-1.5 text-xs font-semibold">
              {/* 上段: カウボーイ・投票・ブル */}
              <div className="grid grid-cols-3 gap-1.5">
                {(["cowboy", "draw", "bull"] as const).map((key) => {
                  const pct = Math.round(cardStat.rates[key] * 100);
                  const labels: Record<string, string> = { cowboy: "カウボーイ", draw: "投票", bull: "ブル" };
                  const colors: Record<string, string> = { cowboy: "text-red-400", draw: "text-green-400", bull: "text-blue-400" };
                  return (
                    <div key={key} className={`rounded px-2 py-1.5 text-center ${pct >= 50 ? "bg-amber-500/30 border border-amber-500/60" : "bg-gray-800/60 border border-gray-700/40"}`}>
                      <div className={`text-[10px] ${colors[key]}`}>{labels[key]}</div>
                      <div className={`text-base font-black ${pct >= 50 ? "text-amber-300" : "text-gray-300"}`}>{pct}%</div>
                    </div>
                  );
                })}
              </div>
              {/* 区切り */}
              <div className="border-t border-gray-700/50" />
              {/* 下段: 左列（任意ハンド）と右列（勝利ハンド）を横並び */}
              <div className="flex gap-1.5">
                {/* 左列: FL/CN / 1ペア / Aペア */}
                <div className="flex flex-col gap-1.5 flex-1">
                  {(["any_flash", "any_pair", "any_ace"] as const).map((key) => {
                    const pct = Math.round(cardStat.rates[key] * 100);
                    const labels: Record<string, string> = { any_flash: "FL/CN", any_pair: "1ペア", any_ace: "Aペア" };
                    return (
                      <div key={key} className={`rounded px-2 py-1.5 text-center ${pct >= 50 ? "bg-amber-500/30 border border-amber-500/60" : "bg-gray-800/60 border border-gray-700/40"}`}>
                        <div className="text-[10px] text-gray-400">{labels[key]}</div>
                        <div className={`text-base font-black ${pct >= 50 ? "text-amber-300" : "text-gray-300"}`}>{pct}%</div>
                      </div>
                    );
                  })}
                </div>
                {/* セパレーター */}
                <div className="w-px bg-gray-700/50" />
                {/* 右列: ハイ/1P + 2ペア / 3K+ + FH / 4K+ */}
                <div className="flex flex-col gap-1.5 flex-1">
                  <div className="grid grid-cols-2 gap-1.5">
                    {(["win_high", "win_two"] as const).map((key) => {
                      const pct = Math.round(cardStat.rates[key] * 100);
                      const labels: Record<string, string> = { win_high: "ハイ/1P", win_two: "2ペア" };
                      return (
                        <div key={key} className={`rounded px-2 py-1.5 text-center ${pct >= 50 ? "bg-amber-500/30 border border-amber-500/60" : "bg-gray-800/60 border border-gray-700/40"}`}>
                          <div className="text-[10px] text-gray-400">{labels[key]}</div>
                          <div className={`text-base font-black ${pct >= 50 ? "text-amber-300" : "text-gray-300"}`}>{pct}%</div>
                        </div>
                      );
                    })}
                  </div>
                  <div className="grid grid-cols-2 gap-1.5">
                    {(["win_sf", "win_fh"] as const).map((key) => {
                      const pct = Math.round(cardStat.rates[key] * 100);
                      const labels: Record<string, string> = { win_sf: "3K+", win_fh: "FH" };
                      return (
                        <div key={key} className={`rounded px-2 py-1.5 text-center ${pct >= 50 ? "bg-amber-500/30 border border-amber-500/60" : "bg-gray-800/60 border border-gray-700/40"}`}>
                          <div className="text-[10px] text-gray-400">{labels[key]}</div>
                          <div className={`text-base font-black ${pct >= 50 ? "text-amber-300" : "text-gray-300"}`}>{pct}%</div>
                        </div>
                      );
                    })}
                  </div>
                  <div className={`rounded px-2 py-1.5 text-center ${Math.round(cardStat.rates.win_four * 100) >= 50 ? "bg-amber-500/30 border border-amber-500/60" : "bg-gray-800/60 border border-gray-700/40"}`}>
                    <div className="text-[10px] text-gray-400">4K+</div>
                    <div className={`text-base font-black ${Math.round(cardStat.rates.win_four * 100) >= 50 ? "text-amber-300" : "text-gray-300"}`}>{Math.round(cardStat.rates.win_four * 100)}%</div>
                  </div>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* 統計カード */}
        {stats && (
          <>
            <section className="grid grid-cols-2 md:grid-cols-5 gap-3">
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
              <StatCard
                label="エラー"
                value={`${stats.result_counts.error ?? 0} (${((stats.result_rates.error ?? 0) * 100).toFixed(1)}%)`}
                className="border-red-950 bg-red-950/20 text-red-400"
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
            {stats.result_counts.error !== undefined && stats.result_counts.error > 0 && (
              <ResultBar label="エラー"       count={stats.result_counts.error}   total={stats.total} color="bg-red-800" />
            )}
          </section>
        )}

        {/* グラフと期間フィルター */}
        {games.length >= 2 && (
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-gray-400">分析グラフ</h2>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500 font-medium">集計期間:</span>
                <select
                  value={limit}
                  onChange={(e) => setLimit(Number(e.target.value))}
                  className="bg-gray-900 border border-gray-800 text-gray-300 text-xs rounded px-2.5 py-1 focus:outline-none focus:border-yellow-400 cursor-pointer font-medium"
                >
                  <option value={50}>直近 50 件</option>
                  <option value={100}>直近 100 件</option>
                  <option value={200}>直近 200 件</option>
                  <option value={500}>直近 500 件</option>
                </select>
              </div>
            </div>
            {(() => {
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
          </div>
        )}

        {/* ゲーム履歴テーブル */}
        {games.length > 0 && (
          <section>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-gray-400">
                ゲーム履歴 (全 {gamesData?.total} 件)
              </h2>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500 font-medium">表示件数:</span>
                <select
                  value={historyLimit}
                  onChange={(e) => setHistoryLimit(Number(e.target.value))}
                  className="bg-gray-900 border border-gray-800 text-gray-300 text-xs rounded px-2.5 py-1 focus:outline-none focus:border-yellow-400 cursor-pointer font-medium"
                >
                  <option value={10}>10 件</option>
                  <option value={25}>25 件</option>
                  <option value={50}>50 件</option>
                  <option value={100}>100 件</option>
                </select>
              </div>
            </div>
            <div className="overflow-x-auto rounded-xl border border-gray-800">
              <table className="min-w-full text-xs">
                <thead className="bg-gray-900 text-gray-400">
                  <tr>
                    <Th>#</Th>
                    <Th>結果</Th>
                    <Th>予測</Th>
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
                  {games.slice(0, historyLimit).map((g, i) => (
                    <GameRow key={g.id} game={g} prevGame={games[i + 1]} onViewLog={handleViewLog} onViewCapture={handleViewCapture} />
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {!stats && !error && (
          <div className="text-center text-gray-500 py-16">読み込み中…</div>
        )}

        {/* ログビューアーモーダル */}
        {isLogModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm">
            <div className="bg-gray-950 border border-gray-800 rounded-xl max-w-4xl w-full max-h-[85vh] flex flex-col p-6 shadow-2xl">
              <div className="flex items-center justify-between border-b border-gray-800 pb-3">
                <h3 className="text-sm font-semibold text-yellow-400 font-mono">
                  📄 Round Log: {selectedLogTitle}
                </h3>
                <button
                  onClick={() => setIsLogModalOpen(false)}
                  className="text-gray-500 hover:text-gray-300 transition text-xs font-semibold px-2 py-1 bg-gray-900 rounded border border-gray-800"
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

        {/* 結果キャプチャモーダル */}
        {isCaptureModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
            <div className="bg-gray-950 border border-gray-800 rounded-xl max-w-3xl w-full max-h-[85vh] flex flex-col p-6 shadow-2xl">
              <div className="flex items-center justify-between border-b border-gray-800 pb-3 mb-4">
                <h3 className="text-sm font-semibold text-yellow-400">
                  📷 {selectedCaptureTitle}
                </h3>
                <button
                  onClick={handleCloseCaptureModal}
                  className="text-gray-500 hover:text-gray-300 transition text-xs font-semibold px-2 py-1 bg-gray-900 rounded border border-gray-800"
                >
                  閉じる
                </button>
              </div>
              <div className="flex-1 overflow-auto flex items-center justify-center bg-black/40 rounded border border-gray-900 p-2">
                {selectedCaptureUrl ? (
                  <img
                    src={selectedCaptureUrl}
                    alt={selectedCaptureTitle}
                    className="max-w-full max-h-[60vh] object-contain rounded-md"
                  />
                ) : (
                  <div className="text-gray-500 text-xs py-8">画像を読み込めませんでした</div>
                )}
              </div>
            </div>
          </div>
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

function CopyButton({ value, title }: { value: string; title?: string }) {
  const [copied, setCopied] = useState(false);
  function handleCopy() {
    navigator.clipboard.writeText(value).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    });
  }
  return (
    <button
      onClick={handleCopy}
      title={title ?? `"${value}" をコピー`}
      className="ml-1 px-1 py-0.5 rounded text-xs font-mono transition
        bg-gray-700 hover:bg-gray-600 text-gray-400 hover:text-white active:scale-95"
    >
      {copied ? <span className="text-green-400">✓</span> : <span>⎘</span>}
    </button>
  );
}

function GameRow({
  game,
  prevGame,
  onViewLog,
  onViewCapture,
}: {
  game: Game;
  prevGame?: Game;
  onViewLog: (logFile: string) => void | Promise<void>;
  onViewCapture: (gameId: number) => void | Promise<void>;
  key?: any;
}) {
  const colorCls = RESULT_COLOR[game.result as GameResult] ?? "bg-gray-800 text-gray-300";
  const dt = new Date(game.recorded_at);
  const dtStr = `${dt.getMonth() + 1}/${dt.getDate()} ${dt.getHours().toString().padStart(2,"0")}:${dt.getMinutes().toString().padStart(2,"0")}:${dt.getSeconds().toString().padStart(2,"0")}`;

  const elapsedSec = prevGame
    ? Math.round((dt.getTime() - new Date(prevGame.recorded_at).getTime()) / 1000)
    : null;
  const elapsedStr = elapsedSec == null ? null
    : elapsedSec < 60 ? `+${elapsedSec}s`
    : `+${Math.floor(elapsedSec / 60)}m${elapsedSec % 60 > 0 ? `${elapsedSec % 60}s` : ""}`;
  const elapsedCls = elapsedSec == null ? ""
    : elapsedSec > 300 ? "text-red-500"
    : elapsedSec > 60  ? "text-amber-500"
    : "text-gray-600";

  return (
    <tr className="hover:bg-gray-800/50 transition">
      <td className="px-3 py-1.5 text-gray-500">{game.id}</td>
      <td className="px-3 py-1.5">
        <div className="flex items-center gap-1.5">
          <span className={`px-2 py-0.5 rounded text-xs font-semibold ${colorCls}`}>
            {RESULT_LABEL[game.result as GameResult] ?? game.result}
          </span>
          {game.has_capture && (
            <button
              onClick={() => onViewCapture(game.id)}
              title="結果表示のキャプチャを表示"
              className="text-gray-400 hover:text-yellow-400 transition hover:scale-110 active:scale-95 p-0.5"
            >
              📷
            </button>
          )}
        </div>
      </td>
      <td className="px-3 py-1.5 text-center">
        {game.pred_result ? (
          <span title={`予測: ${game.pred_result} (${game.model_version ?? ""})`}>
            <span className={game.pred_result === game.result ? "text-green-400" : "text-red-400"}>
              {game.pred_result === game.result ? "✓" : "✗"}
            </span>
            {" "}
            <span className="text-gray-400 text-xs">
              {game.pred_result === "cowboy" ? "🤠" : game.pred_result === "bull" ? "🐂" : "🎲"}
            </span>
          </span>
        ) : (
          <span className="text-gray-700">—</span>
        )}
      </td>
      <td className="px-3 py-1.5 text-gray-400">
        {game.round_number ? (
          <button
            onClick={() => onViewLog(game.log_file_name || `${game.round_number}.log`)}
            title="ラウンドログを表示"
            className="hover:text-yellow-400 hover:underline transition font-mono active:scale-95 text-left"
          >
            {game.round_number}
          </button>
        ) : (
          "—"
        )}
      </td>
      <td className="px-1 py-1">
        <div className="flex items-center gap-1">
          {game.card_image && (
            <CardThumb src={game.card_image} label={game.open_card ?? ""} />
          )}
          <span className="font-mono text-yellow-300 text-xs">{game.open_card ?? "—"}</span>
          {game.open_card && (
            <CopyButton
              value={game.ocr_debug ?? game.open_card}
              title={game.ocr_debug ? "DEBUGログをコピー" : "カード名をコピー"}
            />
          )}
          
          {game.ocr_debug && (
            <div className="relative group ml-1 flex items-center">
              <span className="text-gray-400 hover:text-gray-200 cursor-help text-xs p-0.5 bg-gray-800 rounded select-none">ℹ️</span>
              <div className="absolute left-0 bottom-full mb-1.5 hidden group-hover:block bg-gray-900 border border-gray-700 text-gray-200 text-[10px] rounded p-2.5 whitespace-pre z-50 shadow-2xl font-mono max-w-xs md:max-w-md pointer-events-none">
                {game.ocr_debug}
              </div>
            </div>
          )}
        </div>
      </td>
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
      <td className="px-3 py-1.5 text-gray-500 whitespace-nowrap">
        <div className="flex items-center gap-2">
          <div className="flex flex-col leading-tight">
            <span>{dtStr}</span>
            {elapsedStr && (
              <span className={`text-[10px] ${elapsedCls}`}>{elapsedStr}</span>
            )}
          </div>
          {game.log_file_name && (
            <button
              onClick={() => onViewLog(game.log_file_name!)}
              title="ラウンドログを表示"
              className="px-1.5 py-0.5 rounded text-[10px] bg-gray-900 border border-gray-800 hover:bg-gray-800 text-gray-400 hover:text-white transition font-mono active:scale-95"
            >
              📝 ログ
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}

type SideBetPred = Record<string, number | null> | null | undefined;

// ── 常時表示 AI予測カード ─────────────────────────────────────────────────────
type SideBetPredType = {
  any_flash?: number | null; any_pair?: number | null; any_ace?: number | null;
  win_high?: number | null; win_two?: number | null; win_sf?: number | null;
  win_fh?: number | null; win_four?: number | null;
};

function AIPredictionCard({ prediction, sideBet, roundNumber, gameState, openCard, gaps }: {
  prediction: { cowboy: number; draw: number; bull: number; predicted: "cowboy" | "draw" | "bull"; model_version: string };
  sideBet?: SideBetPredType | null;
  roundNumber?: number | null;
  gameState?: string | null;
  openCard?: string | null;
  gaps?: Record<string, number>;
}) {
  const MAIN: { key: "cowboy" | "draw" | "bull"; emoji: string; label: string; bar: string; ring: string }[] = [
    { key: "cowboy", emoji: "🤠", label: "カウボーイ", bar: "bg-red-500",   ring: "ring-red-500"   },
    { key: "draw",   emoji: "🎲", label: "抽選",       bar: "bg-green-500", ring: "ring-green-500" },
    { key: "bull",   emoji: "🐂", label: "ブル",       bar: "bg-blue-500",  ring: "ring-blue-500"  },
  ];
  const SIDE: { key: string; label: string }[] = [
    { key: "any_flash", label: "FL/CN" }, { key: "any_pair", label: "1ペア" },
    { key: "any_ace",   label: "Aペア" }, { key: "win_high",  label: "ハイ/1P" },
    { key: "win_two",   label: "2ペア" }, { key: "win_sf",    label: "3K+" },
    { key: "win_fh",    label: "FH" },    { key: "win_four",  label: "4K+" },
  ];

  const maxPct = Math.max(
    Math.round(prediction.cowboy * 100),
    Math.round(prediction.draw   * 100),
    Math.round(prediction.bull   * 100),
  );
  const isLowConf = maxPct < 40;

  const stateLabel: Record<string, string> = {
    betting: "🗳️ 投票中",
    preparing: "🔄 準備中",
    result: "✅ 結果表示",
    cooldown: "💤 待機中",
  };

  return (
    <section className={`rounded-xl border-2 p-4 ${isLowConf ? "border-yellow-800/50 bg-yellow-950/20" : "border-yellow-600/60 bg-yellow-950/30"}`}>
      {/* ヘッダー */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-bold text-yellow-400">🤖 AI予測</h2>
          {roundNumber != null && (
            <span className="text-xs px-2 py-0.5 bg-gray-800 text-gray-300 rounded font-mono">R{roundNumber}</span>
          )}
          {openCard && (
            <span className="text-xs px-2 py-0.5 bg-gray-800 text-gray-300 rounded font-mono">{openCard}</span>
          )}
          {gameState && stateLabel[gameState] && (
            <span className={`text-xs px-2 py-0.5 rounded font-semibold ${gameState === "betting" ? "bg-yellow-900 text-yellow-300" : gameState === "result" ? "bg-green-900 text-green-300" : "bg-gray-800 text-gray-400"}`}>
              {stateLabel[gameState]}
            </span>
          )}
          {isLowConf && (
            <span className="text-[10px] px-1.5 py-0.5 bg-yellow-900/60 text-yellow-600 border border-yellow-800/50 rounded">低信頼度</span>
          )}
        </div>
        <span className="text-[10px] text-gray-600">※ 現在進行中のラウンドの予測です</span>
      </div>

      {/* メイン予測 — 3カラムグリッド */}
      <div className="grid grid-cols-3 gap-3 mb-3">
        {MAIN.map(({ key, emoji, label, bar, ring }) => {
          const pct = Math.round(prediction[key] * 100);
          const isPred = prediction.predicted === key;
          const gap = gaps?.[key];
          return (
            <div
              key={key}
              className={`rounded-lg p-3 flex flex-col items-center gap-1 transition ${
                isPred
                  ? `bg-gray-800 ring-2 ${ring} shadow-lg`
                  : "bg-gray-900/60 opacity-60"
              }`}
            >
              <span className="text-2xl">{emoji}</span>
              <span className="text-xs text-gray-400">{label}</span>
              <span className={`text-2xl font-black ${isPred ? "text-white" : "text-gray-500"}`}>{pct}%</span>
              <div className="w-full h-1.5 bg-gray-700 rounded-full overflow-hidden">
                <div className={`h-full ${bar}`} style={{ width: `${pct}%` }} />
              </div>
              {isPred && (
                <span className="text-[10px] font-bold text-yellow-300 mt-0.5">← 予測</span>
              )}
              {gap != null && (
                <span className="text-[9px] text-gray-600">前回{gap}G前</span>
              )}
            </div>
          );
        })}
      </div>

      {/* サイドベット予測 */}
      {sideBet && (
        <div className="border-t border-gray-700/50 pt-3">
          <p className="text-[10px] text-gray-500 font-semibold mb-2">サイドベット予測（50%以上で YES）</p>
          <div className="grid grid-cols-4 gap-1.5">
            {SIDE.map(({ key, label }) => {
              const prob = (sideBet as Record<string, number | null | undefined>)[key];
              if (prob == null) return null;
              const pct = Math.round(prob * 100);
              const isYes = pct >= 50;
              const gap = gaps?.[key];
              return (
                <div
                  key={key}
                  className={`rounded px-2 py-1.5 text-center ${
                    isYes
                      ? "bg-green-900/50 border border-green-700/60"
                      : "bg-gray-800/50 border border-gray-700/30"
                  }`}
                >
                  <div className="text-[9px] text-gray-400 mb-0.5">{label}</div>
                  <div className={`text-xs font-bold ${isYes ? "text-green-300" : "text-gray-600"}`}>
                    {isYes ? "YES" : "—"}
                  </div>
                  <div className={`text-[9px] ${isYes ? "text-green-500" : "text-gray-600"}`}>{pct}%</div>
                  {gap != null && (
                    <div className="text-[8px] text-gray-700">{gap}G前</div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}

// ── キャプチャ内コンパクトゲージ（折りたたみ内専用）────────────────────────
function PredictionGauge({ prediction, sideBet, gaps }: {
  prediction: {
    cowboy: number;
    draw: number;
    bull: number;
    predicted: "cowboy" | "draw" | "bull";
    model_version: string;
  };
  sideBet?: SideBetPred;
  gaps?: Record<string, number>;
}) {
  const entries: { key: "cowboy" | "draw" | "bull"; emoji: string; color: string }[] = [
    { key: "cowboy", emoji: "🤠", color: "bg-red-600" },
    { key: "bull",   emoji: "🐂", color: "bg-blue-600" },
    { key: "draw",   emoji: "🎲", color: "bg-green-600" },
  ];
  const sideBetEntries: { key: string; label: string }[] = [
    { key: "any_flash", label: "FL/CN" },
    { key: "any_pair",  label: "1ペア" },
    { key: "any_ace",   label: "Aペア" },
    { key: "win_high",  label: "ハイ/1P" },
    { key: "win_two",   label: "2ペア" },
    { key: "win_sf",    label: "3K+" },
    { key: "win_fh",    label: "FH" },
    { key: "win_four",  label: "4K+" },
  ];
  const maxPct = Math.max(
    Math.round(prediction.cowboy * 100),
    Math.round(prediction.draw   * 100),
    Math.round(prediction.bull   * 100),
  );
  const isLowConf = maxPct < 40;
  return (
    <div className="mt-2 border-t border-gray-700 pt-2 space-y-1">
      <div className="text-xs text-gray-400 font-semibold mb-1">【AI予測】</div>
      {entries.map(({ key, emoji, color }) => {
        const pct = Math.round(prediction[key] * 100);
        const isPredicted = prediction.predicted === key;
        const gap = gaps?.[key];
        return (
          <div
            key={key}
            className={`flex items-center gap-2 rounded px-1 py-0.5 ${isPredicted ? "bg-yellow-950/40 ring-1 ring-yellow-700/50" : ""}`}
          >
            <span className="w-5 text-center text-sm">{emoji}</span>
            <div className={`flex-1 h-3 rounded-full overflow-hidden ${isPredicted ? "bg-gray-700" : "bg-gray-800"}`}>
              <div
                className={`h-full transition-all ${isPredicted ? (isLowConf ? "bg-yellow-700" : color) : color}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className={`w-8 text-right text-xs font-mono ${isPredicted ? "text-yellow-300 font-bold" : "text-gray-400"}`}>
              {pct}%
            </span>
            {gap != null && (
              <span className="text-[10px] text-gray-500 w-12 text-right shrink-0">
                前回{gap}G前
              </span>
            )}
          </div>
        );
      })}
      <div className={`text-xs mt-1 flex items-center gap-2 ${isLowConf ? "text-yellow-600" : "text-yellow-400"}`}>
        <span>→ 予測: {prediction.predicted === "cowboy" ? "🤠 Cowboy" : prediction.predicted === "bull" ? "🐂 Bull" : "🎲 Draw"}</span>
        {isLowConf && <span className="text-[10px] bg-yellow-900/50 text-yellow-600 border border-yellow-800/50 rounded px-1.5 py-0.5">低信頼度</span>}
      </div>
      {sideBet && (
        <div className="mt-2 border-t border-gray-800 pt-2">
          <div className="text-xs text-gray-500 font-semibold mb-1">【サイドベット予測】</div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
            {sideBetEntries.map(({ key, label }) => {
              const prob = sideBet[key];
              if (prob == null) return null;
              const pct = Math.round(prob * 100);
              const isHigh = pct >= 55;
              const gap = gaps?.[key];
              return (
                <div key={key} className="flex items-center gap-1.5">
                  <span className={`text-[10px] w-10 text-right shrink-0 ${isHigh ? "text-yellow-300 font-bold" : "text-gray-500"}`}>
                    {label}
                  </span>
                  <div className="flex-1 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full transition-all ${isHigh ? "bg-yellow-500" : "bg-gray-600"}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className={`text-[10px] w-6 text-right font-mono shrink-0 ${isHigh ? "text-yellow-300 font-bold" : "text-gray-600"}`}>
                    {pct}%
                  </span>
                  {gap != null && (
                    <span className="text-[10px] text-gray-600 w-10 text-right shrink-0">{gap}G前</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function CardThumb({ src, label }: { src: string; label: string }) {
  return (
    <a href={src} target="_blank" rel="noreferrer" title={`${label} クリックで拡大`}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={label}
        className="rounded border border-gray-600 cursor-zoom-in hover:opacity-80 transition bg-gray-800"
        style={{ width: 28, height: 40, objectFit: "cover" }}
      />
    </a>
  );
}
