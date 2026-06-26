"""
features.py — 特徴量構築ロジック（capture/predict.py と共用）

このファイルを変更する場合は capture/predict.py の build_features も同期すること。
"""

from __future__ import annotations

from datetime import datetime

RANK_ORDER = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
RANK_TO_NUM = {r: i + 2 for i, r in enumerate(RANK_ORDER)}
RESULT_TO_INT = {"cowboy": 0, "draw": 1, "bull": 2}

FEATURE_NAMES: list[str] = (
    ["open_rank_num"]
    + [f"open_rank_{r}" for r in RANK_ORDER]
    + [f"open_suit_{s}" for s in ["S", "H", "D", "C"]]
    + ["open_is_red"]
    + [f"prev_result_{i}" for i in range(1, 4)]
    + [f"prev_rank_num_{i}" for i in range(1, 3)]
    + ["cowboy_streak", "bull_streak", "cowboy_rate_10", "bull_rate_10",
       "cowboy_rate_50", "draw_rate_50"]
    + ["hour", "dow"]
    + [f"prev_bet_c_ratio_{i}" for i in range(1, 4)]
    + ["cur_bet_c_ratio", "cur_has_bets"]
)


def _parse_card(card: str) -> tuple[str | None, str | None]:
    if not card:
        return None, None
    for rank in ["10", "A", "K", "Q", "J", "9", "8", "7", "6", "5", "4", "3", "2"]:
        if card.startswith(rank):
            suit = card[len(rank):] if len(card) > len(rank) else None
            return rank, suit
    return None, None


def build_features(
    open_card: str,
    recent_games: list[dict],
    jackpot_stock: int | None,
    now: datetime,
    current_bets: dict | None = None,
) -> dict:
    """
    特徴量辞書を構築する。recent_games は新しい順のゲーム履歴リスト。
    capture/predict.py の build_features と同一ロジック。
    """
    features: dict[str, float] = {}

    rank, suit = _parse_card(open_card)
    rank_num = RANK_TO_NUM.get(rank, 0) if rank else 0
    features["open_rank_num"] = float(rank_num)

    for r in RANK_ORDER:
        features[f"open_rank_{r}"] = 1.0 if rank == r else 0.0
    for s in ["S", "H", "D", "C"]:
        features[f"open_suit_{s}"] = 1.0 if suit == s else 0.0
    features["open_is_red"] = 1.0 if suit in ("H", "D") else 0.0

    valid = [g for g in recent_games if g.get("result") in RESULT_TO_INT]

    for i in range(1, 4):
        idx = i - 1
        if idx < len(valid):
            features[f"prev_result_{i}"] = float(RESULT_TO_INT[valid[idx]["result"]])
        else:
            features[f"prev_result_{i}"] = -1.0

    for i in range(1, 3):
        idx = i - 1
        if idx < len(valid):
            card_i = valid[idx].get("open_card", "")
            rank_i, _ = _parse_card(card_i or "")
            features[f"prev_rank_num_{i}"] = float(RANK_TO_NUM.get(rank_i, 0) if rank_i else 0)
        else:
            features[f"prev_rank_num_{i}"] = 0.0

    cowboy_streak = 0
    for g in valid:
        if g["result"] == "cowboy":
            cowboy_streak += 1
        else:
            break
    features["cowboy_streak"] = float(cowboy_streak)

    bull_streak = 0
    for g in valid:
        if g["result"] == "bull":
            bull_streak += 1
        else:
            break
    features["bull_streak"] = float(bull_streak)

    last10 = valid[:10]
    features["cowboy_rate_10"] = (
        sum(1 for g in last10 if g["result"] == "cowboy") / len(last10) if last10 else 0.5
    )
    features["bull_rate_10"] = (
        sum(1 for g in last10 if g["result"] == "bull") / len(last10) if last10 else 0.5
    )

    last50 = valid[:50]
    features["cowboy_rate_50"] = (
        sum(1 for g in last50 if g["result"] == "cowboy") / len(last50) if last50 else 0.5
    )
    features["draw_rate_50"] = (
        sum(1 for g in last50 if g["result"] == "draw") / len(last50) if last50 else 0.5
    )

    features["hour"] = float(now.hour)
    features["dow"] = float(now.weekday())

    # ── ベット特徴量 ──────────────────────────────────────────
    # 直近3ゲームのカウボーイ賭け率（cowboy / (cowboy + bull)）
    # ハウスが多い方を負けさせる傾向があるかを学習させる
    for i in range(1, 4):
        g = valid[i - 1] if i - 1 < len(valid) else None
        if g:
            bc = g.get("bet_cowboy") or 0
            bb = g.get("bet_bull") or 0
            total = bc + bb
            features[f"prev_bet_c_ratio_{i}"] = bc / total if total > 0 else 0.5
        else:
            features[f"prev_bet_c_ratio_{i}"] = 0.5

    # 現在ゲームのベット比率（ベット確定後に再予測する際に渡される）
    if current_bets:
        bc = current_bets.get("cowboy") or 0
        bb = current_bets.get("bull") or 0
        total = bc + bb
        features["cur_bet_c_ratio"] = bc / total if total > 0 else 0.5
        features["cur_has_bets"] = 1.0
    else:
        features["cur_bet_c_ratio"] = 0.5
        features["cur_has_bets"] = 0.0

    return features


def features_to_row(features: dict) -> list[float]:
    """特徴量辞書を FEATURE_NAMES 順のリストに変換する"""
    return [features.get(name, 0.0) for name in FEATURE_NAMES]
