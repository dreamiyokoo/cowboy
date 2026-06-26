"""
predict.py — 特徴量構築 + モデル推論モジュール

capture.py から呼ばれる。モデルファイルが存在しない場合は無音で無効化する。
"""

from __future__ import annotations

import pickle
from datetime import datetime
from pathlib import Path
from typing import Any

RANK_ORDER = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
RANK_TO_NUM = {r: i + 2 for i, r in enumerate(RANK_ORDER)}
RESULT_TO_INT = {"cowboy": 0, "draw": 1, "bull": 2}


SIDE_BET_KEYS = ["any_flash", "any_pair", "any_ace", "win_high", "win_two", "win_sf", "win_fh", "win_four"]


def load_side_bet_models(path: Path) -> dict | None:
    """サイドベットモデル辞書をロード。存在しない場合は None。"""
    try:
        path = Path(path)
        if not path.exists():
            return None
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception as e:
        print(f"[WARN] サイドベットモデルロード失敗: {e}")
        return None


def predict_side_bets(
    models: dict,
    open_card: str,
    recent_games: list[dict],
    jackpot_stock: int | None = None,
    now: datetime | None = None,
    current_bets: dict | None = None,
) -> dict:
    """
    サイドベット各種の勝利確率を返す。

    Returns:
        {"any_flash": 0.53, "any_pair": 0.10, ...}
    """
    if now is None:
        now = datetime.now()
    result: dict = {}
    try:
        features = build_features(open_card, recent_games, jackpot_stock, now, current_bets)
        feat_keys = sorted(features.keys())
        X = [[features.get(k, 0.0) for k in feat_keys]]
        for key in SIDE_BET_KEYS:
            model = models.get(key)
            if model is None:
                result[key] = None
                continue
            try:
                proba = model.predict_proba(X)[0]
                result[key] = round(float(proba[1]), 4)
            except Exception:
                result[key] = None
    except Exception as e:
        print(f"[WARN] サイドベット予測失敗: {e}")
    return result


def load_model(path: Path) -> Any | None:
    """モデルファイル（.pkl）をロードして返す。存在しない場合は None。"""
    try:
        path = Path(path)
        if not path.exists():
            return None
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception as e:
        print(f"[WARN] モデルロード失敗: {e}")
        return None


def _parse_card(card: str) -> tuple[str | None, str | None]:
    """'AH' → ('A', 'H'), '10D' → ('10', 'D')"""
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
    ml/features.py と同じロジックを保つこと（#2 参照）。
    """
    features: dict[str, float] = {}

    # ── カード特徴量 ──────────────────────────────────────────
    rank, suit = _parse_card(open_card)
    rank_num = RANK_TO_NUM.get(rank, 0) if rank else 0
    features["open_rank_num"] = float(rank_num)

    for r in RANK_ORDER:
        features[f"open_rank_{r}"] = 1.0 if rank == r else 0.0
    for s in ["S", "H", "D", "C"]:
        features[f"open_suit_{s}"] = 1.0 if suit == s else 0.0
    features["open_is_red"] = 1.0 if suit in ("H", "D") else 0.0

    # ── 時系列特徴量 ──────────────────────────────────────────
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

    # ── 時刻特徴量 ────────────────────────────────────────────
    features["hour"] = float(now.hour)
    features["dow"] = float(now.weekday())

    # ── ベット特徴量 ──────────────────────────────────────────
    for i in range(1, 4):
        g = valid[i - 1] if i - 1 < len(valid) else None
        if g:
            bc = g.get("bet_cowboy") or 0
            bb = g.get("bet_bull") or 0
            total = bc + bb
            features[f"prev_bet_c_ratio_{i}"] = bc / total if total > 0 else 0.5
        else:
            features[f"prev_bet_c_ratio_{i}"] = 0.5

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


def predict(
    model: Any,
    open_card: str,
    recent_games: list[dict],
    jackpot_stock: int | None = None,
    now: datetime | None = None,
    current_bets: dict | None = None,
) -> dict | None:
    """
    予測確率を返す。モデル未ロード時は None。

    Returns:
        {"cowboy": 0.52, "draw": 0.05, "bull": 0.43,
         "predicted": "cowboy", "model_version": "lgbm_v1"}
    """
    if model is None:
        return None
    if now is None:
        now = datetime.now()

    try:
        features = build_features(open_card, recent_games, jackpot_stock, now, current_bets)
        feature_names_attr = getattr(model, "feature_names_in_", None)
        feature_names = list(feature_names_attr) if feature_names_attr is not None else list(features.keys())
        X = [[features.get(f, 0.0) for f in feature_names]]

        proba = model.predict_proba(X)[0]
        classes = list(model.classes_) if hasattr(model, "classes_") else [0, 1, 2]

        prob_map = {RESULT_TO_INT.get(c, c): p for c, p in zip(classes, proba)}
        cowboy_p = float(prob_map.get(0, 0.0))
        draw_p   = float(prob_map.get(1, 0.0))
        bull_p   = float(prob_map.get(2, 0.0))

        predicted_idx = int(proba.argmax())
        predicted = ["cowboy", "draw", "bull"][predicted_idx] if predicted_idx < 3 else "cowboy"

        model_version = getattr(model, "_model_version", "unknown")

        return {
            "cowboy":        round(cowboy_p, 4),
            "draw":          round(draw_p,   4),
            "bull":          round(bull_p,   4),
            "predicted":     predicted,
            "model_version": model_version,
        }
    except Exception as e:
        print(f"[WARN] 予測失敗: {e}")
        return None
