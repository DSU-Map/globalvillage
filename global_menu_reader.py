# menu_reader.py

import io
import re
import datetime
from urllib.parse import urljoin, urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup
import pdfplumber

BASE_URL = "https://uni.dongseo.ac.kr"
MEAL_POST_URL = "https://uni.dongseo.ac.kr/dormitory/index.php?pCode=MN5000024"


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

    # 1) embed
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

    # 2) iframe
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

    # 3) a 태그
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


def parse_menu_text(raw_text: str) -> dict:
    """
    PDF 전체 텍스트를 파싱해서

    {
      "origin": "<원산지 전체 문자열>",
      "menus": {
        "YYYY-MM-DD": {
          "weekday": "월",
          "lunch": [...],   # 중식 메뉴 리스트
          "dinner": [...]   # 석식 메뉴 리스트
        },
        ...
      }
    }

    형태로 반환.
    """

    lines = [line.strip() for line in raw_text.splitlines()]
    lines = [line for line in lines if line]

    # 1) 날짜 라인 찾기
    date_line = None
    for line in lines:
        if "월" in line and "일" in line:
            date_line = line
            break

    # 2) 요일 라인 (날짜 다음 줄)
    weekday_line = None
    if date_line:
        idx = lines.index(date_line)
        if idx + 1 < len(lines):
            weekday_line = lines[idx + 1]

    # 3) 날짜 파싱 -> YYYY-MM-DD
    date_pattern = re.compile(r"(?P<month>\d{1,2})\s*월\s*(?P<day>\d{1,2})\s*일")
    date_pairs = date_pattern.findall(date_line or "")

    this_year = datetime.date.today().year
    date_keys: list[str] = []
    for (mm, dd) in date_pairs:
        mm_i = int(mm)
        dd_i = int(dd)
        try:
            d = datetime.date(this_year, mm_i, dd_i)
            date_keys.append(d.strftime("%Y-%m-%d"))
        except ValueError:
            pass

    # 4) 요일 파싱
    weekdays: list[str] = []
    if weekday_line:
        weekdays = weekday_line.split()

    # 5) 메뉴 본문 시작 인덱스
    if date_line and weekday_line:
        start_idx = lines.index(weekday_line) + 1
    elif date_line:
        start_idx = lines.index(date_line) + 1
    else:
        start_idx = 0

    # 6) 메뉴 본문과 원산지 분리
    menu_body_lines: list[str] = []
    origin_lines: list[str] = []
    in_origin = False

    for i in range(start_idx, len(lines)):
        line = lines[i]

        # "원산지"라는 단어가 처음 등장하는 지점부터는 전부 원산지 블록으로 취급
        if ("원산지" in line or "원 산 지" in line) and not in_origin:
            in_origin = True

        if in_origin:
            origin_lines.append(line)
        else:
            menu_body_lines.append(line)

    # 7) 중식/석식 블록 나누기 (아직은 전체 공통)
    half_point = len(menu_body_lines) // 2
    lunch_block_lines = menu_body_lines[:half_point]
    dinner_block_lines = menu_body_lines[half_point:]

    lunch_items = lunch_block_lines
    dinner_items = dinner_block_lines

    menus: dict[str, dict] = {}
    for i, dk in enumerate(date_keys):
        wd = weekdays[i] if i < len(weekdays) else ""
        menus[dk] = {
            "weekday": wd,
            "lunch": lunch_items,
            "dinner": dinner_items,
        }

    origin_text = "\n".join(origin_lines).strip()

    return {
        "origin": origin_text,  # 원산지 전체 블록 문자열
        "menus": menus          # 날짜별 중식/석식
    }


def fetch_current_menu() -> dict:
    pdf_url = find_pdf_url_from_page()
    if not pdf_url:
        raise RuntimeError("PDF URL을 찾지 못했습니다.")

    pdf_bytes = download_pdf_bytes(pdf_url)
    raw_text = extract_text_from_pdf_bytes(pdf_bytes)
    parsed = parse_menu_text(raw_text)
    return parsed


if __name__ == "__main__":
    from pprint import pprint
    data = fetch_current_menu()
    pprint(data)
