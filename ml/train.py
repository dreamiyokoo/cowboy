#!/usr/bin/env python3
"""
train.py — LightGBM / ロジスティック回帰 学習スクリプト

使い方:
    python ml/train.py --model lgbm      # LightGBM
    python ml/train.py --model logistic  # ロジスティック回帰
    python ml/train.py --eval            # 学習せず精度評価のみ

出力:
    capture/model.pkl         学習済みモデル
    ml/feature_names.json     特徴量名リスト
    ml/train_report.json      評価レポート
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
from datetime import datetime
from pathlib import Path

import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from features import FEATURE_NAMES, RESULT_TO_INT, build_features, features_to_row

ROOT = Path(__file__).parent.parent
ML_DIR = Path(__file__).parent
MODEL_OUT = ROOT / "capture" / "model.pkl"
FEATURE_NAMES_OUT = ML_DIR / "feature_names.json"
REPORT_OUT = ML_DIR / "train_report.json"

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8002")
USERNAME = os.getenv("CAPTURE_USERNAME", os.getenv("SEED_USERNAME", "admin"))
PASSWORD = os.getenv("CAPTURE_PASSWORD", os.getenv("SEED_PASSWORD", "changeme"))


def fetch_all_games() -> list[dict]:
    print(f"[INFO] ゲーム履歴を取得中: {BASE_URL}")
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{BASE_URL}/api/v1/auth/login",
            json={"username": USERNAME, "password": PASSWORD},
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]

        games = []
        offset = 0
        limit = 1000
        while True:
            r = client.get(
                f"{BASE_URL}/api/v1/games",
                params={"limit": limit, "offset": offset},
                headers={"Authorization": f"Bearer {token}"},
            )
            r.raise_for_status()
            data = r.json()
            batch = data["games"]
            games.extend(batch)
            if len(games) >= data["total"] or len(batch) < limit:
                break
            offset += limit

    valid = [g for g in games if g.get("result") in RESULT_TO_INT]
    print(f"[INFO] 取得: 全{len(games)}件 / 有効{len(valid)}件")
    return valid


def build_dataset(games: list[dict]) -> tuple[list[list[float]], list[int]]:
    """時系列順（古い→新しい）でソートし、特徴量行列とラベルを構築する"""
    sorted_games = sorted(games, key=lambda g: g.get("recorded_at", ""))
    X, y = [], []
    for i, game in enumerate(sorted_games):
        recent = list(reversed(sorted_games[max(0, i - 50):i]))
        recorded_at = game.get("recorded_at", "")
        try:
            now = datetime.fromisoformat(recorded_at)
        except Exception:
            now = datetime.now()
        feats = build_features(
            game.get("open_card") or "",
            recent,
            game.get("jackpot_stock"),
            now,
            current_bets={
                "cowboy": game.get("bet_cowboy"),
                "bull":   game.get("bet_bull"),
            },
        )
        X.append(features_to_row(feats))
        y.append(RESULT_TO_INT[game["result"]])
    return X, y


def train_lgbm(X_train, y_train, X_val=None, y_val=None):
    try:
        import lightgbm as lgb
    except ImportError:
        print("[ERROR] lightgbm がインストールされていません: pip install lightgbm")
        sys.exit(1)

    params = {
        "objective": "multiclass",
        "num_class": 3,
        "metric": "multi_logloss",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "n_estimators": 200,
        "random_state": 42,
        "verbose": -1,
    }
    model = lgb.LGBMClassifier(**params)
    eval_set = [(X_val, y_val)] if X_val is not None else None
    model.fit(
        X_train, y_train,
        eval_set=eval_set,
        callbacks=[lgb.early_stopping(20, verbose=False), lgb.log_evaluation(period=-1)]
        if eval_set else None,
        feature_name=FEATURE_NAMES,
    )
    model._model_version = "lgbm_v1"
    return model


def train_logistic(X_train, y_train):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline

    model = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(
            multi_class="multinomial",
            max_iter=500,
            C=1.0,
            random_state=42,
        )),
    ])
    model.fit(X_train, y_train)
    model._model_version = "logistic_v1"
    return model


def evaluate(model, X, y) -> dict:
    from sklearn.metrics import accuracy_score, log_loss, confusion_matrix

    proba = model.predict_proba(X)
    preds = proba.argmax(axis=1)
    acc = accuracy_score(y, preds)
    ll = log_loss(y, proba)
    cm = confusion_matrix(y, preds, labels=[0, 1, 2]).tolist()

    # 期待ROI: argmax(P) で賭けた場合の収支（均一賭け額と仮定）
    result_names = ["cowboy", "draw", "bull"]
    correct = sum(1 for p, t in zip(preds, y) if p == t)
    total = len(y)

    return {
        "accuracy": round(acc, 4),
        "log_loss": round(ll, 4),
        "correct": correct,
        "total": total,
        "confusion_matrix": cm,
        "class_names": result_names,
    }


def cross_validate(X, y, model_type: str, n_splits: int = 5) -> dict:
    from sklearn.model_selection import TimeSeriesSplit

    tscv = TimeSeriesSplit(n_splits=n_splits)
    accs, lls = [], []
    X_arr = np.array(X)
    y_arr = np.array(y)

    for fold, (train_idx, val_idx) in enumerate(tscv.split(X_arr)):
        X_tr, X_val_fold = X_arr[train_idx], X_arr[val_idx]
        y_tr, y_val_fold = y_arr[train_idx], y_arr[val_idx]
        if model_type == "lgbm":
            m = train_lgbm(X_tr, y_tr, X_val_fold, y_val_fold)
        else:
            m = train_logistic(X_tr, y_tr)
        report = evaluate(m, X_val_fold, y_val_fold)
        accs.append(report["accuracy"])
        lls.append(report["log_loss"])
        print(f"  Fold {fold+1}: acc={report['accuracy']:.4f}  loss={report['log_loss']:.4f}")

    return {
        "cv_accuracy_mean": round(float(np.mean(accs)), 4),
        "cv_accuracy_std":  round(float(np.std(accs)), 4),
        "cv_log_loss_mean": round(float(np.mean(lls)), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="ML学習スクリプト")
    parser.add_argument("--model", choices=["lgbm", "logistic"], default="lgbm")
    parser.add_argument("--eval", action="store_true", help="学習せず既存モデルで評価のみ")
    parser.add_argument("--no-cv", action="store_true", help="交差検証をスキップ")
    args = parser.parse_args()

    games = fetch_all_games()
    if len(games) < 10:
        print(f"[ERROR] 学習データが不足しています ({len(games)}件)。最低10件必要です。")
        sys.exit(1)

    X, y = build_dataset(games)
    print(f"[INFO] データセット: {len(X)}件 / {len(FEATURE_NAMES)}特徴量")

    if args.eval:
        if not MODEL_OUT.exists():
            print(f"[ERROR] モデルファイルが見つかりません: {MODEL_OUT}")
            sys.exit(1)
        with open(MODEL_OUT, "rb") as f:
            model = pickle.load(f)
        report = evaluate(model, X, y)
        print(f"[INFO] 評価結果: accuracy={report['accuracy']}  log_loss={report['log_loss']}")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    # 交差検証
    cv_result = {}
    if not args.no_cv:
        print(f"[INFO] TimeSeriesSplit 交差検証 (5-fold) ...")
        cv_result = cross_validate(X, y, args.model)
        print(f"[INFO] CV: acc={cv_result['cv_accuracy_mean']:.4f}±{cv_result['cv_accuracy_std']:.4f}  "
              f"loss={cv_result['cv_log_loss_mean']:.4f}")

    # 全データで最終学習
    print(f"[INFO] 全データで最終学習 ({args.model}) ...")
    if args.model == "lgbm":
        model = train_lgbm(X, y)
    else:
        model = train_logistic(X, y)

    # 評価
    report = evaluate(model, X, y)
    print(f"[INFO] 学習データ評価: accuracy={report['accuracy']}  log_loss={report['log_loss']}")

    # モデル保存
    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    version = getattr(model, "_model_version", f"{args.model}_v1")
    backup = MODEL_OUT.parent / f"model_{version}.pkl"
    with open(MODEL_OUT, "wb") as f:
        pickle.dump(model, f)
    with open(backup, "wb") as f:
        pickle.dump(model, f)
    print(f"[INFO] モデル保存: {MODEL_OUT}  ({backup.name})")

    # 特徴量名保存
    with open(FEATURE_NAMES_OUT, "w") as f:
        json.dump(FEATURE_NAMES, f, indent=2, ensure_ascii=False)

    # レポート保存
    full_report = {
        "model_type": args.model,
        "model_version": version,
        "trained_at": datetime.now().isoformat(),
        "n_samples": len(X),
        "n_features": len(FEATURE_NAMES),
        **cv_result,
        **{f"train_{k}": v for k, v in report.items()},
    }
    with open(REPORT_OUT, "w") as f:
        json.dump(full_report, f, indent=2, ensure_ascii=False)
    print(f"[INFO] レポート保存: {REPORT_OUT}")
    print(json.dumps(full_report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
