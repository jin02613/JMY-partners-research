# -*- coding: utf-8 -*-
"""
종목쇼핑 백엔드 모듈
- 전 상장사 재무지표 수집 + 엑셀 다운로드
- 기존 overview 캐시 + finstate 캐시 활용
- 캐시 미존재 종목은 네이버 wisereport 크롤링
"""
import pandas as pd
import numpy as np
from datetime import datetime
import time
import threading
import os
import json
import warnings
warnings.filterwarnings('ignore')
from utils import CACHE_DIR, get_cache, set_cache, crawl_wisereport, format_excel


# (openpyxl 서식은 utils.py의 format_excel에서 처리)

# ── 상태 관리 ──
shopping_status = {
    'running': False,
    'progress': 0,
    'total': 0,
    'current_stock': '',
    'cached_count': 0,
    'fetched_count': 0,
    'error_count': 0,
    'started_at': '',
    'message': '',
}

shopping_results = []
_stop_flag = False


# (캐시 함수/디렉토리, wisereport 크롤링은 utils.py에서 import)

def _fetch_overview_from_naver(stock_code, corp_name):
    """네이버 wisereport에서 기업 개요 데이터 크롤링 (crawl_wisereport 사용)"""
    wr = crawl_wisereport(stock_code)
    result = {
        'company': corp_name,
        'stock_code': stock_code,
        'sector': wr.get('sector', ''),
        'sub_sector': wr.get('sub_sector', ''),
        'current_price': wr.get('current_price'),
        'market_cap': wr.get('market_cap'),
        'eps': wr.get('eps'), 'bps': wr.get('bps'),
        'per': wr.get('per'), 'pbr': wr.get('pbr'),
        'roe': None, 'div_yield': wr.get('div_yield'),
        'per_5y': None, 'pbr_5y': None, 'roe_5y': None,
    }
    # ROE 계산
    if result['eps'] and result['bps'] and result['bps'] > 0:
        result['roe'] = round(result['eps'] / result['bps'] * 100, 2)
    return result


def _calc_extra_metrics(stock_code, overview):
    """finstate 캐시에서 PSR, PCR, ROA 추가 계산"""
    psr = None
    pcr = None
    roa = None
    market_cap = overview.get('market_cap')  # 억원 단위

    # finstate 캐시 파일 찾기 (CFS 우선)
    finstate = None
    for suffix in ['CFS', 'OFS']:
        cache_key = f"finstate_{stock_code}_2016_2026_{suffix}"
        data = get_cache(cache_key)
        if data:
            finstate = data
            break

    if not finstate or not market_cap or market_cap <= 0:
        return psr, pcr, roa

    statements = finstate.get('statements', {})

    # ── PSR = 시가총액 ÷ TTM매출액 ──
    income_stmt = statements.get('손익계산서', {})
    income_accounts = income_stmt.get('accounts', [])
    income_data = income_stmt.get('data', {})

    revenue_idx = None
    for i, acc in enumerate(income_accounts):
        nm = acc.get('name', '')
        if nm in ('매출액', '수익(매출액)', '영업수익'):
            revenue_idx = i
            break

    if revenue_idx is not None and income_data:
        sorted_q = sorted(income_data.keys())
        recent_4q = sorted_q[-4:] if len(sorted_q) >= 4 else sorted_q
        ttm_revenue = 0
        q_count = 0
        for qk in recent_4q:
            vals = income_data[qk]
            if revenue_idx < len(vals) and vals[revenue_idx] is not None:
                ttm_revenue += vals[revenue_idx]
                q_count += 1
        if q_count >= 4 and ttm_revenue > 0:
            psr = round(market_cap / ttm_revenue, 2)

    # ── PCR = 시가총액 ÷ TTM영업현금흐름 ──
    cf_stmt = statements.get('현금흐름표', {})
    cf_accounts = cf_stmt.get('accounts', [])
    cf_data = cf_stmt.get('data', {})

    opcf_idx = None
    for i, acc in enumerate(cf_accounts):
        nm = acc.get('name', '')
        if '영업활동' in nm and ('현금흐름' in nm or '현금' in nm):
            opcf_idx = i
            break

    if opcf_idx is not None and cf_data:
        sorted_q = sorted(cf_data.keys())
        recent_4q = sorted_q[-4:] if len(sorted_q) >= 4 else sorted_q
        ttm_opcf = 0
        q_count = 0
        for qk in recent_4q:
            vals = cf_data[qk]
            if opcf_idx < len(vals) and vals[opcf_idx] is not None:
                ttm_opcf += vals[opcf_idx]
                q_count += 1
        if q_count >= 4 and ttm_opcf > 0:
            pcr = round(market_cap / ttm_opcf, 2)

    # ── ROA = TTM 지배순이익 ÷ 자산총계 × 100 ──
    bs_stmt = statements.get('재무상태표', {})
    bs_accounts = bs_stmt.get('accounts', [])
    bs_data = bs_stmt.get('data', {})

    asset_idx = None
    for i, acc in enumerate(bs_accounts):
        nm = acc.get('name', '')
        did = acc.get('data_id', '')
        if nm == '자산총계' or did == 'ifrs-full_Assets':
            asset_idx = i
            break

    ni_idx = None
    for i, acc in enumerate(income_accounts):
        nm = acc.get('name', '')
        if '지배' in nm and '비지배' not in nm:
            ni_idx = i
            break
    if ni_idx is None:
        for i, acc in enumerate(income_accounts):
            if acc.get('name', '') in ('당기순이익', '당기순이익(손실)'):
                ni_idx = i
                break

    if ni_idx is not None and asset_idx is not None and income_data and bs_data:
        sorted_q = sorted(income_data.keys())
        recent_4q = sorted_q[-4:] if len(sorted_q) >= 4 else sorted_q
        ttm_ni = 0
        q_count = 0
        for qk in recent_4q:
            vals = income_data[qk]
            if ni_idx < len(vals) and vals[ni_idx] is not None:
                ttm_ni += vals[ni_idx]
                q_count += 1

        sorted_bs = sorted(bs_data.keys())
        if sorted_bs and q_count >= 4:
            latest_q = sorted_bs[-1]
            vals = bs_data[latest_q]
            if asset_idx < len(vals) and vals[asset_idx] is not None and vals[asset_idx] > 0:
                roa = round(ttm_ni / vals[asset_idx] * 100, 2)

    return psr, pcr, roa


def _get_accounting_type(stock_code):
    """회계기준 (연결/개별) 확인"""
    for suffix in ['CFS', 'OFS']:
        cache_key = f"finstate_{stock_code}_2016_2026_{suffix}"
        data = get_cache(cache_key)
        if data:
            fs_type = data.get('fs_type_used', suffix)
            return '연결' if 'CFS' in fs_type or 'CFS' in suffix else '개별'
    return ''


def _get_fdr_stock_list():
    """FinanceDataReader로 코스피/코스닥 전체 종목 목록 가져오기"""
    try:
        import FinanceDataReader as fdr
        kospi = fdr.StockListing('KOSPI')
        kosdaq = fdr.StockListing('KOSDAQ')
        kospi['시장'] = '코스피'
        kosdaq['시장'] = '코스닥'
        combined = pd.concat([kospi, kosdaq], ignore_index=True)
        return combined
    except Exception:
        return pd.DataFrame()


def run_shopping_collection(dart_instance, get_listed_fn):
    """전 종목 데이터 수집 (백그라운드 스레드)"""
    global shopping_results, shopping_status, _stop_flag
    _stop_flag = False

    shopping_status['running'] = True
    shopping_status['started_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    shopping_status['message'] = 'FDR에서 상장사 목록 조회 중...'

    try:
        _run_shopping_inner(dart_instance, get_listed_fn)
    except Exception as e:
        shopping_status['running'] = False
        shopping_status['message'] = f'오류 발생: {e}'


def _run_shopping_inner(dart_instance, get_listed_fn):
    """실제 수집 로직 (try-except 래핑용)"""
    global shopping_results, shopping_status, _stop_flag

    # FDR로 전체 코스피/코스닥 종목 + 시가총액/종가를 한 번에 가져옴
    fdr_df = _get_fdr_stock_list()
    if fdr_df.empty:
        shopping_status['running'] = False
        shopping_status['message'] = 'FDR 종목 목록 조회 실패'
        return []

    total = len(fdr_df)
    shopping_status['total'] = total
    shopping_status['progress'] = 0
    shopping_status['cached_count'] = 0
    shopping_status['fetched_count'] = 0
    shopping_status['error_count'] = 0
    shopping_status['message'] = f'{total}개 종목 수집 시작...'

    results = []

    for idx, (_, fdr_row) in enumerate(fdr_df.iterrows()):
        if _stop_flag:
            shopping_status['message'] = '사용자에 의해 중지됨'
            break

        stock_code = str(fdr_row.get('Code', '')).strip()
        corp_name = str(fdr_row.get('Name', '')).strip()
        market_type = fdr_row.get('시장', '')

        # FDR 값 안전하게 숫자 변환
        try:
            fdr_close = float(fdr_row.get('Close', 0) or 0)
        except (ValueError, TypeError):
            fdr_close = 0
        try:
            fdr_marcap = float(fdr_row.get('Marcap', 0) or 0)
        except (ValueError, TypeError):
            fdr_marcap = 0

        if not stock_code or len(stock_code) != 6:
            shopping_status['error_count'] += 1
            continue

        shopping_status['progress'] = idx + 1
        shopping_status['current_stock'] = f'{corp_name} ({stock_code})'

        # FDR에서 시가총액(억원), 주가 기본값
        fdr_marcap_억 = round(fdr_marcap / 100000000) if fdr_marcap > 0 else None
        fdr_price = int(fdr_close) if fdr_close > 0 else None

        # overview 캐시 읽기
        cache_key = f"overview_{stock_code}"
        overview = get_cache(cache_key)

        if overview:
            shopping_status['cached_count'] += 1
        else:
            # 캐시 없으면 네이버에서 간소 크롤링
            try:
                overview = _fetch_overview_from_naver(stock_code, corp_name)
                shopping_status['fetched_count'] += 1
                # rate limit 방지
                time.sleep(0.3)
            except Exception:
                shopping_status['error_count'] += 1
                overview = None

        # overview가 없어도 FDR 데이터로 기본 레코드 생성
        if not overview:
            overview = {
                'company': corp_name,
                'stock_code': stock_code,
                'sector': '', 'sub_sector': '',
                'current_price': fdr_price,
                'market_cap': fdr_marcap_억,
                'eps': None, 'bps': None, 'per': None, 'pbr': None,
                'roe': None, 'div_yield': None,
                'per_5y': None, 'pbr_5y': None, 'roe_5y': None,
            }

        # FDR 데이터로 주가/시총 보완 (overview가 오래된 경우)
        if not overview.get('current_price') and fdr_price:
            overview['current_price'] = fdr_price
        if not overview.get('market_cap') and fdr_marcap_억:
            overview['market_cap'] = fdr_marcap_억

        # ── 시가총액 결정: FDR Marcap(종목별 Close×Stocks) 우선 사용 ──
        # 네이버 wisereport는 우선주 코드로 조회해도 회사 전체 시가총액을 반환하므로
        # FDR의 개별 종목 시가총액이 더 정확함 (특히 우선주)
        final_marcap_억 = fdr_marcap_억 if fdr_marcap_억 else overview.get('market_cap')

        # 추가 지표 계산 (finstate 캐시 있으면)
        # PSR/PCR/ROA는 시가총액 기반이므로 overview의 market_cap 임시 교체
        saved_mc = overview.get('market_cap')
        if final_marcap_억:
            overview['market_cap'] = final_marcap_억
        psr, pcr, roa = _calc_extra_metrics(stock_code, overview)
        overview['market_cap'] = saved_mc  # 복원

        # PER Index (5년): 현재PER ÷ 5년평균PER
        per_val = overview.get('per')
        per_5y = overview.get('per_5y')
        pei = round(per_val / per_5y, 2) if per_val and per_5y and per_5y > 0 else None

        # PBR Index (5년): 현재PBR ÷ 5년평균PBR
        pbr_val = overview.get('pbr')
        pbr_5y = overview.get('pbr_5y')
        pbi = round(pbr_val / pbr_5y, 2) if pbr_val and pbr_5y and pbr_5y > 0 else None

        roe_val = overview.get('roe')
        roe_5y = overview.get('roe_5y')
        acct_type = _get_accounting_type(stock_code)

        rec = {
            '종목명': overview.get('company', corp_name),
            '종목코드': stock_code,
            '시장': market_type,
            '업종': overview.get('sector', ''),
            '세부업종': overview.get('sub_sector', ''),
            '회계기준': acct_type,
            '시가총액(억)': final_marcap_억,
            '주가': overview.get('current_price') or fdr_price,
            '현재PER': per_val,
            '5년PER': pei,
            'PBR': pbr_val,
            '5년PBR': pbi,
            'PSR': psr,
            'PCR': pcr,
            'ROE': roe_val,
            '5년ROE': roe_5y,
            'ROA': roa,
            'EPS': overview.get('eps'),
            'BPS': overview.get('bps'),
            '배당수익률': overview.get('div_yield'),
        }
        results.append(rec)

    shopping_results = results
    shopping_status['running'] = False
    if not _stop_flag:
        shopping_status['message'] = f'완료! {len(results)}개 종목 수집'
    # 수집 결과를 파일로 저장 (서버 재시작 후에도 유지)
    _save_shopping_results(results)
    return results


def start_shopping_thread(dart_instance, get_listed_fn):
    """스크리닝 스레드 시작"""
    global _stop_flag
    if shopping_status['running']:
        return {'error': '이미 실행 중입니다'}
    _stop_flag = False
    t = threading.Thread(
        target=run_shopping_collection,
        args=(dart_instance, get_listed_fn),
        daemon=True
    )
    t.start()
    return {'status': 'started'}


def stop_shopping():
    """수집 중지"""
    global _stop_flag
    _stop_flag = True
    return {'status': 'stopped'}


_SHOPPING_CACHE_FILE = os.path.join(CACHE_DIR, 'shopping_results.json')


def _save_shopping_results(results):
    """수집 결과를 JSON 파일로 저장"""
    try:
        with open(_SHOPPING_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump({'updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                       'data': results}, f, ensure_ascii=False)
    except Exception:
        pass


def _load_shopping_results():
    """저장된 수집 결과를 파일에서 로드"""
    try:
        with open(_SHOPPING_CACHE_FILE, 'r', encoding='utf-8') as f:
            obj = json.load(f)
            return obj.get('data', [])
    except Exception:
        return []


def get_shopping_data():
    """현재 수집된 결과 반환 (메모리에 없으면 파일에서 로드)"""
    global shopping_results
    if not shopping_results:
        shopping_results = _load_shopping_results()
    return shopping_results


COLUMNS_ORDER = [
    '순위', '종목명', '종목코드', '시장', '업종', '세부업종', '회계기준',
    '시가총액(억)', '주가', '현재PER', '5년PER', 'PBR', '5년PBR',
    'PSR', 'PCR', 'ROE', '5년ROE', 'ROA', 'EPS', 'BPS', '배당수익률',
]


def generate_shopping_excel(data=None):
    """엑셀 파일 생성"""
    if data is None:
        data = shopping_results
    if not data:
        return None

    df = pd.DataFrame(data)

    # 시가총액 기준 내림차순 정렬 + 순위 부여
    df = df.sort_values('시가총액(억)', ascending=False, na_position='last').reset_index(drop=True)
    df.insert(0, '순위', range(1, len(df) + 1))

    # 컬럼 순서 맞추기
    available_cols = [c for c in COLUMNS_ORDER if c in df.columns]
    df = df[available_cols]

    # 파일 생성
    today = datetime.now().strftime('%Y%m%d_%H%M')
    excel_path = os.path.join(CACHE_DIR, f'종목쇼핑_전종목_{today}.xlsx')
    os.makedirs(os.path.dirname(excel_path), exist_ok=True)
    df.to_excel(excel_path, index=False, sheet_name='종목쇼핑')

    # 서식 적용
    format_excel(excel_path, available_cols, {
        'header_color': '2F5496',
        'accent_color': '548235',
        'accent_cols': ['5년PER', '5년PBR', '5년ROE'],
        'decimal_cols': ['현재PER', '5년PER', 'PBR', '5년PBR', 'PSR', 'PCR', 'ROE', '5년ROE', 'ROA', '배당수익률'],
        'int_cols': ['순위', '시가총액(억)', '주가', 'EPS', 'BPS'],
        'width_map': {'순위': 6, '종목명': 16, '종목코드': 10, '시장': 8,
                      '업종': 18, '세부업종': 22, '회계기준': 8, '시가총액(억)': 12, '주가': 10},
        'default_width': 10,
    })

    return excel_path
