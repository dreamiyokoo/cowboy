export interface CapturePreview {
  open_detected_at: string | null;   // オープンカード検出時刻
  result_detected_at: string | null; // 結果検出時刻
  result: GameResult | null;
  open_card: string | null;
  round_number: number | null;       // ラウンド番号
  cowboy_hand: number | null;
  bull_hand: number | null;
  screen_image: string | null;
  round_image?: string | null;
  open_card_image?: string | null;
  result_image?: string | null;
  bet_images?: Record<string, string | null> | null;
  win_images?: Record<string, string | null> | null;
  winning_hand_images?: (string | null)[] | null;
  bet_values?: Record<string, number | null> | null;
  win_scores?: Record<string, number> | null;
  result_scores?: Record<string, number> | null;
  winning_hand_scores?: number[] | null;
  jackpot_stock?: number | null;
  jackpot_stock_image?: string | null;
  timer_value?: number | null;
  timer_image?: string | null;
  game_state?: "result" | "betting" | "preparing" | "cooldown" | "unknown";
  remaining_seconds?: number | null;
}

// ── 型定義 ─────────────────────────────────────────────

export type GameResult = "cowboy" | "draw" | "bull" | "error";

export interface Game {
  id: number;
  open_card: string | null;
  result: GameResult;
  cowboy_hand: number | null;
  bull_hand: number | null;
  round_number: number | null;
  recorded_at: string;
  // 上段3つ
  bet_cowboy: number | null;
  bet_draw: number | null;
  bet_bull: number | null;
  // 任意のハンド
  bet_any_flash: number | null;
  bet_any_pair: number | null;
  bet_any_ace: number | null;
  // 勝利ハンド
  bet_win_high: number | null;
  bet_win_two: number | null;
  bet_win_sf: number | null;
  bet_win_fh: number | null;
  bet_win_four: number | null;
  jackpot_stock: number | null;
  // WIN フラグ
  win_any_flash: boolean | null;
  win_any_pair: boolean | null;
  win_any_ace: boolean | null;
  win_high: boolean | null;
  win_two: boolean | null;
  win_sf: boolean | null;
  win_fh: boolean | null;
  win_four: boolean | null;
  // 合計
  total_bet: number | null;
  // オープンカード画像（base64 JPEG data URL）
  card_image?: string | null;
  ocr_debug?: string | null;
  log_file_name?: string | null;
  has_capture?: boolean;
}

export interface GamesResponse {
  games: Game[];
  total: number;
  limit: number;
  offset: number;
}

export interface StatsResponse {
  total: number;
  result_counts: { cowboy: number; draw: number; bull: number; error?: number };
  result_rates: { cowboy: number; draw: number; bull: number; error?: number };
  records_with_full_bets: number;
  total_bet_all_positions: number | null;
  total_bet_sum: number;
  total_payout: number;
  user_pnl: number;
}

export interface CardStatsRates {
  cowboy: number;
  draw: number;
  bull: number;
  any_flash: number;
  any_pair: number;
  any_ace: number;
  win_high: number;
  win_two: number;
  win_sf: number;
  win_fh: number;
  win_four: number;
}

export interface CardStatsItem {
  card: string;
  total: number;
  rates: CardStatsRates;
}

export interface CardStatsResponse {
  card_stats: CardStatsItem[];
}

// ── API クライアント ───────────────────────────────────

declare const process: { env: { NEXT_PUBLIC_API_URL?: string } };

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

export async function apiFetch<T>(
  path: string,
  token: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const err = await res.text().catch(() => "");
    throw Object.assign(new Error(err || String(res.status)), { status: res.status });
  }
  return res.json() as Promise<T>;
}

export async function fetchStats(token: string): Promise<StatsResponse> {
  return apiFetch<StatsResponse>("/api/v1/games/stats", token);
}

export async function fetchGames(
  token: string,
  limit = 100,
  offset = 0
): Promise<GamesResponse> {
  return apiFetch<GamesResponse>(
    `/api/v1/games?limit=${limit}&offset=${offset}`,
    token
  );
}

export async function fetchCapturePreview(token: string): Promise<CapturePreview | null> {
  try {
    return await apiFetch<CapturePreview>("/api/v1/capture/preview", token);
  } catch (e: unknown) {
    if (e instanceof Error && "status" in e && (e as { status: number }).status === 404) {
      return null;
    }
    throw e;
  }
}

export async function fetchCardStats(token: string): Promise<CardStatsResponse> {
  return apiFetch<CardStatsResponse>("/api/v1/games/card-stats", token);
}

export async function fetchCardStatSingle(
  token: string,
  card: string
): Promise<CardStatsItem | null> {
  try {
    return await apiFetch<CardStatsItem>(`/api/v1/games/card-stats/${encodeURIComponent(card)}`, token);
  } catch (e: unknown) {
    if (e instanceof Error && "status" in e && (e as { status: number }).status === 404) {
      return null;
    }
    throw e;
  }
}

// ── 表示用ヘルパー ────────────────────────────────────

export function fmtAmount(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

export const RESULT_LABEL: Record<GameResult, string> = {
  cowboy: "カウボーイ",
  draw: "抽選",
  bull: "ブル",
  error: "エラー",
};

export const RESULT_COLOR: Record<GameResult, string> = {
  cowboy: "bg-red-900 text-red-300",
  draw: "bg-green-900 text-green-300",
  bull: "bg-blue-900 text-blue-300",
  error: "bg-red-600 text-white font-bold animate-pulse",
};

export const BET_COLUMNS: { key: keyof Game; label: string }[] = [
  { key: "bet_cowboy",    label: "カウボーイ" },
  { key: "bet_draw",      label: "抽選" },
  { key: "bet_bull",      label: "ブル" },
  { key: "bet_any_flash", label: "FL/CN" },
  { key: "bet_any_pair",  label: "1ペア" },
  { key: "bet_any_ace",   label: "Aペア" },
  { key: "bet_win_high",  label: "ハイ/1P" },
  { key: "bet_win_two",   label: "2ペア" },
  { key: "bet_win_sf",    label: "3K/ST/FL" },
  { key: "bet_win_fh",    label: "FH" },
  { key: "bet_win_four",  label: "4K+" },
];

// ── 倍率・勝利ペイアウト ─────────────────────────────────

export const WIN_ODDS: Record<string, number> = {
  cowboy:    2.02,
  draw:      22,
  bull:      2.02,
  any_flash: 1.67,
  any_pair:  8.5,
  any_ace:   100,
  win_high:  2.2,
  win_two:   3.1,
  win_sf:    4.7,
  win_fh:    20.5,
  win_four:  250,
};

// ゲーム履歴の WIN カラム → ベットキー・倍率キーのマッピング
export const WIN_COL_MAP: Record<string, { betKey: keyof Game; oddsKey: string }> = {
  win_any_flash: { betKey: "bet_any_flash", oddsKey: "any_flash" },
  win_any_pair:  { betKey: "bet_any_pair",  oddsKey: "any_pair"  },
  win_any_ace:   { betKey: "bet_any_ace",   oddsKey: "any_ace"   },
  win_high:      { betKey: "bet_win_high",  oddsKey: "win_high"  },
  win_two:       { betKey: "bet_win_two",   oddsKey: "win_two"   },
  win_sf:        { betKey: "bet_win_sf",    oddsKey: "win_sf"    },
  win_fh:        { betKey: "bet_win_fh",    oddsKey: "win_fh"    },
  win_four:      { betKey: "bet_win_four",  oddsKey: "win_four"  },
};

export const WIN_COLUMNS: { key: keyof Game; label: string }[] = [
  { key: "win_any_flash", label: "FL/CN" },
  { key: "win_any_pair",  label: "1ペア" },
  { key: "win_any_ace",   label: "Aペア" },
  { key: "win_high",      label: "ハイ/1P" },
  { key: "win_two",       label: "2ペア" },
  { key: "win_sf",        label: "3K+" },
  { key: "win_fh",        label: "FH" },
  { key: "win_four",      label: "4K+" },
];

// 勝利ハンド行（winning_hand_rows）の idx → bet/odds キーマッピング
export const WINNING_HAND_ROW_KEYS = ["any_flash", "any_pair", "any_ace"] as const;
export const WINNING_HAND_ROW_LABELS = ["FL/CN", "1ペア", "Aペア"] as const;

export function calcBetTotal(game: Game): number {
  const bets = [
    game.bet_cowboy, game.bet_draw, game.bet_bull,
    game.bet_any_flash, game.bet_any_pair, game.bet_any_ace,
    game.bet_win_high, game.bet_win_two, game.bet_win_sf, game.bet_win_fh, game.bet_win_four,
  ];
  return bets.reduce<number>((sum, b) => sum + (b ?? 0), 0);
}

export function calcPayout(game: Game): number {
  const resultBet = game.result === "cowboy" ? game.bet_cowboy
    : game.result === "draw" ? game.bet_draw
    : game.bet_bull;
  let payout = Math.floor((resultBet ?? 0) * (WIN_ODDS[game.result] ?? 0));
  for (const [winKey, map] of Object.entries(WIN_COL_MAP)) {
    if (game[winKey as keyof Game] === true) {
      const bet = game[map.betKey] as number | null;
      payout += Math.floor((bet ?? 0) * WIN_ODDS[map.oddsKey]);
    }
  }
  return payout;
}
