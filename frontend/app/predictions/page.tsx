"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  getValidAccessToken,
  clearAccessToken,
} from "@/app/lib/auth";
import {
  fetchGames,
  fetchPredictionAccuracy,
  type Game,
  type GameResult,
  type PredictionAccuracyResponse,
} from "@/app/lib/api";

type TabId = "validation" | "cards" | "spec";

export default function PredictionsPage() {
  const router = useRouter();
  const [games, setGames] = useState<Game[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<TabId>("validation");
  const [predAccuracy, setPredAccuracy] = useState<PredictionAccuracyResponse | null>(null);

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

      // 予測精度データ取得
      try {
        const acc = await fetchPredictionAccuracy(token);
        setPredAccuracy(acc);
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
      {/* Header */}
      <header className="sticky top-0 z-10 flex items-center justify-between
                         bg-gray-900/80 backdrop-blur border-b border-gray-800 px-6 py-3">
        <h1 className="text-xl font-bold text-yellow-400 flex items-center gap-2">
          <span>🔮</span> AI・機械学習予測分析
        </h1>
        <div className="flex items-center gap-4">
          <Link
            href="/dashboard"
            className="text-sm px-3 py-1 rounded bg-gray-800 hover:bg-gray-700 transition text-gray-300 font-medium"
          >
            🏠 ダッシュボード
          </Link>
          <Link
            href="/card-stats"
            className="text-sm px-3 py-1 rounded bg-gray-800 hover:bg-gray-700 transition text-gray-300 font-medium"
          >
            📊 勝率統計
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

            {/* Tab content 3: ML System Specification */}
            {activeTab === "spec" && (
              <div className="space-y-6 animate-fadeIn text-sm leading-relaxed">
                <div className="bg-gray-900/40 border border-gray-800 rounded-xl p-6 space-y-6">
                  <div>
                    <h2 className="text-lg font-bold text-yellow-400 border-b border-gray-800 pb-2 flex items-center gap-2">
                      <span>🔮</span> カウボーイ AI機械学習予測システム設計書
                    </h2>
                    <p className="text-xs text-gray-400 mt-2">過去にキャプチャしたデータをもとに、機械学習で勝敗を予測するシステムの構造設計です。</p>
                  </div>

                  {/* Section 1 */}
                  <div className="space-y-3">
                    <h3 className="text-sm font-bold text-gray-200 border-l-4 border-yellow-500 pl-2">1. 予測のターゲット変数（目的変数）</h3>
                    <p className="text-gray-300">
                      モデルの目的は、各ゲームの最終結果（`result`）がどのポジションになるかを予測する<strong>多クラス分類 (Multi-class Classification)</strong> タスクです。
                    </p>
                    <div className="bg-gray-950/50 border border-gray-850 rounded p-4 text-xs font-mono grid grid-cols-3 gap-2">
                      <div className="text-red-400">P(cowboy): カウボーイ勝確率</div>
                      <div className="text-blue-400">P(bull): ブル勝確率</div>
                      <div className="text-green-400">P(draw): 抽選（タイ）確率</div>
                    </div>
                  </div>

                  {/* Section 2 */}
                  <div className="space-y-3">
                    <h3 className="text-sm font-bold text-gray-200 border-l-4 border-yellow-500 pl-2">2. 特徴量設計 (Feature Engineering)</h3>
                    <p className="text-gray-300">予測モデルにインプットする特徴量の設計リストです。</p>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
                      <div className="bg-gray-950/50 border border-gray-850 rounded p-4 space-y-2">
                        <h4 className="font-bold text-yellow-400">① カード特徴量 (物理因子)</h4>
                        <ul className="list-disc list-inside space-y-1 text-gray-400">
                          <li>オープンカードの数字 (2〜A)</li>
                          <li>オープンカードのスート (S,H,D,C)</li>
                          <li>カードの強さ順の数値化</li>
                        </ul>
                      </div>
                      <div className="bg-gray-950/50 border border-gray-850 rounded p-4 space-y-2">
                        <h4 className="font-bold text-yellow-400">② ベット特徴量 (集団心理/情報)</h4>
                        <ul className="list-disc list-inside space-y-1 text-gray-400">
                          <li>カウボーイ vs ブルの金額比率</li>
                          <li>大口ベット（クジラ）の検知フラグ</li>
                          <li>サイドベットの賭け金分布</li>
                        </ul>
                      </div>
                      <div className="bg-gray-950/50 border border-gray-850 rounded p-4 space-y-2">
                        <h4 className="font-bold text-yellow-400">③ 時系列特徴量 (シャッフル癖)</h4>
                        <ul className="list-disc list-inside space-y-1 text-gray-400">
                          <li>直近 1〜3 ゲームの勝敗結果</li>
                          <li>直近のオープンカード数字の塊</li>
                          <li>カウボーイ/ブルの現在の連勝数</li>
                        </ul>
                      </div>
                    </div>
                  </div>

                  {/* Section 3 */}
                  <div className="space-y-3">
                    <h3 className="text-sm font-bold text-gray-200 border-l-4 border-yellow-500 pl-2">3. 採用モデル & アルゴリズム候補</h3>
                    <div className="space-y-3 text-xs text-gray-300">
                      <div className="flex gap-4 items-start bg-gray-950/40 p-3 rounded border border-gray-850">
                        <span className="px-2 py-1 bg-yellow-500/10 text-yellow-400 font-bold rounded">LightGBM</span>
                        <div>
                          <strong className="block mb-1">勾配ブースティング木（推奨）</strong>
                          ベット比率やカードランクなどの非線形な関係を捉える上で最も精度が高く、リアルタイム予測に対応可能。
                        </div>
                      </div>
                      <div className="flex gap-4 items-start bg-gray-950/40 p-3 rounded border border-gray-850">
                        <span className="px-2 py-1 bg-yellow-500/10 text-yellow-400 font-bold rounded">Logistic Regression</span>
                        <div>
                          <strong className="block mb-1">ロジスティック回帰</strong>
                          どの変数が勝敗に最も寄与しているか（Aカードの出現、偏ったベットなど）を数式として明確に説明できるベースラインモデル。
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Section 4 */}
                  <div className="space-y-3">
                    <h3 className="text-sm font-bold text-gray-200 border-l-4 border-yellow-500 pl-2">4. 期待値(ROI)インジケーターによるバックテスト方法</h3>
                    <p className="text-gray-300">
                      モデルの良し悪しは予測の正解率(Accuracy)ではなく、<strong>期待値が1.0を超えるゲームにのみ賭けた場合のシミュレーション収支</strong>で判定します。
                    </p>
                    <div className="bg-yellow-950/5 border border-yellow-900/20 rounded-lg p-4 text-xs text-yellow-400/90 leading-relaxed font-mono">
                      【期待期待値の計算式】<br />
                      期待利益 = (予測した勝率 × 配当オッズ) - 1.0 <br />
                      ※ 例: カウボーイの予測確率が 55% でオッズが 2.02 倍の場合、期待値は (0.55 × 2.02) = 1.111 (期待ROI +11.1%) となり、ベットゴーと判定。
                    </div>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
