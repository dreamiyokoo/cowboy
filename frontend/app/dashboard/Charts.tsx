"use client";

import {
  ResponsiveContainer,
  LineChart,
  AreaChart,
  BarChart,
  Line,
  Area,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from "recharts";
import { calcBetTotal, calcPayout, fmtAmount, type Game } from "@/app/lib/api";

// ── データ加工 ──────────────────────────────────────────

export interface ChartDataPoint {
  idx: number;
  label: string;
  cowboyBullDiff: number;
  pnl: number;
  cumulPnl: number;
  payout: number;
  betTotal: number;
}

export function buildChartData(games: Game[]): ChartDataPoint[] {
  const chronological = [...games].reverse(); // oldest → newest
  let cumulCowboy = 0;
  let cumulBull = 0;
  let cumulPnl = 0;

  return chronological.map((g, i) => {
    if (g.result === "cowboy") cumulCowboy++;
    if (g.result === "bull") cumulBull++;
    const betTotal = calcBetTotal(g);
    const payout = calcPayout(g);
    const pnl = payout - betTotal;
    cumulPnl += pnl;

    const dt = new Date(g.recorded_at);
    const label = `${dt.getMonth() + 1}/${dt.getDate()} ${dt.getHours().toString().padStart(2, "0")}:${dt.getMinutes().toString().padStart(2, "0")}`;

    return {
      idx: i + 1,
      label,
      cowboyBullDiff: cumulCowboy - cumulBull,
      pnl,
      cumulPnl,
      payout,
      betTotal,
    };
  });
}

// ── 共通スタイル ────────────────────────────────────────

const AXIS_STYLE = { fontSize: 10, fill: "#6b7280" };
const GRID_STYLE = { stroke: "#374151", strokeDasharray: "3 3" };

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
      <h3 className="text-xs font-semibold text-gray-400 mb-3">{title}</h3>
      {children}
    </div>
  );
}

function AmountTooltip({ active, payload, label }: { active?: boolean; payload?: { value: number; name: string; color: string }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-xs">
      <p className="text-gray-400 mb-1">{label}</p>
      {payload.map((p) => (
        <p key={p.name} style={{ color: p.color }}>
          {p.name}: {fmtAmount(p.value)}
        </p>
      ))}
    </div>
  );
}

// ── グラフ本体 ──────────────────────────────────────────

export function CowboyBullDiffChart({ data }: { data: ChartDataPoint[] }) {
  const last = data[data.length - 1];
  const diffColor = last && last.cowboyBullDiff >= 0 ? "#f87171" : "#60a5fa";

  return (
    <ChartCard title={`カウボーイ vs ブル 勝利差 (現在: ${last ? (last.cowboyBullDiff >= 0 ? "+" : "") + last.cowboyBullDiff : "—"})`}>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid {...GRID_STYLE} />
          <XAxis dataKey="idx" tick={AXIS_STYLE} interval="preserveStartEnd" />
          <YAxis tick={AXIS_STYLE} width={32} />
          <ReferenceLine y={0} stroke="#6b7280" strokeDasharray="4 4" />
          <Tooltip
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              const v = payload[0]?.value as number;
              return (
                <div className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-xs">
                  <p className="text-gray-400">ゲーム {label}</p>
                  <p style={{ color: diffColor }}>差分: {v >= 0 ? "+" : ""}{v}</p>
                </div>
              );
            }}
          />
          <Line
            type="monotone"
            dataKey="cowboyBullDiff"
            name="差分"
            stroke={diffColor}
            dot={false}
            strokeWidth={2}
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function CumulPnlChart({ data }: { data: ChartDataPoint[] }) {
  const last = data[data.length - 1];
  const isProfit = last ? last.cumulPnl >= 0 : true;

  return (
    <ChartCard title={`収支合算 (現在: ${last ? (last.cumulPnl >= 0 ? "+" : "") + fmtAmount(last.cumulPnl) : "—"})`}>
      <ResponsiveContainer width="100%" height={180}>
        <AreaChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={isProfit ? "#4ade80" : "#f87171"} stopOpacity={0.3} />
              <stop offset="95%" stopColor={isProfit ? "#4ade80" : "#f87171"} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid {...GRID_STYLE} />
          <XAxis dataKey="idx" tick={AXIS_STYLE} interval="preserveStartEnd" />
          <YAxis tick={AXIS_STYLE} width={48} tickFormatter={(v) => fmtAmount(v)} />
          <ReferenceLine y={0} stroke="#6b7280" strokeDasharray="4 4" />
          <Tooltip content={<AmountTooltip />} />
          <Area
            type="monotone"
            dataKey="cumulPnl"
            name="累計収支"
            stroke={isProfit ? "#4ade80" : "#f87171"}
            fill="url(#pnlGrad)"
            strokeWidth={2}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function PayoutChart({ data }: { data: ChartDataPoint[] }) {
  return (
    <ChartCard title="払い出し（ゲームごと）">
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid {...GRID_STYLE} />
          <XAxis dataKey="idx" tick={AXIS_STYLE} interval="preserveStartEnd" />
          <YAxis tick={AXIS_STYLE} width={48} tickFormatter={(v) => fmtAmount(v)} />
          <Tooltip content={<AmountTooltip />} />
          <Bar dataKey="payout" name="払い出し" fill="#facc15" radius={[2, 2, 0, 0]} maxBarSize={20} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function BetTotalChart({ data }: { data: ChartDataPoint[] }) {
  return (
    <ChartCard title="ベット合計（ゲームごと）">
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid {...GRID_STYLE} />
          <XAxis dataKey="idx" tick={AXIS_STYLE} interval="preserveStartEnd" />
          <YAxis tick={AXIS_STYLE} width={48} tickFormatter={(v) => fmtAmount(v)} />
          <Tooltip content={<AmountTooltip />} />
          <Bar dataKey="betTotal" name="ベット合計" fill="#818cf8" radius={[2, 2, 0, 0]} maxBarSize={20} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
