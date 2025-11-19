import io
import re
import datetime
from urllib.parse import urljoin, urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup
import pdfplumber

# 동서대 기숙사 식단표 페이지 (HTML)
BASE_URL = "https://uni.dongseo.ac.kr"
MEAL_POST_URL = "https://uni.dongseo.ac.kr/dormitory/index.php?pCode=MN5000024"


# ------------------------------------------------------------------
# 1. 페이지(HTML)에서 실제 PDF URL 찾기
# ------------------------------------------------------------------
def find_pdf_url_from_page(page_url: str = MEAL_POST_URL) -> str | None:
    resp = requests.get(page_url, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    def resolve_pdfviewer_url(url_candidate: str) -> str | None:
        """
        PDFViewer/?file=... 형태면 file 인자를 디코딩해서 실제 PDF 경로로 바꾼다.
        """
        if "PDFViewer" not in url_candidate:
            return None

        parsed = urlparse(url_candidate)
        qs = parse_qs(parsed.query)
        file_param_list = qs.get("file")
        if not file_param_list:
            return None

        encoded_path = file_param_list[0]
        decoded_path = unquote(encoded_path)  # "%2F_Data..." -> "/_Data..."

        if decoded_path.startswith("/"):
            return urljoin(BASE_URL, decoded_path)
        else:
            return urljoin(BASE_URL + "/", decoded_path)

    # 1) <embed> 태그
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

    # 2) <iframe> 태그
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

    # 3) <a href="...pdf"> 태그
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
# 3. PDF 전체 텍스트 -> 날짜별 중식/석식 + 원산지 파싱
# ------------------------------------------------------------------
def parse_menu_text(raw_text: str) -> dict:
    """
    PDF에서 추출한 전체 텍스트(raw_text)를
    날짜별 중식/석식/요일 + 원산지 정보로 파싱한다.

    반환 형식:

    {
      "origin": "<맨 아래 일괄표시 원산지 텍스트 전체>",
      "menus": {
        "YYYY-MM-DD": {
          "weekday": "월",
          "lunch": [...6개 정도 문자열...],
          "dinner": [...6개 정도 문자열...]
        },
        ...
      }
    }
    """

    lines = [line.strip() for line in raw_text.splitlines()]
    lines = [line for line in lines if line]

    # 1) 날짜 줄 찾기 (예: "11월 17일 11월 18일 ...")
    date_line = None
    for line in lines:
        if "월" in line and "일" in line:
            date_line = line
            break
    if not date_line:
        raise ValueError("날짜 줄을 찾지 못했습니다.")

    idx_date = lines.index(date_line)

    # 2) 요일 줄 찾기 (날짜 줄 아래 몇 줄 안에 "월 화 수 목 금" 형태)
    weekday_line = None
    idx_weekday = None
    for i in range(idx_date + 1, min(idx_date + 5, len(lines))):
        cand = lines[i]
        # 괄호 제거 후 요일 글자만으로 구성되었는지 간단 체크
        tmp = cand.replace("(", "").replace(")", "")
        if all(ch in "월화수목금토일 " for ch in tmp):
            weekday_line = cand
            idx_weekday = i
            break
    if weekday_line is None:
        raise ValueError("요일 줄을 찾지 못했습니다.")

    # 3) 날짜 파싱 -> YYYY-MM-DD 리스트
    date_pattern = re.compile(r"(?P<m>\d{1,2})월\s*(?P<d>\d{1,2})일")
    pairs = date_pattern.findall(date_line)
    year = datetime.date.today().year

    date_keys: list[str] = []
    for mm, dd in pairs:
        d = datetime.date(year, int(mm), int(dd))
        date_keys.append(d.strftime("%Y-%m-%d"))
    num_days = len(date_keys)

    # 4) 요일 파싱
    weekdays = weekday_line.split()

    # 5) 메뉴 줄 / 원산지 줄 분리
    menu_lines: list[str] = []
    origin_lines: list[str] = []
    in_origin = False

    skip_tokens = {"주 간 식 단 표", "구분", "중식", "석식", "원산", "지"}

    for i in range(idx_weekday + 1, len(lines)):
        line = lines[i]

        # (1) 중앙에 있는 '원산지' 헤더는 사용하지 않으므로 스킵
        if line.strip() == "원산지":
            continue

        # (2) 맨 아래 진짜 원산지 시작: '<원산지 일괄표시>' 같은 줄
        if "<원산지" in line and not in_origin:
            in_origin = True

        # (3) 원산지 모드이면 origin에 쌓기
        if in_origin:
            origin_lines.append(line)
            continue

        # (4) 메뉴 테이블에서 필요 없는 줄 제거
        if line in skip_tokens:
            continue

        # (5) 나머지는 메뉴 줄로 취급
        menu_lines.append(line)

    origin_text = "\n".join(origin_lines).strip()

    # 6) 메뉴 줄을 중식/석식으로 나누기
    # 현재 PDF 기준: 총 12줄 = 중식 6줄 + 석식 6줄
    total_rows = len(menu_lines)
    half = total_rows // 2
    lunch_rows = menu_lines[:half]
    dinner_rows = menu_lines[half:]

    # 7) 각 줄을 열 단위로 쪼개서 요일별로 배분
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
            menus[date_keys[i]]["lunch"].append(
                cols[i] if i < len(cols) else ""
            )

    # 석식
    for row in dinner_rows:
        cols = row.split()
        for i in range(num_days):
            menus[date_keys[i]]["dinner"].append(
                cols[i] if i < len(cols) else ""
            )

    return {
        "origin": origin_text,
        "menus": menus,
    }


# ------------------------------------------------------------------
# 4. 편의 함수들
# ------------------------------------------------------------------
def fetch_current_menu_from_web() -> dict:
    """
    동서대 기숙사 식단표 페이지에서 PDF를 찾아 내려받고,
    날짜별 메뉴 + 원산지 정보로 파싱해서 반환.
    """
    pdf_url = find_pdf_url_from_page()
    if not pdf_url:
        raise RuntimeError("PDF URL을 찾지 못했습니다.")

    pdf_bytes = download_pdf_bytes(pdf_url)
    raw_text = extract_text_from_pdf_bytes(pdf_bytes)
    return parse_menu_text(raw_text)


def parse_menu_from_file(path: str) -> dict:
    """
    로컬에 있는 PDF 파일 경로를 받아서,
    동일한 방식으로 파싱(테스트용).
    """
    with open(path, "rb") as f:
        pdf_bytes = f.read()
    raw_text = extract_text_from_pdf_bytes(pdf_bytes)
    return parse_menu_text(raw_text)


# ------------------------------------------------------------------
# 5. 단독 실행 테스트용
# ------------------------------------------------------------------
if __name__ == "__main__":
    # (1) 웹에서 직접 가져와서 테스트
    # data = fetch_current_menu_from_web()

    # (2) 또는 로컬 PDF 파일로 테스트
    # data = parse_menu_from_file("25년_11월_3째주_식단표.pdf")

    # 여기서는 예시로 구조만 출력
    # from pprint import pprint
    # pprint(data)
    pass
