# -*- coding: utf-8 -*-
"""
기업 재무분석 대시보드 서버
- Flask 기반 웹 서버
- DART Open API를 통한 분기별 재무데이터 수집
- 종목 검색, 기간 설정, 연결/개별 전환, 연환산/연간/분기 전환
- 차트 모듈: app_실적차트.py, app_매출이익지수.py
"""

from flask import Flask, jsonify, request, render_template_string, make_response, send_file
import OpenDartReader
import pandas as pd
from datetime import datetime
import time
import json
import os
import re
import requests as http_requests
import warnings
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils import (
    CACHE_DIR, get_cache, set_cache, QUARTER_CODES,
    resolve_stock_code, apply_restatement, crawl_wisereport, format_excel,
)

# 차트 모듈 import
from app_실적차트 import get_실적차트_html, get_실적차트_js
from app_매출이익지수 import get_매출이익지수_html, get_매출이익지수_js
from app_10년데이타 import get_10년데이타_html, get_10년데이타_js
from app_기업개요 import get_기업개요_html, get_기업개요_js
from app_실적그래프_차트 import get_실적그래프_차트_js
from backend_finstate import fetch_full_finstate_data
from app_순운전자본 import get_순운전자본_html, get_순운전자본_js
from backend_nwc import (
    find_excel_files, load_excel_results, get_results_data,
    start_screening_thread, stop_screening, screening_status,
    generate_excel_download, nwc_results
)
from app_종목쇼핑 import get_종목쇼핑_html, get_종목쇼핑_js
from backend_shopping import (
    start_shopping_thread, stop_shopping, shopping_status,
    get_shopping_data, generate_shopping_excel
)
warnings.filterwarnings('ignore')

# =============================================
DART_API_KEY = '994d8176c72277fd0f195cc374cd2beab2670ba2'
ADMIN_KEY = '026131'
# =============================================

app = Flask(__name__)
dart = OpenDartReader(DART_API_KEY)

# 상장사 목록 캐시 (코스피/코스닥만)
_listed_companies = None

# 결산월 캐시 (stock_code → acc_mt)
_acc_mt_cache = {}

# DART finstate_all 인메모리 캐시 (DART API 중복 호출 방지)
# 키: (company, year, reprt_code, fs_div) → (timestamp, DataFrame|None)
_finstate_cache = {}
_finstate_cache_lock = threading.Lock()
_FINSTATE_CACHE_TTL = 600  # 10분

def cached_finstate_all(company_name, year, reprt_code, fs_div):
    """dart.finstate_all() 래퍼 — 10분간 인메모리 캐시 (thread-safe)"""
    key = (company_name, year, reprt_code, fs_div)
    now = time.time()
    with _finstate_cache_lock:
        if key in _finstate_cache:
            ts, data = _finstate_cache[key]
            if now - ts < _FINSTATE_CACHE_TTL:
                return data
    # Lock 밖에서 API 호출 (블로킹 최소화)
    fs = dart.finstate_all(company_name, year, reprt_code=reprt_code, fs_div=fs_div)
    with _finstate_cache_lock:
        _finstate_cache[key] = (time.time(), fs)
    return fs

def get_listed_companies():
    global _listed_companies
    if _listed_companies is None:
        cc = dart.corp_codes
        _listed_companies = cc[
            cc['stock_code'].notna() &
            (cc['stock_code'] != '') &
            (cc['stock_code'].str.strip() != '')
        ].copy()
    return _listed_companies

def get_acc_mt(stock_code):
    """종목의 결산월 조회 (캐시 활용)"""
    if stock_code in _acc_mt_cache:
        return _acc_mt_cache[stock_code]
    try:
        info = dart.company(stock_code)
        if info is not None:
            acc_mt = str(info.get('acc_mt', '12') if isinstance(info, dict) else info.iloc[0].get('acc_mt', '12'))
            _acc_mt_cache[stock_code] = acc_mt
            return acc_mt
    except Exception:
        pass
    _acc_mt_cache[stock_code] = '12'
    return '12'


def fetch_naver_daily_prices(stock_code, start_year, end_year):
    """네이버 금융에서 일별 주가 데이터 조회"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    start_date = f"{start_year - 1}0101"  # 1년 전부터 (연환산 계산용)
    end_date = f"{end_year + 1}1231"

    url = (
        f'https://api.finance.naver.com/siseJson.naver'
        f'?symbol={stock_code}&requestType=1'
        f'&startTime={start_date}&endTime={end_date}&timeframe=day'
    )
    try:
        res = http_requests.get(url, headers=headers, timeout=15)
        if res.status_code != 200:
            return {}

        # 응답 파싱: JS 배열 형식 → 파이썬 리스트
        text = res.text.strip()
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        result = {}  # {(year, month, day): close_price}
        for line in lines[1:]:  # 헤더 스킵
            line = line.strip().rstrip(',')
            if not line.startswith('['):
                continue
            parts = line.strip('[]').split(',')
            if len(parts) < 5:
                continue
            date_str = parts[0].strip().strip('"\'')
            close = parts[4].strip()
            try:
                year = int(date_str[:4])
                month = int(date_str[4:6])
                day = int(date_str[6:8])
                result[(year, month, day)] = int(close)
            except (ValueError, IndexError):
                continue
        return result
    except Exception:
        return {}


# 네이버 일별주가 메모리 캐시 (5분 TTL)
_daily_price_cache = {}

def fetch_naver_daily_prices_cached(stock_code, start_year, end_year):
    """fetch_naver_daily_prices 캐시 래퍼 — 동일 종목/기간 중복 크롤링 방지"""
    key = (stock_code, start_year, end_year)
    if key in _daily_price_cache:
        ts, data = _daily_price_cache[key]
        if time.time() - ts < 300:
            return data
    data = fetch_naver_daily_prices(stock_code, start_year, end_year)
    _daily_price_cache[key] = (time.time(), data)
    return data


def fetch_naver_shares_outstanding(stock_code):
    """네이버 금융에서 상장주식수 조회"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f'https://finance.naver.com/item/main.naver?code={stock_code}'
    try:
        res = http_requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return None
        # 상장주식수 추출 (HTML 파싱)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(res.text, 'html.parser')
        # 방법1: 종목 요약정보 테이블에서
        for table in soup.find_all('table', {'summary': True}):
            for tr in table.find_all('tr'):
                th = tr.find('th')
                td = tr.find('td')
                if th and td:
                    label = th.get_text(strip=True)
                    if '상장주식수' in label:
                        val_text = td.get_text(strip=True).replace(',', '').replace('주', '')
                        try:
                            return int(val_text)
                        except ValueError:
                            pass
        # 방법2: 정규식으로 상장주식수 찾기
        match = re.search(r'상장주식수[^0-9]*?([0-9,]+)', res.text)
        if match:
            val_text = match.group(1).replace(',', '')
            try:
                return int(val_text)
            except ValueError:
                pass
        return None
    except Exception:
        return None


# DART 주식총수 메모리 캐시 (5분 TTL)
_dart_shares_cache = {}

def fetch_dart_shares(stock_code):
    """DART에서 보통주/우선주/자사주 조회 (5분 캐시)
    Returns: {'common': int, 'preferred': int, 'treasury': int, 'total': int}
    """
    if stock_code in _dart_shares_cache:
        ts, data = _dart_shares_cache[stock_code]
        if time.time() - ts < 300:
            return data

    empty = {'common': 0, 'preferred': 0, 'treasury': 0, 'total': 0}
    try:
        corp_info = dart.company(stock_code)
        corp_code_val = ''
        if isinstance(corp_info, dict):
            corp_code_val = corp_info.get('corp_code', '')
        elif corp_info is not None and len(corp_info) > 0:
            corp_code_val = corp_info.iloc[0].get('corp_code', '')

        if not corp_code_val:
            _dart_shares_cache[stock_code] = (time.time(), empty)
            return empty

        now_year = datetime.now().year
        report_attempts = [
            (now_year, '11014'), (now_year, '11012'), (now_year, '11013'),
            (now_year - 1, '11011'), (now_year - 1, '11014'), (now_year - 1, '11012'),
        ]
        for r_year, r_code in report_attempts:
            try:
                stock_df = dart.report(corp_code_val, '주식총수', r_year, r_code)
                if stock_df is not None and len(stock_df) > 0:
                    common_row = stock_df[stock_df['se'].str.contains('보통주', na=False)]
                    pref_row = stock_df[stock_df['se'].str.contains('우선주', na=False)]

                    if len(common_row) > 0:
                        row = common_row.iloc[0]
                        issued = str(row.get('istc_totqy', '')).replace(',', '').replace('-', '0').strip()
                        treasury = str(row.get('tesstk_co', '')).replace(',', '').replace('-', '0').strip()
                        if issued.isdigit() and int(issued) > 0:
                            common_num = int(issued)
                            treasury_num = int(treasury) if treasury.isdigit() else 0
                            pref_num = 0
                            if len(pref_row) > 0:
                                pref_val = str(pref_row.iloc[0].get('istc_totqy', '')).replace(',', '').replace('-', '0').strip()
                                if pref_val.isdigit():
                                    pref_num = int(pref_val)
                            result = {
                                'common': common_num,
                                'preferred': pref_num,
                                'treasury': treasury_num,
                                'total': common_num + pref_num,
                            }
                            _dart_shares_cache[stock_code] = (time.time(), result)
                            return result
                    else:
                        # 보통주 행이 없으면 합계 행 사용
                        total_row = stock_df[stock_df['se'].str.contains('합계', na=False)]
                        if len(total_row) > 0:
                            row = total_row.iloc[0]
                            issued = str(row.get('istc_totqy', '')).replace(',', '').replace('-', '0').strip()
                            treasury = str(row.get('tesstk_co', '')).replace(',', '').replace('-', '0').strip()
                            if issued.isdigit() and int(issued) > 0:
                                issued_num = int(issued)
                                treasury_num = int(treasury) if treasury.isdigit() else 0
                                result = {
                                    'common': issued_num,
                                    'preferred': 0,
                                    'treasury': treasury_num,
                                    'total': issued_num,
                                }
                                _dart_shares_cache[stock_code] = (time.time(), result)
                                return result
            except Exception:
                continue
        _dart_shares_cache[stock_code] = (time.time(), empty)
        return empty
    except Exception:
        _dart_shares_cache[stock_code] = (time.time(), empty)
        return empty


def fetch_stock_price_data(stock_code, start_year, end_year, acc_mt):
    """분기별 + 월별 주가 + 상장주식수 데이터 구성 (일별 종가 기반)

    반환 키 유형:
      - "YYYYQN"  : 이미 종료된 분기의 말일 종가 (실적 차트용)
      - "YYYY-MM" : 매월 마지막 거래일 종가 (주가 라인 차트용, 어제까지)
      - "latest"  : 가장 최근 거래일 데이터
    """
    acc_mt = int(acc_mt)
    daily_prices = fetch_naver_daily_prices_cached(stock_code, start_year, end_year)
    shares = fetch_naver_shares_outstanding(stock_code)
    dart_shares = fetch_dart_shares(stock_code)
    pref_shares = dart_shares['preferred']
    total_shares = (shares or 0) + pref_shares

    if not daily_prices:
        return {}

    from datetime import date as _date

    # 가장 최근 거래일 (어제 또는 마지막 거래일)
    latest_trade = max(daily_prices.keys())  # (year, month, day)
    latest_price = daily_prices[latest_trade]
    today = _date.today()

    result = {}

    # 1) 분기별 데이터 — 이미 끝난 분기만 (실적 차트·PER·PBR 등에서 사용)
    for year in range(start_year, end_year + 1):
        for qtr in range(1, 5):
            label = f"{year}Q{qtr}"
            end_month = ((acc_mt % 12) + qtr * 3) % 12
            if end_month == 0:
                end_month = 12
            cal_year = year - 1 if end_month > acc_mt else year

            # 분기 종료 판정: 해당 분기 말월의 마지막 날이 오늘보다 과거여야 함
            import calendar
            last_day_of_month = calendar.monthrange(cal_year, end_month)[1]
            qtr_end_date = _date(cal_year, end_month, last_day_of_month)
            if qtr_end_date >= today:
                # 이 분기는 아직 끝나지 않았으므로 스킵
                continue

            month_prices = {k: v for k, v in daily_prices.items()
                          if k[0] == cal_year and k[1] == end_month}
            if month_prices:
                last_day_key = max(month_prices.keys())
                price = month_prices[last_day_key]
            else:
                # 해당 월에 거래 데이터가 없으면 스킵
                continue

            result[label] = {
                'price': price,
                'shares': shares,
                'total_shares': total_shares,
                'preferred_shares': pref_shares,
            }

    # 2) 최근 거래일 데이터 (PBR, 시총대비 순현금 등에서 사용)
    result['latest'] = {
        'price': latest_price,
        'shares': shares,
        'total_shares': total_shares,
        'preferred_shares': pref_shares,
        'date': f"{latest_trade[0]}-{latest_trade[1]:02d}-{latest_trade[2]:02d}",
    }

    # 3) 월별 데이터 (주가 라인 차트용) — 매월 마지막 거래일 종가, 어제까지
    month_groups = {}  # (year, month) → [(year, month, day), ...]
    for ymd in sorted(daily_prices.keys()):
        mk = (ymd[0], ymd[1])
        if mk not in month_groups:
            month_groups[mk] = []
        month_groups[mk].append(ymd)

    for mk in sorted(month_groups.keys()):
        last_day = max(month_groups[mk])
        price = daily_prices[last_day]
        label = f"{mk[0]}-{mk[1]:02d}"  # "YYYY-MM"
        result[label] = {
            'price': price,
            'shares': shares,
            'total_shares': total_shares,
            'preferred_shares': pref_shares,
        }

    return result



# (캐시 함수/디렉토리는 utils.py에서 import)

# 추출 대상 항목과 검색 키워드
TARGET_ITEMS = {
    '매출액': ['매출액', '수익(매출액)', '영업수익', '매출'],
    '영업이익': ['영업이익', '영업이익(손실)'],
    '지배순이익': [
        '지배기업 소유지분',                    # 삼성전자 (손익계산서)
        '지배기업 소유주지분',                   # NAVER (포괄손익계산서)
        '지배기업의 소유주에게 귀속되는 당기순이익',
        '당기순이익',                           # fallback (개별 재무제표)
        '당기순이익(손실)',
    ],
}


# (QUARTER_CODES는 utils.py에서 import)

def parse_amount(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    val_str = str(val).replace(',', '').strip()
    if val_str == '':
        return None
    try:
        return int(val_str)
    except ValueError:
        try:
            return int(float(val_str))
        except ValueError:
            return None


def extract_controlling_income(data, column_name='thstrm_amount'):
    """지배주주 귀속 순이익을 추출 (포괄손익계산서/손익계산서에서)

    순이익 행(당기순이익/분기순이익/계속영업이익) 바로 다음 1~3행에서
    지배 귀속분을 찾는 방식으로 정확히 추출
    """
    if 'sj_nm' not in data.columns:
        return None

    income_data = data[data['sj_nm'].isin(['손익계산서', '포괄손익계산서'])].reset_index(drop=True)
    if len(income_data) == 0:
        return None

    # 순이익 행을 찾고, 다음 몇 행에서 지배 귀속분 확인
    net_income_keywords = ['당기순이익', '분기순이익', '반기순이익', '계속영업이익']
    for i in range(len(income_data)):
        acct = str(income_data.iloc[i].get('account_nm', '')).strip()
        is_net_income = any(kw in acct for kw in net_income_keywords)
        if not is_net_income:
            continue

        # 순이익 행 발견! 다음 1~3행에서 지배 귀속분 검색
        for j in range(1, min(4, len(income_data) - i)):
            next_row = income_data.iloc[i + j]
            next_acct = str(next_row.get('account_nm', '')).strip()
            if '지배' in next_acct and '비지배' not in next_acct:
                val = next_row.get(column_name, None)
                return parse_amount(val)
            # 주당이익이 나오면 지배/비지배 분리 없는 것 → 순이익 자체 반환
            if '주당' in next_acct:
                break

        # 지배 귀속분을 못 찾으면 순이익 자체 반환 (개별 재무제표 등)
        val = income_data.iloc[i].get(column_name, None)
        return parse_amount(val)

    # 순이익 행을 못 찾으면 직접 검색
    for kw in net_income_keywords:
        matched = income_data[income_data['account_nm'].str.contains(kw, na=False, regex=False)]
        if len(matched) > 0:
            val = matched.iloc[0].get(column_name, None)
            return parse_amount(val)

    return None


def extract_value(data, item_name, column_name='thstrm_amount'):
    search_terms = TARGET_ITEMS[item_name]

    # 지배순이익은 특수 로직으로 추출
    if item_name == '지배순이익':
        result = extract_controlling_income(data, column_name)
        if result is not None:
            return result
        # fallback: 일반 검색 (개별 재무제표 등)

    # 일반 검색
    for term in search_terms:
        matched = data[data['account_nm'].str.strip() == term]
        if len(matched) == 0:
            matched = data[data['account_nm'].str.contains(term, na=False, regex=False)]
        if len(matched) > 0:
            val = matched.iloc[0].get(column_name, None)
            return parse_amount(val)
    return None



# (_apply_restatement는 utils.py의 apply_restatement로 대체)

def _fetch_single_quarter(company_name, year, qtr_key, reprt_code, fs_pref):
    """단일 분기 DART 데이터 조회 (병렬 worker용)"""
    label = f"{year}{qtr_key}"
    fs_div = 'CFS' if fs_pref == 'CFS' else 'OFS'
    fallback_div = 'OFS' if fs_pref == 'CFS' else 'CFS'

    try:
        fs = cached_finstate_all(company_name, year, reprt_code=reprt_code, fs_div=fs_div)
    except Exception:
        try:
            fs = cached_finstate_all(company_name, year, reprt_code=reprt_code, fs_div=fallback_div)
            if fs is not None and len(fs) > 0:
                return (year, qtr_key, label, fs, '개별' if fs_pref == 'CFS' else '연결')
            return None
        except Exception:
            return None

    if fs is None or len(fs) == 0:
        try:
            fs = cached_finstate_all(company_name, year, reprt_code=reprt_code, fs_div=fallback_div)
            if fs is not None and len(fs) > 0:
                return (year, qtr_key, label, fs, '개별' if fs_pref == 'CFS' else '연결')
        except Exception:
            pass
        return None

    fs_type = '연결' if fs_pref == 'CFS' else '개별'
    return (year, qtr_key, label, fs, fs_type)


def fetch_quarterly_data(company_name, start_year, end_year, fs_pref='CFS'):
    """DART에서 분기별 재무 데이터 수집 (병렬)"""
    years = list(range(start_year, end_year + 1))
    raw_data = {}
    fs_type_used = {}

    # 전체 (year, qtr_key) 조합 생성
    tasks = []
    for year in years:
        for qtr_key, (reprt_code, reprt_name) in QUARTER_CODES.items():
            tasks.append((company_name, year, qtr_key, reprt_code, fs_pref))

    # ThreadPoolExecutor로 병렬 호출 (max 10 workers)
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_fetch_single_quarter, *t): t for t in tasks}
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                year, qtr_key, label, fs, fs_type = result
                raw_data[(year, qtr_key)] = fs
                fs_type_used[label] = fs_type

    apply_restatement(raw_data, years)

    # 개별 분기 데이터 계산
    quarterly_results = {}
    for year in years:
        for qtr_key in ['Q1', 'Q2', 'Q3', 'Q4']:
            label = f"{year}{qtr_key}"
            data = raw_data.get((year, qtr_key))
            if data is None:
                continue

            qtr_data = {}
            if qtr_key in ('Q1', 'Q2', 'Q3'):
                for item_name in TARGET_ITEMS:
                    qtr_data[item_name] = extract_value(data, item_name, 'thstrm_amount')
            else:
                # Q4 = 연간 - Q1~Q3 합산
                for item_name in TARGET_ITEMS:
                    annual_val = extract_value(data, item_name, 'thstrm_amount')
                    if annual_val is None:
                        qtr_data[item_name] = None
                        continue

                    # Q1+Q2+Q3 단독값 합산
                    q123_sum = 0
                    q123_count = 0
                    for q in ['Q1', 'Q2', 'Q3']:
                        qd = raw_data.get((year, q))
                        if qd is not None:
                            v = extract_value(qd, item_name, 'thstrm_amount')
                            if v is not None:
                                q123_sum += v
                                q123_count += 1

                    if q123_count >= 1:
                        # 가용 분기 데이터로 Q4 계산: 연간 - 가용합
                        # Q1 부재 시 Q4에 Q1분이 포함되나, 연환산 합산 시 연간 합계에 근사
                        qtr_data[item_name] = annual_val - q123_sum
                    else:
                        # Q1~Q3 데이터 전혀 없으면 연간값 그대로
                        qtr_data[item_name] = annual_val

            quarterly_results[label] = qtr_data

    # 억원 단위로 변환 (프론트에서 조/억 자동 결정)
    chart_data = {}
    for label in sorted(quarterly_results.keys()):
        qtr = quarterly_results[label]
        chart_data[label] = {'fs_type': fs_type_used.get(label, 'N/A')}
        for item in TARGET_ITEMS:
            val = qtr.get(item)
            chart_data[label][item] = round(val / 1e8) if val is not None else None

    return chart_data


@app.route('/api/finstate', methods=['GET'])
def get_finstate():
    """전체 재무제표 데이터 조회 (10년 데이타 탭용)"""
    company = request.args.get('company', '삼성전자').strip()
    start_year = int(request.args.get('start', 2016))
    end_year = int(request.args.get('end', datetime.now().year))
    fs_pref = request.args.get('fs', 'CFS')
    refresh = request.args.get('refresh', '0') == '1'

    cache_key = f"finstate_{company}_{start_year}_{end_year}_{fs_pref}"

    if not refresh:
        cached = get_cache(cache_key)
        if cached:
            return jsonify(cached)

    try:
        statements, fs_type_used = fetch_full_finstate_data(
            dart, company, start_year, end_year, fs_pref, parse_amount,
            finstate_fn=cached_finstate_all
        )

        # 결산월
        sc, _ = resolve_stock_code(company, get_listed_companies())
        acc_mt = get_acc_mt(sc) if sc else '12'

        response = {
            'company': company,
            'start_year': start_year,
            'end_year': end_year,
            'fs_pref': fs_pref,
            'acc_mt': acc_mt,
            'statements': statements,
            'fs_type_used': fs_type_used,
        }

        set_cache(cache_key, response)
        return jsonify(response)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/dividend', methods=['GET'])
def get_dividend():
    """배당 데이터 조회 (DART '6. 배당에 관한 사항')"""
    company = request.args.get('company', '삼성전자').strip()
    start_year = int(request.args.get('start', 2016))
    end_year = int(request.args.get('end', datetime.now().year))
    refresh = request.args.get('refresh', '0') == '1'

    stock_code, _ = resolve_stock_code(company, get_listed_companies())
    if not stock_code:
        return jsonify({'error': '종목코드를 찾을 수 없습니다.'}), 404

    cache_key = f"dividend_{stock_code}_{start_year}_{end_year}"
    if not refresh:
        cached = get_cache(cache_key)
        if cached:
            return jsonify(cached)

    def _fetch_single_dividend(stock_code, year):
        """단일 년도 배당 데이터 조회 (병렬 worker용)"""
        try:
            df = dart.report(stock_code, '배당', year, '11011')
            if df is None or len(df) == 0:
                return None

            entry = {'year': year, 'dps': None, 'payout_ratio': None, 'div_yield': None, 'par_value': None}
            common_stock = df['stock_knd'].isin(['보통주', '일반주'])

            par_rows = df[df['se'] == '주당액면가액(원)']
            if len(par_rows) > 0:
                val = par_rows.iloc[0].get('thstrm', '')
                if val and str(val).strip() not in ['', '-']:
                    try:
                        entry['par_value'] = int(str(val).replace(',', '').replace(' ', ''))
                    except (ValueError, TypeError):
                        pass

            dps_rows = df[(df['se'] == '주당 현금배당금(원)') & common_stock]
            if len(dps_rows) > 0:
                val = dps_rows.iloc[0].get('thstrm', '')
                if val and str(val).strip() not in ['', '-']:
                    try:
                        entry['dps'] = int(str(val).replace(',', '').replace(' ', ''))
                    except (ValueError, TypeError):
                        pass

            payout_rows = df[df['se'].str.contains('현금배당성향', na=False)]
            if len(payout_rows) > 0:
                val = payout_rows.iloc[0].get('thstrm', '')
                if val and str(val).strip() not in ['', '-']:
                    try:
                        entry['payout_ratio'] = round(float(str(val).replace(',', '').replace(' ', '')), 1)
                    except (ValueError, TypeError):
                        pass

            yield_rows = df[(df['se'].str.contains('현금배당수익률', na=False)) & common_stock]
            if len(yield_rows) > 0:
                val = yield_rows.iloc[0].get('thstrm', '')
                if val and str(val).strip() not in ['', '-']:
                    try:
                        entry['div_yield'] = round(float(str(val).replace(',', '').replace(' ', '')), 1)
                    except (ValueError, TypeError):
                        pass

            if any(v is not None for k, v in entry.items() if k not in ('year', 'par_value')):
                return (year, entry)
            return None
        except Exception as e:
            print(f"배당 데이터 조회 오류 ({year}): {e}")
            return None

    try:
        dividend_data = {}

        # 병렬 배당 데이터 조회 (max 10 workers)
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(_fetch_single_dividend, stock_code, y): y
                       for y in range(start_year, end_year + 1)}
            for future in as_completed(futures):
                result_item = future.result()
                if result_item is not None:
                    year, entry = result_item
                    dividend_data[str(year)] = entry

        # 액면분할 조정: 가장 최근 액면가 기준으로 과거 DPS를 조정
        if dividend_data:
            years_sorted = sorted(dividend_data.keys())
            latest_par = None
            for y in reversed(years_sorted):
                pv = dividend_data[y].get('par_value')
                if pv and pv > 0:
                    latest_par = pv
                    break

            if latest_par:
                for y in years_sorted:
                    pv = dividend_data[y].get('par_value')
                    if pv and pv > latest_par and dividend_data[y].get('dps') is not None:
                        ratio = pv / latest_par  # 예: 5000/100 = 50
                        dividend_data[y]['dps'] = round(dividend_data[y]['dps'] / ratio)

            # par_value 필드 제거 (프론트에 불필요)
            for y in dividend_data:
                dividend_data[y].pop('par_value', None)

        response = {
            'company': company,
            'stock_code': stock_code,
            'dividend': dividend_data,
        }

        set_cache(cache_key, response)
        return jsonify(response)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/overview', methods=['GET'])
def get_overview():
    """기업개요 데이터 조회 (업종, 세부업종, 매출비중)"""
    company = request.args.get('company', '삼성전자').strip()
    refresh = request.args.get('refresh', '0') == '1'

    stock_code, corp_name = resolve_stock_code(company, get_listed_companies())
    if not stock_code:
        return jsonify({'error': f'{company} 종목을 찾을 수 없습니다.'}), 404

    cache_key = f"overview_{stock_code}"
    if not refresh:
        cached = get_cache(cache_key)
        if cached:
            return jsonify(cached)

    result = {
        'company': corp_name,
        'stock_code': stock_code,
        'sector': '',
        'sub_sector': '',
        'revenue_breakdown': '',
        'revenue_details': [],
        'description': '',
        # 주가/시장
        'current_price': None,
        'price_change': None,
        'price_change_pct': None,
        'price_time': None,
        'market_cap': None,
        # 주식수 (DART)
        'shares_outstanding': None,
        'preferred_shares': None,
        'total_shares': None,
        'treasury_shares': None,
        'treasury_pct': None,
        # 투자지표 (wisereport)
        'eps': None, 'bps': None, 'per': None, 'pbr': None,
        'div_yield': None, 'dps': None, 'payout_ratio': None,
        # 52주 고/저
        'week52_high': None, 'week52_low': None,
        # 5년 지표
        'per_5y': None, 'pbr_5y': None, 'roe_5y': None,
        'eps_growth_5y': None, 'bps_growth_5y': None, 'div_yield_5y': None,
    }

    # ── 병렬 데이터 수집 (wisereport, dart_shares, finstate 동시 실행) ──
    now_year = datetime.now().year
    def _task_wisereport():
        return crawl_wisereport(stock_code)

    def _task_dart_shares():
        return fetch_dart_shares(stock_code)

    def _task_finstate():
        return fetch_full_finstate_data(dart, stock_code, now_year - 5, now_year, 'CFS', parse_amount, finstate_fn=cached_finstate_all)

    wr = None
    dart_shares_result = None
    fs_data = None

    with ThreadPoolExecutor(max_workers=3) as executor:
        f_wr = executor.submit(_task_wisereport)
        f_shares = executor.submit(_task_dart_shares)
        f_finstate = executor.submit(_task_finstate)

        try:
            wr = f_wr.result()
        except Exception as e:
            print(f"네이버 기업개요 조회 오류: {e}")
        try:
            dart_shares_result = f_shares.result()
        except Exception as e:
            print(f"DART 주식총수 조회 오류: {e}")
        try:
            fs_data = f_finstate.result()
        except Exception as e:
            print(f"EPS/BPS/PER/PBR 계산 오류: {e}")

    # 1. wisereport 결과 적용
    if wr:
        for key in ['description', 'sector', 'sub_sector', 'current_price', 'price_change',
                     'price_change_pct', 'market_cap', 'eps', 'bps', 'per', 'pbr',
                     'div_yield', 'dps', 'week52_high', 'week52_low', 'shares_outstanding']:
            if wr.get(key) is not None:
                result[key] = wr[key]

    # 1-2. 네이버 52주 고/저가 (일별 종가에서 계산 - fallback)
    if result['week52_high'] is None:
        try:
            daily = fetch_naver_daily_prices_cached(stock_code, datetime.now().year - 1, datetime.now().year)
            if daily:
                from datetime import timedelta
                today = datetime.now()
                one_year_ago = today - timedelta(days=365)
                recent_prices = [p for (y, m, d), p in daily.items()
                                 if datetime(y, m, d) >= one_year_ago]
                if recent_prices:
                    result['week52_high'] = max(recent_prices)
                    result['week52_low'] = min(recent_prices)
        except Exception as e:
            print(f"52주 고저가 조회 오류: {e}")

    # 1-3. dart_shares 결과 적용
    try:
        if dart_shares_result and dart_shares_result['common'] > 0:
            dart_shares = dart_shares_result
            result['shares_outstanding'] = dart_shares['common']
            result['preferred_shares'] = dart_shares['preferred']
            result['total_shares'] = dart_shares['total']
            result['treasury_shares'] = dart_shares['treasury']
            result['treasury_pct'] = round(dart_shares['treasury'] / dart_shares['common'] * 100, 2) if dart_shares['common'] > 0 else 0
            if result['current_price'] and result['current_price'] > 0:
                result['market_cap'] = round(result['current_price'] * dart_shares['common'] / 100000000)
    except Exception as e:
        print(f"DART 주식총수 처리 오류: {e}")

    # 1-4. EPS/BPS/PER/PBR/ROE 직접 계산 (finstate 결과 활용)
    try:
        statements = None
        if fs_data:
            statements, fs_type_used = fs_data

        total_shares_for_calc = result.get('total_shares') or result.get('shares_outstanding')
        price = result.get('current_price')

        if statements and total_shares_for_calc and total_shares_for_calc > 0:
            # ── 지배순이익(TTM) 구하기: 최근 4분기 합산 ──
            income_stmt = statements.get('손익계산서', {})
            income_accounts = income_stmt.get('accounts', [])
            income_data = income_stmt.get('data', {})

            # 지배순이익 인덱스 찾기 — "지배" 키워드로 통합 매칭
            ni_idx = None
            for i, acc in enumerate(income_accounts):
                nm = acc.get('name', '')
                if '지배' in nm and '비지배' not in nm:
                    ni_idx = i
                    break
                if acc.get('id') == 'ifrs-full_ProfitLossAttributableToOwnersOfParent':
                    ni_idx = i
                    break
            # 당기순이익 fallback
            if ni_idx is None:
                for i, acc in enumerate(income_accounts):
                    if acc.get('name', '') in ('당기순이익', '당기순이익(손실)') or acc.get('display_name') == '당기순이익':
                        ni_idx = i
                        break

            if ni_idx is not None:
                # 분기 키를 정렬해서 최근 4분기 찾기
                sorted_quarters = sorted(income_data.keys())
                recent_4q = sorted_quarters[-4:] if len(sorted_quarters) >= 4 else sorted_quarters

                ttm_ni = 0
                q_count = 0
                for qk in recent_4q:
                    vals = income_data[qk]
                    if ni_idx < len(vals) and vals[ni_idx] is not None:
                        ttm_ni += vals[ni_idx]  # 억원 단위
                        q_count += 1

                if q_count >= 4 and ttm_ni != 0:
                    # EPS = TTM 지배순이익(억원) × 1억 ÷ 주식총수(보통주+우선주)
                    result['eps'] = round(ttm_ni * 100000000 / total_shares_for_calc)
                    if price and price > 0:
                        result['per'] = round(price / result['eps'], 2) if result['eps'] > 0 else None

            # ── BPS 구하기: 최근 분기 지배기업 자본 ──
            bs_stmt = statements.get('재무상태표', {})
            bs_accounts = bs_stmt.get('accounts', [])
            bs_data = bs_stmt.get('data', {})

            equity_idx = None
            for i, acc in enumerate(bs_accounts):
                nm = acc.get('name', '')
                if '지배기업' in nm and ('소유주' in nm or '지분' in nm) and '자본' in nm:
                    equity_idx = i
                    break
                if acc.get('data_id') == 'ifrs-full_EquityAttributableToOwnersOfParent':
                    equity_idx = i
                    break
            # 자본총계 fallback
            if equity_idx is None:
                for i, acc in enumerate(bs_accounts):
                    if acc.get('data_id') == 'ifrs-full_Equity' or acc.get('name', '') == '자본총계':
                        equity_idx = i
                        break

            if equity_idx is not None:
                sorted_bs_quarters = sorted(bs_data.keys())
                if sorted_bs_quarters:
                    latest_q = sorted_bs_quarters[-1]
                    vals = bs_data[latest_q]
                    if equity_idx < len(vals) and vals[equity_idx] is not None:
                        equity_val = vals[equity_idx]  # 억원 단위
                        # BPS = 자본(억원) × 1억 ÷ 주식총수(보통주+우선주)
                        result['bps'] = round(equity_val * 100000000 / total_shares_for_calc)
                        if price and price > 0 and result['bps'] > 0:
                            result['pbr'] = round(price / result['bps'], 2)

            # ── ROE 계산 ──
            if result['eps'] and result['bps'] and result['bps'] > 0:
                result['roe'] = round(result['eps'] / result['bps'] * 100, 2)

            # ── 5년 평균 PER/PBR/ROE 계산 ──
            try:
                import re as re_mod
                yearly_eps = {}
                yearly_bps = {}

                def parse_quarter_key(qk):
                    """분기 키에서 연도와 분기 추출 (예: '2024Q1' → (2024, 'Q1'))"""
                    m = re_mod.match(r'(\d{4})(Q[1-4])?', qk)
                    if m:
                        return int(m.group(1)), m.group(2) or ''
                    return None, ''

                # 연간 EPS 계산 (Q1+Q2+Q3+Q4)
                if ni_idx is not None:
                    for qk in sorted(income_data.keys()):
                        yr, q_num = parse_quarter_key(qk)
                        if yr is None:
                            continue
                        vals = income_data[qk]
                        if ni_idx < len(vals) and vals[ni_idx] is not None:
                            yearly_eps[yr] = yearly_eps.get(yr, 0) + vals[ni_idx]

                # 연간 BPS (연말 기준 = Q4)
                if equity_idx is not None:
                    for qk in sorted(bs_data.keys()):
                        yr, q_num = parse_quarter_key(qk)
                        if yr is None:
                            continue
                        vals = bs_data[qk]
                        if equity_idx < len(vals) and vals[equity_idx] is not None:
                            if q_num == 'Q4' or q_num == '':
                                yearly_bps[yr] = vals[equity_idx]
                            else:
                                # 최신 분기로 갱신 (연말 데이터 없으면 최신 분기 사용)
                                if yr not in yearly_bps:
                                    yearly_bps[yr] = vals[equity_idx]


                # 4분기(Q1~Q4) 모두 있는 완전연도만 사용
                complete_years = []
                for y in range(now_year - 5, now_year):
                    if y in yearly_eps:
                        # 해당 연도에 4개 분기 데이터가 모두 있는지 확인
                        q_keys = [f"{y}Q{q}" for q in range(1, 5)]
                        q_count = sum(1 for k in q_keys if k in income_data)
                        if q_count == 4:
                            complete_years.append(y)


                # 연말 주가 가져오기 (5년 PER/PBR 계산용)
                yearend_prices = {}
                if complete_years:
                    price_data = fetch_naver_daily_prices_cached(stock_code, complete_years[0], complete_years[-1])
                    for yr in complete_years:
                        # 12월 마지막 거래일 종가 찾기
                        dec_prices = {(y, m, d): p for (y, m, d), p in price_data.items() if y == yr and m == 12}
                        if dec_prices:
                            last_day = max(dec_prices.keys())
                            yearend_prices[yr] = dec_prices[last_day]

                # 5년 평균 계산 (연말 주가 기준 PER/PBR)
                per_list = []
                pbr_list = []
                roe_list = []
                for yr in complete_years:
                    ni = yearly_eps[yr]
                    eps_yr = ni * 100000000 / total_shares_for_calc if total_shares_for_calc > 0 else 0
                    if yr in yearly_bps:
                        eq = yearly_bps[yr]
                        bps_yr = eq * 100000000 / total_shares_for_calc if total_shares_for_calc > 0 else 0
                    else:
                        bps_yr = 0

                    yr_price = yearend_prices.get(yr)

                    if eps_yr > 0 and bps_yr > 0:
                        roe_list.append(eps_yr / bps_yr * 100)
                    if yr_price and yr_price > 0:
                        if eps_yr > 0:
                            per_list.append(yr_price / eps_yr)
                        if bps_yr > 0:
                            pbr_list.append(yr_price / bps_yr)

                if roe_list:
                    result['roe_5y'] = round(sum(roe_list) / len(roe_list), 2)
                if per_list:
                    result['per_5y'] = round(sum(per_list) / len(per_list), 2)
                if pbr_list:
                    result['pbr_5y'] = round(sum(pbr_list) / len(pbr_list), 2)


                # EPS 성장률 (CAGR) - 완전연도 기준
                if len(complete_years) >= 2:
                    first_yr = complete_years[0]
                    last_yr = complete_years[-1]
                    n = last_yr - first_yr
                    if n > 0:
                        eps_first = yearly_eps[first_yr] * 100000000 / total_shares_for_calc if total_shares_for_calc > 0 else 0
                        eps_last = yearly_eps[last_yr] * 100000000 / total_shares_for_calc if total_shares_for_calc > 0 else 0
                        if eps_first > 0 and eps_last > 0:
                            result['eps_growth_5y'] = round(((eps_last / eps_first) ** (1 / n) - 1) * 100, 1)

                # BPS 성장률 (CAGR) - 완전연도 기준
                bps_complete_years = [y for y in complete_years if y in yearly_bps]
                if len(bps_complete_years) >= 2:
                    first_yr = bps_complete_years[0]
                    last_yr = bps_complete_years[-1]
                    n = last_yr - first_yr
                    if n > 0:
                        bps_first = yearly_bps[first_yr] * 100000000 / total_shares_for_calc if total_shares_for_calc > 0 else 0
                        bps_last = yearly_bps[last_yr] * 100000000 / total_shares_for_calc if total_shares_for_calc > 0 else 0
                        if bps_first > 0 and bps_last > 0:
                            result['bps_growth_5y'] = round(((bps_last / bps_first) ** (1 / n) - 1) * 100, 1)

            except Exception as e:
                import traceback
                print(f"5년 지표 계산 오류: {e}")
                traceback.print_exc()

    except Exception as e:
        print(f"EPS/BPS/PER/PBR 계산 오류: {e}")

    # 1-5. 배당성향 계산 (DPS는 wisereport 테이블에서 직접 가져옴)
    if result['dps'] and result['eps'] and result['eps'] > 0:
        result['payout_ratio'] = round(result['dps'] / result['eps'] * 100, 1)
    if result['div_yield'] is None and result['dps'] and result['current_price'] and result['current_price'] > 0:
        result['div_yield'] = round(result['dps'] / result['current_price'] * 100, 2)

    # ── 매출비중 파싱 헬퍼 ──
    _SKIP = {'합계', '계'}
    _SUBTOTAL_KW = {'소계', '합계', '합 계', '소 계'}
    _EXPORT_KW = {'수출', '내수', '수 출', '내 수'}
    _NON_REVENUE = {'영업이익', '총자산', '내부매출액', '당기순이익', '자산총계'}

    def _parse_amt(cell):
        s = cell.replace(',','').replace('△','-').replace('▵','-').replace(' ','').strip()
        s = re.sub(r'\([^)]*%\)', '', s)
        s = s.replace('(','-').replace(')','').strip()
        if not s or s == '-':
            return None
        try:
            return float(s)
        except (ValueError, TypeError):
            return None

    def _row_amt(row, amt_col):
        if 0 < amt_col < len(row):
            v = _parse_amt(row[amt_col])
            if v is not None:
                return v
        for cell in row[1:]:
            v = _parse_amt(cell)
            if v is not None:
                return v
        return None

    def _is_text_cell(s):
        """셀이 텍스트(부문명 등)인지 판별"""
        s = s.replace('\xa0', ' ').strip()
        if not s or s == '-':
            return False
        pure = re.sub(r'[\d,.\-()%△▵\s]', '', s)
        return bool(pure)

    # 2. DART에서 매출 비중 정보 가져오기
    try:
        from bs4 import BeautifulSoup
        reports = dart.list(stock_code, start='2024-01-01', kind='A')
        if reports is not None and len(reports) > 0:
            periodic = reports[reports['report_nm'].str.contains('사업보고서|분기보고서|반기보고서')]
            if len(periodic) > 0:
                rcept_no = periodic.iloc[0]['rcept_no']
                docs = dart.sub_docs(rcept_no)

                doc_candidates = []
                sales_doc = docs[docs['title'].str.contains('매출')]
                if len(sales_doc) > 0:
                    doc_candidates.append(sales_doc.iloc[0]['url'])
                prod_doc = docs[docs['title'].str.contains('주요 제품|주요제품')]
                if len(prod_doc) > 0:
                    url = prod_doc.iloc[0]['url']
                    if url not in doc_candidates:
                        doc_candidates.append(url)

                for doc_url in doc_candidates:
                    resp = http_requests.get(doc_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                    resp.encoding = 'utf-8'
                    doc_soup = BeautifulSoup(resp.text, 'html.parser')
                    tables = doc_soup.find_all('table')

                    for table in tables[:5]:
                        html_rows = table.find_all('tr')
                        if len(html_rows) < 3:
                            continue

                        # ── rowspan/colspan → 2D 그리드 ──
                        grid = []
                        rowspan_tracker = {}
                        for ri, tr in enumerate(html_rows):
                            cells = tr.find_all(['td', 'th'])
                            row_data = []
                            ci = 0
                            cell_idx = 0
                            while cell_idx < len(cells) or ci in rowspan_tracker:
                                if ci in rowspan_tracker:
                                    remaining, text = rowspan_tracker[ci]
                                    row_data.append(text)
                                    if remaining > 1:
                                        rowspan_tracker[ci] = (remaining - 1, text)
                                    else:
                                        del rowspan_tracker[ci]
                                    ci += 1
                                elif cell_idx < len(cells):
                                    cell = cells[cell_idx]
                                    text = cell.get_text(strip=True).replace('\xa0', ' ')
                                    rs = int(cell.get('rowspan', 1))
                                    cs = int(cell.get('colspan', 1))
                                    for c_offset in range(cs):
                                        actual_ci = ci + c_offset
                                        while actual_ci in rowspan_tracker:
                                            remaining, rtext = rowspan_tracker[actual_ci]
                                            row_data.append(rtext)
                                            if remaining > 1:
                                                rowspan_tracker[actual_ci] = (remaining - 1, rtext)
                                            else:
                                                del rowspan_tracker[actual_ci]
                                            actual_ci += 1
                                            ci += 1
                                        row_data.append(text)
                                        if rs > 1:
                                            rowspan_tracker[actual_ci] = (rs - 1, text)
                                    ci += cs
                                    cell_idx += 1
                                else:
                                    break
                            while ci in rowspan_tracker:
                                remaining, text = rowspan_tracker[ci]
                                row_data.append(text)
                                if remaining > 1:
                                    rowspan_tracker[ci] = (remaining - 1, text)
                                else:
                                    del rowspan_tracker[ci]
                                ci += 1
                            grid.append(row_data)

                        if not grid:
                            continue

                        # ── Step 1: 열 역할 감지 (1회) ──
                        header = [h.replace(' ', '') for h in grid[0]]
                        amt_col = -1
                        for ci, ht in enumerate(header):
                            if re.search(r'제\d+기|금액|매출액', ht):
                                amt_col = ci
                                break
                        if amt_col < 0 and len(grid) > 1:
                            for ci, cell in enumerate(grid[1]):
                                if _parse_amt(cell) is not None:
                                    amt_col = ci
                                    break
                        if amt_col < 0:
                            continue

                        # text_cols: 금액 열 앞의 텍스트 열들 (매출유형 열 제외)
                        _SALE_TYPE_KW = {'매출유형', '매출형태'}
                        text_cols = []
                        for ci in range(amt_col):
                            h = header[ci] if ci < len(header) else ''
                            if h in _SALE_TYPE_KW:
                                continue
                            # 데이터에서 매출유형 패턴 감지 ("제ㆍ상품", "제품", "상품" 등이 대부분인 열)
                            col_vals = [row[ci].replace('\xa0',' ').strip().replace(' ','') for row in grid[1:] if ci < len(row)]
                            sale_type_count = sum(1 for v in col_vals if v and any(kw in v for kw in ('제ㆍ상품', '제품매출', '상품매출', '용역매출')))
                            if sale_type_count > len(col_vals) * 0.5:
                                continue
                            text_cols.append(ci)

                        # 매출액/영업이익 혼합 테이블 감지
                        rev_filter_col = -1
                        for ci in text_cols:
                            vals = {row[ci].replace(' ', '') for row in grid[1:] if ci < len(row)}
                            if vals & _NON_REVENUE and '매출액' in vals:
                                rev_filter_col = ci
                                break

                        # ── Step 2: 합계(total) 찾기 ──
                        total_amt = 0
                        for row in reversed(grid[1:]):
                            if row and row[0].replace(' ', '') in _SKIP:
                                v = _row_amt(row, amt_col)
                                if v and abs(v) > total_amt:
                                    total_amt = abs(v)
                                    break
                        if total_amt <= 0:
                            for row in grid[1:]:
                                if row and row[0].replace(' ', '') in _SKIP:
                                    continue
                                if any(c.replace(' ', '') in _SUBTOTAL_KW for c in row):
                                    continue
                                v = _row_amt(row, amt_col)
                                if v is not None:
                                    total_amt += abs(v)
                        if total_amt <= 0:
                            continue

                        # ── Step 3: 1-pass 지연 확정 파서 ──
                        NOISE = _SUBTOTAL_KW | _EXPORT_KW
                        results = {}
                        result_order = []
                        current_group = ''
                        pending = {}
                        pending_order = []

                        def _flush_pending():
                            for pn in pending_order:
                                if pn not in results:
                                    results[pn] = pending[pn]
                                    result_order.append(pn)

                        for row in grid[1:]:
                            if not row or row[0].replace(' ', '') in _SKIP:
                                continue

                            # 매출액 필터 (영업이익/총자산 행 스킵)
                            if rev_filter_col >= 0 and rev_filter_col < len(row):
                                if row[rev_filter_col].replace(' ', '') != '매출액':
                                    continue

                            # 행 분류
                            is_subtotal = any(c.replace(' ', '') in _SUBTOTAL_KW for c in row)
                            is_export = any(c.replace(' ', '') in _EXPORT_KW for c in row)
                            if is_export and not is_subtotal:
                                continue

                            amt = _row_amt(row, amt_col)

                            # 텍스트 열 추출
                            texts = []
                            for ci in text_cols:
                                if ci < len(row):
                                    s = row[ci].replace('\xa0', ' ').strip()
                                    sc = s.replace(' ', '')
                                    if sc and sc not in NOISE and _is_text_cell(s):
                                        texts.append(s)
                                    else:
                                        texts.append('')
                                else:
                                    texts.append('')

                            # 소계 행에서도 그룹명 갱신 (수출/내수로만 구성된 테이블 대응)
                            # 사업부문이 '-'(빈 문자열) → 다음 비어있지 않은 텍스트를 그룹으로
                            grp_from_texts = ''
                            for t in texts:
                                if t:
                                    grp_from_texts = t
                                    break
                            if grp_from_texts and grp_from_texts != current_group:
                                if not is_subtotal:
                                    # 일반 행에서 그룹 전환 → pending flush (아래에서 처리)
                                    pass
                                else:
                                    # 소계 행에서 새 그룹 발견 → 기존 pending flush 후 그룹 갱신
                                    _flush_pending()
                                    pending = {}
                                    pending_order = []
                                    current_group = grp_from_texts

                            if is_subtotal:
                                if current_group and amt is not None:
                                    pending = {}
                                    pending_order = []
                                    if current_group not in results:
                                        results[current_group] = amt
                                        result_order.append(current_group)
                                    elif abs(amt) > abs(results[current_group]):
                                        results[current_group] = amt
                                continue

                            # 그룹명/상세명 결정: 첫 번째 비어있지 않은 텍스트를 group으로
                            group = ''
                            detail = ''
                            for ti, t in enumerate(texts):
                                if t:
                                    if not group:
                                        group = t
                                    elif not detail:
                                        detail = t
                                        break

                            if group and group != current_group:
                                _flush_pending()
                                pending = {}
                                pending_order = []
                                current_group = group

                            if amt is None:
                                continue

                            # group과 detail이 같거나 detail이 group에 포함되면 group만 사용
                            if group and detail and detail.replace(' ', '') != group.replace(' ', ''):
                                name = f"{group}-{detail}"
                            else:
                                name = group or detail or '기타'
                            if name in pending:
                                pending[name] += amt
                            else:
                                pending[name] = amt
                                pending_order.append(name)

                        # 마지막 그룹 확정
                        _flush_pending()

                        # ── Step 4: 비중 계산 ──
                        if results:
                            segments = []
                            details = []
                            for name in result_order:
                                pct = (results[name] / total_amt) * 100
                                segments.append(f"{name}: {pct:.1f}%")
                                details.append({'name': name, 'pct': f"{pct:.1f}%", 'products': ''})
                            result['revenue_breakdown'] = ', '.join(segments)
                            result['revenue_details'] = details
                            break  # 테이블 루프 탈출

                    if result.get('revenue_breakdown'):
                        break  # 문서 루프 탈출
    except Exception as e:
        print(f"DART 매출비중 조회 오류: {e}")

    set_cache(cache_key, result)
    return jsonify(result)


@app.route('/api/realtime_price', methods=['GET'])
def get_realtime_price():
    """실시간 주가 조회 (캐시 없음, 네이버 finance에서 직접)"""
    company = request.args.get('company', '').strip()

    stock_code, _ = resolve_stock_code(company, get_listed_companies())
    if not stock_code:
        return jsonify({'error': f'{company} 종목을 찾을 수 없습니다.'}), 404

    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        url = f'https://polling.finance.naver.com/api/realtime/domestic/stock/{stock_code}'
        resp = http_requests.get(url, headers=headers, timeout=5)
        data = resp.json()
        d = data['datas'][0]

        price = int(d['closePrice'].replace(',', ''))
        diff = int(d['compareToPreviousClosePrice'].replace(',', ''))
        pct = float(d['fluctuationsRatio'])
        direction = d.get('compareToPreviousPrice', {}).get('name', '')

        # FALLING/LOWER_LIMIT → 음수
        if direction in ('FALLING', 'LOWER_LIMIT'):
            diff = -abs(diff)
            pct = -abs(pct)

        result = {
            'stock_code': stock_code,
            'current_price': price,
            'price_change': diff,
            'price_change_pct': pct,
        }

        # 시가총액 — overview 캐시에서 total_shares 가져와서 계산
        cache_key = f"overview_{stock_code}"
        cached = get_cache(cache_key)
        if cached and cached.get('total_shares'):
            total = cached['total_shares']
            result['market_cap'] = int(price * total / 100000000)

        return jsonify(result)
    except Exception as e:
        return jsonify({'error': f'실시간 주가 조회 실패: {e}'}), 500


@app.route('/api/price_chart', methods=['GET'])
def get_price_chart():
    """주가차트용 일별 주가 데이터 (10년치)"""
    company = request.args.get('company', '').strip()

    stock_code, _ = resolve_stock_code(company, get_listed_companies())
    if not stock_code:
        return jsonify({'error': f'{company} 종목을 찾을 수 없습니다.'}), 404

    now_year = datetime.now().year
    price_data = fetch_naver_daily_prices_cached(stock_code, now_year - 10, now_year)

    # {(year, month, day): price} → [{date: 'YYYY-MM-DD', close: price}] 로 변환
    chart_data = []
    for (y, m, d), price in sorted(price_data.items()):
        chart_data.append({
            'date': f"{y:04d}-{m:02d}-{d:02d}",
            'close': price
        })

    return jsonify({'stock_code': stock_code, 'data': chart_data})


@app.route('/')
def index():
    response = make_response(render_template_string(HTML_TEMPLATE))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


# ── 순운전자본 API 라우트 ──
@app.route('/api/nwc/latest', methods=['GET'])
def nwc_latest():
    """최신 NWC 엑셀 파일 자동 로드"""
    files = find_excel_files()
    if not files:
        return jsonify({'success': False, 'error': '결과 파일이 없습니다'})
    latest = files[0]  # 이미 수정일 내림차순 정렬됨
    result = load_excel_results(latest['path'])
    if result['success']:
        return jsonify({
            'success': True,
            'count': result['count'],
            'file': result['file'],
            'data': get_results_data()
        })
    return jsonify(result)

@app.route('/api/nwc/screening', methods=['POST'])
def nwc_screening():
    """전종목 스크리닝 시작 (관리자 전용)"""
    if request.json.get('admin') != ADMIN_KEY:
        return jsonify({'error': '관리자 권한이 필요합니다'}), 403
    return jsonify(start_screening_thread(dart))

@app.route('/api/nwc/screening/status', methods=['GET'])
def nwc_screening_status():
    """스크리닝 진행 상황"""
    return jsonify(screening_status)

@app.route('/api/nwc/screening/stop', methods=['POST'])
def nwc_screening_stop():
    """스크리닝 중지 (관리자 전용)"""
    if request.json.get('admin') != ADMIN_KEY:
        return jsonify({'error': '관리자 권한이 필요합니다'}), 403
    return jsonify(stop_screening())

@app.route('/api/nwc/screening/results', methods=['GET'])
def nwc_screening_results():
    """스크리닝 결과 데이터"""
    return jsonify({'data': get_results_data()})

@app.route('/api/nwc/download', methods=['GET'])
def nwc_download():
    """엑셀 다운로드"""
    data = get_results_data()
    if not data:
        return jsonify({'error': '다운로드할 데이터가 없습니다'}), 400
    excel_path = generate_excel_download(data)
    if excel_path and os.path.exists(excel_path):
        return send_file(excel_path, as_attachment=True,
                         download_name=os.path.basename(excel_path))
    return jsonify({'error': '엑셀 생성 실패'}), 500


# ── 종목쇼핑 API ──
@app.route('/api/shopping/collect', methods=['POST'])
def shopping_collect():
    """전 종목 데이터 수집 시작 (관리자 전용)"""
    if request.json.get('admin') != ADMIN_KEY:
        return jsonify({'error': '관리자 권한이 필요합니다'}), 403
    return jsonify(start_shopping_thread(dart, get_listed_companies))

@app.route('/api/shopping/status', methods=['GET'])
def shopping_status_api():
    """수집 진행 상황"""
    return jsonify(shopping_status)

@app.route('/api/shopping/stop', methods=['POST'])
def shopping_stop():
    """수집 중지 (관리자 전용)"""
    if request.json.get('admin') != ADMIN_KEY:
        return jsonify({'error': '관리자 권한이 필요합니다'}), 403
    return jsonify(stop_shopping())

@app.route('/api/shopping/results', methods=['GET'])
def shopping_results():
    """수집 결과 데이터"""
    return jsonify({'data': get_shopping_data()})

@app.route('/api/shopping/download', methods=['GET'])
def shopping_download():
    """종목쇼핑 엑셀 다운로드"""
    data = get_shopping_data()
    if not data:
        return jsonify({'error': '다운로드할 데이터가 없습니다'}), 400
    excel_path = generate_shopping_excel(data)
    if excel_path and os.path.exists(excel_path):
        return send_file(excel_path, as_attachment=True,
                         download_name=os.path.basename(excel_path))
    return jsonify({'error': '엑셀 생성 실패'}), 500


_corp_cls_cache = {}  # {stock_code: 'Y'|'K'|'N'|'E'}

def _is_listed(stock_code):
    """corp_cls가 Y(코스피) 또는 K(코스닥)인지 확인 (캐시)"""
    if stock_code in _corp_cls_cache:
        return _corp_cls_cache[stock_code] in ('Y', 'K')
    try:
        info = dart.company(stock_code)
        cls = info.get('corp_cls', 'E') if isinstance(info, dict) else info.iloc[0].get('corp_cls', 'E')
        _corp_cls_cache[stock_code] = cls
        return cls in ('Y', 'K')
    except Exception:
        _corp_cls_cache[stock_code] = 'E'
        return False


@app.route('/api/search', methods=['GET'])
def search_company():
    """종목명 검색 (코스피/코스닥 상장사만)"""
    query = request.args.get('q', '').strip()
    if len(query) < 1:
        return jsonify([])

    try:
        listed = get_listed_companies()
        # corp_name에서 검색
        matched = listed[listed['corp_name'].str.contains(query, na=False, regex=False)].copy()
        if len(matched) == 0:
            return jsonify([])

        # 정렬: 정확 일치 > 시작 일치 > 포함 일치, 이름 짧은 순
        matched['_exact'] = matched['corp_name'] == query
        matched['_starts'] = matched['corp_name'].str.startswith(query)
        matched['_len'] = matched['corp_name'].str.len()
        matched = matched.sort_values(['_exact', '_starts', '_len'], ascending=[False, False, True])

        items = []
        for _, row in matched.head(30).iterrows():
            stock_code = row.get('stock_code', '')
            if not _is_listed(stock_code):
                continue
            items.append({
                'name': row.get('corp_name', ''),
                'code': stock_code,
            })
            if len(items) >= 15:
                break
        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/data', methods=['GET'])
def get_data():
    """분기별 재무 데이터 조회"""
    company = request.args.get('company', '삼성전자').strip()
    start_year = int(request.args.get('start', 2016))
    end_year = int(request.args.get('end', datetime.now().year))
    fs_pref = request.args.get('fs', 'CFS')  # CFS=연결, OFS=개별

    refresh = request.args.get('refresh', '0') == '1'
    cache_key = f"quarterly_{company}_{start_year}_{end_year}_{fs_pref}"

    # 캐시 확인 (새로고침이 아닐 때) — 실적 데이터만 캐시
    cached = None
    if not refresh:
        cached = get_cache(cache_key)

    try:
        if cached:
            data = cached.get('quarters', {})
            acc_mt = cached.get('acc_mt', '12')
            stock_code_for_price = cached.get('stock_code', None)
        else:
            data = fetch_quarterly_data(company, start_year, end_year, fs_pref)

            # 결산월 조회 + stock_code 확인
            stock_code_for_price, _ = resolve_stock_code(company, get_listed_companies())
            acc_mt = get_acc_mt(stock_code_for_price) if stock_code_for_price else '12'

            # 실적 데이터만 캐시에 저장 (주가 제외)
            cache_data = {
                'company': company,
                'start_year': start_year,
                'end_year': end_year,
                'fs_pref': fs_pref,
                'acc_mt': acc_mt,
                'stock_code': stock_code_for_price,
                'quarters': data,
            }
            set_cache(cache_key, cache_data)

        # 주가/주식수 데이터는 항상 최신으로 조회
        price_data = {}
        if stock_code_for_price:
            try:
                price_data = fetch_stock_price_data(
                    stock_code_for_price, start_year, end_year, acc_mt
                )
            except Exception:
                pass

        result = {
            'company': company,
            'start_year': start_year,
            'end_year': end_year,
            'fs_pref': fs_pref,
            'acc_mt': acc_mt,
            'quarters': data,
            'price_data': price_data,
        }
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================
# HTML 템플릿 조합
# =============================================
HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>기업분석 대시보드</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
  :root {
    --primary: #03c75a;
    --primary-light: #f0faf4;
    --accent: #5dd39e;
    --border: #d0d5d0;
    --bg-light: #f0f0f0;
    --text-muted: #888;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif; background: #f0f2f5; color: #333; }
  .container { max-width: 1000px; margin: 0 auto; padding: 20px; }

  /* 메인 탭 네비게이션 */
  .main-tabs {
    display: flex; gap: 0; margin-bottom: 16px;
    background: #fff; border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    overflow: hidden;
  }
  .main-tab {
    flex: 1; padding: 14px 24px; border: none; background: #fff;
    font-size: 15px; font-weight: 700; color: var(--text-muted); cursor: pointer;
    transition: all 0.2s; text-align: center;
    border-bottom: 3px solid transparent;
  }
  .main-tab:hover:not(.active) { background: #f8faf8; color: #555; }
  .main-tab.active { color: var(--primary); border-bottom-color: var(--primary); background: #fff; }
  .main-tab + .main-tab { border-left: 1px solid var(--bg-light); }

  /* 탭 콘텐츠 영역 */
  .tab-content { display: none; }
  .tab-content.active { display: block; }

  /* 상단 헤더 - 네이버 스타일 */
  .top-bar {
    display: flex; align-items: center; gap: 24px; padding: 20px 28px;
    background: #fff; border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    margin-bottom: 16px; flex-wrap: wrap;
  }
  .company-title { font-size: 36px; font-weight: 900; color: #222; min-width: 160px; letter-spacing: -0.5px; transition: color 0.15s; }
  .company-title:hover { color: var(--primary); }
  .company-title .stock-code { font-size: 16px; color: #999; font-weight: 400; margin-left: 8px; }
  .company-header-name { transition: color 0.15s; }
  .company-header-name:hover { color: var(--primary); }

  /* 검색창 - 네이버 스타일 */
  .search-box { position: relative; flex: 1; max-width: 520px; }
  .search-box input {
    width: 100%; padding: 14px 20px 14px 48px; border: 2px solid var(--primary);
    border-radius: 28px; font-size: 16px; outline: none; transition: all 0.2s;
    background: #fff; box-shadow: 0 2px 8px rgba(3,199,90,0.08);
  }
  .search-box input:focus { border-color: #02b350; box-shadow: 0 4px 16px rgba(3,199,90,0.18); }
  .search-box::before {
    content: '🔍'; position: absolute; left: 16px; top: 50%; transform: translateY(-50%);
    font-size: 18px; z-index: 1;
  }
  .search-results {
    position: absolute; top: calc(100% + 4px); left: 0; width: 100%; background: #fff;
    border: 1px solid #e0e0e0; border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.12);
    z-index: 100; max-height: 360px; overflow-y: auto; display: none;
  }
  .search-results .item {
    padding: 12px 20px; cursor: pointer; border-bottom: 1px solid #f5f5f5;
    display: flex; justify-content: space-between; align-items: center;
  }
  .search-results .item:hover { background: var(--primary-light); }
  .search-results .item .name { font-weight: 600; font-size: 15px; }
  .search-results .item .code { color: #999; font-size: 13px; }

  /* 컨트롤 바 */
  .controls {
    display: flex; align-items: center; gap: 12px; padding: 12px 20px;
    background: #f5f7f5; border-radius: 10px; margin-bottom: 16px; flex-wrap: wrap;
  }
  .control-label { font-size: 13px; font-weight: 600; color: #555; }
  .control-select {
    padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px;
    font-size: 13px; background: #fff; cursor: pointer; outline: none;
  }
  .control-select:focus { border-color: var(--primary); }
  .separator { width: 1px; height: 28px; background: var(--border); margin: 0 4px; }

  /* 토글 버튼 그룹 */
  .btn-group { display: flex; border-radius: 6px; overflow: hidden; border: 1px solid var(--border); }
  .btn-toggle {
    padding: 7px 18px; border: none; background: #fff; font-size: 13px;
    font-weight: 600; cursor: pointer; color: #555; transition: all 0.15s;
  }
  .btn-toggle.active { background: var(--accent); color: #fff; }
  .btn-toggle:hover:not(.active) { background: var(--primary-light); }
  .btn-toggle + .btn-toggle { border-left: 1px solid var(--border); }

  /* 로딩 */
  .loading-overlay {
    position: absolute; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(255,255,255,0.85); display: none; align-items: center;
    justify-content: center; z-index: 50; border-radius: 12px;
  }
  .loading-overlay.show { display: flex; }
  .spinner {
    width: 40px; height: 40px; border: 4px solid #e0f5e8;
    border-top-color: var(--primary); border-radius: 50%; animation: spin 0.8s linear infinite;
  }
  .loading-text { margin-left: 14px; font-size: 14px; color: #555; font-weight: 600; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* 공유 서브탭 스타일 */
  .data-sub-tabs, .chart-sub-tabs, .chart-bottom-tabs {
    display: flex; gap: 0; margin-bottom: 12px;
    background: #fff; border-radius: 8px; overflow: hidden;
    border: 1px solid var(--border);
  }
  .chart-bottom-tabs { margin-bottom: 0; margin-top: 32px; }
  .data-sub-tab, .chart-sub-tab, .chart-bottom-tab {
    flex: 1; padding: 10px 16px; border: none; background: #fff;
    font-size: 13px; font-weight: 600; color: var(--text-muted); cursor: pointer;
    transition: all 0.2s; text-align: center;
  }
  .data-sub-tab.active, .chart-sub-tab.active, .chart-bottom-tab.active { background: var(--accent); color: #fff; }
  .data-sub-tab:hover:not(.active), .chart-sub-tab:hover:not(.active), .chart-bottom-tab:hover:not(.active) { background: var(--primary-light); color: #555; }
  .data-sub-tab + .data-sub-tab, .chart-sub-tab + .chart-sub-tab, .chart-bottom-tab + .chart-bottom-tab { border-left: 1px solid var(--border); }
  .chart-tab-content { display: none; }
  .chart-tab-content.active { display: block; }
  .chart-tab-placeholder {
    text-align: center; color: var(--text-muted); padding: 80px 0;
    font-size: 15px; background: #fff; border-radius: 12px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }

  /* 차트 헤더 */
  .chart-header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 12px; flex-wrap: wrap; gap: 8px;
  }
  .chart-header-left {
    font-size: 13px; font-weight: 600; color: var(--text-muted);
  }
  .chart-header-center {
    font-size: 18px; font-weight: 800; color: #222;
    position: absolute; left: 50%; transform: translateX(-50%);
  }
  /* 커스텀 범례 */
  .custom-legend {
    display: flex; justify-content: center; gap: 20px;
    padding: 8px 0 0; flex-wrap: wrap;
    position: relative; z-index: 1;
  }
  .legend-item {
    display: inline-flex; align-items: center; gap: 6px;
    font-size: 12px; color: #666; position: relative;
  }
  .legend-dot {
    width: 10px; height: 10px; border-radius: 50%; display: inline-block; flex-shrink: 0;
  }
  .chart-help-btn {
    display: inline-flex; align-items: center; justify-content: center;
    width: 18px; height: 18px; border-radius: 50%; border: 1.5px solid #bbb;
    background: #fff; color: #999; font-size: 11px; font-weight: 700;
    cursor: pointer; flex-shrink: 0; transition: all 0.15s; margin-left: 2px;
  }
  .chart-help-btn:hover { border-color: var(--primary); color: var(--primary); }
  .chart-help-popup {
    display: none; position: absolute; bottom: 28px; left: 50%; transform: translateX(-50%);
    background: #333; color: #fff; padding: 10px 14px; border-radius: 8px;
    font-size: 12px; font-weight: 400; line-height: 1.6; white-space: normal;
    min-width: 280px; max-width: 400px; z-index: 100; box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    text-align: left;
  }
  .chart-help-popup.show { display: block; }
  .chart-help-popup::after {
    content: ''; position: absolute; bottom: -6px; left: 50%; transform: translateX(-50%);
    border-left: 6px solid transparent; border-right: 6px solid transparent;
    border-top: 6px solid #333;
  }
  .chart-header-right {
    display: flex; gap: 0; border: 1px solid var(--border); border-radius: 6px; overflow: hidden;
  }
  .chart-mode-btn {
    padding: 5px 14px; font-size: 12px; font-weight: 600; color: var(--text-muted);
    border: none; background: #fff; cursor: pointer; transition: all 0.15s;
  }
  .chart-mode-btn + .chart-mode-btn { border-left: 1px solid var(--border); }
  .chart-mode-btn.active { background: var(--accent); color: #fff; }
  .chart-mode-btn:hover:not(.active) { background: var(--primary-light); }

  /* 차트 */
  .chart-wrapper {
    margin-top: 20px; background: #fff; border-radius: 12px; padding: 20px 20px 12px; position: relative;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    max-width: 750px; margin-left: auto; margin-right: auto;
  }
  .chart-container { position: relative; width: 100%; }
  .chart-container canvas { width: 100% !important; height: 400px !important; }

  /* 10년 데이타 탭: 테이블을 전체 너비로 */
  #content-data .chart-wrapper { max-width: 100%; }

  /* 테이블 */
  .table-section {
    margin-top: 20px; background: #fff; border-radius: 12px; padding: 20px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06); overflow-x: auto;
  }
  .table-section h2 { font-size: 15px; color: var(--primary); margin-bottom: 10px; }
  .unit { font-size: 12px; color: var(--text-muted); margin-left: 4px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; white-space: nowrap; }
  th { background: var(--primary); color: #fff; padding: 7px 10px; text-align: center; }
  th:first-child { text-align: left; min-width: 90px; max-width: 150px; position: sticky; left: 0; z-index: 2; }
  td { padding: 6px 10px; text-align: right; border-bottom: 1px solid #e8f5ec; }
  td:first-child { text-align: left; font-weight: 600; background: #f5faf7; position: sticky; left: 0; z-index: 1;
    max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  td:first-child:hover { overflow: visible; white-space: normal; max-width: none;
    background: #eef6f0; box-shadow: 2px 0 8px rgba(0,0,0,0.12); z-index: 3; }
  tr:nth-child(even) td { background: var(--primary-light); }
  tr:nth-child(even) td:first-child { background: #e5f5eb; }
  .negative { color: #d32f2f; }

  /* ── 기업개요 탭 ── */
  .overview-price-indicator-row {
    display: flex; gap: 12px; margin-bottom: 12px; align-items: stretch;
  }
  .overview-price-bar {
    background: #fff; border-radius: 12px; padding: 16px 24px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.08); flex: 1; margin-bottom: 0;
    display: flex; flex-direction: column;
  }
  .overview-indicator-side {
    background: #fff; border-radius: 12px; padding: 16px 14px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.08); flex: 1; max-width: 400px;
  }
  .indicator-grid-compact {
    display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0;
  }
  .indicator-grid-compact .indicator-item {
    padding: 8px 8px; border-bottom: 1px solid var(--bg-light);
  }
  .indicator-grid-compact .indicator-value {
    font-size: 15px;
  }
  .indicator-grid-compact .indicator-label {
    font-size: 11px; margin-bottom: 3px;
  }
  .indicator-grid-compact .indicator-item:nth-child(3n+1) { border-right: 1px solid var(--bg-light); }
  .indicator-grid-compact .indicator-item:nth-child(3n+2) { border-right: 1px solid var(--bg-light); }

  .overview-market-table {
    display: flex; gap: 0; margin-top: auto; padding-top: 8px;
    border-top: 1px solid var(--bg-light);
  }
  .overview-market-cell {
    flex: 1; display: flex; flex-direction: column; gap: 3px;
    padding: 0 16px; border-right: 1px solid var(--bg-light);
  }
  .overview-market-cell:first-child { padding-left: 0; }
  .overview-market-cell:last-child { border-right: none; padding-right: 0; }
  .overview-market-label {
    font-size: 12px; color: var(--text-muted); font-weight: 600; white-space: nowrap;
  }
  .overview-market-value {
    font-size: 15px; font-weight: 700; color: #333; white-space: nowrap;
  }
  .overview-current-price {
    font-size: 36px; font-weight: 800; color: #222; line-height: 1.2;
  }
  .overview-change {
    font-size: 14px; font-weight: 600; color: #d32f2f; margin-top: 4px;
    display: flex; align-items: center; gap: 6px;
  }
  .overview-badge {
    display: inline-block; padding: 2px 8px; background: #e0f5e8; color: var(--primary);
    border-radius: 4px; font-size: 11px; font-weight: 700; margin-left: 4px;
  }
  .overview-time { font-size: 12px; color: #999; margin-top: 4px; }

  .overview-section {
    background: #fff; border-radius: 12px; padding: 20px 24px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.08); margin-bottom: 12px;
    overflow: hidden;
  }
  .overview-section-title {
    font-size: 16px; font-weight: 800; color: var(--primary); margin-bottom: 16px;
  }
  .overview-chart-period { font-size: 13px; color: var(--text-muted); font-weight: 400; margin-left: 4px; }

  .overview-desc {
    font-size: 14px; color: #555; line-height: 1.6;
    padding: 12px 16px; background: #f5faf7; border-radius: 8px; border-left: 4px solid var(--primary);
    cursor: pointer; position: relative;
  }
  .overview-desc.collapsed {
    max-height: 72px; overflow: hidden;
  }
  .overview-desc.collapsed::after {
    content: '더보기 ▼'; position: absolute; bottom: 0; left: 0; right: 0; height: 32px;
    background: linear-gradient(transparent, #f5faf7); pointer-events: none;
    display: flex; align-items: flex-end; justify-content: center;
    font-size: 11px; color: var(--text-muted); padding-bottom: 2px;
  }
  .overview-desc.expanded { max-height: none; overflow: visible; }
  .overview-desc.expanded::after { display: none; }
  .revenue-detail-row {
    cursor: pointer;
  }
  .revenue-detail-products.collapsed {
    max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .revenue-detail-products.expanded {
    max-width: none; white-space: normal;
  }
  .overview-loading-indicator {
    display: flex; align-items: center; gap: 12px;
    padding: 20px 0; justify-content: center;
  }
  .overview-loading-indicator span {
    font-size: 15px; color: var(--text-muted); font-weight: 500;
  }
  .overview-spinner {
    width: 24px; height: 24px;
    border: 3px solid #e0e0e0; border-top: 3px solid var(--primary);
    border-radius: 50%;
    animation: overview-spin 0.8s linear infinite;
  }
  @keyframes overview-spin {
    to { transform: rotate(360deg); }
  }
  .overview-info-grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 8px 24px; margin-top: 16px;
  }
  .overview-info-row { display: flex; align-items: center; gap: 8px; }
  .overview-info-label {
    font-size: 12px; color: var(--text-muted); font-weight: 600; min-width: 60px;
  }
  .overview-info-value { font-size: 14px; color: #333; font-weight: 600; }

  .overview-revenue-bar {
    display: flex; border-radius: 6px; overflow: hidden; height: 28px; gap: 2px;
  }
  .revenue-segment {
    display: flex; align-items: center; justify-content: center;
    font-size: 11px; font-weight: 600; padding: 0 8px; white-space: nowrap;
  }

  .overview-revenue-details {
    margin-top: 10px;
  }
  .revenue-detail-row {
    display: flex; align-items: baseline; padding: 5px 0; border-bottom: 1px solid #f5f5f5;
  }
  .revenue-detail-row:last-child { border-bottom: none; }
  .revenue-detail-name {
    font-size: 13px; font-weight: 700; color: var(--primary); min-width: 80px; flex-shrink: 0;
  }
  .revenue-detail-pct {
    font-size: 12px; font-weight: 600; color: #555; min-width: 50px; text-align: right; margin-right: 12px; flex-shrink: 0;
  }
  .revenue-detail-products {
    font-size: 12px; color: #777; line-height: 1.4;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }

  .indicator-grid {
    display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0;
  }
  .indicator-item {
    padding: 14px 16px; border-bottom: 1px solid var(--bg-light);
  }
  .indicator-item:nth-child(3n+1) { border-right: 1px solid var(--bg-light); }
  .indicator-item:nth-child(3n+2) { border-right: 1px solid var(--bg-light); }
  .indicator-label {
    display: block; font-size: 12px; color: var(--text-muted); font-weight: 600; margin-bottom: 6px;
  }
  .indicator-label small { font-size: 10px; color: #aaa; }
  .indicator-value {
    display: block; font-size: 20px; font-weight: 800; color: #222;
  }
  .highlight-red { color: #d32f2f; }
  .highlight-blue { color: var(--primary); }

  .overview-chart-header {
    display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;
  }
  .overview-chart-left {
    display: flex; flex-direction: column; gap: 10px;
  }
  .overview-52week {
    display: flex; gap: 20px; align-items: flex-start; padding-top: 2px;
  }
  .week52-item {
    display: flex; flex-direction: column; align-items: flex-end; gap: 2px;
  }
  .week52-label {
    font-size: 11px; color: var(--text-muted); font-weight: 600;
  }
  .week52-value {
    font-size: 18px; font-weight: 800;
  }
  .overview-chart-tabs {
    display: flex; gap: 0; flex-wrap: nowrap;
    border: 1px solid #ddd; border-radius: 6px; overflow: hidden;
  }
  .overview-chart-tab {
    padding: 6px 14px; border: none; background: #fff;
    font-size: 12px; font-weight: 600; color: var(--text-muted); cursor: pointer;
    transition: all 0.15s; white-space: nowrap; text-align: center;
  }
  .overview-chart-tab + .overview-chart-tab { border-left: 1px solid #ddd; }
  .overview-chart-tab.active { background: var(--primary); color: #fff; }
  .overview-chart-tab:hover:not(.active) { background: #f5f6fa; }
  .overview-chart-area {
    height: 300px; background: #fafbff; border-radius: 8px; border: 1px solid #eee;
  }
  /* ── 글로벌 네비게이션 ── */
  .global-nav {
    background: var(--primary); padding: 0 24px; display: flex; align-items: center;
    gap: 0; margin: 0 0 16px 0; border-radius: 0;
  }
  .global-nav-item {
    padding: 12px 24px; color: rgba(255,255,255,0.7); font-size: 14px; font-weight: 700;
    cursor: pointer; border: none; background: none; transition: all 0.15s;
    border-bottom: 3px solid transparent; white-space: nowrap;
  }
  .global-nav-item:hover { color: #fff; background: rgba(255,255,255,0.1); }
  .global-nav-item.active {
    color: #fff; border-bottom-color: #fff; background: rgba(255,255,255,0.12);
  }
  .global-nav-item.disabled {
    color: rgba(255,255,255,0.35); cursor: default;
  }
  .global-nav-item.disabled:hover { background: none; color: rgba(255,255,255,0.35); }

  /* ── 회사 헤더 바 ── */
  .company-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 24px; background: #fff;
    border-radius: 12px 12px 0 0; margin: -16px -16px 0 -16px;
    border-bottom: 1px solid #e8e8e8;
  }
  .company-header-left {
    display: flex; align-items: center; gap: 10px;
  }
  .company-header-logo {
    width: 36px; height: 36px;
  }
  .company-header-name {
    font-size: 15px; font-weight: 700; color: #222; letter-spacing: 1px;
  }
  .company-header-nav {
    display: flex; align-items: center; gap: 0;
  }
  .company-header-nav-item {
    padding: 10px 22px; font-size: 13px; font-weight: 600; color: #999;
    cursor: default; border: none; background: none;
    border-left: 1px solid #e8e8e8; white-space: nowrap;
  }
  .company-header-nav-item:first-child { border-left: none; }
  .company-header-nav-item.clickable {
    color: var(--primary); cursor: pointer; transition: all 0.15s;
  }
  .company-header-nav-item.clickable:hover {
    background: var(--primary-light); color: #02a54b;
  }

  /* ══════ 모바일 반응형 ══════ */
  @media (max-width: 768px) {
    .container { padding: 10px 8px; }

    /* 글로벌 네비게이션 */
    .global-nav { padding: 0 8px; overflow-x: auto; -webkit-overflow-scrolling: touch; }
    .global-nav-item { padding: 10px 14px; font-size: 13px; flex-shrink: 0; }

    /* 회사 헤더 */
    .company-header {
      flex-direction: column; align-items: flex-start; gap: 8px;
      padding: 10px 12px; margin: -10px -8px 0 -8px;
    }
    .company-header-nav { flex-wrap: wrap; gap: 0; }
    .company-header-nav-item { padding: 8px 12px; font-size: 12px; }

    /* 상단 검색바 */
    .top-bar { padding: 14px 12px; gap: 12px; }
    .company-title { font-size: 24px; min-width: auto; }
    .company-title .stock-code { font-size: 14px; }
    .search-box { max-width: 100%; flex-basis: 100%; }
    .search-box input { padding: 10px 16px 10px 40px; font-size: 14px; }
    .search-box::before { left: 12px; font-size: 16px; }

    /* 메인 탭 */
    .main-tabs { border-radius: 8px; }
    .main-tab { padding: 10px 8px; font-size: 13px; }

    /* 실적 그래프 서브탭 */
    .chart-sub-tabs, .data-sub-tabs, .chart-bottom-tabs {
      overflow-x: auto; -webkit-overflow-scrolling: touch;
      border-radius: 6px;
    }
    .chart-sub-tab, .data-sub-tab, .chart-bottom-tab {
      flex: none; padding: 8px 12px; font-size: 12px; white-space: nowrap;
    }

    /* 차트 헤더 - 겹침 해결 */
    .chart-header {
      flex-direction: column; align-items: stretch; gap: 6px;
      position: relative;
    }
    .chart-header-left { text-align: left; }
    .chart-header-center {
      position: static; transform: none;
      text-align: center; font-size: 16px;
      order: -1;
    }
    .chart-header-right { align-self: center; }
    .chart-mode-btn { padding: 5px 10px; font-size: 11px; }

    /* 차트 영역 */
    .chart-wrapper { padding: 12px 8px 8px; border-radius: 8px; max-width: 100%; }
    .chart-container canvas { height: 300px !important; }

    /* 커스텀 범례 */
    .custom-legend { gap: 12px; padding: 6px 0 0; }
    .legend-item { font-size: 11px; }

    /* 기업개요 */
    .overview-price-indicator-row { flex-direction: column; }
    .overview-indicator-side { max-width: 100%; }
    .overview-price-bar { padding: 14px 12px; border-radius: 8px; }
    .overview-current-price { font-size: 28px; }
    .overview-market-table { flex-wrap: wrap; gap: 8px; }
    .overview-market-value { font-size: 12px; }
    .indicator-grid-compact { grid-template-columns: 1fr 1fr 1fr; }
    .indicator-grid-compact .indicator-value { font-size: 14px; }
    .indicator-grid-compact .indicator-item { padding: 6px 6px; }

    .overview-section { padding: 14px 12px; border-radius: 8px; overflow: hidden; }
    .overview-info-grid { grid-template-columns: 1fr; gap: 6px; }
    .overview-desc { max-height: 72px; overflow: hidden; }
    .overview-desc.expanded { max-height: none; overflow: visible; }
    .revenue-detail-name { min-width: 60px; font-size: 11px; }
    .revenue-detail-pct { min-width: 40px; font-size: 11px; margin-right: 6px; }
    .revenue-detail-products { font-size: 11px; }
    .revenue-detail-products.expanded { white-space: normal; }
    .overview-chart-left { width: 100%; }
    .overview-chart-tabs { width: 100%; }
    .overview-chart-tab { flex: 1; padding: 8px 0; text-align: center; font-size: 12px; }

    .indicator-grid { grid-template-columns: 1fr 1fr; }
    .indicator-item { padding: 10px 10px; }
    .indicator-item:nth-child(3n+1) { border-right: none; }
    .indicator-item:nth-child(3n+2) { border-right: none; }
    .indicator-item:nth-child(odd) { border-right: 1px solid var(--bg-light); }
    .indicator-value { font-size: 16px; }

    /* 52주 고저 */
    .overview-chart-header { flex-direction: column; gap: 10px; }
    .overview-52week { gap: 12px; }
    .week52-value { font-size: 15px; }
    .overview-chart-area { height: 240px; }

    /* 테이블 */
    .table-section { padding: 10px 8px; border-radius: 8px; }
    table { font-size: 11px; }
    th { padding: 5px 6px; }
    td { padding: 4px 6px; }

    /* 컨트롤바 */
    .controls { padding: 8px 10px; gap: 8px; }
    .btn-toggle { padding: 5px 10px; font-size: 12px; }

    /* 도움말 팝업 */
    .chart-help-popup { min-width: 220px; max-width: 280px; font-size: 11px; }
  }

  @media (max-width: 480px) {
    .container { padding: 6px 4px; }
    .company-title { font-size: 20px; }
    .company-title .stock-code { font-size: 13px; }
    .top-bar { padding: 10px 8px; gap: 8px; }
    .main-tab { padding: 8px 4px; font-size: 12px; }
    .chart-container canvas { height: 260px !important; }
    .overview-current-price { font-size: 24px; }
    .indicator-grid { grid-template-columns: 1fr 1fr; }
    .indicator-value { font-size: 14px; }
    .chart-header-center { font-size: 14px; }
    .overview-chart-area { height: 200px; }
  }
</style>
</head>
<body>
<div class="container">
  <!-- 회사 헤더 -->
  <div class="company-header">
    <div class="company-header-left">
      <svg class="company-header-logo" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
        <circle cx="50" cy="50" r="46" fill="none" stroke="#222" stroke-width="5"/>
        <text x="50" y="56" text-anchor="middle" font-family="Arial, sans-serif" font-size="28" font-weight="bold" fill="#222">JMY</text>
      </svg>
      <span class="company-header-name" onclick="location.reload();" style="cursor:pointer;" title="홈페이지 새로고침">JMY Partners</span>
    </div>
  </div>

  <!-- 글로벌 네비게이션 -->
  <div class="global-nav">
    <button class="global-nav-item active" onclick="switchGlobalMenu('finstate')">기업분석</button>
    <button class="global-nav-item" onclick="switchGlobalMenu('shopping')">종목쇼핑</button>
    <button class="global-nav-item" onclick="switchGlobalMenu('nwc')">순운전자본</button>
    <button class="global-nav-item disabled">-</button>
    <button class="global-nav-item" onclick="adminRefresh()" style="margin-left:auto; color:#ffd700; font-size:13px;" title="관리자 전용: 현재 종목 데이터 갱신">🔒 갱신</button>
  </div>

  <!-- 기업분석 콘텐츠 -->
  <div id="finstate-content">
  <!-- 상단 -->
  <div class="top-bar">
    <div class="company-title" id="companyTitle"><span class="stock-code" id="stockCode"></span></div>
    <div class="search-box">
      <input type="text" id="searchInput" placeholder="종목을 검색해보세요" autocomplete="off">
      <div class="search-results" id="searchResults"></div>
    </div>
  </div>

  <!-- 메인 탭 -->
  <div class="main-tabs">
    <button class="main-tab active" id="tab-overview" onclick="switchTab('overview')">기업개요</button>
    <button class="main-tab" id="tab-chart" onclick="switchTab('chart')">실적 그래프</button>
    <button class="main-tab" id="tab-data" onclick="switchTab('data')">10년 데이타</button>
  </div>

  <!-- 탭1: 기업개요 -->
  <div class="tab-content active" id="content-overview">
''' + get_기업개요_html() + '''
  </div>

  <!-- 탭2: 실적 그래프 -->
  <div class="tab-content" id="content-chart">
    <!-- 실적 그래프 서브탭 -->
    <div class="chart-sub-tabs">
      <button class="chart-sub-tab active" onclick="switchChartTab('revenue')" id="chart-tab-revenue">매출 및 수익성</button>
      <button class="chart-sub-tab" onclick="switchChartTab('asset')" id="chart-tab-asset">자산구조 및 배당</button>
      <button class="chart-sub-tab" onclick="switchChartTab('cashflow')" id="chart-tab-cashflow">현금흐름</button>
      <button class="chart-sub-tab" onclick="switchChartTab('debt')" id="chart-tab-debt">부채 및 안전성</button>
      <button class="chart-sub-tab" onclick="switchChartTab('roe')" id="chart-tab-roe">ROE 및 효율성</button>
      <button class="chart-sub-tab" onclick="switchChartTab('valuation')" id="chart-tab-valuation">가치평가</button>
    </div>

    <!-- 컨트롤 바 -->
    <div class="controls">
      <span class="control-label">기간</span>
      <select class="control-select" id="startYear"></select>
      <span style="color:#888;">~</span>
      <select class="control-select" id="endYear"></select>

      <div class="separator"></div>

      <div class="btn-group">
        <button class="btn-toggle active" onclick="setFs('CFS')" id="btn-CFS">연결</button>
        <button class="btn-toggle" onclick="setFs('OFS')" id="btn-OFS">개별</button>
      </div>

      <div class="separator"></div>

      <div class="btn-group">
        <button class="btn-toggle active" onclick="setMode('trailing')" id="btn-trailing">연환산</button>
        <button class="btn-toggle" onclick="setMode('annual')" id="btn-annual">연간</button>
        <button class="btn-toggle" onclick="setMode('quarterly')" id="btn-quarterly">분기</button>
      </div>

      <button onclick="loadData(false)" style="
        margin-left: auto; padding: 8px 20px; background: #5dd39e; color: #fff;
        border: none; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer;
      ">조회</button>
    </div>

    <!-- 서브탭1: 매출 및 수익성 -->
    <div class="chart-tab-content active" id="chart-content-revenue">
''' + get_실적차트_html() + '''
''' + get_매출이익지수_html() + '''

      <!-- 영업이익률, 순이익률 -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">영업이익률, 순이익률</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="marginChart"></canvas></div>
      </div>

      <!-- 매출원가율, 판관비율 -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">매출원가율, 판관비율</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="costRatioChart"></canvas></div>
      </div>
      <!-- 하단 서브탭 -->
      <div class="chart-bottom-tabs">
        <button class="chart-bottom-tab active" onclick="switchChartTab('revenue')">매출 및 수익성</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('asset')">자산구조 및 배당</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('cashflow')">현금흐름</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('debt')">부채 및 안전성</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('roe')">ROE 및 효율성</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('valuation')">가치평가</button>
      </div>
    </div>

    <!-- 서브탭2: 자산구조 및 배당 -->
    <div class="chart-tab-content" id="chart-content-asset">
      <!-- 자산구조 -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">자산구조</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="assetStructChart"></canvas></div>
      </div>

      <!-- 배당금, 배당성향, 시가배당률 -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">배당금, 배당성향, 시가배당률</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="dividendChart"></canvas></div>
      </div>
      <!-- 하단 서브탭 -->
      <div class="chart-bottom-tabs">
        <button class="chart-bottom-tab" onclick="switchChartTab('revenue')">매출 및 수익성</button>
        <button class="chart-bottom-tab active" onclick="switchChartTab('asset')">자산구조 및 배당</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('cashflow')">현금흐름</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('debt')">부채 및 안전성</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('roe')">ROE 및 효율성</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('valuation')">가치평가</button>
      </div>
    </div>

    <!-- 서브탭3: 현금흐름 -->
    <div class="chart-tab-content" id="chart-content-cashflow">
      <!-- 영업/투자/재무 현금흐름 -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">현금흐름</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="cfChart"></canvas></div>
      </div>

      <!-- FCF, 순이익 -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">FCF(잉여현금흐름), 순이익</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="fcfChart"></canvas></div>
      </div>
      <!-- 하단 서브탭 -->
      <div class="chart-bottom-tabs">
        <button class="chart-bottom-tab" onclick="switchChartTab('revenue')">매출 및 수익성</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('asset')">자산구조 및 배당</button>
        <button class="chart-bottom-tab active" onclick="switchChartTab('cashflow')">현금흐름</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('debt')">부채 및 안전성</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('roe')">ROE 및 효율성</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('valuation')">가치평가</button>
      </div>
    </div>

    <!-- 서브탭4: 부채 및 안전성 -->
    <div class="chart-tab-content" id="chart-content-debt">
      <!-- 부채비율, 유동비율 -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">부채비율, 유동비율</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="debtRatioChart"></canvas></div>
      </div>

      <!-- 차입금과 차입금 비중 -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">차입금과 차입금 비중</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="borrowingChart"></canvas></div>
      </div>

      <!-- 영업이익, 이자비용 -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">영업이익, 이자비용</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="interestChart"></canvas></div>
      </div>

      <!-- 이자보상배율 -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">이자보상배율</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="icrChart"></canvas></div>
      </div>

      <!-- 순현금 & 시총대비 순현금 비중 -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">순현금 & 시총대비 순현금 비중</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="netCashChart"></canvas></div>
      </div>
      <!-- 하단 서브탭 -->
      <div class="chart-bottom-tabs">
        <button class="chart-bottom-tab" onclick="switchChartTab('revenue')">매출 및 수익성</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('asset')">자산구조 및 배당</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('cashflow')">현금흐름</button>
        <button class="chart-bottom-tab active" onclick="switchChartTab('debt')">부채 및 안전성</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('roe')">ROE 및 효율성</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('valuation')">가치평가</button>
      </div>
    </div>

    <!-- 서브탭5: ROE 및 효율성 -->
    <div class="chart-tab-content" id="chart-content-roe">
      <!-- ROE, PBR -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">ROE(자기자본이익률), PBR</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="roePbrChart"></canvas></div>
      </div>

      <!-- 듀퐁분석 -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">듀퐁분석</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="dupontChart"></canvas></div>
      </div>

      <!-- ROA, ROIC, ROE -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">ROA, ROIC, ROE</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="roaRoicChart"></canvas></div>
      </div>

      <!-- 운전자본 회전일수 -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">운전자본 회전일수</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="wcTurnChart"></canvas></div>
      </div>

      <!-- 현금회전일수 -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">현금회전일수</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="cashTurnChart"></canvas></div>
      </div>
      <!-- 하단 서브탭 -->
      <div class="chart-bottom-tabs">
        <button class="chart-bottom-tab" onclick="switchChartTab('revenue')">매출 및 수익성</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('asset')">자산구조 및 배당</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('cashflow')">현금흐름</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('debt')">부채 및 안전성</button>
        <button class="chart-bottom-tab active" onclick="switchChartTab('roe')">ROE 및 효율성</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('valuation')">가치평가</button>
      </div>
    </div>

    <!-- ── 가치평가 탭 ── -->
    <div class="chart-tab-content" id="chart-content-valuation">
      <!-- 조정 순운전자본 -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">조정 순운전자본</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="cashAssetChart"></canvas></div>
      </div>

      <!-- 주가 vs. 주당순자산(BPS) -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">주가 vs. 주당순자산(BPS)</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="priceBpsChart"></canvas></div>
      </div>

      <!-- 주가 vs. 주당순이익(EPS) -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">주가 vs. 주당순이익(EPS)</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="priceEpsChart"></canvas></div>
      </div>

      <!-- PER(주가수익배수) -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">PER(주가수익배수)</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="perChart"></canvas></div>
      </div>

      <!-- PBR(주가순자산배수) -->
      <div class="chart-wrapper">
        <div class="chart-header">
          <div class="chart-header-left chart-company-name"></div>
          <div class="chart-header-center">PBR(주가순자산배수)</div>
          <div class="chart-header-right">
            <button class="chart-mode-btn active" onclick="setMode('trailing')" data-mode="trailing">연환산</button>
            <button class="chart-mode-btn" onclick="setMode('annual')" data-mode="annual">연간</button>
            <button class="chart-mode-btn" onclick="setMode('quarterly')" data-mode="quarterly">분기</button>
          </div>
        </div>
        <div class="chart-container"><canvas id="pbrChart"></canvas></div>
      </div>

      <!-- 하단 서브탭 -->
      <div class="chart-bottom-tabs">
        <button class="chart-bottom-tab" onclick="switchChartTab('revenue')">매출 및 수익성</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('asset')">자산구조 및 배당</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('cashflow')">현금흐름</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('debt')">부채 및 안전성</button>
        <button class="chart-bottom-tab" onclick="switchChartTab('roe')">ROE 및 효율성</button>
        <button class="chart-bottom-tab active" onclick="switchChartTab('valuation')">가치평가</button>
      </div>
    </div>
  </div>

  <!-- 탭3: 10년 데이타 -->
  <div class="tab-content" id="content-data">
''' + get_10년데이타_html() + '''
  </div>
  </div><!-- /finstate-content -->

  <!-- 순운전자본 콘텐츠 -->
''' + get_순운전자본_html() + '''

  <!-- 종목쇼핑 콘텐츠 -->
''' + get_종목쇼핑_html() + '''

</div><!-- /container -->

<!-- 관리자 비밀번호 모달 -->
<div id="adminModal" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); z-index:10000; justify-content:center; align-items:center;">
  <div style="background:#fff; border-radius:12px; padding:28px 32px; min-width:320px; box-shadow:0 8px 32px rgba(0,0,0,0.3);">
    <h3 style="margin:0 0 16px 0; font-size:16px; color:#333;">🔒 관리자 인증</h3>
    <input type="password" id="adminPwInput" placeholder="비밀번호를 입력하세요" style="width:100%; padding:10px 12px; border:1px solid #ccc; border-radius:6px; font-size:14px; box-sizing:border-box;">
    <div id="adminPwError" style="color:#e74c3c; font-size:12px; margin-top:6px; display:none;">비밀번호가 일치하지 않습니다.</div>
    <div style="display:flex; gap:8px; margin-top:16px; justify-content:flex-end;">
      <button onclick="closeAdminModal()" style="padding:8px 18px; border:1px solid #ddd; background:#fff; border-radius:6px; cursor:pointer; font-size:13px;">취소</button>
      <button onclick="submitAdminPw()" style="padding:8px 18px; border:none; background:#5dd39e; color:#fff; border-radius:6px; cursor:pointer; font-size:13px; font-weight:600;">확인</button>
    </div>
  </div>
</div>

<script>
// ── 실적 그래프 서브탭 전환 ──
let currentChartTab = 'revenue';
function switchChartTab(tabName) {
  currentChartTab = tabName;
  // 상단 서브탭 활성화
  document.querySelectorAll('.chart-sub-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.chart-tab-content').forEach(c => c.classList.remove('active'));
  document.getElementById('chart-tab-' + tabName).classList.add('active');
  document.getElementById('chart-content-' + tabName).classList.add('active');
  // 하단 서브탭 활성화
  const tabMap = {revenue:0, asset:1, cashflow:2, debt:3, roe:4, valuation:5};
  const idx = tabMap[tabName];
  document.querySelectorAll('.chart-bottom-tabs').forEach(container => {
    const btns = container.querySelectorAll('.chart-bottom-tab');
    btns.forEach((b, i) => {
      b.classList.toggle('active', i === idx);
    });
  });
  // 서브탭 전환 시 상단으로 스크롤
  const tabsEl = document.querySelector('.chart-sub-tabs');
  if (tabsEl) tabsEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── 글로벌 네비게이션 ──
function switchGlobalMenu(menu) {
  // 네비게이션 버튼 활성화
  document.querySelectorAll('.global-nav-item').forEach(btn => {
    btn.classList.remove('active');
    if (menu === 'finstate' && btn.textContent === '기업분석') btn.classList.add('active');
    if (menu === 'nwc' && btn.textContent === '순운전자본') btn.classList.add('active');
    if (menu === 'shopping' && btn.textContent === '종목쇼핑') btn.classList.add('active');
  });

  // 콘텐츠 전환
  document.getElementById('finstate-content').style.display = menu === 'finstate' ? 'block' : 'none';
  document.getElementById('nwc-content').style.display = menu === 'nwc' ? 'block' : 'none';
  document.getElementById('shopping-content').style.display = menu === 'shopping' ? 'block' : 'none';

  if (menu === 'nwc') {
    nwcInit();
  }
  if (menu === 'shopping') {
    shopInit();
  }
}

// ── 상태 ──
let rawData = {};
let priceData = {};
let chartDataLoaded = false;
let chart = null;
let priceRevChartInst = null;
let priceNiChartInst = null;
let currentMode = 'trailing';
let currentFs = 'CFS';
// URL 파라미터에서 종목 복원 (F5 새로고침 대응)
const _urlParams = new URLSearchParams(window.location.search);
let currentCompany = _urlParams.get('company') || '삼성전자';
let currentStockCode = _urlParams.get('code') || '005930';
let accMt = 12;  // 결산월 (기본: 12월)

const ITEMS = ['매출액', '영업이익', '지배순이익'];
const COLORS = {
  '매출액':     { bar: 'rgba(176,196,222,0.7)', border: 'rgba(143,170,220,1)' },
  '영업이익':   { line: 'rgba(47,84,150,1)' },
  '지배순이익': { line: 'rgba(112,173,71,1)' },
};

// ── 초기화 ──
function initYearSelectors() {
  const now = new Date().getFullYear();
  const startSel = document.getElementById('startYear');
  const endSel = document.getElementById('endYear');
  for (let y = now; y >= 2000; y--) {
    startSel.add(new Option(y + '년', y));
    endSel.add(new Option(y + '년', y));
  }
  startSel.value = now - 10;
  endSel.value = now;
}

// ── 종목 검색 ──
let searchTimeout = null;
let lastSearchResults = [];
let _searchSuppressed = false;

document.getElementById('searchInput').addEventListener('input', function() {
  clearTimeout(searchTimeout);
  if (_searchSuppressed) { _searchSuppressed = false; return; }
  const q = this.value.trim();
  if (q.length < 1) { hideResults(); return; }
  searchTimeout = setTimeout(() => searchCompany(q), 300);
});

document.getElementById('searchInput').addEventListener('keydown', async function(e) {
  if (e.key === 'Enter') {
    e.preventDefault();
    clearTimeout(searchTimeout);
    const q = this.value.trim();
    if (q.length < 1) return;
    if (lastSearchResults.length > 0) {
      selectCompany(lastSearchResults[0].name, lastSearchResults[0].code);
    } else {
      await searchCompany(q);
      if (lastSearchResults.length > 0) {
        selectCompany(lastSearchResults[0].name, lastSearchResults[0].code);
      }
    }
  }
});

document.getElementById('searchInput').addEventListener('focus', function() {
  _searchSuppressed = false;
});

document.addEventListener('click', function(e) {
  if (!e.target.closest('.search-box')) hideResults();
});

async function searchCompany(query) {
  try {
    const res = await fetch('/api/search?q=' + encodeURIComponent(query));
    const items = await res.json();
    lastSearchResults = items.length && !items.error ? items : [];
    const container = document.getElementById('searchResults');
    if (!lastSearchResults.length) { hideResults(); return; }

    container.innerHTML = lastSearchResults.map(item =>
      `<div class="item" onclick="selectCompany('${item.name.replace(/'/g,"\\\\'")}', '${item.code}')"
           onmouseenter="prefetchOverview('${item.code}')">
        <span class="name">${item.name}</span>
        <span class="code">${item.code || ''}</span>
      </div>`
    ).join('');
    container.style.display = 'block';
  } catch(e) { hideResults(); lastSearchResults = []; }
}

function selectCompany(name, code) {
  currentCompany = name;
  currentStockCode = code;
  // URL 파라미터 업데이트 (F5 새로고침 시 종목 유지)
  const newUrl = window.location.pathname + '?company=' + encodeURIComponent(name) + '&code=' + encodeURIComponent(code || '');
  window.history.replaceState(null, '', newUrl);
  finDataLoaded = false;
  finData = null;
  _dividendData = null;
  _dividendLoading = false;
  overviewLoaded = false;
  overviewLoadedCompany = '';
  clearTimeout(searchTimeout);
  _searchSuppressed = true;
  document.getElementById('searchInput').value = '';
  hideResults();
  lastSearchResults = [];
  document.getElementById('searchInput').blur();

  // ── 기업이름/코드 즉시 변경 (API 응답 전에) ──
  document.getElementById('companyTitle').innerHTML =
    name + '<span class="stock-code">' + (code || '') + '</span>';
  document.title = name + ' 기업분석';

  // 차트 데이터 캐시 무효화
  chartDataLoaded = false;

  // 기업개요 탭으로 자동 전환 + 실적 그래프 서브탭 리셋
  switchTab('overview');
  switchChartTab('revenue');
  // loadData()는 실적 그래프 탭 전환 시 지연 로드 (기업개요 먼저 표시)
}

function hideResults() {
  const container = document.getElementById('searchResults');
  container.style.display = 'none';
  container.innerHTML = '';
}

// ── 관리자 갱신 ──
const ADMIN_PW = '026131';

function adminRefresh() {
  if (!currentCompany && !currentStockCode) {
    alert('먼저 종목을 선택해주세요.');
    return;
  }
  const modal = document.getElementById('adminModal');
  const input = document.getElementById('adminPwInput');
  const error = document.getElementById('adminPwError');
  input.value = '';
  error.style.display = 'none';
  modal.style.display = 'flex';
  setTimeout(() => input.focus(), 100);
}

function closeAdminModal() {
  document.getElementById('adminModal').style.display = 'none';
}

function submitAdminPw() {
  const pw = document.getElementById('adminPwInput').value;
  if (pw !== ADMIN_PW) {
    document.getElementById('adminPwError').style.display = 'block';
    document.getElementById('adminPwInput').value = '';
    document.getElementById('adminPwInput').focus();
    return;
  }
  closeAdminModal();
  refreshAllData();
}

// Enter 키로 비밀번호 제출
document.addEventListener('keydown', function(e) {
  if (document.getElementById('adminModal').style.display === 'flex') {
    if (e.key === 'Enter') submitAdminPw();
    if (e.key === 'Escape') closeAdminModal();
  }
});

async function refreshAllData() {
  overviewLoaded = false;
  overviewLoadedCompany = '';
  finDataLoaded = false;
  chartDataLoaded = false;
  showLoading('모든 데이터를 갱신하는 중...');
  try {
    await Promise.all([
      loadOverviewData(true),
      loadData(true),
      loadFinData(true)
    ]);
  } catch(e) {
    console.error('갱신 중 오류:', e);
  } finally {
    hideLoading();
  }
  alert('✅ 모든 데이터가 갱신되었습니다.');
}

// ── 데이터 로드 ──

async function loadData(refresh = false) {
  if (chartDataLoaded && !refresh) return;  // 이미 로드됨 → 스킵

  const startYear = document.getElementById('startYear').value;
  const endYear = document.getElementById('endYear').value;

  const _showFn = refresh ? showLoading : showChartLoading;
  const _hideFn = refresh ? hideLoading : hideChartLoading;
  _showFn(refresh ? `${currentCompany} 최신 데이터 갱신 중...` : `${currentCompany} 실적 데이터를 불러오는 중...`);

  try {
    const queryName = currentStockCode || currentCompany;
    let url = `/api/data?company=${encodeURIComponent(queryName)}&start=${startYear}&end=${endYear}&fs=${currentFs}`;
    if (refresh) url += '&refresh=1';
    const res = await fetch(url);
    const result = await res.json();

    if (result.error) {
      alert('오류: ' + result.error);
      _hideFn();
      return;
    }

    // 데이터 업데이트
    accMt = parseInt(result.acc_mt) || 12;
    priceData = result.price_data || {};
    rawData = {};
    for (const [label, qdata] of Object.entries(result.quarters)) {
      rawData[label] = {};
      ITEMS.forEach(item => { rawData[label][item] = qdata[item]; });
    }

    // UI 업데이트
    document.getElementById('companyTitle').innerHTML =
      currentCompany + '<span class="stock-code">' + (currentStockCode ? currentStockCode : '') + '</span>';
    document.title = currentCompany + ' 기업분석';

    chartDataLoaded = true;
    buildChart(currentMode);
    // priceData 로드 완료 → finData가 있으면 5년 지표 업데이트
    if (finDataLoaded && finData && typeof update5YearIndicators === 'function') update5YearIndicators();
  } catch(e) {
    alert('데이터 로드 실패: ' + e.message);
  }
  _hideFn();
}

function showLoading(text) {
  document.getElementById('loadingText').textContent = text || '로딩 중...';
  document.getElementById('loadingOverlay').classList.add('show');
}
function hideLoading() {
  document.getElementById('loadingOverlay').classList.remove('show');
}

// 차트 영역 내부 로딩 (전체 페이지 블로킹 없이)
function showChartLoading(text) {
  let el = document.getElementById('chartLoadingOverlay');
  if (!el) {
    el = document.createElement('div');
    el.id = 'chartLoadingOverlay';
    el.style.cssText = 'position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(255,255,255,0.85);display:flex;align-items:center;justify-content:center;z-index:100;flex-direction:column;gap:12px;';
    el.innerHTML = '<div class="loading-spinner" style="width:36px;height:36px;border:3px solid #e0e0e0;border-top:3px solid #1976d2;border-radius:50%;animation:spin 1s linear infinite;"></div><div id="chartLoadingText" style="color:#555;font-size:14px;"></div>';
    const chartContent = document.getElementById('content-chart');
    if (chartContent) {
      chartContent.style.position = 'relative';
      chartContent.appendChild(el);
    }
  }
  el.style.display = 'flex';
  const textEl = document.getElementById('chartLoadingText');
  if (textEl) textEl.textContent = text || '로딩 중...';
}
function hideChartLoading() {
  const el = document.getElementById('chartLoadingOverlay');
  if (el) el.style.display = 'none';
}

// ── 검색 결과 hover 프리페치 ──
const _prefetchedCodes = new Set();
function prefetchOverview(code) {
  if (!code || _prefetchedCodes.has(code)) return;
  _prefetchedCodes.add(code);
  // 서버 캐시 워밍 (결과는 버림, loadOverviewData에서 캐시 히트)
  fetch(`/api/overview?company=${encodeURIComponent(code)}`).catch(() => {});
}

// ── 차트 도움말 토글 ──
function toggleChartHelp(btn) {
  const popup = btn.nextElementSibling;
  const isOpen = popup.classList.contains('show');
  // 모든 팝업 닫기
  document.querySelectorAll('.chart-help-popup.show').forEach(p => p.classList.remove('show'));
  if (!isOpen) popup.classList.add('show');
}
// 다른 영역 클릭 시 팝업 닫기
document.addEventListener('click', function(e) {
  if (!e.target.classList.contains('chart-help-btn')) {
    document.querySelectorAll('.chart-help-popup.show').forEach(p => p.classList.remove('show'));
  }
});

// ── 모드 전환 ──
function setMode(mode) {
  currentMode = mode;
  // 컨트롤바 버튼
  document.querySelectorAll('#btn-trailing,#btn-annual,#btn-quarterly').forEach(b => b.classList.remove('active'));
  document.getElementById('btn-' + mode).classList.add('active');
  // 모든 차트 내부 버튼 동기화 (data-mode 속성 기반)
  document.querySelectorAll('.chart-mode-btn').forEach(b => {
    b.classList.toggle('active', b.getAttribute('data-mode') === mode || b.id === 'chartBtn-' + mode || b.id === 'priceBtn-' + mode);
  });
  if (Object.keys(rawData).length > 0) buildChart(mode);
}

// ── 회사명 동기화 ──
function syncCompanyNames() {
  document.querySelectorAll('.chart-company-name').forEach(el => {
    el.textContent = currentCompany;
  });
}

// ── 빈 차트 초기화 (데이터 없는 차트용) ──
const emptyChartInstances = {};
function initEmptyChart(canvasId, chartTitle, seriesNames, type) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  if (emptyChartInstances[canvasId]) emptyChartInstances[canvasId].destroy();

  const colors = [
    'rgba(47,84,150,1)', 'rgba(112,173,71,1)', 'rgba(220,53,69,1)',
    'rgba(255,159,64,1)', 'rgba(143,170,220,1)', 'rgba(153,102,255,1)',
  ];
  const bgColors = [
    'rgba(47,84,150,0.6)', 'rgba(112,173,71,0.6)', 'rgba(220,53,69,0.6)',
    'rgba(255,159,64,0.6)', 'rgba(143,170,220,0.6)', 'rgba(153,102,255,0.6)',
  ];

  const datasets = seriesNames.map((name, i) => ({
    label: name,
    data: [],
    borderColor: colors[i % colors.length],
    backgroundColor: type === 'bar' ? bgColors[i % bgColors.length] : colors[i % colors.length],
    borderWidth: type === 'bar' ? 1 : 2.5,
    pointRadius: 0,
    tension: 0.3,
    fill: false,
  }));

  emptyChartInstances[canvasId] = new Chart(canvas, {
    type: type || 'line',
    data: { labels: [], datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        title: { display: false },
        legend: { position: 'bottom', labels: { usePointStyle: true, padding: 16, font: { size: 12 } } },
      },
      scales: {
        x: { ticks: { font: { size: 11 } }, grid: { display: false } },
        y: { ticks: { font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } },
      },
    },
  });
}

function initAllEmptyCharts() {
  // 매출 및 수익성
  initEmptyChart('marginChart', '영업이익률, 순이익률', ['영업이익률(%)', '순이익률(지배)(%)'], 'line');
  initEmptyChart('costRatioChart', '매출원가율, 판관비율', ['매출원가율(%)', '판관비율(%)'], 'line');
  // 자산구조 및 배당
  initEmptyChart('assetStructChart', '자산구조', ['유동자산', '비유동자산', '유동부채', '비유동부채', '자본총계'], 'bar');
  initEmptyChart('dividendChart', '배당', ['배당금', '배당성향(%)', '시가배당률(%)'], 'bar');
  // 현금흐름
  initEmptyChart('cfChart', '현금흐름', ['영업활동', '투자활동', '재무활동'], 'line');
  initEmptyChart('fcfChart', 'FCF', ['FCF(잉여현금흐름)', '순이익(지배)'], 'bar');
  // 부채 및 안전성
  initEmptyChart('debtRatioChart', '부채/유동비율', ['부채비율(%)', '유동비율(%)'], 'line');
  initEmptyChart('borrowingChart', '차입금', ['차입금', '차입금비중(%)'], 'bar');
  initEmptyChart('interestChart', '영업이익/이자비용', ['영업이익', '이자비용'], 'bar');
  initEmptyChart('icrChart', '이자보상배율', ['이자보상배율(배)'], 'line');
  initEmptyChart('netCashChart', '순현금 & 시총대비', ['순현금', '시총대비 순현금비중(%)'], 'bar');
  // ROE 및 효율성
  initEmptyChart('roePbrChart', 'ROE/PBR', ['ROE(지배)(%)', 'PBR(배)'], 'bar');
  initEmptyChart('dupontChart', '듀퐁분석', ['순이익률(지배)(%)', '총자산회전률(회)', '재무레버리지(배)'], 'line');
  initEmptyChart('roaRoicChart', 'ROA/ROIC/ROE', ['ROA(지배)(%)', 'ROIC(%)', 'ROE(지배)(%)'], 'line');
  initEmptyChart('wcTurnChart', '운전자본 회전일수', ['매출채권(일)', '재고자산(일)', '매입채무(일)', '운전자본(일)'], 'line');
  initEmptyChart('cashTurnChart', '현금회전일수', ['현금회전일수(일)'], 'line');
  // 가치평가
  initEmptyChart('cashAssetChart', '조정 순운전자본', ['조정유동자산', '조정유동부채', '조정순운전자본', '시가총액'], 'line');
  initEmptyChart('priceBpsChart', '주가 vs. BPS', ['주가(원)', 'BPS(원)'], 'line');
  initEmptyChart('priceEpsChart', '주가 vs. EPS', ['주가(원)', 'EPS(원)'], 'line');
  initEmptyChart('perChart', 'PER', ['PER(배)'], 'line');
  initEmptyChart('pbrChart', 'PBR', ['PBR(배)'], 'line');
}

function setFs(fs) {
  currentFs = fs;
  document.querySelectorAll('#btn-CFS,#btn-OFS').forEach(b => b.classList.remove('active'));
  document.getElementById('btn-' + fs).classList.add('active');
}

// ── 분기→결산월 변환 ──
function qtrEndMonth(qtrNum) {
  const m = ((accMt % 12) + qtrNum * 3) % 12;
  return m === 0 ? 12 : m;
}

function toDisplayLabel(rawLabel, mode) {
  const year = parseInt(rawLabel.slice(0, 4));
  const qtr = parseInt(rawLabel.slice(5));
  const endMonth = qtrEndMonth(qtr);

  let displayYear = year;
  if (endMonth > accMt) {
    displayYear = year - 1;
  }

  const mm = String(endMonth).padStart(2, '0');
  if (mode === 'annual') {
    return year + '.' + String(accMt).padStart(2, '0');
  }
  const yy = String(displayYear).slice(2);
  return yy + '.' + mm;
}

// ── 차트 모듈 JS ──
''' + get_실적차트_js() + '''
''' + get_매출이익지수_js() + '''
''' + get_10년데이타_js() + '''
''' + get_기업개요_js() + '''
''' + get_실적그래프_차트_js() + '''
''' + get_순운전자본_js() + '''
''' + get_종목쇼핑_js() + '''

// ── 통합 빌드 ──
function buildChart(mode) {
  syncCompanyNames();
  buildMainChart(mode);
  buildPriceChart(mode);
  buildAllFinCharts(mode);
}

// ── 탭 전환 ──
async function switchTab(tabName) {
  document.querySelectorAll('.main-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  document.getElementById('tab-' + tabName).classList.add('active');
  document.getElementById('content-' + tabName).classList.add('active');
  if (tabName === 'data') loadFinData();
  if (tabName === 'chart') {
    if (!chartDataLoaded) await loadData();
    loadFinDataForChart();
  }
  if (tabName === 'overview') loadOverviewData();
}

// ── 실적 그래프 탭용 finData 로드 ──
async function loadFinDataForChart() {
  if (finDataLoaded && finData) {
    buildAllFinCharts(currentMode);
    return;
  }
  // finData가 없으면 로드
  await loadFinData();
  buildAllFinCharts(currentMode);
}

// ── 시작 ──
// URL 파라미터 종목으로 즉시 제목 표시 (깜빡임 방지)
document.getElementById('companyTitle').innerHTML =
  currentCompany + '<span class="stock-code">' + (currentStockCode || '') + '</span>';
document.title = currentCompany + ' 기업분석';
initYearSelectors();
initAllEmptyCharts();
// loadData()는 실적 그래프 탭 전환 시 지연 로드 (기업개요 먼저 표시)
loadOverviewData();
</script>
</body>
</html>'''


if __name__ == '__main__':
    print("\n" + "=" * 50)
    print("  기업 재무분석 대시보드 서버")
    print("  http://localhost:5000")
    print("=" * 50 + "\n")
    app.run(debug=False, port=5000)
