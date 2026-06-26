"use client";
import type { CapturePreview } from "@/app/lib/api";

interface Props {
  preview: CapturePreview | null;
}

type StepState = "done" | "active" | "idle";

interface Step {
  key: string;
  label: string;
  sub?: string;
}

export default function GameProgressBar({ preview }: Props) {
  const state = preview?.game_state;

  if (!state || state === "cooldown" || state === "unknown") return null;

  const card       = preview?.open_card ?? null;
  const remaining  = preview?.remaining_seconds ?? null;
  const roundNum   = preview?.round_number ?? null;
  const predicted  = preview?.prediction?.predicted ?? null;

  // 4-step flow: 準備 → カード開示 → 投票中 → 結果
  // activeIndex: 0=preparing, 1=card/prediction, 2=betting countdown, 3=result
  let activeIndex = 0;
  if (state === "result")                       activeIndex = 3;
  else if (state === "betting" && remaining !== null && remaining <= 5) activeIndex = 2; // bet scan zone
  else if (state === "betting")                 activeIndex = 2;
  else if (state === "preparing" && card)       activeIndex = 1;

  const RESULT_LABEL: Record<string, string> = { cowboy: "カウボーイ", draw: "抽選", bull: "ブル" };

  const steps: Step[] = [
    {
      key: "prepare",
      label: "準備中",
    },
    {
      key: "card",
      label: card ? `開札: ${card}` : "カード開示",
      sub: predicted ? `予測: ${RESULT_LABEL[predicted] ?? predicted}` : undefined,
    },
    {
      key: "betting",
      label: "投票中",
      sub: remaining !== null ? `残り ${remaining}s` : undefined,
    },
    {
      key: "result",
      label: "結果",
    },
  ];

  function stepState(i: number): StepState {
    if (i < activeIndex) return "done";
    if (i === activeIndex) return "active";
    return "idle";
  }

  // Progress bar fill % (only meaningful during betting)
  const MAX_TIMER = 13; // observed max timer value
  const fillPct = state === "betting" && remaining !== null
    ? Math.max(0, Math.min(100, ((MAX_TIMER - remaining) / MAX_TIMER) * 100))
    : state === "result"
    ? 100
    : 0;

  const barColor =
    state === "result"      ? "bg-green-500"
    : remaining !== null && remaining <= 5 ? "bg-red-500"
    : remaining !== null && remaining <= 8 ? "bg-amber-400"
    : "bg-emerald-500";

  return (
    <div className="sticky top-[52px] z-[9] bg-gray-950/95 backdrop-blur-sm border-b border-gray-800/70 px-6 py-2">
      {/* Step indicators */}
      <div className="flex items-center gap-0 max-w-2xl">
        {steps.map((step, i) => {
          const ss = stepState(i);
          const isLast = i === steps.length - 1;
          return (
            <div key={step.key} className="flex items-center min-w-0">
              {/* Node + label */}
              <div className="flex items-center gap-1.5 shrink-0">
                {/* Circle */}
                <div
                  className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold border shrink-0
                    ${ss === "active"
                      ? "border-yellow-400 bg-yellow-400/20 text-yellow-300 ring-2 ring-yellow-400/30"
                      : ss === "done"
                      ? "border-green-500 bg-green-500/20 text-green-400"
                      : "border-gray-700 bg-gray-900 text-gray-600"
                    }`}
                >
                  {ss === "done" ? "✓" : i + 1}
                </div>
                {/* Label */}
                <div className="flex flex-col leading-tight">
                  <span
                    className={`text-[11px] font-semibold whitespace-nowrap
                      ${ss === "active" ? "text-yellow-300" : ss === "done" ? "text-green-400" : "text-gray-600"}`}
                  >
                    {step.label}
                  </span>
                  {step.sub && ss !== "idle" && (
                    <span className={`text-[10px] whitespace-nowrap
                      ${ss === "active" ? "text-yellow-500/80" : "text-green-600/80"}`}>
                      {step.sub}
                    </span>
                  )}
                </div>
              </div>
              {/* Connector line */}
              {!isLast && (
                <div className={`mx-2 flex-1 h-px min-w-[20px] max-w-[48px]
                  ${i < activeIndex ? "bg-green-600/60" : "bg-gray-800"}`}
                />
              )}
            </div>
          );
        })}

        {/* Round number */}
        {roundNum && (
          <span className="ml-4 text-[10px] text-gray-500 font-mono tabular-nums">
            R.{roundNum}
          </span>
        )}
      </div>

      {/* Countdown progress bar */}
      <div className="mt-1.5 max-w-2xl h-0.5 bg-gray-800 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-1000 ease-linear ${barColor}`}
          style={{ width: `${fillPct}%` }}
        />
      </div>
    </div>
  );
}
