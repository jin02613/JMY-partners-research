# -*- coding: utf-8 -*-
"""
전체 재무제표 데이터 백엔드 모듈 (10년 데이타 탭용)
- DART API에서 손익계산서/재무상태표/현금흐름표 전체 항목 수집
- account_id 기반 올바른 재무제표 순서 정렬 + 카테고리 헤더 지원
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from backend_nwc import get_amount, get_noncurrent_financial_assets, get_long_term_debt
from utils import QUARTER_CODES, apply_restatement


STATEMENT_TYPES = {
    '손익계산서': ['손익계산서', '포괄손익계산서'],
    '재무상태표': ['재무상태표'],
    '현금흐름표': ['현금흐름표'],
}

# (QUARTER_CODES는 utils.py에서 import)

# IFRS 기준 손익계산서 account_id 표시 순서 (카테고리 헤더 포함)
INCOME_STMT_ORDER = [
    {'id': 'ifrs-full_Revenue', 'is_header': False},
    {'id': 'ifrs-full_CostOfSales', 'is_header': False},
    {'id': 'ifrs-full_GrossProfit', 'is_header': False},
    {'id': 'dart_TotalSellingGeneralAdministrativeExpenses', 'is_header': False},
    {'id': 'dart_OperatingIncomeLoss', 'is_header': False},
    {'id': 'dart_OtherGains', 'is_header': False},
    {'id': 'dart_OtherLosses', 'is_header': False},
    {'id': 'ifrs-full_ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod', 'is_header': False},
    {'id': 'ifrs-full_FinanceIncome', 'is_header': False},
    {'id': 'ifrs-full_FinanceCosts', 'is_header': False},
    {'id': 'ifrs-full_ProfitLossBeforeTax', 'is_header': False},
    {'id': 'ifrs-full_IncomeTaxExpenseContinuingOperations', 'is_header': False},
    {'id': 'ifrs-full_ProfitLoss', 'is_header': False, 'display_name': '당기순이익'},
    # 카테고리 헤더: 당기순이익의 귀속
    {'id': '_header_profit_attribution', 'name': '당기순이익의 귀속', 'is_header': True},
    {'id': 'ifrs-full_ProfitLossAttributableToOwnersOfParent', 'is_header': False},
    {'id': 'ifrs-full_ProfitLossAttributableToNoncontrollingInterests', 'is_header': False},
    # 카테고리 헤더: 주당이익
    {'id': '_header_eps', 'name': '주당이익', 'is_header': True},
    {'id': 'ifrs-full_BasicEarningsLossPerShare', 'is_header': False},
    {'id': 'ifrs-full_DilutedEarningsLossPerShare', 'is_header': False},
]

# IFRS 기준 포괄손익계산서 account_id 표시 순서 (2025 Q3 보고서 기준)
# level: 1=대항목(기타포괄손익/총포괄손익, +버튼), 2=중항목(비재분류/재분류, +버튼), 3=소항목(접기대상)
# 현금흐름표와 동일한 L1/L2/L3 패턴
COMPREHENSIVE_STMT_ORDER = [
    {'id': 'ifrs-full_ProfitLoss', 'is_header': False, 'display_name': '당기순이익',
     'match_names': ['당기순이익', '당기순이익(손실)', '분기순이익', '분기순이익(손실)', '반기순이익']},
    # ── 기타포괄손익 (L1: +버튼, 하위 전체 접기/펼치기) ──
    {'id': '_header_oci', 'name': '기타포괄손익', 'is_header': True, 'level': 1,
     'data_id': 'ifrs-full_OtherComprehensiveIncome'},
    # 비재분류 (L2: +버튼, L3 접기/펼치기)
    {'id': '_header_oci_not_reclass', 'name': '후속적으로 당기손익으로 재분류되지 않는 포괄손익', 'is_header': True, 'level': 2,
     'data_id': 'ifrs-full_OtherComprehensiveIncomeThatWillNotBeReclassifiedToProfitOrLossNetOfTax',
     'alt_ids': ['dart_OtherComprehensiveIncomeThatWillNotBeReclassifiedToProfitOrLossNetOfTax'],
     'match_names': ['후속적으로 당기손익으로 재분류되지 않는 포괄손익', '후속적으로 당기손익으로 재분류되지 않는 항목']},
    {'id': 'ifrs-full_OtherComprehensiveIncomeNetOfTaxGainsLossesFromInvestmentsInEquityInstruments', 'is_header': False, 'level': 3,
     'display_name': '기타포괄손익-공정가치금융자산평가손익',
     'match_names': ['기타포괄손익-공정가치금융자산평가손익']},
    {'id': 'ifrs-full_ShareOfOtherComprehensiveIncomeOfAssociatesAndJointVenturesAccountedForUsingEquityMethodThatWillNotBeReclassifiedToProfitOrLossNetOfTax',
     'is_header': False, 'level': 3,
     'alt_ids': ['dart_ShareOfOtherComprehensiveIncomeOfAssociatesAndJointVenturesAccountedForUsingEquityMethodThatWillNotBeReclassifiedToProfitOrLossNetOfTax'],
     'display_name': '관계기업 및 공동기업의 기타포괄손익 지분(비재분류)'},
    {'id': 'ifrs-full_OtherComprehensiveIncomeNetOfTaxGainsLossesOnRemeasurementsOfDefinedBenefitPlans', 'is_header': False, 'level': 3,
     'alt_ids': ['dart_OtherComprehensiveIncomeNetOfTaxGainsLossesOnRemeasurementsOfDefinedBenefitPlans'],
     'display_name': '순확정급여부채 재측정요소',
     'match_names': ['순확정급여부채 재측정요소', '순확정급여부채(자산) 재측정요소']},
    # 재분류 (L2: +버튼, L3 접기/펼치기)
    {'id': '_header_oci_reclass', 'name': '후속적으로 당기손익으로 재분류되는 포괄손익', 'is_header': True, 'level': 2,
     'data_id': 'ifrs-full_OtherComprehensiveIncomeThatWillBeReclassifiedToProfitOrLossNetOfTax',
     'alt_ids': ['dart_OtherComprehensiveIncomeThatWillBeReclassifiedToProfitOrLossNetOfTax'],
     'match_names': ['후속적으로 당기손익으로 재분류되는 포괄손익', '후속적으로 당기손익으로 재분류되는 항목']},
    {'id': 'ifrs-full_OtherComprehensiveIncomeNetOfTaxAvailableforsaleFinancialAssets', 'is_header': False, 'level': 3,
     'display_name': '매도가능금융자산평가손익',
     'match_names': ['매도가능금융자산평가손익']},
    {'id': 'ifrs-full_ShareOfOtherComprehensiveIncomeOfAssociatesAndJointVenturesAccountedForUsingEquityMethodThatWillBeReclassifiedToProfitOrLossNetOfTax',
     'is_header': False, 'level': 3,
     'alt_ids': ['dart_ShareOfOtherComprehensiveIncomeOfAssociatesAndJointVenturesAccountedForUsingEquityMethodThatWillBeReclassifiedToProfitOrLossNetOfTax'],
     'display_name': '관계기업 및 공동기업의 기타포괄손익 지분(재분류)'},
    {'id': 'ifrs-full_GainsLossesOnExchangeDifferencesOnTranslationNetOfTax', 'is_header': False, 'level': 3,
     'display_name': '해외사업장환산외환차이',
     'match_names': ['해외사업장환산외환차이']},
    {'id': 'ifrs-full_GainsLossesOnCashFlowHedgesNetOfTax', 'is_header': False, 'level': 3,
     'display_name': '현금흐름위험회피파생상품평가손익',
     'match_names': ['현금흐름위험회피파생상품평가손익']},
    # ── 총포괄손익 (L1: +버튼으로 귀속 하위 접기/펼치기) ──
    {'id': '_header_ci', 'name': '총포괄손익', 'is_header': True, 'level': 1,
     'data_id': 'ifrs-full_ComprehensiveIncome',
     'match_names': ['총포괄손익', '분기총포괄손익', '반기총포괄손익']},
    {'id': 'ifrs-full_ComprehensiveIncomeAttributableToOwnersOfParent', 'is_header': False},
    {'id': 'ifrs-full_ComprehensiveIncomeAttributableToNoncontrollingInterests', 'is_header': False},
]

# 손익계산서 + 포괄손익계산서 통합 ORDER
# 손익계산서 항목 뒤에 포괄손익계산서 항목(당기순이익 제외)을 붙임
COMBINED_INCOME_ORDER = INCOME_STMT_ORDER + COMPREHENSIVE_STMT_ORDER[1:]  # [1:]로 당기순이익 중복 제거

# IFRS 기준 재무상태표 account_id 표시 순서
# level: 1=대항목(자산총계 등, 항상 표시), 2=중항목(유동자산 등, 항상 표시+접기버튼)
# data_id: 헤더 행에 표시할 합계 account_id
BALANCE_SHEET_ORDER = [
    # ── 자산 ── (2025 Q3 보고서 순서 기준)
    {'id': '_header_assets', 'name': '자산총계', 'is_header': True, 'level': 1, 'data_id': 'ifrs-full_Assets'},
    {'id': '_header_current_assets', 'name': '유동자산', 'is_header': True, 'level': 2, 'data_id': 'ifrs-full_CurrentAssets'},
    {'id': 'ifrs-full_CashAndCashEquivalents', 'is_header': False},
    {'id': 'ifrs-full_ShorttermDepositsNotClassifiedAsCashEquivalents', 'is_header': False,
     'alt_ids': ['dart_ShortTermDepositsNotClassifiedAsCashEquivalents']},
    {'id': 'ifrs-full_CurrentFinancialAssetsAtFairValueThroughProfitOrLoss', 'is_header': False,
     'alt_ids': ['ifrs-full_CurrentFinancialAssetsAtFairValueThroughProfitOrLossMandatorilyMeasuredAtFairValue'],
     'match_names': ['단기당기손익-공정가치금융자산', '유동 당기손익-공정가치측정금융자산', '유동 당기손익-공정가치금융자산']},
    {'id': 'ifrs-full_CurrentFinancialAssetsAtAmortisedCost', 'is_header': False,
     'match_names': ['단기상각후원가금융자산']},
    {'id': 'ifrs-full_CurrentTradeReceivables', 'is_header': False,
     'alt_ids': ['dart_ShortTermTradeReceivable', 'ifrs-full_TradeAndOtherCurrentReceivables'],
     'match_names': ['매출채권', '매출채권 및 기타유동채권']},
    {'id': 'dart_ShortTermOtherReceivablesNet', 'is_header': False,
     'match_names': ['미수금']},
    {'id': 'ifrs-full_Prepayments', 'is_header': False,
     'match_names': ['선급금']},
    {'id': 'ifrs-full_CurrentPrepaidExpenses', 'is_header': False,
     'match_names': ['선급비용']},
    {'id': 'ifrs-full_CurrentContractAssets', 'is_header': False,
     'match_names': ['계약자산', '유동계약자산']},
    {'id': 'dart_ShortTermLoansReceivable', 'is_header': False,
     'match_names': ['대여금 및 관련채권', '단기대여금', '유동 대여금 및 관련채권']},
    {'id': 'ifrs-full_CurrentTaxAssets', 'is_header': False,
     'match_names': ['당기법인세자산']},
    {'id': 'ifrs-full_Inventories', 'is_header': False},
    {'id': 'ifrs-full_OtherCurrentAssets', 'is_header': False,
     'alt_ids': ['dart_OtherCurrentAssets']},
    {'id': 'ifrs-full_NoncurrentAssetsOrDisposalGroupsClassifiedAsHeldForSaleOrAsHeldForDistributionToOwners', 'is_header': False,
     'match_names': ['매각예정분류자산']},
    {'id': '_header_noncurrent_assets', 'name': '비유동자산', 'is_header': True, 'level': 2, 'data_id': 'ifrs-full_NoncurrentAssets'},
    {'id': 'ifrs-full_InvestmentsInSubsidiariesJointVenturesAndAssociates', 'is_header': False,
     'match_names': ['종속기업투자', '종속기업에 대한 투자', '관계종속기업투자', '종속·관계기업투자']},
    {'id': 'ifrs-full_InvestmentAccountedForUsingEquityMethod', 'is_header': False,
     'match_names': ['관계기업 및 공동기업 투자', '관계기업투자', '관계기업에 대한 투자', '지분법적용투자']},
    {'id': 'dart_LongTermFinancialInstruments', 'is_header': False,
     'match_names': ['장기금융상품']},
    {'id': 'dart_LongTermLoansReceivable', 'is_header': False,
     'match_names': ['장기대여금', '장기대여금 및 관련채권', '비유동 대여금 및 관련채권']},
    {'id': 'ifrs-full_PropertyPlantAndEquipment', 'is_header': False},
    {'id': 'ifrs-full_RightofuseAssets', 'is_header': False,
     'match_names': ['사용권자산']},
    {'id': 'ifrs-full_InvestmentProperty', 'is_header': False,
     'match_names': ['투자부동산']},
    {'id': 'ifrs-full_IntangibleAssetsAndGoodwill', 'is_header': False,
     'alt_ids': ['ifrs-full_IntangibleAssetsOtherThanGoodwill'], 'match_names': ['무형자산']},
    {'id': 'ifrs-full_NoncurrentFinancialAssetsAtFairValueThroughProfitOrLoss', 'is_header': False,
     'alt_ids': ['dart_NonCurrentFairValueFinancialAsset'],
     'match_names': ['장기당기손익-공정가치금융자산', '당기손익-공정가치금융자산', '비유동 당기손익-공정가치측정금융자산', '비유동 당기손익-공정가치금융자산']},
    {'id': 'ifrs-full_NoncurrentFinancialAssetsMeasuredAtFairValueThroughOtherComprehensiveIncome', 'is_header': False,
     'match_names': ['기타포괄손익-공정가치금융자산', '장기기타포괄손익-공정가치금융자산']},
    {'id': 'ifrs-full_NoncurrentRecognisedAssetsDefinedBenefitPlan', 'is_header': False,
     'alt_ids': ['dart_DepositsForSeveranceInsurance'], 'match_names': ['순확정급여자산']},
    {'id': 'ifrs-full_DeferredTaxAssets', 'is_header': False},
    {'id': 'ifrs-full_OtherNoncurrentAssets', 'is_header': False,
     'alt_ids': ['dart_OtherNonCurrentAssets']},
    # ── 부채 ── (2025 Q3 보고서 순서 기준)
    {'id': '_header_liabilities', 'name': '부채총계', 'is_header': True, 'level': 1, 'data_id': 'ifrs-full_Liabilities'},
    {'id': '_header_current_liabilities', 'name': '유동부채', 'is_header': True, 'level': 2, 'data_id': 'ifrs-full_CurrentLiabilities'},
    {'id': 'ifrs-full_TradeAndOtherCurrentPayablesToTradeSuppliers', 'is_header': False,
     'alt_ids': ['ifrs-full_TradeAndOtherCurrentPayables'],
     'match_names': ['매입채무', '매입채무 및 기타유동채무']},
    {'id': 'ifrs-full_ShorttermBorrowings', 'is_header': False,
     'match_names': ['단기차입금']},
    {'id': 'ifrs-full_OtherCurrentPayables', 'is_header': False,
     'match_names': ['미지급금']},
    {'id': 'ifrs-full_CurrentAdvances', 'is_header': False,
     'match_names': ['선수금']},
    {'id': 'dart_ShortTermWithholdings', 'is_header': False,
     'match_names': ['예수금']},
    {'id': 'ifrs-full_AccrualsClassifiedAsCurrent', 'is_header': False,
     'match_names': ['미지급비용']},
    {'id': 'ifrs-full_CurrentTaxLiabilities', 'is_header': False},
    {'id': 'ifrs-full_CurrentPortionOfLongtermBorrowings', 'is_header': False,
     'match_names': ['유동성장기부채']},
    {'id': 'ifrs-full_CurrentProvisions', 'is_header': False,
     'match_names': ['충당부채', '유동충당부채']},
    {'id': 'ifrs-full_CurrentContractLiabilities', 'is_header': False,
     'match_names': ['계약부채']},
    {'id': 'ifrs-full_CurrentLeaseLiabilities', 'is_header': False,
     'match_names': ['리스부채', '유동 리스부채']},
    {'id': 'ifrs-full_OtherCurrentLiabilities', 'is_header': False,
     'alt_ids': ['dart_OtherCurrentLiabilities']},
    {'id': 'ifrs-full_LiabilitiesIncludedInDisposalGroupsClassifiedAsHeldForSale', 'is_header': False,
     'match_names': ['매각예정분류부채']},
    {'id': '_header_noncurrent_liabilities', 'name': '비유동부채', 'is_header': True, 'level': 2, 'data_id': 'ifrs-full_NoncurrentLiabilities'},
    {'id': 'ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued', 'is_header': False,
     'alt_ids': ['dart_BondsIssued']},
    {'id': 'ifrs-full_NoncurrentPortionOfNoncurrentLoansReceived', 'is_header': False,
     'alt_ids': ['dart_LongTermBorrowingsGross'],
     'match_names': ['장기차입금']},
    {'id': 'ifrs-full_OtherNoncurrentPayables', 'is_header': False,
     'alt_ids': ['dart_LongTermOtherPayablesGross']},
    {'id': 'ifrs-full_NoncurrentRecognisedLiabilitiesDefinedBenefitPlan', 'is_header': False,
     'alt_ids': ['dart_PostemploymentBenefitObligations'], 'match_names': ['순확정급여부채', '확정급여부채']},
    {'id': 'ifrs-full_NoncurrentLeaseLiabilities', 'is_header': False,
     'match_names': ['비유동 리스부채', '장기리스부채']},
    {'id': 'ifrs-full_DeferredTaxLiabilities', 'is_header': False},
    {'id': 'ifrs-full_NoncurrentProvisions', 'is_header': False,
     'match_names': ['비유동충당부채']},
    {'id': 'ifrs-full_OtherNoncurrentLiabilities', 'is_header': False,
     'alt_ids': ['dart_OtherNonCurrentLiabilities']},
    # ── 자본 ──
    {'id': '_header_equity', 'name': '자본총계', 'is_header': True, 'level': 1, 'data_id': 'ifrs-full_Equity'},
    {'id': '_header_equity_parent', 'name': '지배기업 소유주지분', 'is_header': True, 'level': 2, 'data_id': 'ifrs-full_EquityAttributableToOwnersOfParent'},
    {'id': 'ifrs-full_IssuedCapital', 'is_header': False},
    {'id': 'dart_IssuedCapitalOfPreferredStock', 'is_header': False},
    {'id': 'dart_IssuedCapitalOfCommonStock', 'is_header': False},
    {'id': 'ifrs-full_SharePremium', 'is_header': False},
    {'id': 'ifrs-full_RetainedEarnings', 'is_header': False},
    {'id': 'dart_ElementsOfOtherStockholdersEquity', 'is_header': False},
    # 비지배지분 (자본총계 하위)
    {'id': 'ifrs-full_NoncontrollingInterests', 'is_header': False},
]

# IFRS 기준 현금흐름표 account_id 표시 순서 (2025 Q3 보고서 기준)
# level: 1=대항목(영업/투자/재무활동, 항상 표시), 2=중항목(영업에서 창출된 현금흐름, 항상 표시+접기버튼), 3=소항목(접기 대상)
CASHFLOW_STMT_ORDER = [
    # ── 영업활동현금흐름 ──
    {'id': '_header_operating', 'name': '영업활동현금흐름', 'is_header': True, 'level': 1,
     'data_id': 'ifrs-full_CashFlowsFromUsedInOperatingActivities'},
    {'id': '_header_operating_sub', 'name': '영업에서 창출된 현금흐름', 'is_header': True, 'level': 2,
     'data_id': 'ifrs-full_CashFlowsFromUsedInOperations',
     'match_names': ['영업에서 창출된 현금흐름', '영업에서 창출된 현금']},
    {'id': 'ifrs-full_ProfitLoss', 'is_header': False, 'level': 3, 'display_name': '당기순이익',
     'match_names': ['당기순이익', '당기순이익(손실)', '분기순이익', '분기순이익(손실)', '반기순이익']},
    {'id': 'ifrs-full_AdjustmentsForReconcileProfitLoss', 'is_header': False, 'level': 3,
     'match_names': ['조정']},
    {'id': 'dart_AdjustmentsForAssetsLiabilitiesOfOperatingActivities', 'is_header': False, 'level': 3,
     'match_names': ['영업활동으로 인한 자산부채의 변동', '영업활동으로인한자산부채의변동']},
    {'id': 'ifrs-full_InterestReceivedClassifiedAsOperatingActivities', 'is_header': False,
     'match_names': ['이자의 수취']},
    {'id': 'ifrs-full_InterestPaidClassifiedAsOperatingActivities', 'is_header': False,
     'match_names': ['이자의 지급'], 'negate': True},
    {'id': 'ifrs-full_DividendsReceivedClassifiedAsOperatingActivities', 'is_header': False,
     'match_names': ['배당금 수입', '배당금수입']},
    {'id': 'ifrs-full_IncomeTaxesPaidRefundClassifiedAsOperatingActivities', 'is_header': False,
     'match_names': ['법인세 납부액', '법인세납부액'], 'negate': True},
    # ── 투자활동현금흐름 ──
    {'id': '_header_investing', 'name': '투자활동현금흐름', 'is_header': True, 'level': 1,
     'data_id': 'ifrs-full_CashFlowsFromUsedInInvestingActivities'},
    {'id': 'dart_ShortTermFinancialInstrumentsChange', 'is_header': False,
     'match_names': ['단기금융상품의 순감소(증가)', '단기금융상품의 순증감']},
    {'id': 'dart_ShortTermAmortizedCostChange', 'is_header': False,
     'match_names': ['단기상각후원가금융자산의 순감소(증가)', '단기상각후원가금융자산의 순증감']},
    {'id': 'dart_ShortTermFVPLChange', 'is_header': False,
     'match_names': ['단기당기손익-공정가치금융자산의 순감소(증가)', '단기당기손익-공정가치금융자산의 순증감']},
    {'id': 'dart_ProceedsFromSalesOfLongTermFinancialInstruments', 'is_header': False,
     'match_names': ['장기금융상품의 처분']},
    {'id': 'dart_PurchaseOfLongTermFinancialInstruments', 'is_header': False,
     'match_names': ['장기금융상품의 취득'], 'negate': True},
    {'id': 'dart_ProceedsFromSalesOfFairValueFinancialAsset', 'is_header': False,
     'alt_ids': ['dart_ProceedsFromSalesOfAvailableForSaleFinancialAssets'],
     'match_names': ['당기손익-공정가치금융자산의 처분', '단기매도가능금융자산의 처분']},
    {'id': 'dart_PurchaseOfFairValueFinancialAsset', 'is_header': False,
     'alt_ids': ['dart_PurchaseOfAvailableForSaleFinancialAssets'],
     'match_names': ['당기손익-공정가치금융자산의 취득', '단기매도가능금융자산의 취득'], 'negate': True},
    {'id': 'dart_ProceedsFromSalesOfFinancialAssetsAtFairValueThroughOtherComprehensiveIncome', 'is_header': False,
     'alt_ids': ['dart_ProceedsFromSalesOfNonCurrentAvailableForSaleFinancialAssets'],
     'match_names': ['기타포괄손익-공정가치금융자산의 처분', '장기매도가능금융자산의 처분']},
    {'id': 'dart_PurchaseOfFinancialAssetsAtFairValueThroughOtherComprehensiveIncome', 'is_header': False,
     'alt_ids': ['dart_PurchaseOfNonCurrentAvailableForSaleFinancialAssets'],
     'match_names': ['기타포괄손익-공정가치금융자산의 취득', '장기매도가능금융자산의 취득'], 'negate': True},
    {'id': 'dart_ProceedsFromSalesOfAmortizedCost', 'is_header': False,
     'match_names': ['상각후원가금융자산의 처분']},
    {'id': 'dart_PurchaseOfAmortizedCost', 'is_header': False,
     'match_names': ['상각후원가금융자산의 취득'], 'negate': True},
    {'id': 'ifrs-full_ProceedsFromSalesOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities', 'is_header': False,
     'match_names': ['유형자산의 처분']},
    {'id': 'ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities', 'is_header': False,
     'match_names': ['유형자산의 취득'], 'negate': True},
    {'id': 'ifrs-full_ProceedsFromSalesOfIntangibleAssetsClassifiedAsInvestingActivities', 'is_header': False,
     'match_names': ['무형자산의 처분']},
    {'id': 'ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities', 'is_header': False,
     'match_names': ['무형자산의 취득'], 'negate': True},
    {'id': 'ifrs-full_ProceedsFromSalesOfInvestmentsAccountedForUsingEquityMethod', 'is_header': False,
     'match_names': ['관계기업 및 공동기업 투자의 처분']},
    {'id': 'ifrs-full_PurchaseOfInterestsInInvestmentsAccountedForUsingEquityMethod', 'is_header': False,
     'match_names': ['관계기업 및 공동기업 투자의 취득'], 'negate': True},
    {'id': 'ifrs-full_CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinessesClassifiedAsInvestingActivities', 'is_header': False,
     'match_names': ['사업결합으로 인한 순현금유출액', '사업결합으로 인한 현금유출액'], 'negate': True},
    {'id': 'dart_ProceedsFromSalesOfNonCurrentAssetsOrDisposalGroupsClassifiedAsHeldForSale', 'is_header': False,
     'match_names': ['매각예정분류자산의 처분으로 인한 현금유입액']},
    {'id': 'dart_ProceedsFromBusinessTransfer', 'is_header': False,
     'match_names': ['사업양도로 인한 현급유입액', '사업양도로 인한 현금유입액']},
    {'id': 'ifrs-full_OtherInflowsOutflowsOfCashClassifiedAsInvestingActivities', 'is_header': False,
     'match_names': ['기타투자활동으로 인한 현금유출입액', '현금의 기타유출입']},
    # ── 재무활동현금흐름 ──
    {'id': '_header_financing', 'name': '재무활동현금흐름', 'is_header': True, 'level': 1,
     'data_id': 'ifrs-full_CashFlowsFromUsedInFinancingActivities'},
    {'id': 'ifrs-full_CashFlowsFromUsedInIncreaseDecreaseInCurrentBorrowings', 'is_header': False,
     'match_names': ['단기차입금의 순증가(감소)', '단기차입금의 순증감']},
    {'id': 'dart_ProceedsFromLongTermBorrowings', 'is_header': False,
     'match_names': ['장기차입금의 차입', '사채 및 장기차입금의 차입']},
    {'id': 'ifrs-full_RepaymentsOfNoncurrentBorrowings', 'is_header': False,
     'alt_ids': ['dart_RepaymentsOfLongTermBorrowings'],
     'match_names': ['사채 및 장기차입금의 상환'], 'negate': True},
    {'id': 'dart_AcquisitionOfTreasuryShares', 'is_header': False,
     'alt_ids': ['ifrs-full_PurchaseOfTreasuryShares'],
     'match_names': ['자기주식의 취득'], 'negate': True},
    {'id': 'dart_DispositionOfTreasuryShares', 'is_header': False,
     'match_names': ['자기주식의 처분']},
    {'id': 'ifrs-full_DividendsPaidClassifiedAsFinancingActivities', 'is_header': False,
     'match_names': ['배당금의 지급', '배당금 지급'], 'negate': True},
    {'id': 'dart_NoncontrollingInterestsChange', 'is_header': False,
     'match_names': ['비지배지분의 증감']},
    # ── 기타 (그룹 밖 대항목) ──
    {'id': 'ifrs-full_EffectOfExchangeRateChangesOnCashAndCashEquivalents', 'is_header': False, 'is_total': True,
     'match_names': ['외화환산으로 인한 현금의 변동']},
    {'id': 'ifrs-full_IncreaseDecreaseInCashAndCashEquivalents', 'is_header': False, 'is_total': True,
     'match_names': ['현금및현금성자산의 증가(감소)', '현금및현금성자산의 순증감', '현금 및 현금성자산의 순증가(감소)']},
    {'id': 'dart_CashAndCashEquivalentsAtBeginningOfPeriodCf', 'is_header': False, 'is_total': True,
     'match_names': ['기초의 현금및현금성자산', '기초 현금 및 현금성자산']},
    {'id': 'dart_CashAndCashEquivalentsAtEndOfPeriodCf', 'is_header': False, 'is_total': True,
     'match_names': ['분기말의 현금및현금성자산', '기말의 현금및현금성자산', '기말 현금 및 현금성자산']},
]


def _alt_account_id(acct_id):
    """ifrs-full_ ↔ ifrs_ 변환 (DART API 구버전/신버전 호환)"""
    if acct_id.startswith('ifrs-full_'):
        return 'ifrs_' + acct_id[len('ifrs-full_'):]
    elif acct_id.startswith('ifrs_') and not acct_id.startswith('ifrs-full_'):
        return 'ifrs-full_' + acct_id[len('ifrs_'):]
    return None


def _build_account_order(raw_data, sj_values, stmt_name):
    """account_id 기반으로 올바른 계정과목 순서 추출 → [{id, name, is_header}] 반환"""

    # 우선순위 정렬표 선택
    if stmt_name == '손익계산서':
        priority_order = COMBINED_INCOME_ORDER
    elif stmt_name == '재무상태표':
        priority_order = BALANCE_SHEET_ORDER
    elif stmt_name == '현금흐름표':
        priority_order = CASHFLOW_STMT_ORDER
    else:
        priority_order = None

    # 모든 분기에서 account_id → account_nm 수집 (최신 이름 우선)
    # ifrs_ ↔ ifrs-full_ 양방향 호환 등록
    # name_to_exists: account_nm이 데이터에 존재하는지 확인용
    id_to_name = {}
    name_to_exists = set()
    for (year, qtr_key), df in sorted(raw_data.items(), reverse=True):
        filtered = df[df['sj_nm'].isin(sj_values)]
        for _, row in filtered.iterrows():
            acct_id = str(row.get('account_id', '')).strip()
            acct_nm = str(row.get('account_nm', '')).strip()
            if acct_nm:
                name_to_exists.add(acct_nm)
            if acct_id and acct_nm and not acct_id.startswith('-'):
                if acct_id not in id_to_name:
                    id_to_name[acct_id] = acct_nm
                # 대체 ID도 등록 (ifrs_ ↔ ifrs-full_ 호환)
                alt_id = _alt_account_id(acct_id)
                if alt_id and alt_id not in id_to_name:
                    id_to_name[alt_id] = acct_nm

    if not id_to_name:
        return []

    if priority_order:
        # 우선순위 표 기반 정렬
        result = []
        seen_ids = set()

        for item in priority_order:
            if item['is_header']:
                data_id = item.get('data_id')
                # 헤더의 match_names 확인 (data_id가 없는 경우 이름 매칭으로 존재 확인)
                header_match_names = item.get('match_names', [])
                header_found = True  # 기본적으로 헤더는 포함
                if data_id:
                    # data_id로 존재 확인
                    if data_id not in id_to_name:
                        auto_alt = _alt_account_id(data_id)
                        if not (auto_alt and auto_alt in id_to_name):
                            # match_names로 폴백
                            header_found = False
                            for nm in header_match_names:
                                if nm in name_to_exists:
                                    header_found = True
                                    break
                if not header_found:
                    continue
                entry = {
                    'id': item['id'],
                    'name': item['name'],
                    'is_header': True,
                }
                if data_id:
                    entry['data_id'] = data_id
                    entry['match_names'] = header_match_names
                    seen_ids.add(data_id)
                    alt = _alt_account_id(data_id)
                    if alt:
                        seen_ids.add(alt)
                if item.get('level'):
                    entry['level'] = item['level']
                result.append(entry)
            else:
                # id_to_name에 없어도 alt_ids, match_names로 확인
                found = False
                found_name = None
                alt_ids = item.get('alt_ids', [])
                match_names = item.get('match_names', [])
                for aid in alt_ids:
                    if aid in id_to_name:
                        found = True
                        found_name = id_to_name[aid]
                        break
                if not found:
                    auto_alt = _alt_account_id(item['id'])
                    if auto_alt and auto_alt in id_to_name:
                        found = True
                        found_name = id_to_name[auto_alt]
                if not found:
                    for nm in match_names:
                        if nm in name_to_exists:
                            found = True
                            found_name = nm
                            break

                if found or item['id'] in id_to_name:
                    name = item.get('display_name') or id_to_name.get(item['id'], found_name or item['id'])
                    entry = {
                        'id': item['id'],
                        'name': name,
                        'is_header': False,
                    }
                    if item.get('is_total'):
                        entry['is_total'] = True
                    if item.get('level'):
                        entry['level'] = item['level']
                    if item.get('negate'):
                        entry['negate'] = True
                    if item.get('alt_ids'):
                        entry['alt_ids'] = item['alt_ids']
                    if item.get('match_names'):
                        entry['match_names'] = item['match_names']
                    result.append(entry)
                    seen_ids.add(item['id'])
                    alt = _alt_account_id(item['id'])
                    if alt:
                        seen_ids.add(alt)
                    for aid in alt_ids:
                        seen_ids.add(aid)
                        a2 = _alt_account_id(aid)
                        if a2:
                            seen_ids.add(a2)

        # 현금흐름표는 ORDER에 정의된 항목만 사용 (나머지 항목 추가 안 함)
        if stmt_name not in ('현금흐름표',):
            # 가장 항목이 많은 DataFrame에서 나머지 항목 추가
            best_df = None
            best_count = 0
            for (year, qtr_key), df in sorted(raw_data.items(), reverse=True):
                filtered = df[df['sj_nm'].isin(sj_values)]
                if len(filtered) > best_count:
                    best_count = len(filtered)
                    best_df = filtered

            if best_df is not None:
                for _, row in best_df.iterrows():
                    acct_id = str(row.get('account_id', '')).strip()
                    acct_nm = str(row.get('account_nm', '')).strip()
                    alt = _alt_account_id(acct_id) if acct_id else None
                    if acct_id and acct_nm and acct_id not in seen_ids and (alt is None or alt not in seen_ids):
                        result.append({
                            'id': acct_id,
                            'name': acct_nm,
                            'is_header': False,
                        })
                        seen_ids.add(acct_id)
                        if alt:
                            seen_ids.add(alt)

        return result
    else:
        # 재무상태표/현금흐름표: best_df의 원래 순서 사용 (account_id 기반)
        best_df = None
        best_count = 0
        for (year, qtr_key), df in sorted(raw_data.items(), reverse=True):
            filtered = df[df['sj_nm'].isin(sj_values)]
            if len(filtered) > best_count:
                best_count = len(filtered)
                best_df = filtered

        if best_df is None:
            return []

        seen_ids = set()
        result = []
        for _, row in best_df.iterrows():
            acct_id = str(row.get('account_id', '')).strip()
            acct_nm = str(row.get('account_nm', '')).strip()
            if acct_id and acct_id not in seen_ids:
                result.append({
                    'id': acct_id,
                    'name': id_to_name.get(acct_id, acct_nm),
                    'is_header': False,
                })
                seen_ids.add(acct_id)
        return result


def _match_account(filtered_df, acct_id, alt_ids=None, match_names=None):
    """account_id로 매칭, 실패시 ifrs_ ↔ ifrs-full_ 대체 ID, alt_ids, match_names 순서로 재시도"""
    matched = filtered_df[filtered_df['account_id'].str.strip() == acct_id]
    if len(matched) > 0:
        return matched
    # ifrs_ ↔ ifrs-full_ 자동 변환
    auto_alt = _alt_account_id(acct_id)
    if auto_alt:
        matched = filtered_df[filtered_df['account_id'].str.strip() == auto_alt]
        if len(matched) > 0:
            return matched
    # 명시적 alt_ids (과거 DART ID 호환)
    if alt_ids:
        for aid in alt_ids:
            matched = filtered_df[filtered_df['account_id'].str.strip() == aid]
            if len(matched) > 0:
                return matched
            auto_alt2 = _alt_account_id(aid)
            if auto_alt2:
                matched = filtered_df[filtered_df['account_id'].str.strip() == auto_alt2]
                if len(matched) > 0:
                    return matched
    # 계정이름(account_nm)으로 폴백 매칭 (표준계정코드 미사용 항목용)
    if match_names:
        for nm in match_names:
            matched = filtered_df[filtered_df['account_nm'].str.strip() == nm]
            if len(matched) > 0:
                return matched
    return matched


def _extract_all_values(filtered_df, account_order, column_name, parse_amount_fn):
    """account_id 기반으로 값 추출 (백만원 → 억원 변환)"""
    values = []
    for item in account_order:
        if item['is_header']:
            # 카테고리 헤더: data_id가 있으면 해당 값 추출
            data_id = item.get('data_id')
            if data_id:
                header_match_names = item.get('match_names')
                matched = _match_account(filtered_df, data_id, match_names=header_match_names)
                if len(matched) > 0:
                    val = parse_amount_fn(matched.iloc[0].get(column_name, None))
                    values.append(round(val / 1e8) if val is not None else None)
                else:
                    values.append(None)
            else:
                values.append(None)
            continue

        acct_id = item['id']
        alt_ids = item.get('alt_ids')
        match_names = item.get('match_names')
        negate = item.get('negate', False)
        matched = _match_account(filtered_df, acct_id, alt_ids=alt_ids, match_names=match_names)
        if len(matched) > 0:
            val = parse_amount_fn(matched.iloc[0].get(column_name, None))
            if val is not None:
                converted = round(val / 1e8)
                values.append(-converted if negate and converted > 0 else converted)
            else:
                values.append(None)
        else:
            values.append(None)
    return values



# (_apply_restatement는 utils.py의 apply_restatement로 대체)


def _fetch_single_finstate(finstate_fn, company_name, year, qtr_key, reprt_code, fs_pref):
    """단일 분기 전체 재무제표 조회 (병렬 worker용)"""
    label = f"{year}{qtr_key}"
    fs_div = 'CFS' if fs_pref == 'CFS' else 'OFS'
    fallback_div = 'OFS' if fs_pref == 'CFS' else 'CFS'

    try:
        fs = finstate_fn(company_name, year, reprt_code=reprt_code, fs_div=fs_div)
    except Exception:
        try:
            fs = finstate_fn(company_name, year, reprt_code=reprt_code, fs_div=fallback_div)
            if fs is not None and len(fs) > 0:
                return (year, qtr_key, label, fs, '개별' if fs_pref == 'CFS' else '연결')
            return None
        except Exception:
            return None

    if fs is None or len(fs) == 0:
        try:
            fs = finstate_fn(company_name, year, reprt_code=reprt_code, fs_div=fallback_div)
            if fs is not None and len(fs) > 0:
                return (year, qtr_key, label, fs, '개별' if fs_pref == 'CFS' else '연결')
        except Exception:
            pass
        return None

    fs_type = '연결' if fs_pref == 'CFS' else '개별'
    return (year, qtr_key, label, fs, fs_type)


def fetch_full_finstate_data(dart, company_name, start_year, end_year, fs_pref, parse_amount_fn, finstate_fn=None):
    """DART에서 전체 재무제표 데이터 수집 (모든 계정 항목, 병렬)
    finstate_fn: 선택적 캐시 래퍼 함수. 없으면 dart.finstate_all 직접 호출.
    """
    _finstate = finstate_fn or (lambda name, yr, reprt_code, fs_div: dart.finstate_all(name, yr, reprt_code=reprt_code, fs_div=fs_div))
    years = list(range(start_year, end_year + 1))
    raw_data = {}
    fs_type_used = {}

    # 전체 (year, qtr_key) 조합 생성
    tasks = []
    for year in years:
        for qtr_key, (reprt_code, reprt_name) in QUARTER_CODES.items():
            tasks.append((_finstate, company_name, year, qtr_key, reprt_code, fs_pref))

    # ThreadPoolExecutor로 병렬 호출 (max 10 workers)
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_fetch_single_finstate, *t): t for t in tasks}
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                year, qtr_key, label, fs, fs_type = result
                raw_data[(year, qtr_key)] = fs
                fs_type_used[label] = fs_type

    apply_restatement(raw_data, years)

    # 재무제표별 데이터 구성
    result = {}
    for stmt_name, sj_values in STATEMENT_TYPES.items():
        account_order = _build_account_order(raw_data, sj_values, stmt_name)
        if not account_order:
            continue

        stmt_data = {}
        is_bs = (stmt_name == '재무상태표')
        is_cf = (stmt_name == '현금흐름표')

        for year in years:
            for qtr_key in ['Q1', 'Q2', 'Q3', 'Q4']:
                label = f"{year}{qtr_key}"
                df = raw_data.get((year, qtr_key))
                if df is None:
                    continue

                filtered = df[df['sj_nm'].isin(sj_values)]

                if is_bs or is_cf or qtr_key in ('Q1', 'Q2', 'Q3'):
                    values = _extract_all_values(filtered, account_order, 'thstrm_amount', parse_amount_fn)
                    # 현금흐름표: ProfitLoss는 DART API에서 분기 단독값으로 반환됨
                    # → Q2/Q3에서 직전 분기의 (이미 보정된) 누적값을 더하여 보정
                    if is_cf and qtr_key in ('Q2', 'Q3'):
                        for idx, item in enumerate(account_order):
                            if not item['is_header'] and item.get('id') == 'ifrs-full_ProfitLoss':
                                if values[idx] is not None:
                                    # 직전 분기의 누적값 (이미 보정됨) 을 더함
                                    prev_qtr = 'Q1' if qtr_key == 'Q2' else 'Q2'
                                    prev_label = f"{year}{prev_qtr}"
                                    prev_val = 0
                                    if prev_label in stmt_data and stmt_data[prev_label][idx] is not None:
                                        prev_val = stmt_data[prev_label][idx]
                                    values[idx] = values[idx] + prev_val
                                break
                else:
                    # Q4: 연간 - Q1~Q3
                    annual_values = _extract_all_values(filtered, account_order, 'thstrm_amount', parse_amount_fn)

                    q123_totals = [0] * len(account_order)
                    q123_counts = [0] * len(account_order)
                    for q in ['Q1', 'Q2', 'Q3']:
                        qdf = raw_data.get((year, q))
                        if qdf is None:
                            continue
                        qf = qdf[qdf['sj_nm'].isin(sj_values)]
                        qvals = _extract_all_values(qf, account_order, 'thstrm_amount', parse_amount_fn)
                        for i, v in enumerate(qvals):
                            if v is not None:
                                q123_totals[i] += v
                                q123_counts[i] += 1

                    values = []
                    for i in range(len(account_order)):
                        if account_order[i]['is_header'] and not account_order[i].get('data_id'):
                            values.append(None)
                        elif annual_values[i] is not None and q123_counts[i] == 3:
                            values.append(annual_values[i] - q123_totals[i])
                        elif annual_values[i] is not None and q123_counts[i] == 0:
                            values.append(annual_values[i])
                        else:
                            values.append(None)

                stmt_data[label] = values

        # accounts를 JSON 직렬화 가능한 형태로 변환
        accounts_info = []
        for item in account_order:
            entry = {
                'name': item['name'],
                'is_header': item['is_header'],
            }
            if item.get('data_id'):
                entry['has_data'] = True
            if item.get('is_total'):
                entry['is_total'] = True
            if item.get('level'):
                entry['level'] = item['level']
            accounts_info.append(entry)

        result[stmt_name] = {
            'accounts': accounts_info,
            'data': stmt_data,
        }

    # ── 조정순운전자본 계산 (backend_nwc.py 로직 활용) ──
    adj_nwc_data = {}
    for year in years:
        for qtr_key in ['Q1', 'Q2', 'Q3', 'Q4']:
            label = f"{year}{qtr_key}"
            df = raw_data.get((year, qtr_key))
            if df is None:
                continue
            try:
                bs_data = df[df['sj_nm'].str.contains('재무상태표', na=False)]
                if len(bs_data) == 0:
                    continue

                current_assets, _ = get_amount(bs_data, ['유동자산'])
                current_liabilities, _ = get_amount(bs_data, ['유동부채'])
                accounts_receivable, _ = get_amount(bs_data, ['매출채권', '외상매출금'])
                inventory, _ = get_amount(bs_data, ['재고자산'])
                noncurrent_financial_assets = get_noncurrent_financial_assets(bs_data)
                accounts_payable, _ = get_amount(bs_data, ['단기매입채무', '유동매입채무', '매입채무'], exclude_keywords=['매입채무 외'])
                if accounts_payable == 0:
                    accounts_payable, _ = get_amount(bs_data, ['매입채무 및'])
                long_term_borrowings, bonds_val = get_long_term_debt(bs_data)

                adj_ca = current_assets - accounts_receivable - inventory + noncurrent_financial_assets
                adj_cl = current_liabilities - accounts_payable + long_term_borrowings + bonds_val
                adj_nwc = adj_ca - adj_cl

                adj_nwc_data[label] = {
                    'adj_ca': round(adj_ca, 2),
                    'adj_cl': round(adj_cl, 2),
                    'adj_nwc': round(adj_nwc, 2),
                }
            except Exception:
                continue

    result['_adj_nwc'] = adj_nwc_data

    return result, fs_type_used
