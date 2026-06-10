import sys
import os
import numpy as np
import cv2

# capture モジュールをインポートできるようにパスを追加
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from capture.capture import is_card_back_green

def test_is_card_back_green():
    print("=== is_card_back_green テスト ===")
    crop = [0, 100, 0, 100]

    # 1. 完全な緑色画像 (H: 60, S: 255, V: 255)
    # BGR で表すと緑は (0, 255, 0)
    green_img = np.zeros((100, 100, 3), dtype=np.uint8)
    green_img[:] = (0, 180, 0) # やや暗めの緑
    res1 = is_card_back_green(green_img, crop)
    print(f"テスト1 (緑画像): 判定={res1} (期待値: True)")
    assert res1 == True, "テスト1失敗"

    # 2. 完全な白色画像 (表面のベース)
    white_img = np.zeros((100, 100, 3), dtype=np.uint8)
    white_img[:] = (255, 255, 255)
    res2 = is_card_back_green(white_img, crop)
    print(f"テスト2 (白画像): 判定={res2} (期待値: False)")
    assert res2 == False, "テスト2失敗"

    # 3. 完全な黒色画像 (検出失敗領域など)
    black_img = np.zeros((100, 100, 3), dtype=np.uint8)
    res3 = is_card_back_green(black_img, crop)
    print(f"テスト3 (黒画像): 判定={res3} (期待値: False)")
    assert res3 == False, "テスト3失敗"

    # 4. 実像ファイルが存在すればそれをテスト
    raw_screen_path = os.path.join(os.path.dirname(__file__), "../raw_screen.png")
    if os.path.exists(raw_screen_path):
        img = cv2.imread(raw_screen_path)
        real_crop = [743, 805, 303, 337]
        res4 = is_card_back_green(img, real_crop)
        print(f"テスト4 (raw_screen.png {real_crop}): 判定={res4} (表面を想定)")
        # raw_screen.png はおそらくカードが開いている画像
    
    crop_card_path = os.path.join(os.path.dirname(__file__), "../crop_open_card.png")
    if os.path.exists(crop_card_path):
        img_card = cv2.imread(crop_card_path)
        # crop_open_card.png は既に切り抜かれた画像なので crop 全体を指定
        card_crop = [0, img_card.shape[0], 0, img_card.shape[1]]
        res5 = is_card_back_green(img_card, card_crop)
        print(f"テスト5 (crop_open_card.png 全体): 判定={res5} (表面を想定)")

    print("全てのテストが正常に通過しました！")

if __name__ == "__main__":
    test_is_card_back_green()
