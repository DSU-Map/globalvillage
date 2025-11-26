import json
import os
from global_menu_reader import fetch_current_menu_from_web

def save_global_menu():
    new_data = fetch_current_menu_from_web()

    # 기존 JSON 있으면 로딩
    if os.path.exists("global_menu.json"):
        with open("global_menu.json", "r", encoding="utf-8") as f:
            old_data = json.load(f)

        # 같으면 업데이트 X
        if new_data == old_data:
            print("변화 없음 → 업데이트 생략")
            return False

    # 다르면 새로 저장
    with open("global_menu.json", "w", encoding="utf-8") as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)

    print("변화 감지 → JSON 업데이트 완료")
    return True


if __name__ == "__main__":
    save_global_menu()
