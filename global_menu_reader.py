import io
import re
import datetime
from urllib.parse import urljoin, urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup
import pdfplumber

# 동서대 기숙사 식단표 페이지
BASE_URL = "https://uni.dongseo.ac.kr"
MEAL_POST_URL = "https://uni.dongseo.ac.kr/dormitory/?pCode=MN5000024"


# ------------------------------------------------------------------
# 0. 공통 유틸
# ------------------------------------------------------------------
def clean_menu_item(text: str) -> str:
    """
    메뉴 항목 정리:
    - 여러 칸 공백 → 1칸으로
    - 앞/뒤 공백 제거
    - '-', '–', '—' 같은 placeholder는 빈 문자열로 취급
    """
    if text is None:
        return ""
    # 모든 공백(탭, 여러 칸 등)을 1칸으로
    t = re.sub(r"\s+", " ", text).strip()
    # placeholder 제거
    if t in ("", "-", "–", "—"):
        return ""
    return t


# ------------------------------------------------------------------
# 1. HTML 페이지에서 실제 PDF URL 찾기
# ------------------------------------------------------------------
def find_pdf_url_from_page(page_url: str = MEAL_POST_URL) -> str | None:
    resp = requests.get(page_url, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    def resolve_pdfviewer_url(url_candidate: str) -> str | None:
        if "PDFViewer" not in url_candidate:
            return None
        parsed = urlparse(url_candidate)
        qs = parse_qs(parsed.query)
        file_param_list = qs.get("file")
        if not file_param_list:
            return None
        encoded_path = file_param_list[0]
        decoded_path = unquote(encoded_path)
        if decoded_path.startswith("/"):
            return urljoin(BASE_URL, decoded_path)
        else:
            return urljoin(BASE_URL + "/", decoded_path)

    # <embed>
    embed_tag = soup.find("embed")
    if embed_tag:
        src_val = embed_tag.get("src", "")
        if src_val:
            real_pdf = resolve_pdfviewer_url(src_val)
            if real_pdf:
                return real_pdf
            m = re.search(r"(/[^\"'\s]*\.pdf[^\"'\s]*)", src_val, re.IGNORECASE)
            if m:
                src_val = m.group(1)
            if src_val.startswith("http"):
                return src_val
            elif src_val.startswith("/"):
                return urljoin(BASE_URL, src_val)
            else:
                return urljoin(BASE_URL + "/", src_val)

    # <iframe>
    iframe_tag = soup.find("iframe")
    if iframe_tag:
        src_val = iframe_tag.get("src", "")
        if src_val:
            real_pdf = resolve_pdfviewer_url(src_val)
            if real_pdf:
                return real_pdf
            m = re.search(r"(/[^\"'\s]*\.pdf[^\"'\s]*)", src_val, re.IGNORECASE)
            if m:
                src_val = m.group(1)
            if src_val.startswith("http"):
                return src_val
            elif src_val.startswith("/"):
                return urljoin(BASE_URL, src_val)
            else:
                return urljoin(BASE_URL + "/", src_val)

    # <a href="...pdf">
    for a in soup.find_all("a", href=True):
        href = a["href"]
        real_pdf = resolve_pdfviewer_url(href)
        if real_pdf:
            return real_pdf
        m = re.search(r"(/[^\"'\s]*\.pdf[^\"'\s]*)", href, re.IGNORECASE)
        if m:
            candidate = m.group(1)
            if candidate.startswith("http"):
                return candidate
            elif candidate.startswith("/"):
                return urljoin(BASE_URL, candidate)
            else:
                return urljoin(BASE_URL + "/", candidate)
    return None


# ------------------------------------------------------------------
# 2. PDF 다운로드 & 텍스트 추출
# ------------------------------------------------------------------
def download_pdf_bytes(pdf_url: str) -> bytes:
    r = requests.get(pdf_url, timeout=10)
    r.raise_for_status()
    return r.content


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    texts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            texts.append(page_text)
    return "\n".join(texts)


# ------------------------------------------------------------------
# 3. PDF 텍스트 -> 날짜별 중식/석식 + 원산지 파싱
# ------------------------------------------------------------------
def parse_menu_text(raw_text: str) -> dict:
    """
    반환 형식:
    {
      "origin": "<원산지 본문만>",
      "origin_notice": "<알레르기/안내 문구>",
      "menus": {
        "YYYY-MM-DD": {
          "weekday": "월",
          "lunch": [...],   # placeholder 제거된 메뉴 리스트
          "dinner": [...]
        },
        ...
      }
    }
    """
    lines = [line.strip() for line in raw_text.splitlines()]
    lines = [line for line in lines if line]

    # 1) 날짜 줄
    date_line = None
    for line in lines:
        if "월" in line and "일" in line:
            date_line = line
            break
    if not date_line:
        raise ValueError("날짜 줄을 찾지 못했습니다.")
    idx_date = lines.index(date_line)

    # 2) 요일 줄
    weekday_line = None
    idx_weekday = None
    for i in range(idx_date + 1, min(idx_date + 5, len(lines))):
        cand = lines[i]
        tmp = cand.replace("(", "").replace(")", "")
        if all(ch in "월화수목금토일 " for ch in tmp):
            weekday_line = cand
            idx_weekday = i
            break
    if weekday_line is None:
        raise ValueError("요일 줄을 찾지 못했습니다.")

    # 3) 날짜 리스트
    date_pattern = re.compile(r"(?P<m>\d{1,2})월\s*(?P<d>\d{1,2})일")
    pairs = date_pattern.findall(date_line)
    year = datetime.date.today().year
    date_keys: list[str] = []
    for mm, dd in pairs:
        d = datetime.date(year, int(mm), int(dd))
        date_keys.append(d.strftime("%Y-%m-%d"))
    num_days = len(date_keys)

    weekdays = weekday_line.split()

    # 4) 메뉴 줄 / 원산지 줄 분리
    menu_lines: list[str] = []
    origin_lines: list[str] = []
    in_origin = False
    skip_tokens = {"주 간 식 단 표", "구분", "중식", "석식", "원산", "지"}

    for i in range(idx_weekday + 1, len(lines)):
        line = lines[i]

        # 중앙 원산지 헤더는 무시
        if line.strip() == "원산지":
            continue

        # 맨 아래 진짜 원산지 시작
        if "<원산지" in line and not in_origin:
            in_origin = True

        if in_origin:
            origin_lines.append(line)
            continue

        if line in skip_tokens:
            continue

        menu_lines.append(line)

    # 원산지 텍스트를 본문/안내로 분리
    origin_text_raw = "\n".join(origin_lines).strip()
    origin_main_lines: list[str] = []
    origin_notice_lines: list[str] = []

    for line in origin_text_raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("*"):
            origin_notice_lines.append(stripped)
        elif stripped:
            origin_main_lines.append(stripped)

    origin_main = "\n".join(origin_main_lines).strip()
    origin_notice = "\n".join(origin_notice_lines).strip()

    # 5) 메뉴 줄을 중식/석식으로 나누기
    total_rows = len(menu_lines)
    half = total_rows // 2
    lunch_rows = menu_lines[:half]
    dinner_rows = menu_lines[half:]

    # 6) 열 단위로 요일별 메뉴 구성
    menus: dict[str, dict] = {
        dk: {
            "weekday": weekdays[i] if i < len(weekdays) else "",
            "lunch": [],
            "dinner": [],
        }
        for i, dk in enumerate(date_keys)
    }

    # 중식
    for row in lunch_rows:
        cols = row.split()
        for i in range(num_days):
            raw_item = cols[i] if i < len(cols) else ""
            item = clean_menu_item(raw_item)
            if not item:
                continue
            menus[date_keys[i]]["lunch"].append(item)

    # 석식
    for row in dinner_rows:
        cols = row.split()
        for i in range(num_days):
            raw_item = cols[i] if i < len(cols) else ""
            item = clean_menu_item(raw_item)
            if not item:
                continue
            menus[date_keys[i]]["dinner"].append(item)

    return {
        "origin": origin_main,
        "origin_notice": origin_notice,
        "menus": menus,
    }


# ------------------------------------------------------------------
# 4. 편의 함수들
# ------------------------------------------------------------------
def fetch_current_menu_from_web() -> dict:
    pdf_url = find_pdf_url_from_page()
    if not pdf_url:
        raise RuntimeError("PDF URL을 찾지 못했습니다.")
    pdf_bytes = download_pdf_bytes(pdf_url)
    raw_text = extract_text_from_pdf_bytes(pdf_bytes)
    return parse_menu_text(raw_text)


def parse_menu_from_file(path: str) -> dict:
    with open(path, "rb") as f:
        pdf_bytes = f.read()
    raw_text = extract_text_from_pdf_bytes(pdf_bytes)
    return parse_menu_text(raw_text)


if __name__ == "__main__":
    data = fetch_current_menu_from_web()
    from pprint import pprint
    pprint(data)
