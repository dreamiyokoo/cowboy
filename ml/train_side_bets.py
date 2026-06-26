"""
train_side_bets.py — サイドベット予測モデルの学習

各サイドベット（FL/CN, 1ペア, Aペア, ハイ/1P, 2ペア, 3K+, FH, 4K+）について
二値分類モデルを個別に学習し capture/side_bet_models.pkl に保存する。

Usage:
    python3 ml/train_side_bets.py
"""
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import requests
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "capture"))
from predict import build_features  # noqa: E402

import os  # noqa: E402
API_BASE = os.getenv("API_BASE_URL", "http://localhost:8002")
USERNAME = os.getenv("CAPTURE_USERNAME", "admin")
PASSWORD = os.getenv("CAPTURE_PASSWORD", "changeme")

SIDE_BET_COLS = {
    "any_flash": "win_any_flash",
    "any_pair":  "win_any_pair",
    "any_ace":   "win_any_ace",
    "win_high":  "win_high",
    "win_two":   "win_two",
    "win_sf":    "win_sf",
    "win_fh":    "win_fh",
    "win_four":  "win_four",
}

SIDE_BET_ODDS = {
    "any_flash": 1.67,
    "any_pair":  8.5,
    "any_ace":   100.0,
    "win_high":  2.2,
    "win_two":   3.1,
    "win_sf":    4.7,
    "win_fh":    20.5,
    "win_four":  250.0,
}


def get_token() -> str:
    r = requests.post(f"{API_BASE}/api/v1/auth/login",
                      json={"username": USERNAME, "password": PASSWORD}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def fetch_games(token: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}"}
    all_games = []
    offset = 0
    while True:
        r = requests.get(f"{API_BASE}/api/v1/games?limit=200&offset={offset}",
                         headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        games = data.get("games", [])
        if not games:
            break
        all_games.extend(games)
        if len(all_games) >= data.get("total", 0):
            break
        offset += 200
    return all_games


def main():
    print("サイドベットモデル学習開始...")
    token = get_token()
    games = fetch_games(token)
    print(f"取得ゲーム数: {len(games)}")

    # 時系列順（古い→新しい）
    games_sorted = sorted(games, key=lambda g: g["recorded_at"])

    results: dict = {}

    for bet_key, win_col in SIDE_BET_COLS.items():
        # win_col が None でないゲームのみ
        valid = [g for g in games_sorted
                 if g.get(win_col) is not None and g.get("open_card")]

        if len(valid) < 30:
            print(f"  [{bet_key}] データ不足 ({len(valid)}件) → スキップ")
            results[bet_key] = None
            continue

        X_list = []
        y_list = []
        for i, g in enumerate(valid):
            recent = valid[max(0, i - 50):i][::-1]  # 直近50件（新しい順）
            recent_dicts = [{"result": r.get("result"), "open_card": r.get("open_card")} for r in recent]
            feat = build_features(g["open_card"], recent_dicts, g.get("jackpot_stock"), __import__("datetime").datetime.fromisoformat(g["recorded_at"]))
            X_list.append([feat.get(k, 0.0) for k in sorted(feat.keys())])
            y_list.append(1 if g[win_col] else 0)

        X = np.array(X_list)
        y = np.array(y_list)
        pos_rate = y.mean()

        model = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(
                class_weight="balanced",
                max_iter=1000,
                random_state=42,
            )),
        ])
        model.fit(X, y)
        model._feature_names = sorted(feat.keys())  # type: ignore[attr-defined]
        model._bet_key = bet_key  # type: ignore[attr-defined]

        # 簡易評価
        pred = model.predict(X)
        acc = (pred == y).mean()
        print(f"  [{bet_key}] n={len(y)}, pos_rate={pos_rate:.1%}, train_acc={acc:.1%}")

        results[bet_key] = model

    out_path = ROOT / "capture" / "side_bet_models.pkl"
    with open(out_path, "wb") as f:
        pickle.dump(results, f)
    print(f"\n保存: {out_path}")

    # feature_names も保存
    sample_feat = None
    for m in results.values():
        if m is not None:
            sample_feat = m._feature_names
            break
    if sample_feat:
        (ROOT / "ml" / "side_bet_feature_names.json").write_text(
            json.dumps(sample_feat, ensure_ascii=False, indent=2)
        )

    print("完了")


if __name__ == "__main__":
    main()
