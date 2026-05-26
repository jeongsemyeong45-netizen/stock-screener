"""
한국 주식 종가 스크리너 (네이버 금융 버전)
- 거래량 상위
- 급등 상위
- 외국인 순매수 상위
데이터 출처: 네이버 금융 (finance.naver.com)
"""

import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re

# ===== 페이지 설정 =====
st.set_page_config(
    page_title="장마감 스크리너",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    .stDataFrame { font-size: 14px; }
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    [data-testid="stMetricValue"] { font-size: 1.5rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 4px; }
    .stTabs [data-baseweb="tab"] { padding: 8px 12px; font-size: 14px; }
</style>
""", unsafe_allow_html=True)


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


def parse_number(s):
    """문자열을 숫자로"""
    if s is None:
        return 0
    s = str(s).strip().replace(",", "").replace("+", "")
    if not s or s == "-" or s == "N/A":
        return 0
    try:
        return float(s)
    except ValueError:
        return 0


@st.cache_data(ttl=1800)
def fetch_html(url):
    """페이지 HTML 받기"""
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.encoding = "euc-kr"
    return r.text


@st.cache_data(ttl=1800)
def get_trading_date():
    """최근 영업일"""
    try:
        html = fetch_html("https://finance.naver.com/sise/")
        match = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", html)
        if match:
            return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    except Exception:
        pass
    return datetime.now().strftime("%Y-%m-%d")


def _parse_naver_table(html, market_label, value_col_idx=5, value_col_name="거래량"):
    """네이버 시세 테이블 공통 파서"""
    rows = []
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", {"class": "type_2"})
    if not table:
        return rows

    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 7:
            continue
        name_tag = tds[1].find("a")
        if not name_tag:
            continue
        href = name_tag.get("href", "")
        code_match = re.search(r"code=(\d{6})", href)
        if not code_match:
            continue

        try:
            price = int(parse_number(tds[2].text))
            rate_text = tds[4].text.strip().replace("%", "")
            rate = parse_number(rate_text)
            value = int(parse_number(tds[value_col_idx].text))
        except (ValueError, IndexError):
            continue

        rows.append({
            "종목명": name_tag.text.strip(),
            "티커": code_match.group(1),
            "현재가": price,
            "등락률(%)": rate,
            value_col_name: value,
            "시장": market_label,
        })
    return rows


@st.cache_data(ttl=1800)
def scrape_volume_top(market_code, max_pages=3):
    """거래량 상위"""
    rows = []
    market_label = "KOSPI" if market_code == 0 else "KOSDAQ"
    for page in range(1, max_pages + 1):
        url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={market_code}&page={page}"
        try:
            html = fetch_html(url)
            rows.extend(_parse_naver_table(html, market_label, 5, "거래량"))
        except Exception as e:
            st.warning(f"{market_label} 거래량 페이지 {page} 실패: {e}")
    return pd.DataFrame(rows)


@st.cache_data(ttl=1800)
def scrape_rise_top(market_code, max_pages=3):
    """상승률 상위"""
    rows = []
    market_label = "KOSPI" if market_code == 0 else "KOSDAQ"
    for page in range(1, max_pages + 1):
        url = f"https://finance.naver.com/sise/sise_rise.naver?sosok={market_code}&page={page}"
        try:
            html = fetch_html(url)
            rows.extend(_parse_naver_table(html, market_label, 5, "거래량"))
        except Exception as e:
            st.warning(f"{market_label} 상승률 페이지 {page} 실패: {e}")
    return pd.DataFrame(rows)


@st.cache_data(ttl=1800)
def scrape_foreign_top(market_code, max_pages=2):
    """외국인 순매수 상위"""
    rows = []
    market_label = "KOSPI" if market_code == 0 else "KOSDAQ"
    for page in range(1, max_pages + 1):
        url = f"https://finance.naver.com/sise/sise_deal_rank.naver?sosok={market_code}&investor_gubun=9000&type=buy&page={page}"
        try:
            html = fetch_html(url)
            soup = BeautifulSoup(html, "lxml")
            tables = soup.find_all("table")
            for table in tables:
                for tr in table.find_all("tr"):
                    tds = tr.find_all("td")
                    if len(tds) < 6:
                        continue
                    name_tag = tds[1].find("a") if len(tds) > 1 else None
                    if not name_tag:
                        continue
                    href = name_tag.get("href", "")
                    code_match = re.search(r"code=(\d{6})", href)
                    if not code_match:
                        continue
                    try:
                        price = int(parse_number(tds[2].text))
                    except (ValueError, IndexError):
                        price = 0
                    rows.append({
                        "종목명": name_tag.text.strip(),
                        "티커": code_match.group(1),
                        "현재가": price,
                        "시장": market_label,
                    })
        except Exception as e:
            st.warning(f"{market_label} 외국인 페이지 {page} 실패: {e}")
    # 중복 제거
    df = pd.DataFrame(rows).drop_duplicates(subset=["티커"]).reset_index(drop=True)
    df["외국인_순위"] = df.index + 1
    return df


# ===== 메인 UI =====
st.title("📈 장마감 스크리너")
st.caption("데이터 출처: 네이버 금융 | 30분 캐시")

trading_date = get_trading_date()
st.caption(f"기준일: **{trading_date}**")

with st.expander("⚙️ 설정", expanded=False):
    col1, col2 = st.columns(2)
    with col1:
        markets = st.multiselect("시장", ["KOSPI", "KOSDAQ"], default=["KOSPI", "KOSDAQ"])
        pages_per_market = st.slider("페이지 수", 1, 5, 3, help="페이지당 약 50종목")
    with col2:
        min_price = st.number_input("최소 현재가 (원)", 0, 100000, 1000, 500)
        top_n = st.slider("표시 상위 N개", 10, 100, 30, 5)

if st.button("🔄 새로고침", type="primary"):
    st.cache_data.clear()
    st.rerun()

if not markets:
    st.warning("시장을 선택해주세요.")
    st.stop()

market_codes = [0 if m == "KOSPI" else 1 for m in markets]

# ===== 탭 =====
tab1, tab2, tab3, tab4 = st.tabs(["🔥 거래량", "🚀 급등", "💰 외국인 매수", "⭐ 교집합"])

vol_df = pd.DataFrame()
rise_df = pd.DataFrame()
for_df = pd.DataFrame()

with tab1:
    st.subheader("거래량 상위")
    with st.spinner("로딩 중..."):
        dfs = [scrape_volume_top(mc, pages_per_market) for mc in market_codes]
        vol_df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    if not vol_df.empty:
        vol_df = vol_df[vol_df["현재가"] >= min_price]
        vol_df = vol_df.sort_values("거래량", ascending=False).head(top_n)
        display = vol_df.copy()
        display["거래량(만주)"] = (display["거래량"] / 10000).round(0).astype(int)
        st.metric("종목 수", len(display))
        st.dataframe(
            display[["종목명", "티커", "시장", "현재가", "등락률(%)", "거래량(만주)"]],
            use_container_width=True, hide_index=True, height=500
        )
    else:
        st.warning("데이터 없음")

with tab2:
    st.subheader("상승률 상위")
    with st.spinner("로딩 중..."):
        dfs = [scrape_rise_top(mc, pages_per_market) for mc in market_codes]
        rise_df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    if not rise_df.empty:
        rise_df = rise_df[rise_df["현재가"] >= min_price]
        rise_df = rise_df.sort_values("등락률(%)", ascending=False).head(top_n)
        st.metric("종목 수", len(rise_df))
        st.dataframe(
            rise_df[["종목명", "티커", "시장", "현재가", "등락률(%)", "거래량"]],
            use_container_width=True, hide_index=True, height=500
        )
    else:
        st.warning("데이터 없음")

with tab3:
    st.subheader("외국인 순매수 상위")
    with st.spinner("로딩 중..."):
        dfs = [scrape_foreign_top(mc, 2) for mc in market_codes]
        for_df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    if not for_df.empty:
        for_df = for_df[for_df["현재가"] >= min_price]
        for_df = for_df.sort_values("외국인_순위").head(top_n)
        st.metric("종목 수", len(for_df))
        st.dataframe(
            for_df[["외국인_순위", "종목명", "티커", "시장", "현재가"]],
            use_container_width=True, hide_index=True, height=500
        )
    else:
        st.warning("데이터 없음. 페이지 구조가 바뀌었을 수 있음.")

with tab4:
    st.subheader("⭐ 여러 조건 만족")
    set_vol = set(vol_df["티커"]) if not vol_df.empty else set()
    set_rise = set(rise_df["티커"]) if not rise_df.empty else set()
    set_for = set(for_df["티커"]) if not for_df.empty else set()

    all_three = set_vol & set_rise & set_for
    two_of_three = ((set_vol & set_rise) | (set_vol & set_for) | (set_rise & set_for)) - all_three

    all_df = pd.concat([vol_df, rise_df, for_df], ignore_index=True).drop_duplicates(subset=["티커"])

    if all_three:
        st.success(f"🎯 세 조건 모두 만족: {len(all_three)}종목")
        target = all_df[all_df["티커"].isin(all_three)][["종목명", "티커", "시장", "현재가"]]
        st.dataframe(target, use_container_width=True, hide_index=True)
    else:
        st.info("세 조건 모두 만족하는 종목 없음 (다른 탭이 비어있으면 정상)")

    if two_of_three:
        st.markdown("---")
        def which(ticker):
            tags = []
            if ticker in set_vol: tags.append("거래량")
            if ticker in set_rise: tags.append("급등")
            if ticker in set_for: tags.append("외국인")
            return " + ".join(tags)
        st.info(f"📌 두 조건 만족: {len(two_of_three)}종목")
        target2 = all_df[all_df["티커"].isin(two_of_three)][["종목명", "티커", "시장", "현재가"]].copy()
        target2["해당조건"] = target2["티커"].apply(which)
        st.dataframe(target2, use_container_width=True, hide_index=True)


st.markdown("---")
st.caption("⚠️ 데이터: 네이버 금융. 투자 권유 아님. 본인 판단 책임.")
st.caption("💡 폰: 브라우저에서 열고 '홈 화면에 추가'")
