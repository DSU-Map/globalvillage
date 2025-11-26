import json
import os
from global_menu_reader import fetch_current_menu_from_web

def save_global_menu():
    # 1) 웹에서 최신 식단 데이터 가져오기
    new_data = fetch_current_menu_from_web()

    # 2) 기존 JSON이 있으면 비교
    if os.path.exists("global_menu.json"):
        try:
            with open("global_menu.json", "r", encoding="utf-8") as f:
                old_data = json.load(f)
        except Exception:
            # 깨져 있거나 형식이 이상하면 그냥 새로 만듦
            old_data = None

        if old_data == new_data:
            print("변화 없음 → global_menu.json 그대로 유지")
            return  # 파일 안 건드림

    # 3) 변경 있음 또는 파일 없음 → 새로 저장
    with open("global_menu.json", "w", encoding="utf-8") as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)

    print("변화 감지 → global_menu.json 업데이트 완료")

if __name__ == "__main__":
    save_global_menu()
