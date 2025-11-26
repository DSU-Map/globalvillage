import json
import os
import datetime
from global_menu_reader import fetch_current_menu_from_web

STATE_FILE = "menu_update_state.json"
MENU_FILE = "global_menu.json"


def get_kst_now() -> datetime.datetime:
    """GitHub Actions는 UTC 기준이라, KST(+9)로 보정."""
    return datetime.datetime.utcnow() + datetime.timedelta(hours=9)


def is_kst_saturday() -> bool:
    # 월=0, 화=1, ..., 토=5, 일=6
    return get_kst_now().weekday() == 5


def load_state() -> dict:
    """menu_update_state.json에서 상태 읽기. 없거나 깨졌으면 stable=True 기본."""
    if not os.path.exists(STATE_FILE):
        return {"stable": True}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"stable": True}
        return {"stable": bool(data.get("stable", True))}
    except Exception:
        return {"stable": True}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def update_global_menu() -> bool:
    """
    최신 식단을 웹에서 가져와서 기존 JSON과 비교.
    - 변경 없음: 파일 수정 안 함, False 반환
    - 변경 있음: 파일 덮어쓰기, True 반환
    """
    new_data = fetch_current_menu_from_web()

    old_data = None
    if os.path.exists(MENU_FILE):
        try:
            with open(MENU_FILE, "r", encoding="utf-8") as f:
                old_data = json.load(f)
        except Exception:
            old_data = None

    if old_data == new_data:
        print("변화 없음 → global_menu.json 그대로 유지")
        return False

    with open(MENU_FILE, "w", encoding="utf-8") as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)

    print("변화 감지 → global_menu.json 업데이트 완료")
    return True


def main():
    state = load_state()
    stable = state["stable"]
    is_sat = is_kst_saturday()

    # 1) stable 모드(주 1회 모드)인데 토요일이 아니면 그냥 스킵
    if stable and not is_sat:
        print("stable 모드 & 토요일 아님 → 오늘은 스킵")
        return

    # 2) 실제로 메뉴 업데이트 시도
    changed = update_global_menu()

    # 3) 모드 전환 로직
    if stable:
        # 토요일에만 여기까지 들어옴
        if not changed:
            # 토요일인데도 변화 없음 → 매일 모드로 전환
            state["stable"] = False
            save_state(state)
            print("변화 없음 → 매일 새벽 4시 모드로 전환")
        else:
            print("변화 감지 → 계속 토요일 전용 모드 유지")
    else:
        # 매일 모드
        if changed:
            # 매일 체크하던 중 변화 발견 → 다시 토요일 모드로
            state["stable"] = True
            save_state(state)
            print("변화 감지 → 다시 토요일 전용 모드로 복귀")
        else:
            print("매일 모드 & 아직 변화 없음 → 내일 다시 시도")


if __name__ == "__main__":
    main()
