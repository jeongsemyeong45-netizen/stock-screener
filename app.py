"""
한국 주식 종가 스크리너
- 거래량 급증 (20일 평균 대비 N배 이상)
- 52주 신고가
- 기관/외인 순매수 상위

모바일 친화적 단일 화면 대시보드
"""

import streamlit as st
import pandas as pd
from pykrx import stock
from datetime import datetime, timedelta
import time

# ===== 페이지 설정 =====
st.set_page_config(
    page_title="장마감 스크리너",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ===== 모바일 친화 CSS =====
st.markdown("""
<style>
    /* 모바일에서 표가 더 잘 보이게 */
    .stDataFrame { font-size: 14px; }
    /* 헤더 여백 줄이기 */
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    /* 메트릭 글자 크기 */
    [data-testid="stMetricValue"] { font-size: 1.5rem; }
    /* 탭 모바일 최적화 */
    .stTabs [data-baseweb="tab-list"] { gap: 4px; }
    .stTabs [data-baseweb="tab"] { padding: 8px 12px; font-size: 14px; }
</style>
""", unsafe_allow_html=True)


# ===== 유틸 함수 =====
@st.cache_data(ttl=3600)
def get_last_trading_day():
    """실제 거래 데이터가 있는 가장 최근 영업일 반환 (공휴일/주말 자동 회피)"""
    today = datetime.now()
    # 18시 이전이면 당일 데이터가 아직 불안정하니 어제부터 탐색
    if today.hour < 18:
        today = today - timedelta(days=1)

    # 최대 10일 전까지 거슬러 올라가며 실제 데이터가 있는 날 찾기
    for _ in range(10):
        # 주말은 즉시 스킵
        while today.weekday() >= 5:
            today = today - timedelta(days=1)

        date_str = today.strftime("%Y%m%d")
        try:
            # KOSPI에서 삼성전자(005930) 데이터로 영업일 여부 확인 (가장 가볍게)
            df = stock.get_market_ohlcv(date_str, date_str, "005930")
            if not df.empty and df["종가"].iloc[0] > 0:
                return date_str
        except Exception:
            pass

        today = today - timedelta(days=1)

    # 10일 내 영업일을 못 찾으면 (있을 리 없지만) 그냥 어제 반환
    return (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")


@st.cache_data(ttl=3600)  # 1시간 캐시
def load_market_ohlcv(date, market):
    """전 종목 OHLCV (재시도 + 에러 핸들링)"""
    import time as _time
    last_error = None
    for attempt in range(3):
        try:
            df = stock.get_market_ohlcv(date, market=market)
            if df is None or df.empty:
                last_error = f"{market} 데이터가 비어있음 (date={date})"
                _time.sleep(1)
                continue
            df = df.reset_index()
            df["시장"] = market
            return df
        except Exception as e:
            last_error = f"{market} 로딩 실패: {type(e).__name__}: {e}"
            _time.sleep(2)
    # 3번 모두 실패
    st.error(f"❌ {last_error}")
    st.info(f"날짜 {date}의 {market} 데이터를 받을 수 없음. KRX 서버 일시 장애 가능. 잠시 후 🔄 새로고침 또는 사이드바에서 시장을 하나만 선택해보세요.")
    st.stop()


@st.cache_data(ttl=3600)
def load_market_cap(date, market):
    """시가총액"""
    df = stock.get_market_cap(date, market=market)
    return df.reset_index()


@st.cache_data(ttl=3600)
def load_ticker_names(date, market):
    """종목명 매핑"""
    tickers = stock.get_market_ticker_list(date, market=market)
    return {t: stock.get_market_ticker_name(t) for t in tickers}


@st.cache_data(ttl=3600)
def load_investor_value(date, market):
    """투자자별 순매수 (금액 기준)"""
    df = stock.get_market_trading_value_by_ticker(date, market=market)
    return df.reset_index()


@st.cache_data(ttl=3600)
def calc_volume_ratio(date, market, days=20):
    """20일 평균 거래량 대비 당일 거래량 비율"""
    end = datetime.strptime(date, "%Y%m%d")
    start = (end - timedelta(days=days * 2 + 10)).strftime("%Y%m%d")

    tickers = stock.get_market_ticker_list(date, market=market)
    results = []

    progress = st.progress(0, text=f"{market} 거래량 분석 중...")
    for i, ticker in enumerate(tickers):
        try:
            df = stock.get_market_ohlcv(start, date, ticker)
            if len(df) < days + 1:
                continue
            today_vol = df["거래량"].iloc[-1]
            avg_vol = df["거래량"].iloc[-(days + 1):-1].mean()
            if avg_vol == 0:
                continue
            ratio = today_vol / avg_vol
            results.append({
                "티커": ticker,
                "당일거래량": today_vol,
                "20일평균": int(avg_vol),
                "배수": round(ratio, 1),
            })
        except Exception:
            continue
        if i % 50 == 0:
            progress.progress(i / len(tickers), text=f"{market} 거래량 분석 중... {i}/{len(tickers)}")
    progress.empty()

    return pd.DataFrame(results)


@st.cache_data(ttl=3600)
def calc_52week_high(date, market):
    """52주 신고가 종목 (당일 고가가 52주 최고가와 같거나 갱신)"""
    end = datetime.strptime(date, "%Y%m%d")
    start = (end - timedelta(days=400)).strftime("%Y%m%d")

    tickers = stock.get_market_ticker_list(date, market=market)
    results = []

    progress = st.progress(0, text=f"{market} 52주 신고가 분석 중...")
    for i, ticker in enumerate(tickers):
        try:
            df = stock.get_market_ohlcv(start, date, ticker)
            if len(df) < 60:
                continue
            today_high = df["고가"].iloc[-1]
            today_close = df["종가"].iloc[-1]
            year_high = df["고가"].iloc[-252:].max() if len(df) >= 252 else df["고가"].max()
            if today_high >= year_high:
                results.append({
                    "티커": ticker,
                    "종가": today_close,
                    "당일고가": today_high,
                    "52주최고": int(year_high),
                })
        except Exception:
            continue
        if i % 50 == 0:
            progress.progress(i / len(tickers), text=f"{market} 신고가 분석 중... {i}/{len(tickers)}")
    progress.empty()

    return pd.DataFrame(results)


def filter_excluded(df, ticker_col="티커"):
    """우선주, 스팩 등 제외 (간단 필터)"""
    if df.empty:
        return df
    # 종목명에 '우', '스팩'이 포함된 것 제외 (완벽하진 않지만 대부분 잡힘)
    mask = ~df["종목명"].str.contains(r"우$|우B$|스팩|리츠", regex=True, na=False)
    return df[mask]


# ===== 메인 =====
st.title("📈 장마감 스크리너")
date = get_last_trading_day()
date_display = datetime.strptime(date, "%Y%m%d").strftime("%Y-%m-%d")
st.caption(f"기준일: **{date_display}** (장 마감 후 18시 이후 데이터 안정)")

# 설정
with st.expander("⚙️ 필터 설정", expanded=False):
    col1, col2 = st.columns(2)
    with col1:
        vol_multiplier = st.slider("거래량 배수 (당일 / 20일평균)", 2.0, 10.0, 5.0, 0.5)
        top_n_investor = st.slider("기관/외인 상위 N개", 10, 50, 30, 5)
    with col2:
        min_market_cap = st.number_input("최소 시가총액 (억원)", 0, 100000, 500, 100)
        markets = st.multiselect("시장", ["KOSPI", "KOSDAQ"], default=["KOSPI", "KOSDAQ"])

    apply_intersection = st.checkbox("✨ 세 조건 모두 만족하는 종목 하이라이트", value=True)

if st.button("🔄 데이터 새로고침", type="primary"):
    st.cache_data.clear()
    st.rerun()

if not markets:
    st.warning("시장을 1개 이상 선택해줘.")
    st.stop()

# 데이터 로드
with st.spinner("기본 데이터 로딩 중..."):
    ohlcv_list, cap_list, investor_list, name_map = [], [], [], {}
    for m in markets:
        ohlcv_list.append(load_market_ohlcv(date, m))
        cap_list.append(load_market_cap(date, m))
        investor_list.append(load_investor_value(date, m))
        name_map.update(load_ticker_names(date, m))

    ohlcv = pd.concat(ohlcv_list, ignore_index=True)
    ohlcv["종목명"] = ohlcv["티커"].map(name_map)
    cap = pd.concat(cap_list, ignore_index=True)
    cap["종목명"] = cap["티커"].map(name_map)
    investor = pd.concat(investor_list, ignore_index=True)
    investor["종목명"] = investor["티커"].map(name_map)

# 시가총액 필터링용 티커 집합
valid_tickers = set(cap[cap["시가총액"] >= min_market_cap * 1e8]["티커"])


# ===== 탭 구성 =====
tab1, tab2, tab3, tab4 = st.tabs(["🔥 거래량 급증", "🚀 52주 신고가", "💰 기관/외인 매수", "⭐ 교집합"])

# --- 거래량 급증 ---
with tab1:
    st.subheader(f"거래량 {vol_multiplier}배 이상 급증")
    vol_dfs = []
    for m in markets:
        vol_dfs.append(calc_volume_ratio(date, m))
    vol_df = pd.concat(vol_dfs, ignore_index=True)
    vol_df["종목명"] = vol_df["티커"].map(name_map)
    vol_df = vol_df[vol_df["배수"] >= vol_multiplier]
    vol_df = vol_df[vol_df["티커"].isin(valid_tickers)]
    vol_df = filter_excluded(vol_df)
    vol_df = vol_df.merge(ohlcv[["티커", "종가", "등락률"]], on="티커", how="left")
    vol_df = vol_df.sort_values("배수", ascending=False)
    vol_df = vol_df[["종목명", "티커", "종가", "등락률", "당일거래량", "20일평균", "배수"]]

    st.metric("종목 수", len(vol_df))
    st.dataframe(vol_df, use_container_width=True, hide_index=True, height=500)

# --- 52주 신고가 ---
with tab2:
    st.subheader("52주 신고가 갱신 종목")
    high_dfs = []
    for m in markets:
        high_dfs.append(calc_52week_high(date, m))
    high_df = pd.concat(high_dfs, ignore_index=True)
    high_df["종목명"] = high_df["티커"].map(name_map)
    high_df = high_df[high_df["티커"].isin(valid_tickers)]
    high_df = filter_excluded(high_df)
    high_df = high_df.merge(ohlcv[["티커", "등락률"]], on="티커", how="left")
    high_df = high_df.sort_values("등락률", ascending=False)
    high_df = high_df[["종목명", "티커", "종가", "등락률", "당일고가", "52주최고"]]

    st.metric("종목 수", len(high_df))
    st.dataframe(high_df, use_container_width=True, hide_index=True, height=500)

# --- 기관/외인 매수 ---
with tab3:
    st.subheader(f"기관 + 외국인 순매수 상위 {top_n_investor}")
    inv = investor.copy()
    inv = inv[inv["티커"].isin(valid_tickers)]
    inv = filter_excluded(inv)
    inv["기관+외인"] = inv["기관합계"] + inv["외국인합계"]
    # 둘 다 양수인 종목만
    inv = inv[(inv["기관합계"] > 0) & (inv["외국인합계"] > 0)]
    inv = inv.sort_values("기관+외인", ascending=False).head(top_n_investor)
    inv = inv.merge(ohlcv[["티커", "종가", "등락률"]], on="티커", how="left")

    # 단위 변환 (원 -> 억원)
    for col in ["기관합계", "외국인합계", "기관+외인"]:
        inv[col] = (inv[col] / 1e8).round(1)

    inv = inv[["종목명", "티커", "종가", "등락률", "기관합계", "외국인합계", "기관+외인"]]
    inv.columns = ["종목명", "티커", "종가", "등락률", "기관(억)", "외인(억)", "합계(억)"]

    st.metric("종목 수", len(inv))
    st.dataframe(inv, use_container_width=True, hide_index=True, height=500)

# --- 교집합 ---
with tab4:
    st.subheader("⭐ 세 조건 모두 만족")
    st.caption("거래량 급증 + 52주 신고가 + 기관/외인 동반 매수")

    set_vol = set(vol_df["티커"])
    set_high = set(high_df["티커"])
    set_inv = set(inv["티커"])

    all_three = set_vol & set_high & set_inv
    two_of_three = (set_vol & set_high) | (set_vol & set_inv) | (set_high & set_inv)
    two_of_three = two_of_three - all_three

    if all_three:
        st.success(f"🎯 세 조건 모두 만족: {len(all_three)}종목")
        target = ohlcv[ohlcv["티커"].isin(all_three)][["종목명", "티커", "종가", "등락률", "거래량"]]
        st.dataframe(target, use_container_width=True, hide_index=True)
    else:
        st.info("세 조건을 모두 만족하는 종목 없음")

    if two_of_three:
        st.markdown("---")
        st.info(f"📌 두 조건 만족: {len(two_of_three)}종목")
        target2 = ohlcv[ohlcv["티커"].isin(two_of_three)][["종목명", "티커", "종가", "등락률", "거래량"]]
        # 각 종목이 어느 조건에 해당하는지 표시
        def which_conditions(ticker):
            tags = []
            if ticker in set_vol: tags.append("거래량")
            if ticker in set_high: tags.append("신고가")
            if ticker in set_inv: tags.append("수급")
            return " + ".join(tags)
        target2["해당조건"] = target2["티커"].apply(which_conditions)
        st.dataframe(target2, use_container_width=True, hide_index=True)


# ===== 푸터 =====
st.markdown("---")
st.caption("⚠️ 데이터: pykrx (KRX 기반). 투자 권유 아님. 본인 판단 책임.")
st.caption("💡 폰에서 쓰는 법: 브라우저에서 이 페이지 열고 '홈 화면에 추가'")
