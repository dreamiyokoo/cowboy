#!/usr/bin/env python3
"""
スート推定関数のユニットテスト。
実スクリーンショットからカード領域を切り取り、形状ベースのスート推定をテストする。
"""
import sys
sys.path.insert(0, "/app")

import cv2
import numpy as np
from capture import _estimate_suit_by_color, detect_open_card

def make_test_card(suit_color: str, shape: str) -> np.ndarray:
    """
    簡易的なテスト用カード画像を生成する。
    - suit_color: "red" or "black"
    - shape: "diamond" / "heart" / "spade" / "club"
    """
    h, w = 130, 80
    card = np.ones((h, w, 3), dtype=np.uint8) * 255  # 白背景

    cx, cy = w // 2, h // 2

    if shape == "diamond":
        # ひし形 (凸形)
        pts = np.array([[cx, cy-35], [cx+22, cy], [cx, cy+35], [cx-22, cy]], np.int32)
        color = (0, 0, 200)
        cv2.fillPoly(card, [pts], color)
    elif shape == "heart":
        # ハート (上ふくらみ)
        pts_top_l = []
        pts_top_r = []
        for t in np.linspace(0, np.pi, 30):
            pts_top_l.append([cx - 11 + int(-11*np.cos(t)), cy - 10 + int(-11*np.sin(t))])
            pts_top_r.append([cx + 11 + int(11*np.cos(t)), cy - 10 + int(-11*np.sin(t))])
        heart = pts_top_l + pts_top_r[::-1] + [[cx, cy + 32]]
        pts = np.array(heart, np.int32)
        color = (0, 0, 200)
        cv2.fillPoly(card, [pts], color)
    elif shape == "spade":
        # スペード (先端上+ステム)
        pts = np.array([[cx, cy-32], [cx+25, cy+8], [cx-25, cy+8]], np.int32)
        color = (30, 30, 30)
        cv2.fillPoly(card, [pts], color)
        # ステム部
        cv2.rectangle(card, (cx-6, cy+8), (cx+6, cy+25), color, -1)
    elif shape == "club":
        # クラブ (3つの円+ステム)
        color = (30, 30, 30)
        cv2.circle(card, (cx, cy-15), 15, color, -1)
        cv2.circle(card, (cx-16, cy+2), 13, color, -1)
        cv2.circle(card, (cx+16, cy+2), 13, color, -1)
        cv2.rectangle(card, (cx-6, cy+8), (cx+6, cy+28), color, -1)

    return card


def test_with_screenshots():
    """実際のスクリーンショットで各カードの形状推定をテスト"""
    img_path = "/app/raw_screen.png"
    img = cv2.imread(img_path)
    if img is None:
        print(f"[ERROR] {img_path} が見つかりません")
        return

    print("[INFO] 現在のスクリーンショットでのオープンカード検出テスト")
    current_crop = [730, 860, 300, 380]
    y0, y1, x0, x1 = current_crop
    region = img[y0:y1, x0:x1]

    suit = _estimate_suit_by_color(region)
    print(f"  現在のクロップ ({current_crop}) → 推定スート: {suit}")

    # カード全体のdetect_open_card
    result = detect_open_card(img, current_crop, scale=4, debug=True)
    print(f"  detect_open_card 結果: {result}")


def test_synthetic_cards():
    """合成画像で各スートの識別をテスト"""
    print("\n[TEST] 合成カード画像でのスート識別テスト")
    test_cases = [
        ("diamond", "D"),
        ("heart", "H"),
        ("spade", "S"),
        ("club", "C"),
    ]
    all_pass = True
    for shape, expected in test_cases:
        card = make_test_card("red" if shape in ("diamond", "heart") else "black", shape)
        got = _estimate_suit_by_color(card)
        ok = got == expected
        status = "✓" if ok else "✗"
        print(f"  {status} {shape:8s} → expected={expected}, got={got}")
        if not ok:
            all_pass = False
            # 画像を保存してデバッグ
            cv2.imwrite(f"/tmp/test_{shape}.png", card)
    if all_pass:
        print("  → 全テストパス！")
    else:
        print("  → 一部失敗（/tmp/test_*.png を確認してください）")


if __name__ == "__main__":
    test_synthetic_cards()
    test_with_screenshots()
