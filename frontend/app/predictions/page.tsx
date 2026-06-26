"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppHeader from "@/app/components/AppHeader";
import {
  getValidAccessToken,
  clearAccessToken,
} from "@/app/lib/auth";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from "recharts";
import {
  fetchGames,
  fetchPredictionAccuracy,
  fetchPredictionRoi,
  fetchPredictionStreaks,
  fetchGameIntervals,
  fetchGamesArchive,
  fmtAmount,
  type Game,
  type GameResult,
  type PredictionAccuracyResponse,
  type PredictionRoiResponse,
  type PredictionStreaksResponse,
  type GameIntervalsResponse,
  type GamesArchiveResponse,
} from "@/app/lib/api";

type TabId = "validation" | "cards" | "intervals" | "spec" | "archive";

export default function PredictionsPage() {
  const router = useRouter();
  const [games, setGames] = useState<Game[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<TabId>("validation");
  const [predAccuracy, setPredAccuracy] = useState<PredictionAccuracyResponse | null>(null);
  const [predRoi, setPredRoi] = useState<PredictionRoiResponse | null>(null);
  const [predStreaks, setPredStreaks] = useState<PredictionStreaksResponse | null>(null);
  const [gameIntervals, setGameIntervals] = useState<GameIntervalsResponse | null>(null);
  const [roiConfidence, setRoiConfidence] = useState(0);
  const [streakFrom, setStreakFrom] = useState("");
  const [streakTo, setStreakTo] = useState("");
  const [archiveData, setArchiveData] = useState<GamesArchiveResponse | null>(null);
  const [archiveBy, setArchiveBy] = useState<"day" | "hour">("day");

  // Dynamic stats
  const [stats, setStats] = useState({
    total: 0,
    results: { cowboy: 0, draw: 0, bull: 0 },
    cBetHigher: { wins: 0, total: 0, rate: 0 },
    bBetHigher: { wins: 0, total: 0, rate: 0 },
    autocorrelation: {
      c_after_c_rate: 0,
      total_after_c: 0,
      b_after_b_rate: 0,
      total_after_b: 0,
    },
    rankStats: {} as Record<string, { total: number; cowboy: number; draw: number; bull: number }>,
  });

  function logout() {
    clearAccessToken();
    router.replace("/login");
  }

  async function loadStreaks() {
    const token = getValidAccessToken();
    if (!token) { logout(); return; }
    try {
      const streaks = await fetchPredictionStreaks(token, streakFrom || undefined, streakTo || undefined);
      setPredStreaks(streaks);
    } catch (e: any) {
      if (e?.status === 401) logout();
    }
  }

  async function loadData() {
    const token = getValidAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    try {
      setLoading(true);
      
      // Fetch in chunks of 200 to bypass backend limit
      const CHUNK_SIZE = 200;
      const MAX_GAMES = 1000;
      let allGames: Game[] = [];
      
      const promises = [];
      for (let offset = 0; offset < MAX_GAMES; offset += CHUNK_SIZE) {
        promises.push(fetchGames(token, CHUNK_SIZE, offset));
      }
      
      const responses = await Promise.all(promises);
      responses.forEach((res) => {
        if (res && res.games) {
          allGames = allGames.concat(res.games);
        }
      });

      // Sort desc by recorded_at
      allGames.sort((a, b) => new Date(b.recorded_at).getTime() - new Date(a.recorded_at).getTime());

      setGames(allGames);
      calculateStats(allGames);

      // 予測精度・ROI・ストリーク・アーカイブ取得
      try {
        const [acc, roi, streaks, intervals, archive] = await Promise.all([
          fetchPredictionAccuracy(token),
          fetchPredictionRoi(token, roiConfidence || undefined),
          fetchPredictionStreaks(token, streakFrom || undefined, streakTo || undefined),
          fetchGameIntervals(token),
          fetchGamesArchive(token, archiveBy),
        ]);
        setPredAccuracy(acc);
        setPredRoi(roi);
        setPredStreaks(streaks);
        setGameIntervals(intervals);
        setArchiveData(archive);
      } catch {
        // 予測データなしは無視
      }

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

  function calculateStats(gameList: Game[]) {
    const total = gameList.length;
    const results = { cowboy: 0, draw: 0, bull: 0 };
    gameList.forEach((g) => {
      if (g.result in results) results[g.result]++;
    });

    // rank stats
    const rankStats: Record<string, { total: number; cowboy: number; draw: number; bull: number }> = {};
    gameList.forEach((g) => {
      if (!g.open_card) return;
      const rank = g.open_card.slice(0, -1);
      if (!rankStats[rank]) {
        rankStats[rank] = { total: 0, cowboy: 0, draw: 0, bull: 0 };
      }
      rankStats[rank].total++;
      if (g.result in rankStats[rank]) {
        rankStats[rank][g.result]++;
      }
    });

    // bet correlation
    let cBetHigherTotal = 0;
    let cBetHigherWins = 0;
    let bBetHigherTotal = 0;
    let bBetHigherWins = 0;
    gameList.forEach((g) => {
      const betC = g.bet_cowboy || 0;
      const betB = g.bet_bull || 0;
      if (betC > betB) {
        cBetHigherTotal++;
        if (g.result === "cowboy") cBetHigherWins++;
      } else if (betB > betC) {
        bBetHigherTotal++;
        if (g.result === "bull") bBetHigherWins++;
      }
    });

    // autocorrelation (sequential)
    let cAfterCTotal = 0;
    let cAfterCWins = 0;
    let bAfterBTotal = 0;
    let bAfterBWins = 0;
    for (let i = 0; i < gameList.length - 1; i++) {
      const curr = gameList[i].result;
      const prev = gameList[i + 1].result; // gameList is sorted DESC, so index i+1 is previous game
      if (prev === "cowboy") {
        cAfterCTotal++;
        if (curr === "cowboy") cAfterCWins++;
      } else if (prev === "bull") {
        bAfterBTotal++;
        if (curr === "bull") bAfterBWins++;
      }
    }

    setStats({
      total,
      results,
      cBetHigher: {
        wins: cBetHigherWins,
        total: cBetHigherTotal,
        rate: cBetHigherTotal ? cBetHigherWins / cBetHigherTotal : 0,
      },
      bBetHigher: {
        wins: bBetHigherWins,
        total: bBetHigherTotal,
        rate: bBetHigherTotal ? bBetHigherWins / bBetHigherTotal : 0,
      },
      autocorrelation: {
        c_after_c_rate: cAfterCTotal ? cAfterCWins / cAfterCTotal : 0,
        total_after_c: cAfterCTotal,
        b_after_b_rate: bAfterBTotal ? bAfterBWins / bAfterBTotal : 0,
        total_after_b: bAfterBTotal,
      },
      rankStats,
    });
  }

  useEffect(() => {
    if (!getValidAccessToken()) {
      router.replace("/login");
      return;
    }
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const token = getValidAccessToken();
    if (!token) return;
    fetchGamesArchive(token, archiveBy).then(setArchiveData).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [archiveBy]);

  const rankOrder = ["A", "K", "Q", "J", "10", "9", "8", "7", "6", "5", "4", "3", "2"];

  // --- Validation tab computed values ---
  const overallCowboyRate = stats.total ? stats.results.cowboy / stats.total : 0;
  const overallBullRate   = stats.total ? stats.results.bull   / stats.total : 0;
  const MIN_TOTAL    = 100;
  const MIN_AUTOCORR = 30;
  const MIN_BET      = 30;
  const ANOMALY_THRESHOLD = 0.05;

  const autocorrInsufficient =
    stats.total < MIN_TOTAL ||
    stats.autocorrelation.total_after_c < MIN_AUTOCORR ||
    stats.autocorrelation.total_after_b < MIN_AUTOCORR;
  const cDiff = stats.autocorrelation.c_after_c_rate - overallCowboyRate;
  const bDiff = stats.autocorrelation.b_after_b_rate - overallBullRate;
  const autocorrAnomalous =
    !autocorrInsufficient &&
    (Math.abs(cDiff) > ANOMALY_THRESHOLD || Math.abs(bDiff) > ANOMALY_THRESHOLD);

  const betInsufficient =
    stats.cBetHigher.total < MIN_BET ||
    stats.bBetHigher.total < MIN_BET;
  const cBetDiff = stats.cBetHigher.rate - overallCowboyRate;
  const bBetDiff = stats.bBetHigher.rate - overallBullRate;
  const betSuspicious =
    !betInsufficient &&
    (cBetDiff < -ANOMALY_THRESHOLD || bBetDiff < -ANOMALY_THRESHOLD);
  const betNoteworthy =
    !betInsufficient && !betSuspicious &&
    (Math.abs(cBetDiff) > ANOMALY_THRESHOLD || Math.abs(bBetDiff) > ANOMALY_THRESHOLD);

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 font-sans">
      <AppHeader currentPage="predictions" onLogout={logout} />

      {/* Main Content */}
      <main className="p-6 max-w-7xl mx-auto space-y-6">
        {error && (
          <div className="p-4 bg-red-950/50 border border-red-900/50 rounded text-sm text-red-400">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex flex-col items-center justify-center h-96 space-y-4">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-yellow-500"></div>
            <p className="text-gray-400 text-sm">データを集計中...</p>
          </div>
        ) : (
          <>
            {/* Tabs Navigation */}
            <div className="flex border-b border-gray-800">
              <button
                id="tab-validation"
                onClick={() => setActiveTab("validation")}
                className={`px-6 py-3 font-semibold text-sm border-b-2 transition ${
                  activeTab === "validation"
                    ? "border-yellow-500 text-yellow-400"
                    : "border-transparent text-gray-400 hover:text-gray-200"
                }`}
              >
                📊 データ検証 & 分析
              </button>
              <button
                id="tab-cards"
                onClick={() => setActiveTab("cards")}
                className={`px-6 py-3 font-semibold text-sm border-b-2 transition ${
                  activeTab === "cards"
                    ? "border-yellow-500 text-yellow-400"
                    : "border-transparent text-gray-400 hover:text-gray-200"
                }`}
              >
                🃏 オープンカード別勝率
              </button>
              <button
                id="tab-intervals"
                onClick={() => setActiveTab("intervals")}
                className={`px-6 py-3 font-semibold text-sm border-b-2 transition ${
                  activeTab === "intervals"
                    ? "border-yellow-500 text-yellow-400"
                    : "border-transparent text-gray-400 hover:text-gray-200"
                }`}
              >
                🔄 出現間隔統計
              </button>
              <button
                id="tab-spec"
                onClick={() => setActiveTab("spec")}
                className={`px-6 py-3 font-semibold text-sm border-b-2 transition ${
                  activeTab === "spec"
                    ? "border-yellow-500 text-yellow-400"
                    : "border-transparent text-gray-400 hover:text-gray-200"
                }`}
              >
                📋 予測モデル仕様設計
              </button>
              <button
                id="tab-archive"
                onClick={() => setActiveTab("archive")}
                className={`px-6 py-3 font-semibold text-sm border-b-2 transition ${
                  activeTab === "archive"
                    ? "border-yellow-500 text-yellow-400"
                    : "border-transparent text-gray-400 hover:text-gray-200"
                }`}
              >
                📈 収支アーカイブ
              </button>
            </div>

            {/* Tab content 1: Data Validation */}
            {activeTab === "validation" && (
              <div className="space-y-6 animate-fadeIn">
                {/* Overview Cards */}
                <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                  <div className="bg-gray-900/40 border border-gray-800 rounded-xl p-5 backdrop-blur-sm">
                    <p className="text-gray-400 text-xs font-semibold uppercase tracking-wider">分析対象ゲーム数</p>
                    <p className="text-3xl font-bold text-gray-100 mt-2">{stats.total} <span className="text-sm font-normal text-gray-400">Rounds</span></p>
                    {stats.total < MIN_TOTAL && (
                      <p className="text-xs text-amber-500 mt-1">※ 統計には {MIN_TOTAL} 件以上推奨</p>
                    )}
                  </div>
                  <div className="bg-red-950/20 border border-red-900/30 rounded-xl p-5 backdrop-blur-sm">
                    <p className="text-red-400 text-xs font-semibold uppercase tracking-wider">カウボーイ勝率</p>
                    <p className="text-3xl font-bold text-red-400 mt-2">
                      {stats.total ? ((overallCowboyRate) * 100).toFixed(1) : 0}%
                    </p>
                    <p className="text-xs text-gray-500 mt-1">出現数: {stats.results.cowboy}回</p>
                  </div>
                  <div className="bg-blue-950/20 border border-blue-900/30 rounded-xl p-5 backdrop-blur-sm">
                    <p className="text-blue-400 text-xs font-semibold uppercase tracking-wider">ブル勝率</p>
                    <p className="text-3xl font-bold text-blue-400 mt-2">
                      {stats.total ? ((overallBullRate) * 100).toFixed(1) : 0}%
                    </p>
                    <p className="text-xs text-gray-500 mt-1">出現数: {stats.results.bull}回</p>
                  </div>
                  <div className="bg-green-950/20 border border-green-900/30 rounded-xl p-5 backdrop-blur-sm">
                    <p className="text-green-400 text-xs font-semibold uppercase tracking-wider">抽選 (Draw) 率</p>
                    <p className="text-3xl font-bold text-green-400 mt-2">
                      {stats.total ? ((stats.results.draw / stats.total) * 100).toFixed(1) : 0}%
                    </p>
                    <p className="text-xs text-gray-500 mt-1">出現数: {stats.results.draw}回</p>
                  </div>
                </div>

                {/* Autocorrelation & Streaks */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="bg-gray-900/40 border border-gray-800 rounded-xl p-6 space-y-4">
                    <h3 className="text-md font-bold text-yellow-500 flex items-center gap-2">
                      <span>🔁</span> 時系列依存性 (連チャンの流れ検証)
                    </h3>
                    <div className="space-y-3">
                      <div className="flex justify-between items-center bg-gray-950/50 p-3 rounded border border-gray-800/50">
                        <div>
                          <span className="text-sm text-gray-300">カウボーイの次もカウボーイになる確率:</span>
                          <span className="text-xs text-gray-500 ml-2">({stats.autocorrelation.total_after_c}件)</span>
                        </div>
                        {stats.autocorrelation.total_after_c < MIN_AUTOCORR
                          ? <span className="text-xs text-amber-500 font-semibold">データ不足</span>
                          : <span className="text-md font-bold text-red-400">{(stats.autocorrelation.c_after_c_rate * 100).toFixed(1)}%</span>
                        }
                      </div>
                      <div className="flex justify-between items-center bg-gray-950/50 p-3 rounded border border-gray-800/50">
                        <div>
                          <span className="text-sm text-gray-300">ブルの次もブルになる確率:</span>
                          <span className="text-xs text-gray-500 ml-2">({stats.autocorrelation.total_after_b}件)</span>
                        </div>
                        {stats.autocorrelation.total_after_b < MIN_AUTOCORR
                          ? <span className="text-xs text-amber-500 font-semibold">データ不足</span>
                          : <span className="text-md font-bold text-blue-400">{(stats.autocorrelation.b_after_b_rate * 100).toFixed(1)}%</span>
                        }
                      </div>
                    </div>

                    {autocorrInsufficient ? (
                      <div className="bg-amber-950/20 border border-amber-700/40 rounded-lg p-4 text-xs text-amber-400 leading-relaxed">
                        <strong>【統計検証結果】データ収集中</strong><br />
                        信頼性の高い時系列分析には、全体 {MIN_TOTAL} 件・各連続パターン {MIN_AUTOCORR} 件以上のデータが必要です。
                        現在: 全体 {stats.total} 件 / C後 {stats.autocorrelation.total_after_c} 件 / B後 {stats.autocorrelation.total_after_b} 件。
                        引き続きデータを蓄積してください。
                      </div>
                    ) : autocorrAnomalous ? (
                      <div className="bg-orange-950/20 border border-orange-700/40 rounded-lg p-4 text-xs text-orange-400 leading-relaxed">
                        <strong>【統計検証結果】パターン検出の可能性</strong><br />
                        全体勝率（コ: {(overallCowboyRate * 100).toFixed(1)}% / ブ: {(overallBullRate * 100).toFixed(1)}%）と比較して、
                        連続パターン時の勝率に {Math.max(Math.abs(cDiff), Math.abs(bDiff)) > 0.1 ? "顕著な" : "やや"} 差異が見られます
                        （C後C: {cDiff > 0 ? "+" : ""}{(cDiff * 100).toFixed(1)}% / B後B: {bDiff > 0 ? "+" : ""}{(bDiff * 100).toFixed(1)}%）。
                        偶然の偏りの可能性もありますが、さらなるデータ蓄積で確認してください。
                      </div>
                    ) : (
                      <div className="bg-yellow-950/10 border border-yellow-900/30 rounded-lg p-4 text-xs text-yellow-400/90 leading-relaxed">
                        <strong>【統計検証結果】独立試行と判定</strong><br />
                        全体勝率（コ: {(overallCowboyRate * 100).toFixed(1)}% / ブ: {(overallBullRate * 100).toFixed(1)}%）と
                        連続パターン時の勝率はほぼ一致しています（差: C後C {cDiff > 0 ? "+" : ""}{(cDiff * 100).toFixed(1)}% / B後B {bDiff > 0 ? "+" : ""}{(bDiff * 100).toFixed(1)}%）。
                        ゲーム結果は過去に依存しない <strong>独立試行（メモリレス）</strong> の特性を示しており、
                        連チャン罫線による予測は期待値向上に寄与しません。
                      </div>
                    )}
                  </div>

                  {/* Bet Volume Correlation */}
                  <div className="bg-gray-900/40 border border-gray-800 rounded-xl p-6 space-y-4">
                    <h3 className="text-md font-bold text-yellow-500 flex items-center gap-2">
                      <span>💰</span> ベット総額と勝敗の相関 (ハウス操作検証)
                    </h3>
                    <div className="space-y-3">
                      <div className="flex justify-between items-center bg-gray-950/50 p-3 rounded border border-gray-800/50">
                        <div>
                          <span className="text-sm text-gray-300">カウボーイに多く賭けられた時の勝率:</span>
                          <span className="text-xs text-gray-500 ml-2">({stats.cBetHigher.total}件)</span>
                        </div>
                        {stats.cBetHigher.total < MIN_BET
                          ? <span className="text-xs text-amber-500 font-semibold">データ不足</span>
                          : <span className="text-md font-bold text-red-400">{(stats.cBetHigher.rate * 100).toFixed(1)}%</span>
                        }
                      </div>
                      <div className="flex justify-between items-center bg-gray-950/50 p-3 rounded border border-gray-800/50">
                        <div>
                          <span className="text-sm text-gray-300">ブルに多く賭けられた時の勝率:</span>
                          <span className="text-xs text-gray-500 ml-2">({stats.bBetHigher.total}件)</span>
                        </div>
                        {stats.bBetHigher.total < MIN_BET
                          ? <span className="text-xs text-amber-500 font-semibold">データ不足</span>
                          : <span className="text-md font-bold text-blue-400">{(stats.bBetHigher.rate * 100).toFixed(1)}%</span>
                        }
                      </div>
                    </div>

                    {betInsufficient ? (
                      <div className="bg-amber-950/20 border border-amber-700/40 rounded-lg p-4 text-xs text-amber-400 leading-relaxed">
                        <strong>【回収・操作判定】ベットデータ不足</strong><br />
                        操作判定には各方向 {MIN_BET} 件以上のベット偏りデータが必要です。
                        現在: カウボーイ優勢 {stats.cBetHigher.total} 件 / ブル優勢 {stats.bBetHigher.total} 件。
                        ベット額が記録されているゲームが増えると判定が可能になります。
                      </div>
                    ) : betSuspicious ? (
                      <div className="bg-red-950/30 border border-red-700/50 rounded-lg p-4 text-xs text-red-400 leading-relaxed">
                        <strong>【回収・操作判定】⚠️ 操作の兆候を検出</strong><br />
                        多く賭けられた側の勝率が全体平均より有意に低下しています
                        （コ偏重時: {cBetDiff > 0 ? "+" : ""}{(cBetDiff * 100).toFixed(1)}% / ブ偏重時: {bBetDiff > 0 ? "+" : ""}{(bBetDiff * 100).toFixed(1)}%）。
                        「賭け金の多い側を負けさせてハウスが回収する」アルゴリズムの可能性があります。
                        データをさらに蓄積して確認してください。
                      </div>
                    ) : betNoteworthy ? (
                      <div className="bg-orange-950/20 border border-orange-700/40 rounded-lg p-4 text-xs text-orange-400 leading-relaxed">
                        <strong>【回収・操作判定】軽微な偏りを検出</strong><br />
                        全体平均との差異: コ偏重時 {cBetDiff > 0 ? "+" : ""}{(cBetDiff * 100).toFixed(1)}% / ブ偏重時 {bBetDiff > 0 ? "+" : ""}{(bBetDiff * 100).toFixed(1)}%。
                        現時点では偶然の範囲内の可能性が高いですが、引き続き監視してください。
                      </div>
                    ) : (
                      <div className="bg-yellow-950/10 border border-yellow-900/30 rounded-lg p-4 text-xs text-yellow-400/90 leading-relaxed">
                        <strong>【回収・操作判定】異常なし</strong><br />
                        賭け金が偏った側の勝率は全体平均（コ: {(overallCowboyRate * 100).toFixed(1)}% / ブ: {(overallBullRate * 100).toFixed(1)}%）と
                        ほぼ一致しています（差: コ偏重時 {cBetDiff > 0 ? "+" : ""}{(cBetDiff * 100).toFixed(1)}% / ブ偏重時 {bBetDiff > 0 ? "+" : ""}{(bBetDiff * 100).toFixed(1)}%）。
                        <strong>ベット偏りに連動した不正アルゴリズムの明確な兆候は見受けられません</strong>。
                      </div>
                    )}
                  </div>
                </div>

                {/* ML Prediction Accuracy */}
                <div className="bg-gray-900/40 border border-gray-800 rounded-xl p-6 space-y-4">
                  <h3 className="text-md font-bold text-yellow-500 flex items-center gap-2">
                    <span>🤖</span> ML予測精度レポート
                  </h3>

                  {!predAccuracy || predAccuracy.total_predicted === 0 ? (
                    <div className="bg-gray-950/50 border border-gray-800/50 rounded-lg p-6 text-center text-gray-400 text-sm">
                      まだ予測データがありません。<br />
                      <span className="text-xs text-gray-500 mt-1 block">モデルを学習してキャプチャを開始すると、ここに精度が表示されます。</span>
                    </div>
                  ) : (
                    <div className="space-y-5">
                      {/* Overall accuracy */}
                      <div className="flex items-center gap-4 bg-gray-950/50 p-4 rounded border border-gray-800/50">
                        <div className="text-center min-w-[80px]">
                          <p className="text-3xl font-black text-yellow-400">
                            {predAccuracy.accuracy != null ? (predAccuracy.accuracy * 100).toFixed(1) : "—"}%
                          </p>
                          <p className="text-xs text-gray-500 mt-1">全体正解率</p>
                        </div>
                        <div className="flex-1 text-xs text-gray-400">
                          <span className="text-gray-300 font-semibold">{predAccuracy.total_predicted}件</span>の予測データを集計しました。
                          全体正解率はランダム予測（約33%）と比較して評価してください。
                        </div>
                      </div>

                      {/* Per-class accuracy */}
                      <div className="grid grid-cols-3 gap-3">
                        {(
                          [
                            { key: "cowboy", label: "カウボーイ予測時", color: "text-red-400", border: "border-red-900/30", bg: "bg-red-950/20" },
                            { key: "bull",   label: "ブル予測時",       color: "text-blue-400",  border: "border-blue-900/30",  bg: "bg-blue-950/20" },
                            { key: "draw",   label: "抽選予測時",       color: "text-green-400", border: "border-green-900/30", bg: "bg-green-950/20" },
                          ] as const
                        ).map(({ key, label, color, border, bg }) => {
                          const cls = predAccuracy.by_predicted[key];
                          return (
                            <div key={key} className={`${bg} ${border} border rounded-xl p-4 text-center space-y-1`}>
                              <p className={`text-2xl font-black ${color}`}>
                                {cls.accuracy != null ? (cls.accuracy * 100).toFixed(1) : "—"}%
                              </p>
                              <p className="text-xs text-gray-400">{label}</p>
                              <p className="text-xs text-gray-500">{cls.correct}/{cls.total}件</p>
                            </div>
                          );
                        })}
                      </div>

                      {/* Confusion matrix */}
                      {Object.keys(predAccuracy.confusion).length > 0 && (
                        <div>
                          <p className="text-xs text-gray-400 font-semibold mb-2">混同行列（予測 → 実際）</p>
                          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                            {Object.entries(predAccuracy.confusion).map(([key, count]) => {
                              const [predPart, actualPart] = key.split("_pred_");
                              const actual = actualPart?.replace("_actual", "") ?? "";
                              const isCorrect = predPart === actual;
                              return (
                                <div
                                  key={key}
                                  className={`text-xs rounded p-2 border ${
                                    isCorrect
                                      ? "bg-green-950/20 border-green-900/40 text-green-400"
                                      : "bg-gray-950/50 border-gray-800/50 text-gray-400"
                                  }`}
                                >
                                  <span className="font-mono">{predPart} → {actual}</span>
                                  <span className="float-right font-bold">{count}件</span>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {/* Draw note */}
                      <div className="bg-green-950/10 border border-green-900/20 rounded-lg p-3 text-xs text-green-400/80 leading-relaxed">
                        <strong>補足:</strong> 抽選 (draw) は出現率が低い（5〜10%前後）ため、クラス不均衡により正解率が理論上低くなります。
                        draw の正解率の低さは学習の失敗ではなく、確率的に難しいクラスであることを意味します。
                      </div>
                    </div>
                  )}
                </div>

                {/* ROI Panel */}
                <div className="bg-gray-900/40 border border-gray-800 rounded-xl p-6 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <h3 className="text-md font-bold text-yellow-500 flex items-center gap-2">
                      <span>💹</span> 予測ROI・累計損益（予測に従ってベットした場合）
                    </h3>
                    <div className="flex items-center gap-2 text-xs">
                      <label className="text-gray-400">信頼度閾値:</label>
                      <select
                        value={roiConfidence}
                        onChange={e => { setRoiConfidence(Number(e.target.value)); }}
                        className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-gray-200 text-xs"
                      >
                        <option value={0}>すべて</option>
                        <option value={0.55}>55%以上</option>
                        <option value={0.60}>60%以上</option>
                        <option value={0.65}>65%以上</option>
                        <option value={0.70}>70%以上</option>
                        <option value={0.80}>80%以上</option>
                      </select>
                      <button
                        onClick={loadData}
                        className="px-2 py-1 bg-gray-800 hover:bg-gray-700 rounded text-gray-300 transition"
                      >再集計</button>
                    </div>
                  </div>

                  {!predRoi || predRoi.total_with_bets === 0 ? (
                    <div className="bg-gray-950/50 border border-gray-800/50 rounded-lg p-6 text-center text-gray-400 text-sm">
                      ベット額つき予測データがまだありません。<br />
                      <span className="text-xs text-gray-500 mt-1 block">pred_result と bet_* の両方が揃ったゲームが蓄積されると表示されます。</span>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      {/* Overall ROI */}
                      <div className="flex items-center gap-4 bg-gray-950/50 p-4 rounded border border-gray-800/50">
                        <div className="text-center min-w-[100px]">
                          <p className={`text-3xl font-black ${(predRoi.overall_roi ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {predRoi.overall_roi != null ? `${(predRoi.overall_roi * 100).toFixed(1)}%` : "—"}
                          </p>
                          <p className="text-xs text-gray-500 mt-1">全体ROI</p>
                        </div>
                        <div className="flex-1 text-xs text-gray-400">
                          対象 <span className="text-gray-200 font-semibold">{predRoi.total_with_bets}件</span>（ベット額確定済）
                          ／ 全予測 {predRoi.total}件<br />
                          <span className="text-gray-500">ROI = (払戻合計 − ベット合計) ÷ ベット合計。プラスなら予測に従うほど利益。</span>
                        </div>
                        <div className="text-right min-w-[80px]">
                          <p className={`text-lg font-bold ${
                            (() => {
                              const cum = predRoi.cumulative_pnl.at(-1)?.cumulative ?? 0;
                              return cum >= 0 ? "text-green-400" : "text-red-400";
                            })()
                          }`}>
                            {(() => {
                              const cum = predRoi.cumulative_pnl.at(-1)?.cumulative ?? 0;
                              return `${cum >= 0 ? "+" : ""}${cum.toLocaleString()}`;
                            })()}
                          </p>
                          <p className="text-xs text-gray-500">累計損益</p>
                        </div>
                      </div>

                      {/* Per-class ROI */}
                      <div className="grid grid-cols-3 gap-3">
                        {(
                          [
                            { key: "cowboy", label: "カウボーイ予測時", color: "text-red-400", border: "border-red-900/30", bg: "bg-red-950/20" },
                            { key: "bull",   label: "ブル予測時",       color: "text-blue-400",  border: "border-blue-900/30",  bg: "bg-blue-950/20" },
                            { key: "draw",   label: "抽選予測時",       color: "text-green-400", border: "border-green-900/30", bg: "bg-green-950/20" },
                          ] as const
                        ).map(({ key, label, color, border, bg }) => {
                          const cls = predRoi.by_predicted[key];
                          const roi = cls.roi;
                          return (
                            <div key={key} className={`${bg} ${border} border rounded-xl p-4 text-center space-y-1`}>
                              <p className={`text-2xl font-black ${roi == null ? "text-gray-500" : roi >= 0 ? "text-green-400" : "text-red-400"}`}>
                                {roi != null ? `${roi >= 0 ? "+" : ""}${(roi * 100).toFixed(1)}%` : "—"}
                              </p>
                              <p className={`text-xs ${color}`}>{label}</p>
                              <p className="text-xs text-gray-500">{cls.correct}/{cls.total}件正解</p>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>

                {/* Streak Panel */}
                <div className="bg-gray-900/40 border border-gray-800 rounded-xl p-6 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <h3 className="text-md font-bold text-yellow-500 flex items-center gap-2">
                      <span>🔴</span> 連続予測ミストリーク
                    </h3>
                    <div className="flex items-center gap-2 text-xs">
                      <input
                        type="date"
                        value={streakFrom}
                        onChange={e => setStreakFrom(e.target.value)}
                        className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-gray-200 text-xs [&::-webkit-calendar-picker-indicator]:invert"
                      />
                      <span className="text-gray-500">〜</span>
                      <input
                        type="date"
                        value={streakTo}
                        onChange={e => setStreakTo(e.target.value)}
                        className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-gray-200 text-xs [&::-webkit-calendar-picker-indicator]:invert"
                      />
                      <button
                        onClick={loadStreaks}
                        className="px-2 py-1 bg-gray-800 hover:bg-gray-700 rounded text-gray-300 transition"
                      >絞込</button>
                    </div>
                  </div>

                  {!predStreaks || predStreaks.total === 0 ? (
                    <div className="bg-gray-950/50 border border-gray-800/50 rounded-lg p-6 text-center text-gray-400 text-sm">
                      まだ予測データがありません。
                    </div>
                  ) : (
                    <div className="space-y-4">
                      {/* Current streak alert */}
                      {predStreaks.current_miss_streak >= 3 && (
                        <div className={`rounded-lg p-3 text-sm font-bold text-center ${
                          predStreaks.current_miss_streak >= 7
                            ? "bg-red-950/50 border border-red-700/60 text-red-400"
                            : "bg-orange-950/30 border border-orange-700/40 text-orange-400"
                        }`}>
                          ⚠️ 現在 {predStreaks.current_miss_streak}ラウンド連続ミス中
                        </div>
                      )}

                      {/* Streak summary */}
                      <div className="grid grid-cols-2 gap-4">
                        <div className="bg-gray-950/50 border border-gray-800/50 rounded-xl p-5 text-center space-y-1">
                          <p className="text-xs text-gray-400">現在の連続ミス</p>
                          <p className={`text-4xl font-black ${predStreaks.current_miss_streak >= 5 ? "text-red-400" : predStreaks.current_miss_streak >= 3 ? "text-orange-400" : "text-gray-200"}`}>
                            {predStreaks.current_miss_streak}
                          </p>
                          <p className="text-xs text-gray-500">ラウンド連続</p>
                        </div>
                        <div className="bg-gray-950/50 border border-gray-800/50 rounded-xl p-5 text-center space-y-1">
                          <p className="text-xs text-gray-400">最大連続ミス（期間内）</p>
                          <p className="text-4xl font-black text-red-400">
                            {predStreaks.max_miss_streak}
                          </p>
                          <p className="text-xs text-gray-500">ラウンド連続</p>
                        </div>
                      </div>

                      <div className="text-xs text-gray-500 text-right">集計対象: {predStreaks.total}件</div>

                      {/* Streak history */}
                      {predStreaks.streak_history.length > 0 && (
                        <div>
                          <p className="text-xs text-gray-400 font-semibold mb-2">5連続ミス以上の履歴</p>
                          <div className="space-y-1 max-h-48 overflow-y-auto">
                            {predStreaks.streak_history.slice().reverse().map((s, i) => (
                              <div key={i} className="flex items-center justify-between text-xs bg-gray-950/50 border border-gray-800/30 rounded px-3 py-1.5">
                                <span className="text-red-400 font-bold">{s.streak}ラウンド連続ミス</span>
                                <span className="text-gray-500 font-mono">
                                  {new Date(s.from).toLocaleDateString("ja-JP")} 〜 {new Date(s.to).toLocaleDateString("ja-JP")}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Tab content 2: Open Card Stats Matrix */}
            {activeTab === "cards" && (
              <div className="space-y-6 animate-fadeIn">
                <div className="bg-gray-900/20 border border-gray-800 rounded-xl p-6">
                  <div className="flex justify-between items-center mb-6">
                    <div>
                      <h3 className="text-md font-bold text-yellow-400 flex items-center gap-2">
                        <span>🃏</span> オープンカード別の実績勝率マトリクス
                      </h3>
                      <p className="text-xs text-gray-400 mt-1">最初に開かれたカードのランク（数字）ごとの実勝率データです。50%以上の勝率は背景色で強調されます。</p>
                    </div>
                    <div className="text-[11px] bg-gray-900 px-3 py-1.5 rounded border border-gray-800 text-gray-400">
                      総サンプル数: <span className="font-semibold text-gray-200">{stats.total}R</span>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    {rankOrder.map((rank) => {
                      const item = stats.rankStats[rank] || { total: 0, cowboy: 0, draw: 0, bull: 0 };
                      const cowboyRate = item.total ? item.cowboy / item.total : 0;
                      const bullRate = item.total ? item.bull / item.total : 0;
                      const drawRate = item.total ? item.draw / item.total : 0;
                      const favored = cowboyRate > bullRate ? "cowboy" : bullRate > cowboyRate ? "bull" : "none";

                      return (
                        <div key={rank} className="bg-gray-950 border border-gray-850 rounded-xl p-4 flex flex-col justify-between space-y-4 hover:border-gray-700 transition">
                          <div className="flex justify-between items-start">
                            <span className="text-2xl font-black text-yellow-500 tracking-tighter bg-gray-900 px-3 py-1 rounded border border-gray-800">
                              {rank}
                            </span>
                            <div className="text-right">
                              <span className="text-[10px] text-gray-500 block">出現回数</span>
                              <span className="text-xs font-bold text-gray-300">{item.total}回</span>
                            </div>
                          </div>

                          {/* Win Rates Progress Bars */}
                          <div className="space-y-2 text-xs">
                            {/* Cowboy progress */}
                            <div>
                              <div className="flex justify-between items-center mb-1">
                                <span className="text-gray-400">カウボーイ勝率</span>
                                <span className={`font-semibold ${cowboyRate >= 0.5 ? "text-red-400 font-bold" : "text-gray-300"}`}>
                                  {(cowboyRate * 100).toFixed(1)}%
                                </span>
                              </div>
                              <div className="w-full bg-gray-900 rounded-full h-2 overflow-hidden">
                                <div
                                  className="bg-red-500 h-full rounded-full transition-all duration-500"
                                  style={{ width: `${cowboyRate * 100}%` }}
                                ></div>
                              </div>
                            </div>

                            {/* Bull progress */}
                            <div>
                              <div className="flex justify-between items-center mb-1">
                                <span className="text-gray-400">ブル勝率</span>
                                <span className={`font-semibold ${bullRate >= 0.5 ? "text-blue-400 font-bold" : "text-gray-300"}`}>
                                  {(bullRate * 100).toFixed(1)}%
                                </span>
                              </div>
                              <div className="w-full bg-gray-900 rounded-full h-2 overflow-hidden">
                                <div
                                  className="bg-blue-500 h-full rounded-full transition-all duration-500"
                                  style={{ width: `${bullRate * 100}%` }}
                                ></div>
                              </div>
                            </div>

                            {/* Draw progress */}
                            <div>
                              <div className="flex justify-between items-center mb-1">
                                <span className="text-gray-400">抽選 (Draw) 確率</span>
                                <span className="text-gray-400 font-medium">
                                  {(drawRate * 100).toFixed(1)}%
                                </span>
                              </div>
                              <div className="w-full bg-gray-900 rounded-full h-1 overflow-hidden">
                                <div
                                  className="bg-green-500 h-full rounded-full transition-all duration-500"
                                  style={{ width: `${drawRate * 100}%` }}
                                ></div>
                              </div>
                            </div>
                          </div>

                          {/* Favored badge */}
                          <div className="pt-2 border-t border-gray-900/60 flex items-center justify-between text-[11px]">
                            <span className="text-gray-500">有利バイアス:</span>
                            {favored === "cowboy" ? (
                              <span className="px-2.5 py-0.5 rounded bg-red-950/60 border border-red-900/50 text-red-400 font-bold">
                                Cowboy 有利 (+{((cowboyRate - bullRate) * 100).toFixed(0)}%)
                              </span>
                            ) : favored === "bull" ? (
                              <span className="px-2.5 py-0.5 rounded bg-blue-950/60 border border-blue-900/50 text-blue-400 font-bold">
                                Bull 有利 (+{((bullRate - cowboyRate) * 100).toFixed(0)}%)
                              </span>
                            ) : (
                              <span className="text-gray-500 font-medium">なし</span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {/* Tab content 3: Interval Statistics */}
            {activeTab === "intervals" && (
              <div className="space-y-4 animate-fadeIn">
                {!gameIntervals ? (
                  <div className="text-center text-gray-400 py-16">データを読み込み中...</div>
                ) : (() => {
                  const cats = gameIntervals.categories;
                  const GROUPS = [
                    {
                      title: "メイン結果",
                      keys: ["cowboy", "bull", "draw"],
                      colors: {
                        cowboy: { bar: "bg-red-500", text: "text-red-400", border: "border-red-900/40", bg: "bg-red-950/20" },
                        bull:   { bar: "bg-blue-500", text: "text-blue-400", border: "border-blue-900/40", bg: "bg-blue-950/20" },
                        draw:   { bar: "bg-green-500", text: "text-green-400", border: "border-green-900/40", bg: "bg-green-950/20" },
                      } as Record<string, { bar: string; text: string; border: string; bg: string }>,
                    },
                    {
                      title: "サイドベット WIN",
                      keys: ["any_flash", "any_pair", "win_high", "win_two", "win_sf", "win_fh", "any_ace", "win_four"],
                      colors: {} as Record<string, { bar: string; text: string; border: string; bg: string }>,
                    },
                  ];

                  return (
                    <div className="space-y-6">
                      <p className="text-xs text-gray-500">
                        総ゲーム数: <span className="text-gray-300 font-bold">{gameIntervals.total_games.toLocaleString()}</span> 件 ／ インターバル = 連続して出現しなかったゲーム数（1 = 毎回）
                      </p>
                      {GROUPS.map(group => (
                        <div key={group.title}>
                          <h3 className="text-sm font-bold text-yellow-500 mb-3">{group.title}</h3>
                          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                            {group.keys.map(key => {
                              const cat = cats[key];
                              if (!cat) return null;
                              const col = group.colors[key] ?? {
                                bar: "bg-yellow-500", text: "text-yellow-400",
                                border: "border-yellow-900/40", bg: "bg-yellow-950/10",
                              };
                              const maxCount = Math.max(...cat.histogram.map(b => b.count), 1);
                              const isRare = (cat.mean_interval ?? 0) > 30;
                              const gapWarn = cat.current_gap > (cat.p75_interval ?? cat.max_interval ?? 99);
                              return (
                                <div key={key} className={`${col.bg} ${col.border} border rounded-xl p-4 space-y-3`}>
                                  {/* Header */}
                                  <div className="flex items-start justify-between">
                                    <div>
                                      <p className={`font-bold text-sm ${col.text}`}>{cat.label}</p>
                                      <p className="text-xs text-gray-500">オッズ {cat.odds}倍 ／ {cat.count}回出現</p>
                                    </div>
                                    <div className={`text-right ${gapWarn ? "text-orange-400" : "text-gray-300"}`}>
                                      <p className="text-xl font-black">{cat.current_gap}G</p>
                                      <p className="text-[10px] text-gray-500">前回から</p>
                                    </div>
                                  </div>

                                  {/* Summary stats */}
                                  <div className="grid grid-cols-3 gap-1 text-center text-xs">
                                    <div className="bg-gray-900/60 rounded p-1.5">
                                      <p className="text-gray-400">平均</p>
                                      <p className="font-bold text-gray-200">{cat.mean_interval ?? "—"}G</p>
                                    </div>
                                    <div className="bg-gray-900/60 rounded p-1.5">
                                      <p className="text-gray-400">中央値</p>
                                      <p className="font-bold text-gray-200">{cat.median_interval ?? "—"}G</p>
                                    </div>
                                    <div className="bg-gray-900/60 rounded p-1.5">
                                      <p className="text-gray-400">最大空白</p>
                                      <p className="font-bold text-red-400">{cat.max_interval ?? "—"}G</p>
                                    </div>
                                  </div>

                                  {/* Histogram */}
                                  <div>
                                    <p className="text-[10px] text-gray-600 mb-1">インターバル分布</p>
                                    <div className="space-y-0.5">
                                      {cat.histogram.filter(b => b.count > 0 || !isRare).map((b, i) => (
                                        <div key={i} className="flex items-center gap-1.5">
                                          <span className="text-[10px] text-gray-500 font-mono w-12 text-right shrink-0">{b.label}G</span>
                                          <div className="flex-1 bg-gray-900/60 rounded-full h-3 overflow-hidden">
                                            <div
                                              className={`${col.bar} h-full rounded-full transition-all`}
                                              style={{ width: `${(b.count / maxCount) * 100}%` }}
                                            />
                                          </div>
                                          <span className="text-[10px] text-gray-400 w-8 text-right shrink-0">{b.count}</span>
                                        </div>
                                      ))}
                                    </div>
                                  </div>

                                  {/* Warning: current gap exceeds p75 */}
                                  {gapWarn && (
                                    <p className="text-[10px] text-orange-400 bg-orange-950/20 border border-orange-900/30 rounded px-2 py-1">
                                      ⚠ 現在の空白({cat.current_gap}G)が75%ile({cat.p75_interval}G)を超えています
                                    </p>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      ))}
                    </div>
                  );
                })()}
              </div>
            )}

            {/* Tab content 4: ML System Specification */}
            {activeTab === "spec" && (
              <div className="space-y-6 animate-fadeIn text-sm leading-relaxed">

                {/* 現在稼働中の予測ルール（実装済み） */}
                <div className="bg-gray-900/40 border border-yellow-900/40 rounded-xl p-6 space-y-5">
                  <div className="flex items-center gap-3">
                    <span className="px-3 py-1 bg-yellow-500/15 text-yellow-400 font-black text-xs rounded-full border border-yellow-700/50 tracking-widest">LIVE</span>
                    <h2 className="text-lg font-bold text-yellow-400">現在稼働中の予測ロジック</h2>
                  </div>

                  {/* アルゴリズム */}
                  <div className="flex items-start gap-4 bg-yellow-950/10 border border-yellow-900/30 rounded-lg p-4">
                    <div className="text-3xl">🌳</div>
                    <div>
                      <p className="text-yellow-300 font-bold text-base">LightGBM（勾配ブースティング木）</p>
                      <p className="text-xs text-gray-400 mt-1 leading-relaxed">
                        多数の決定木を直列に積み重ね、前の木の誤りを次の木が補正し続けるアンサンブル学習。<br />
                        「このカードが来たとき、直近の流れはこうで、時間帯はこうなら → ブル有利」という<strong className="text-gray-200">複数条件の組み合わせルール</strong>を自動で学習する。
                      </p>
                    </div>
                  </div>

                  {/* 出力 */}
                  <div>
                    <p className="text-xs text-gray-400 font-semibold uppercase tracking-wider mb-2">出力（オープンカード確認後に計算）</p>
                    <div className="grid grid-cols-3 gap-3 text-xs font-mono">
                      <div className="bg-red-950/20 border border-red-900/30 rounded-lg p-3 text-center">
                        <p className="text-red-400 font-bold text-base">P(カウボーイ)</p>
                        <p className="text-gray-500 mt-1">例: 54%</p>
                      </div>
                      <div className="bg-green-950/20 border border-green-900/30 rounded-lg p-3 text-center">
                        <p className="text-green-400 font-bold text-base">P(抽選)</p>
                        <p className="text-gray-500 mt-1">例: 6%</p>
                      </div>
                      <div className="bg-blue-950/20 border border-blue-900/30 rounded-lg p-3 text-center">
                        <p className="text-blue-400 font-bold text-base">P(ブル)</p>
                        <p className="text-gray-500 mt-1">例: 40%</p>
                      </div>
                    </div>
                    <p className="text-xs text-gray-500 mt-2">最も確率が高いクラスを予測結果として表示。ダッシュボードのゲージが 50%超で強調表示。</p>
                  </div>

                  {/* 入力特徴量 */}
                  <div>
                    <p className="text-xs text-gray-400 font-semibold uppercase tracking-wider mb-3">入力特徴量（計 37 変数）</p>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 text-xs">

                      <div className="bg-gray-950/60 border border-gray-800 rounded-lg p-4 space-y-2">
                        <p className="text-yellow-400 font-bold flex items-center gap-1">🃏 カード <span className="text-gray-500 font-normal">19変数</span></p>
                        <ul className="space-y-1 text-gray-300">
                          <li className="flex justify-between"><span>ランク数値</span><span className="text-gray-500 font-mono">rank_num</span></li>
                          <li className="flex justify-between"><span>ランク one-hot</span><span className="text-gray-500 font-mono">×13</span></li>
                          <li className="flex justify-between"><span>スート one-hot</span><span className="text-gray-500 font-mono">×4</span></li>
                          <li className="flex justify-between"><span>赤カードフラグ</span><span className="text-gray-500 font-mono">is_red</span></li>
                        </ul>
                      </div>

                      <div className="bg-gray-950/60 border border-gray-800 rounded-lg p-4 space-y-2">
                        <p className="text-yellow-400 font-bold flex items-center gap-1">📈 流れ <span className="text-gray-500 font-normal">10変数</span></p>
                        <ul className="space-y-1 text-gray-300">
                          <li className="flex justify-between"><span>直前3Gの結果</span><span className="text-gray-500 font-mono">×3</span></li>
                          <li className="flex justify-between"><span>直前2Gのカード</span><span className="text-gray-500 font-mono">×2</span></li>
                          <li className="flex justify-between"><span>カウボーイ/ブル連勝</span><span className="text-gray-500 font-mono">×2</span></li>
                          <li className="flex justify-between"><span>直近10G勝率</span><span className="text-gray-500 font-mono">×2</span></li>
                          <li className="flex justify-between"><span>直近50G勝率/抽選率</span><span className="text-gray-500 font-mono">×2</span></li>
                        </ul>
                      </div>

                      <div className="bg-yellow-950/20 border border-yellow-800/50 rounded-lg p-4 space-y-2">
                        <p className="text-yellow-300 font-bold flex items-center gap-1">💰 ベット額 <span className="text-yellow-600 font-normal">5変数 NEW</span></p>
                        <ul className="space-y-1 text-gray-300">
                          <li className="flex justify-between"><span>直前3Gのカウボーイ率</span><span className="text-gray-500 font-mono">×3</span></li>
                          <li className="flex justify-between"><span>現Gカウボーイ率</span><span className="text-gray-500 font-mono">cur_ratio</span></li>
                          <li className="flex justify-between"><span>ベット確定フラグ</span><span className="text-gray-500 font-mono">has_bets</span></li>
                        </ul>
                        <p className="text-yellow-700 text-[10px] leading-relaxed pt-1">カード検出時は比率 0.5（中立）で初回予測 → ベット確定後（〜4秒前）に再計算して更新</p>
                      </div>

                      <div className="bg-gray-950/60 border border-gray-800 rounded-lg p-4 space-y-2">
                        <p className="text-yellow-400 font-bold flex items-center gap-1">🕐 時刻 <span className="text-gray-500 font-normal">2変数</span></p>
                        <ul className="space-y-1 text-gray-300">
                          <li className="flex justify-between"><span>時刻（0〜23時）</span><span className="text-gray-500 font-mono">hour</span></li>
                          <li className="flex justify-between"><span>曜日（月〜日）</span><span className="text-gray-500 font-mono">dow</span></li>
                        </ul>
                        <p className="text-gray-600 text-[10px] leading-relaxed pt-1 mt-2 border-t border-gray-800">❌ 未使用: ジャックポット額</p>
                      </div>
                    </div>
                  </div>

                  {/* 期待値の考え方 */}
                  <div className="bg-gray-950/60 border border-gray-800 rounded-lg p-4 text-xs space-y-2">
                    <p className="text-gray-200 font-bold">期待値の考え方</p>
                    <p className="text-gray-400 leading-relaxed">
                      正解率（Accuracy）だけでは不十分。カウボーイ/ブルのオッズは <strong className="text-gray-200">2.02倍</strong>なので、
                      50%超えれば期待値プラス。抽選は <strong className="text-gray-200">22倍</strong>なので 5%超えれば期待値プラス。
                    </p>
                    <div className="font-mono text-gray-500 bg-gray-900/50 rounded p-2 leading-relaxed">
                      期待ROI = (予測確率 × オッズ) − 1.0<br />
                      例: カウボーイ 54% × 2.02 = 1.091 → 期待ROI <span className="text-green-400">+9.1%</span>
                    </div>
                  </div>
                </div>

              </div>
            )}

            {/* Tab: Archive */}
            {activeTab === "archive" && (
              <div className="space-y-6 animate-fadeIn">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-gray-400">収支アーカイブ</h2>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-500">単位:</span>
                    <select
                      value={archiveBy}
                      onChange={(e) => setArchiveBy(e.target.value as "day" | "hour")}
                      className="bg-gray-900 border border-gray-800 text-gray-300 text-xs rounded px-2.5 py-1 focus:outline-none focus:border-yellow-400 cursor-pointer"
                    >
                      <option value="day">日別</option>
                      <option value="hour">時間別</option>
                    </select>
                  </div>
                </div>

                {!archiveData ? (
                  <div className="text-center text-gray-500 py-12 text-sm">読み込み中…</div>
                ) : archiveData.records.length === 0 ? (
                  <div className="text-center text-gray-500 py-12 text-sm">データがありません</div>
                ) : (
                  <>
                    {/* PnL Bar Chart */}
                    <div className="bg-gray-900/40 border border-gray-800 rounded-xl p-5">
                      <p className="text-xs text-gray-400 font-semibold mb-4">収支合算（ベット − 払い出し）</p>
                      <ResponsiveContainer width="100%" height={260}>
                        <BarChart
                          data={archiveData.records}
                          margin={{ top: 4, right: 8, left: 8, bottom: 40 }}
                        >
                          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                          <XAxis
                            dataKey="period"
                            tick={{ fill: "#9ca3af", fontSize: 10 }}
                            angle={-35}
                            textAnchor="end"
                            interval={0}
                          />
                          <YAxis
                            tick={{ fill: "#9ca3af", fontSize: 10 }}
                            tickFormatter={(v: number) => fmtAmount(v)}
                          />
                          <Tooltip
                            contentStyle={{ background: "#111827", border: "1px solid #374151", borderRadius: 8 }}
                            labelStyle={{ color: "#e5e7eb", fontSize: 11 }}
                            formatter={(value: number, name: string) => [fmtAmount(value), name]}
                          />
                          <ReferenceLine y={0} stroke="#6b7280" strokeDasharray="4 2" />
                          <Bar
                            dataKey="pnl"
                            name="収支"
                            radius={[3, 3, 0, 0]}
                            isAnimationActive={false}
                          >
                            {archiveData.records.map((r, idx) => (
                              <Cell key={idx} fill={r.pnl >= 0 ? "#22c55e" : "#ef4444"} />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </div>

                    {/* Bet / Payout stacked area */}
                    <div className="bg-gray-900/40 border border-gray-800 rounded-xl p-5">
                      <p className="text-xs text-gray-400 font-semibold mb-4">総ベット vs 払い出し</p>
                      <ResponsiveContainer width="100%" height={220}>
                        <BarChart
                          data={archiveData.records}
                          margin={{ top: 4, right: 8, left: 8, bottom: 40 }}
                        >
                          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                          <XAxis
                            dataKey="period"
                            tick={{ fill: "#9ca3af", fontSize: 10 }}
                            angle={-35}
                            textAnchor="end"
                            interval={0}
                          />
                          <YAxis
                            tick={{ fill: "#9ca3af", fontSize: 10 }}
                            tickFormatter={(v: number) => fmtAmount(v)}
                          />
                          <Tooltip
                            contentStyle={{ background: "#111827", border: "1px solid #374151", borderRadius: 8 }}
                            labelStyle={{ color: "#e5e7eb", fontSize: 11 }}
                            formatter={(value: number, name: string) => [fmtAmount(value), name]}
                          />
                          <Bar dataKey="total_bet"    name="ベット"    fill="#6b7280" radius={[2,2,0,0]} />
                          <Bar dataKey="total_payout" name="払い出し"  fill="#3b82f6" radius={[2,2,0,0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>

                    {/* Summary table */}
                    <div className="overflow-x-auto rounded-xl border border-gray-800">
                      <table className="min-w-full text-xs">
                        <thead className="bg-gray-900 text-gray-400">
                          <tr>
                            <th className="px-3 py-2 text-left font-semibold">{archiveBy === "day" ? "日付" : "時間帯"}</th>
                            <th className="px-3 py-2 text-right font-semibold">ゲーム数</th>
                            <th className="px-3 py-2 text-right font-semibold">CB%</th>
                            <th className="px-3 py-2 text-right font-semibold">ブル%</th>
                            <th className="px-3 py-2 text-right font-semibold">総ベット</th>
                            <th className="px-3 py-2 text-right font-semibold">払い出し</th>
                            <th className="px-3 py-2 text-right font-semibold">収支</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-800">
                          {[...archiveData.records].reverse().map((r) => (
                            <tr key={r.period} className="hover:bg-gray-800/30">
                              <td className="px-3 py-1.5 text-gray-300 whitespace-nowrap font-mono">{r.period}</td>
                              <td className="px-3 py-1.5 text-right text-gray-400">{r.game_count}</td>
                              <td className={`px-3 py-1.5 text-right font-semibold ${(r.cowboy_rate ?? 0) > 0.55 ? "text-red-300" : (r.cowboy_rate ?? 0) < 0.35 ? "text-blue-300" : "text-gray-300"}`}>
                                {r.cowboy_rate != null ? `${(r.cowboy_rate * 100).toFixed(1)}%` : "—"}
                              </td>
                              <td className={`px-3 py-1.5 text-right font-semibold ${(r.bull_rate ?? 0) > 0.55 ? "text-blue-300" : (r.bull_rate ?? 0) < 0.35 ? "text-red-300" : "text-gray-300"}`}>
                                {r.bull_rate != null ? `${(r.bull_rate * 100).toFixed(1)}%` : "—"}
                              </td>
                              <td className="px-3 py-1.5 text-right text-gray-400">{fmtAmount(r.total_bet)}</td>
                              <td className="px-3 py-1.5 text-right text-blue-400">{fmtAmount(r.total_payout)}</td>
                              <td className={`px-3 py-1.5 text-right font-bold ${r.pnl > 0 ? "text-green-400" : r.pnl < 0 ? "text-red-400" : "text-gray-400"}`}>
                                {r.pnl > 0 ? "+" : ""}{fmtAmount(r.pnl)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
