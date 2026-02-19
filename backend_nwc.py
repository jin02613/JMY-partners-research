# -*- coding: utf-8 -*-
"""
순운전자본 스크리닝 백엔드 모듈
- stock_screening.py의 핵심 로직을 Flask API용으로 리팩토링
- 기존 엑셀 결과 로드 + 실시간 스크리닝 지원
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import threading
import os
import glob
import requests
from bs4 import BeautifulSoup
import warnings
warnings.filterwarnings('ignore')

try:
    import FinanceDataReader as fdr
except ImportError:
    fdr = None

try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None
from utils import format_excel

# ── 스크리닝 상태 관리 ──
screening_status = {
    'running': False,
    'progress': 0,
    'total': 0,
    'current_stock': '',
    'found_count': 0,
    'skipped_count': 0,
    'error_count': 0,
    'started_at': '',
    'results': [],
    'message': '',
}

# 결과 데이터 (엑셀 로드 또는 스크리닝 결과)
nwc_results = []

# 엑셀 파일 검색 경로
NWC_EXCEL_DIRS = [
    r'E:\07. Claude code\1. Adj. Net Working Capital',
    r'E:\07. What is AI\1. Claude code practice',
]

COLUMNS_ORDER = [
    '종목명', '세부업종', '매출비중',
    '종목코드', '시장', '사용보고서', '재무제표유형', '시가총액',
    '유동자산', '유동부채', '순운전자본', '순운전자본/시총(배)',
    '매출채권', '재고자산', '비유동금융자산', '조정유동자산',
    '매입채무', '장기차입금', '사채', '조정유동부채',
    '조정순운전자본', '조정순운전자본/시총(배)',
    '투자부동산', '관계종속기업투자',
    '대주주지분율', '자사주비율', '발행주식수', '자기주식수'
]


def find_excel_files():
    """NWC 엑셀 결과 파일 목록 검색"""
    files = []
    for d in NWC_EXCEL_DIRS:
        if os.path.exists(d):
            pattern = os.path.join(d, '순운전자본초과_전종목_*.xlsx')
            for f in glob.glob(pattern):
                fname = os.path.basename(f)
                mtime = os.path.getmtime(f)
                files.append({
                    'path': f,
                    'name': fname,
                    'modified': datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M'),
                    'size': round(os.path.getsize(f) / 1024, 1),
                })
    files.sort(key=lambda x: x['modified'], reverse=True)
    return files


def load_excel_results(file_path):
    """엑셀 파일에서 NWC 결과 로드"""
    global nwc_results
    try:
        df = pd.read_excel(file_path)
        # NaN을 빈 문자열/0으로 변환
        records = []
        for _, row in df.iterrows():
            record = {}
            for col in df.columns:
                val = row[col]
                if pd.isna(val):
                    record[col] = '' if isinstance(val, str) or col in ['종목명', '세부업종', '매출비중', '종목코드', '시장', '사용보고서', '재무제표유형'] else 0
                else:
                    record[col] = val
            records.append(record)
        nwc_results = records
        return {'success': True, 'count': len(records), 'file': os.path.basename(file_path)}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def get_results_data():
    """현재 로드된 결과 데이터 반환"""
    return nwc_results


# ── 분석 헬퍼 함수들 (stock_screening.py에서 가져옴) ──

def get_amount(df, keywords, exclude_keywords=None, after_keyword=None):
    """키워드로 금액 찾기 (당기 금액, 억원)"""
    search_df = df
    if after_keyword:
        after_rows = df[df['account_nm'].str.contains(after_keyword, na=False, regex=False)]
        if len(after_rows) > 0:
            after_idx = after_rows.index[0]
            search_df = df.loc[after_idx:]

    for keyword in keywords:
        matches = search_df[search_df['account_nm'].str.contains(keyword, na=False, regex=False)]
        if exclude_keywords:
            for ex_kw in exclude_keywords:
                matches = matches[~matches['account_nm'].str.contains(ex_kw, na=False, regex=False)]
        if len(matches) > 0:
            val = matches.iloc[0]['thstrm_amount']
            if pd.notna(val) and val != '':
                val_str = str(val).replace(',', '').replace('-', '0')
                try:
                    return float(val_str) / 100000000, matches.iloc[0]['account_nm']
                except:
                    pass
    return 0, "N/A"


def get_noncurrent_financial_assets(df):
    """비유동자산 섹션 내 금융자산 합계 (억원)"""
    df = df.reset_index(drop=True)
    noncurrent_start = None
    noncurrent_end = None

    for idx, row in df.iterrows():
        name = str(row['account_nm'])
        if noncurrent_start is None and name.strip() == '비유동자산':
            noncurrent_start = idx
        elif noncurrent_start is not None and noncurrent_end is None:
            if name.strip() in ['자산총계', '부채총계', '유동자산'] or '부채' in name:
                noncurrent_end = idx
                break

    if noncurrent_start is None:
        return 0
    if noncurrent_end is None:
        noncurrent_end = len(df)

    noncurrent_section = df.iloc[noncurrent_start+1:noncurrent_end].reset_index(drop=True)

    # "기타비유동금융자산" 대항목/소항목 판단
    major_idx = None
    major_value = 0
    for idx, row in noncurrent_section.iterrows():
        name = str(row['account_nm']).strip()
        if name == '기타비유동금융자산' or name.startswith('기타비유동금융자산'):
            val = row['thstrm_amount']
            if pd.notna(val) and val != '':
                val_str = str(val).replace(',', '').replace('-', '0')
                try:
                    major_value = float(val_str) / 100000000
                    major_idx = idx
                except:
                    pass
            break

    if major_idx is not None and major_idx + 1 < len(noncurrent_section):
        next_name = str(noncurrent_section.iloc[major_idx + 1]['account_nm'])
        if '금융자산' in next_name:
            return round(major_value, 2)

    total = 0
    for idx, row in noncurrent_section.iterrows():
        name = str(row['account_nm'])
        if '금융자산' in name:
            val = row['thstrm_amount']
            if pd.notna(val) and val != '':
                val_str = str(val).replace(',', '').replace('-', '0')
                try:
                    total += float(val_str) / 100000000
                except:
                    pass
    return round(total, 2)


def get_long_term_debt(df):
    """비유동부채 섹션에서 장기차입금+사채 합계"""
    df = df.reset_index(drop=True)
    noncurrent_start = None
    noncurrent_end = None

    for idx, row in df.iterrows():
        name = str(row['account_nm'])
        if noncurrent_start is None and name.strip() == '비유동부채':
            noncurrent_start = idx
        elif noncurrent_start is not None and noncurrent_end is None:
            if name.strip() in ['부채총계', '자본', '자본총계'] or '자본' in name:
                noncurrent_end = idx
                break

    if noncurrent_start is None:
        return 0, 0
    if noncurrent_end is None:
        noncurrent_end = len(df)

    noncurrent_section = df.iloc[noncurrent_start+1:noncurrent_end]
    long_term_borrowings = 0
    bonds = 0
    found_combined = False

    for idx, row in noncurrent_section.iterrows():
        name = str(row['account_nm'])
        val = row['thstrm_amount']
        if pd.notna(val) and val != '':
            val_str = str(val).replace(',', '').replace('-', '0')
            try:
                amount = float(val_str) / 100000000
            except:
                continue

            if ('장기차입금' in name or '비유동차입금' in name) and '사채' in name:
                long_term_borrowings = amount
                found_combined = True
            elif not found_combined and ('장기차입금' in name or '비유동차입금' in name):
                if '전환' not in name and '신주인수권' not in name:
                    long_term_borrowings = amount
            elif not found_combined and ('사채' in name or '회사채' in name):
                if '전환사채' not in name and '신주인수권부사채' not in name and '장기차입금' not in name:
                    bonds = amount

    return round(long_term_borrowings, 2), round(bonds, 2)


def analyze_single_company(dart, stock_code, stock_name, market, stocks):
    """단일 기업 조정순운전자본 분석"""
    result = {
        '종목명': stock_name, '종목코드': stock_code, '시장': market,
        '사용보고서': '', '재무제표유형': '', '시가총액': 0,
        '유동자산': 0, '유동부채': 0, '순운전자본': 0, '순운전자본/시총(배)': 0,
        '매출채권': 0, '재고자산': 0, '비유동금융자산': 0, '조정유동자산': 0,
        '매입채무': 0, '장기차입금': 0, '사채': 0, '조정유동부채': 0,
        '조정순운전자본': 0, '조정순운전자본/시총(배)': 0,
        '투자부동산': 0, '관계종속기업투자': 0,
        '대주주지분율': 0, '자사주비율': 0, '발행주식수': 0, '자기주식수': 0,
        '세부업종': '', '매출비중': '',
    }

    try:
        # 종가 가져오기
        if fdr is None:
            return None
        start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        try:
            price_df = fdr.DataReader(stock_code, start_date)
            if price_df is None or len(price_df) == 0:
                return None
            close_price = price_df['Close'].iloc[-1]
        except:
            return None

        if close_price == 0 or stocks == 0:
            return None
        market_cap = (close_price * stocks) / 100000000
        result['시가총액'] = round(market_cap, 2)

        # DART 기업코드 조회
        corp_info = dart.company(stock_code)
        if corp_info is None:
            return None
        corp_code = corp_info['corp_code']

        # 재무제표 가져오기
        fs_data = None
        report_attempts = [
            (2025, '11014', 'CFS', '2025년 3분기 (연결)'),
            (2025, '11014', 'OFS', '2025년 3분기 (개별)'),
            (2025, '11012', 'CFS', '2025년 반기 (연결)'),
            (2025, '11012', 'OFS', '2025년 반기 (개별)'),
            (2025, '11013', 'CFS', '2025년 1분기 (연결)'),
            (2025, '11013', 'OFS', '2025년 1분기 (개별)'),
            (2024, '11011', 'CFS', '2024년 사업보고서 (연결)'),
            (2024, '11011', 'OFS', '2024년 사업보고서 (개별)'),
        ]

        for year, reprt_code, fs_div, desc in report_attempts:
            try:
                fs_data = dart.finstate_all(corp_code, year, reprt_code, fs_div=fs_div)
                if fs_data is not None and len(fs_data) > 0:
                    result['사용보고서'] = desc
                    result['재무제표유형'] = "연결" if fs_div == 'CFS' else "개별"
                    break
            except:
                continue

        if fs_data is None or len(fs_data) == 0:
            return None

        bs_data = fs_data[fs_data['sj_nm'].str.contains('재무상태표', na=False)]
        if len(bs_data) == 0:
            return None

        # 유동자산, 유동부채
        current_assets, _ = get_amount(bs_data, ['유동자산'])
        current_liabilities, _ = get_amount(bs_data, ['유동부채'])
        nwc = current_assets - current_liabilities

        # 조정 항목
        accounts_receivable, _ = get_amount(bs_data, ['매출채권', '외상매출금'])
        inventory, _ = get_amount(bs_data, ['재고자산'])
        noncurrent_financial_assets = get_noncurrent_financial_assets(bs_data)
        accounts_payable, _ = get_amount(bs_data, ['단기매입채무', '유동매입채무', '매입채무'], exclude_keywords=['매입채무 외'])
        if accounts_payable == 0:
            accounts_payable, _ = get_amount(bs_data, ['매입채무 및'])
        long_term_borrowings, bonds_val = get_long_term_debt(bs_data)

        adj_current_assets = current_assets - accounts_receivable - inventory + noncurrent_financial_assets
        adj_current_liabilities = current_liabilities - accounts_payable + long_term_borrowings + bonds_val
        adj_nwc = adj_current_assets - adj_current_liabilities

        # 조정순운전자본 < 시총이면 스킵
        if adj_nwc < market_cap:
            return None

        result['유동자산'] = round(current_assets, 2)
        result['유동부채'] = round(current_liabilities, 2)
        result['순운전자본'] = round(nwc, 2)
        result['순운전자본/시총(배)'] = round(nwc / market_cap, 2) if market_cap > 0 else 0
        result['매출채권'] = round(accounts_receivable, 2)
        result['재고자산'] = round(inventory, 2)
        result['비유동금융자산'] = round(noncurrent_financial_assets, 2)
        result['매입채무'] = round(accounts_payable, 2)
        result['장기차입금'] = round(long_term_borrowings, 2)
        result['사채'] = round(bonds_val, 2)
        result['조정유동자산'] = round(adj_current_assets, 2)
        result['조정유동부채'] = round(adj_current_liabilities, 2)
        result['조정순운전자본'] = round(adj_nwc, 2)
        result['조정순운전자본/시총(배)'] = round(adj_nwc / market_cap, 2) if market_cap > 0 else 0

        # 투자부동산
        investment_property, _ = get_amount(bs_data, ['투자부동산'])
        result['투자부동산'] = round(investment_property, 2)

        # 관계/종속기업 투자
        inv1, _ = get_amount(bs_data, ['관계기업투자', '관계기업에 대한 투자'])
        inv2, _ = get_amount(bs_data, ['종속기업투자', '종속기업에 대한 투자'])
        inv3, _ = get_amount(bs_data, ['지분법적용', '지분법'])
        result['관계종속기업투자'] = round(inv1 + inv2 + inv3, 2)

        # 대주주/자사주
        report_attempts_for_shares = [
            (2025, '11014'), (2025, '11012'), (2025, '11013'), (2024, '11011'),
        ]
        for r_year, r_code in report_attempts_for_shares:
            if result['대주주지분율'] > 0:
                break
            try:
                major_df = dart.report(corp_code, '최대주주', r_year, r_code)
                if major_df is not None and len(major_df) > 0:
                    total_rows = major_df[major_df['nm'].str.strip() == '계']
                    for _, row in total_rows.iterrows():
                        rate = row['trmend_posesn_stock_qota_rt']
                        if rate != '-' and pd.notna(rate) and str(rate).strip():
                            result['대주주지분율'] = float(str(rate).replace(',', ''))
                            break
            except:
                continue

        for r_year, r_code in report_attempts_for_shares:
            if result['발행주식수'] > 0:
                break
            try:
                stock_df = dart.report(corp_code, '주식총수', r_year, r_code)
                if stock_df is not None and len(stock_df) > 0:
                    total_row = stock_df[stock_df['se'].str.contains('보통주|합계', na=False)]
                    if len(total_row) > 0:
                        row = total_row.iloc[0]
                        issued = str(row['istc_totqy']).replace(',', '').replace('-', '0')
                        treasury = str(row['tesstk_co']).replace(',', '').replace('-', '0')
                        if issued.isdigit() and int(issued) > 0:
                            issued_num = int(issued)
                            treasury_num = int(treasury) if treasury.isdigit() else 0
                            result['발행주식수'] = issued_num
                            result['자기주식수'] = treasury_num
                            result['자사주비율'] = round(treasury_num / issued_num * 100, 2)
            except:
                continue

        return result
    except Exception:
        return None


def run_full_screening(dart):
    """전종목 스크리닝 (백그라운드 스레드)"""
    global screening_status, nwc_results

    if fdr is None:
        screening_status['message'] = 'FinanceDataReader 미설치'
        screening_status['running'] = False
        return

    screening_status['running'] = True
    screening_status['started_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    screening_status['results'] = []
    screening_status['found_count'] = 0
    screening_status['skipped_count'] = 0
    screening_status['error_count'] = 0
    screening_status['message'] = '상장 기업 목록 로딩 중...'

    try:
        # KRX 상장 기업 목록
        krx_list = fdr.StockListing('KRX-MARCAP')
        kospi_codes = set(fdr.StockListing('KOSPI')['Code'].tolist())
        kosdaq_codes = set(fdr.StockListing('KOSDAQ')['Code'].tolist())
        krx_list['시장'] = krx_list['Code'].apply(
            lambda x: 'KOSPI' if x in kospi_codes else ('KOSDAQ' if x in kosdaq_codes else 'OTHER')
        )
        krx_list = krx_list[krx_list['시장'].isin(['KOSPI', 'KOSDAQ'])]
        krx_list = krx_list[~krx_list['Name'].str.contains('스팩', na=False)]

        total = len(krx_list)
        screening_status['total'] = total
        screening_status['message'] = f'{total}개 종목 분석 시작'

        results = []
        for idx, row in krx_list.iterrows():
            if not screening_status['running']:
                screening_status['message'] = '사용자에 의해 중단됨'
                break

            stock_code = row['Code']
            stock_name = row['Name']
            market = row['시장']
            stocks = row['Stocks'] if pd.notna(row['Stocks']) else 0

            screening_status['progress'] = len(results) + screening_status['skipped_count'] + screening_status['error_count'] + 1
            screening_status['current_stock'] = f"{stock_name} ({stock_code})"

            result = analyze_single_company(dart, stock_code, stock_name, market, stocks)
            if result:
                results.append(result)
                screening_status['found_count'] = len(results)
            else:
                screening_status['skipped_count'] += 1

            time.sleep(0.05)

        # 정렬
        if results:
            df_results = pd.DataFrame(results)
            df_results = df_results.sort_values('조정순운전자본/시총(배)', ascending=False)
            nwc_results = df_results.to_dict('records')
            screening_status['results'] = nwc_results

        screening_status['message'] = f'완료: {len(results)}개 종목 발견'
    except Exception as e:
        screening_status['message'] = f'오류: {str(e)}'
    finally:
        screening_status['running'] = False


def start_screening_thread(dart):
    """스크리닝을 백그라운드 스레드에서 실행"""
    if screening_status['running']:
        return {'success': False, 'message': '이미 스크리닝이 진행 중입니다'}
    thread = threading.Thread(target=run_full_screening, args=(dart,), daemon=True)
    thread.start()
    return {'success': True, 'message': '스크리닝 시작'}


def stop_screening():
    """스크리닝 중지"""
    screening_status['running'] = False
    return {'success': True, 'message': '중지 요청됨'}


def generate_excel_download(results_data):
    """결과 데이터를 엑셀 파일로 생성하여 경로 반환"""
    if not results_data:
        return None

    df = pd.DataFrame(results_data)

    # 컬럼 순서 맞추기
    available_cols = [c for c in COLUMNS_ORDER if c in df.columns]
    df = df[available_cols]
    df = df.sort_values('조정순운전자본/시총(배)', ascending=False)

    # 임시 파일 생성
    today = datetime.now().strftime('%Y%m%d_%H%M')
    excel_path = os.path.join(
        r'E:\07. Claude code\2. Financial Statements\cache',
        f'순운전자본초과_전종목_{today}.xlsx'
    )
    os.makedirs(os.path.dirname(excel_path), exist_ok=True)
    df.to_excel(excel_path, index=False, sheet_name='분석결과')

    # 엑셀 서식 적용
    format_excel(excel_path, available_cols, {
        'header_color': 'FFA500',
        'accent_color': '228B22',
        'accent_cols': ['조정유동자산', '조정유동부채', '조정순운전자본/시총(배)'],
        'decimal_cols': ['순운전자본/시총(배)', '조정순운전자본/시총(배)', '대주주지분율', '자사주비율'],
        'int_cols': ['시가총액', '유동자산', '유동부채', '순운전자본', '매출채권', '재고자산',
                     '비유동금융자산', '조정유동자산', '매입채무', '장기차입금',
                     '사채', '조정유동부채', '조정순운전자본', '투자부동산', '관계종속기업투자',
                     '발행주식수', '자기주식수'],
        'width_map': {'세부업종': 50, '매출비중': 50, '종목명': 15, '사용보고서': 20},
        'default_width': 12,
    })

    return excel_path
