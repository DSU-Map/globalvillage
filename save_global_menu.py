import json
from global_menu_reader import fetch_current_menu_from_web

def save_global_menu():
    # 1) 웹에서 최신 식단 데이터 가져오기
    data = fetch_current_menu_from_web()

    # 2) JSON 파일로 저장
    with open("global_menu.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("저장 완료: global_menu.json")

if __name__ == "__main__":
    save_global_menu()
