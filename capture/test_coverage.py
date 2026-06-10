#!/usr/bin/env python3
"""
test_coverage.py — 保存されたオープンカード画像（card_shots/*.jpg）を使って、
オープンカードの検出精度（ランク A〜K、スート S/H/D/C）をカバレッジ検証する。

使い方:
    # コンテナ内で実行
    docker exec cowboy-capture-1 python3 /app/test_coverage.py

終了コード:
    0 = 全スートおよび全ランクを1回以上正しく検出できた（またはテスト成功）
    1 = 未検出のスートがある、あるいは不一致がある（テスト失敗）
"""

import argparse
import sys
from pathlib import Path
from collections import defaultdict

import cv2
import numpy as np

# capture.py と同じディレクトリにある
sys.path.insert(0, str(Path(__file__).parent))
from capture import detect_open_card

ALL_RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
ALL_SUITS = ["S", "H", "D", "C"]
SUIT_NAMES = {"S": "♠ スペード", "H": "♥ ハート", "D": "♦ ダイヤ", "C": "♣ クラブ"}

def run_coverage_test(debug: bool) -> bool:
    card_shots_dir = Path(__file__).parent / "card_shots"
    if not card_shots_dir.exists():
        card_shots_dir.mkdir(parents=True, exist_ok=True)
        print(f"[INFO] {card_shots_dir} ディレクトリを作成しました。")
        print("現在テスト用画像がありません。自動キャプチャが有効な状態でゲームが進行すると、")
        print("自動的に `capture/card_shots` 内に最新100件のオープンカード画像が保存されます。")
        print("画像が保存された後に再度このテストを実行してください。")
        return False

    image_files = sorted(card_shots_dir.glob("*.jpg"))
    if not image_files:
        print(f"現在、{card_shots_dir} 内に画像ファイル（*.jpg）が見つかりません。")
        print("自動キャプチャが有効な状態でゲームをプレイし、画像が保存された後に再度実行してください。")
        return False

    print(f"[START] 保存画像によるカバレッジテストを開始します。画像数: {len(image_files)}")
    print()

    # 追跡用
    matched_count = 0
    mismatched_count = 0
    mismatch_details = []

    detected_suits = set()
    detected_ranks = set()
    suit_examples = {}
    rank_examples = {}

    for filepath in image_files:
        # ファイル名解析: {id}_{card}.jpg (例: 123_AH.jpg)
        name = filepath.stem
        parts = name.split("_")
        if len(parts) < 2:
            print(f"  [SKIP] 不正なファイル名: {filepath.name}")
            continue

        expected_card = parts[-1]  # AH, 10D, 等
        if len(expected_card) < 2:
            print(f"  [SKIP] 不正なカード形式: {filepath.name}")
            continue

        # 画像読み込み
        img = cv2.imread(str(filepath))
        if img is None or img.size == 0:
            print(f"  [WARN] 画像の読み込み失敗: {filepath.name}")
            continue

        # detect_open_card 実行。すでに拡大済みなので scale=1
        detected_card = detect_open_card(img, crop=None, scale=1, debug=debug)

        if detected_card == expected_card:
            matched_count += 1
            # 統計更新
            suit = expected_card[-1]
            rank = expected_card[:-1]

            if suit in ALL_SUITS:
                detected_suits.add(suit)
                if suit not in suit_examples:
                    suit_examples[suit] = filepath.name
            if rank in ALL_RANKS:
                detected_ranks.add(rank)
                if rank not in rank_examples:
                    rank_examples[rank] = filepath.name

            if debug:
                print(f"  [PASS] {filepath.name} => 検出: {detected_card} (正解: {expected_card})")
        else:
            mismatched_count += 1
            mismatch_details.append((filepath.name, expected_card, detected_card))
            print(f"  [FAIL] {filepath.name} => 検出: {detected_card} (正解: {expected_card})")

    # ────────────────────────────────────────────────
    # 結果サマリー
    # ────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("テスト結果サマリー")
    print("=" * 60)
    print(f"総テスト画像数: {len(image_files)}")
    print(f"一致 (PASS): {matched_count}")
    print(f"不一致 (FAIL): {mismatched_count}")
    print()

    if mismatch_details:
        print("── 不一致の詳細 ──────────────────────────────")
        for fname, expected, detected in mismatch_details:
            print(f"  ファイル: {fname} (正解: {expected} | 検出: {detected})")
        print()

    # スートカバレッジ
    print("── スート検出カバレッジ（PASS画像のみ） ───────────")
    missing_suits = []
    for suit in ALL_SUITS:
        ok = suit in detected_suits
        icon = "✓" if ok else "✗ MISSING"
        example = f"(ファイル: {suit_examples[suit]})" if ok else ""
        print(f"  {icon}  {SUIT_NAMES[suit]}  {example}")
        if not ok:
            missing_suits.append(suit)

    # ランクカバレッジ
    print()
    print("── ランク検出カバレッジ（PASS画像のみ） ───────────")
    missing_ranks = []
    for rank in ALL_RANKS:
        ok = rank in detected_ranks
        icon = "✓" if ok else "✗"
        example = f"(ファイル: {rank_examples[rank]})" if ok else ""
        print(f"  {icon}  {rank:>3s}  {example}")
        if not ok:
            missing_ranks.append(rank)

    # 判定
    print()
    print("=" * 60)
    if mismatched_count > 0:
        print(f"[FAIL] 検出不一致が {mismatched_count} 件発生しました。")
        return False
    elif missing_suits:
        print(f"[FAIL] 検出に成功した画像の中に未検出スートがあります: {', '.join(SUIT_NAMES[s] for s in missing_suits)}")
        return False
    else:
        print("[PASS] 全ての一致テストにパスしました！")
        if missing_ranks:
            print(f"[INFO] 収集データに含まれなかったランク: {', '.join(missing_ranks)}")
        return True

def main():
    parser = argparse.ArgumentParser(description="オープンカード検出カバレッジテスト (保存画像使用)")
    parser.add_argument("--debug", action="store_true", help="デバッグ情報を表示する")
    args = parser.parse_args()

    success = run_coverage_test(debug=args.debug)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
