# -*- coding: utf-8 -*-
"""
기업개요 탭 모듈
- 상단 가격 영역 (현재가, 등락, 거래소)
- 기업 소개 / 업종 / 매출비중
- 투자지표 (PER, PBR, ROE 등)
- 주가차트 (placeholder)
"""


def get_기업개요_html():
    """기업개요 탭의 HTML을 반환"""
    return '''
    <!-- 가격 + 투자지표 가로 배치 -->
    <div class="overview-price-indicator-row">
      <!-- 가격 영역 -->
      <div class="overview-price-bar">
        <div class="overview-current-price" id="overviewPrice">-</div>
        <div class="overview-change" id="overviewChange">
          <span id="overviewChangeIcon">-</span>
          <span id="overviewChangeAmt">0</span>
          <span id="overviewChangePct">0.00%</span>
          <span class="overview-badge">KRX</span>
        </div>
        <div class="overview-market-table">
          <div class="overview-market-cell">
            <span class="overview-market-label">시가총액</span>
            <span class="overview-market-value" id="overviewMarketCap">-</span>
          </div>
          <div class="overview-market-cell">
            <span class="overview-market-label">상장주식수</span>
            <span class="overview-market-value" id="overviewShares">-</span>
          </div>
          <div class="overview-market-cell">
            <span class="overview-market-label">자사주 비중</span>
            <span class="overview-market-value" id="overviewTreasury">-</span>
          </div>
        </div>
      </div>

      <!-- 투자지표 (주가 옆) -->
      <div class="overview-indicator-side">
        <h3 class="overview-section-title" style="margin-bottom:8px;">투자지표</h3>
        <div class="indicator-grid-compact">
        <div class="indicator-item">
          <span class="indicator-label">PER</span>
          <span class="indicator-value" id="indPER">-</span>
        </div>
        <div class="indicator-item">
          <span class="indicator-label">PBR</span>
          <span class="indicator-value" id="indPBR">-</span>
        </div>
        <div class="indicator-item">
          <span class="indicator-label">ROE</span>
          <span class="indicator-value" id="indROE">-</span>
        </div>

        <div class="indicator-item">
          <span class="indicator-label">5년 PER</span>
          <span class="indicator-value" id="ind5PER">-</span>
        </div>
        <div class="indicator-item">
          <span class="indicator-label">5년 PBR</span>
          <span class="indicator-value" id="ind5PBR">-</span>
        </div>
        <div class="indicator-item">
          <span class="indicator-label">5년 ROE</span>
          <span class="indicator-value" id="ind5ROE">-</span>
        </div>

        <div class="indicator-item">
          <span class="indicator-label">5년 EPS성장률</span>
          <span class="indicator-value" id="ind5EPS">-</span>
        </div>
        <div class="indicator-item">
          <span class="indicator-label">5년 BPS성장률</span>
          <span class="indicator-value" id="ind5BPS">-</span>
        </div>
        <div class="indicator-item">
          <span class="indicator-label">배당수익률</span>
          <span class="indicator-value" id="indDivYield">-</span>
        </div>
        </div>
      </div>
    </div>

    <!-- 1. 기업소개 / 업종 / 매출비중 -->
    <div class="overview-section">
      <div class="overview-desc collapsed" id="overviewDesc" onclick="this.classList.toggle('collapsed'); this.classList.toggle('expanded');" title="클릭하여 더보기">
        기업 소개가 여기에 표시됩니다.
      </div>
      <div class="overview-info-grid">
        <div class="overview-info-row">
          <span class="overview-info-label">업종</span>
          <span class="overview-info-value" id="overviewSector">-</span>
        </div>
        <div class="overview-info-row">
          <span class="overview-info-label">세부업종</span>
          <span class="overview-info-value" id="overviewSubSector">-</span>
        </div>
      </div>
      <div style="margin-top:12px;">
        <span class="overview-info-label" style="margin-bottom:8px; display:block;">매출비중</span>
        <div class="overview-revenue-bar" id="overviewRevenue">
          <div class="revenue-segment" style="flex:1; background:#1a237e; color:#fff;">- (-%)</div>
        </div>
        <div class="overview-revenue-details" id="overviewRevenueDetails"></div>
      </div>
    </div>

    <!-- 3. 주가차트 -->
    <div class="overview-section">
      <div class="overview-chart-header">
        <div class="overview-chart-left">
          <h3 class="overview-section-title" style="margin-bottom:0;">주가차트
            <span class="overview-chart-period">(1년)</span>
          </h3>
          <div class="overview-chart-tabs">
            <button class="overview-chart-tab" onclick="setOverviewChartPeriod('1m')">1개월</button>
            <button class="overview-chart-tab" onclick="setOverviewChartPeriod('3m')">3개월</button>
            <button class="overview-chart-tab" onclick="setOverviewChartPeriod('6m')">6개월</button>
            <button class="overview-chart-tab active" onclick="setOverviewChartPeriod('1y')">1년</button>
            <button class="overview-chart-tab" onclick="setOverviewChartPeriod('3y')">3년</button>
            <button class="overview-chart-tab" onclick="setOverviewChartPeriod('5y')">5년</button>
            <button class="overview-chart-tab" onclick="setOverviewChartPeriod('10y')">10년</button>
          </div>
        </div>
        <div class="overview-52week">
          <div class="week52-item">
            <span class="week52-label">52주 최고가</span>
            <span class="week52-value highlight-red" id="ind52High">-</span>
          </div>
          <div class="week52-item">
            <span class="week52-label">52주 최저가</span>
            <span class="week52-value highlight-blue" id="ind52Low">-</span>
          </div>
        </div>
      </div>
      <div class="overview-chart-area" id="overviewChartArea">
        <canvas id="overviewPriceChart"></canvas>
      </div>
    </div>
'''


def get_기업개요_js():
    """기업개요 탭의 JavaScript를 반환"""
    return '''
// ============ 기업개요 탭 ============

let overviewLoaded = false;
let overviewLoadedCompany = '';

async function loadOverviewData(forceRefresh = false) {
  const company = currentStockCode || currentCompany;

  // 이미 같은 종목 로딩됨
  if (!forceRefresh && overviewLoaded && overviewLoadedCompany === company) return;

  // 로딩 표시 - 눈에 띄는 스피너 + 텍스트
  document.getElementById('overviewDesc').innerHTML = '<div class="overview-loading-indicator"><div class="overview-spinner"></div><span>기업 정보를 불러오는 중...</span></div>';
  document.getElementById('overviewSector').textContent = '-';
  document.getElementById('overviewSubSector').textContent = '-';
  // 가격/시총 영역 초기화
  document.getElementById('overviewPrice').textContent = '-';
  document.getElementById('overviewChangeIcon').textContent = '-';
  document.getElementById('overviewChangeAmt').textContent = '0';
  document.getElementById('overviewChangePct').textContent = '0.00%';
  document.getElementById('overviewMarketCap').textContent = '-';
  document.getElementById('overviewShares').textContent = '-';
  document.getElementById('overviewTreasury').textContent = '-';
  // 매출비중 초기화
  const revBar = document.getElementById('overviewRevenue');
  if (revBar) revBar.innerHTML = '<div class="revenue-segment" style="flex:1; background:#e0e0e0; color:#888;">-</div>';
  const revDet = document.getElementById('overviewRevenueDetails');
  if (revDet) revDet.innerHTML = '';

  try {
    let url = `/api/overview?company=${encodeURIComponent(company)}`;
    if (forceRefresh) url += '&refresh=1';
    const res = await fetch(url);
    const data = await res.json();

    if (data.error) {
      document.getElementById('overviewDesc').textContent = '기업 정보를 가져올 수 없습니다.';
      return;
    }

    // 헬퍼 함수
    const fmt = (v, suffix='') => v != null ? v.toLocaleString() + suffix : '-';
    const fmtF = (v, d=2, suffix='') => v != null ? v.toFixed(d) + suffix : '-';

    // ── 상단 가격 영역 ──
    if (data.current_price != null) {
      document.getElementById('overviewPrice').textContent = data.current_price.toLocaleString() + '원';
      const chg = data.price_change || 0;
      const pct = data.price_change_pct || 0;
      const icon = chg > 0 ? '▲' : chg < 0 ? '▼' : '-';
      const color = chg > 0 ? '#d32f2f' : chg < 0 ? '#1565c0' : '#333';
      const changeEl = document.getElementById('overviewChange');
      changeEl.style.color = color;
      document.getElementById('overviewChangeIcon').textContent = icon;
      document.getElementById('overviewChangeAmt').textContent = Math.abs(chg).toLocaleString();
      document.getElementById('overviewChangePct').textContent = Math.abs(pct).toFixed(2) + '%';
    }

    // 시가총액
    if (data.market_cap != null) {
      const cap = data.market_cap;
      document.getElementById('overviewMarketCap').textContent =
        cap >= 10000 ? (cap / 10000).toFixed(1) + '조원' : cap.toLocaleString() + '억원';
    }

    // 상장주식수
    if (data.shares_outstanding != null) {
      document.getElementById('overviewShares').textContent = data.shares_outstanding.toLocaleString() + '주';
    }

    // ── 기업소개 ──
    const descEl = document.getElementById('overviewDesc');
    descEl.textContent = data.description || '기업 소개 정보 없음';

    // 업종 / 세부업종
    document.getElementById('overviewSector').textContent = data.sector || '-';
    document.getElementById('overviewSubSector').textContent = data.sub_sector || '-';

    // ── 매출비중 ──
    const revenueBar = document.getElementById('overviewRevenue');
    const detailsDiv = document.getElementById('overviewRevenueDetails');
    const colors = ['#1a237e', '#283593', '#3949ab', '#5c6bc0', '#7986cb', '#9fa8da', '#c5cae9', '#e8eaf6'];

    if (data.revenue_details && data.revenue_details.length > 0) {
      // 양수 항목만 바 차트에 표시 (차감/조정 항목은 제외)
      const positiveItems = data.revenue_details.filter(d => parseFloat(d.pct) > 0);
      let barHtml = '';
      positiveItems.forEach((d, i) => {
        const pctNum = Math.abs(parseFloat(d.pct)) || 5;
        const color = colors[i % colors.length];
        const textColor = i < 4 ? '#fff' : '#333';
        const barLabel = d.name.length > 10 ? d.name.substring(0, 10) + '..' : d.name;
        barHtml += `<div class="revenue-segment" style="flex:${pctNum}; background:${color}; color:${textColor};" title="${d.name}: ${d.pct}">${barLabel} (${d.pct})</div>`;
      });
      revenueBar.innerHTML = barHtml;
      let detailHtml = '';
      data.revenue_details.forEach((d, i) => {
        const pctNum = parseFloat(d.pct);
        const isNegative = pctNum < 0;
        const color = isNegative ? '#c62828' : colors[i % colors.length];
        const displayName = d.name;
        const displayProducts = d.products || '-';
        detailHtml += `<div class="revenue-detail-row" onclick="var p=this.querySelector('.revenue-detail-products'); if(p){p.classList.toggle('collapsed'); p.classList.toggle('expanded');}">
          <span class="revenue-detail-name" style="color:${color};">${displayName}</span>
          <span class="revenue-detail-pct" style="${isNegative ? 'color:#c62828;' : ''}">${d.pct}</span>
          <span class="revenue-detail-products collapsed">${displayProducts}</span>
        </div>`;
      });
      detailsDiv.innerHTML = detailHtml;
    } else {
      revenueBar.innerHTML = '<div class="revenue-segment" style="flex:1; background:#e0e0e0; color:#888;">매출비중 정보 없음</div>';
      detailsDiv.innerHTML = '';
    }

    // ── 자사주 비중 (가격 영역 하단) ──
    document.getElementById('overviewTreasury').textContent = data.treasury_pct != null ? data.treasury_pct.toFixed(1) + '%' : '-';

    // ── 52주 고저가 (차트 영역) ──
    document.getElementById('ind52High').textContent = fmt(data.week52_high, '원');
    document.getElementById('ind52Low').textContent = fmt(data.week52_low, '원');
    // PER, PBR, ROE
    document.getElementById('indPER').textContent = data.per != null ? data.per.toFixed(2) + '배' : '-';
    document.getElementById('indPBR').textContent = data.pbr != null ? data.pbr.toFixed(2) + '배' : '-';
    document.getElementById('indROE').textContent = data.roe != null ? data.roe.toFixed(2) + '%' : '-';
    // 5년 PER, PBR, ROE
    document.getElementById('ind5PER').textContent = data.per_5y != null ? data.per_5y.toFixed(2) + '배' : '-';
    document.getElementById('ind5PBR').textContent = data.pbr_5y != null ? data.pbr_5y.toFixed(2) + '배' : '-';
    document.getElementById('ind5ROE').textContent = data.roe_5y != null ? data.roe_5y.toFixed(2) + '%' : '-';
    // 배당수익률
    document.getElementById('indDivYield').textContent = data.div_yield != null ? data.div_yield.toFixed(2) + '%' : '-';
    // 5년 성장률
    document.getElementById('ind5EPS').textContent = data.eps_growth_5y != null ? data.eps_growth_5y.toFixed(1) + '%' : '-';
    document.getElementById('ind5BPS').textContent = data.bps_growth_5y != null ? data.bps_growth_5y.toFixed(1) + '%' : '-';

    overviewLoaded = true;
    overviewLoadedCompany = company;

    // finData 로드 후 5년 지표 업데이트
    if (finDataLoaded && finData) {
      update5YearIndicators();
    } else {
      // finData가 없으면 백그라운드로 로드
      loadFinData().then(() => update5YearIndicators()).catch(() => {});
    }

    // 실시간 주가 업데이트 (캐시 우회)
    fetchRealtimePrice(company, data);

    // 주가차트 로딩
    loadPriceChart(company);

  } catch(e) {
    console.error('기업개요 로딩 오류:', e);
    document.getElementById('overviewDesc').textContent = '데이터 로드 실패: ' + e.message;
  }
}

// ── 실시간 주가 조회 ──
async function fetchRealtimePrice(company, overviewData) {
  try {
    const res = await fetch(`/api/realtime_price?company=${encodeURIComponent(company)}`);
    const rt = await res.json();
    if (rt.error || rt.current_price == null) return;

    // 가격 업데이트
    document.getElementById('overviewPrice').textContent = rt.current_price.toLocaleString() + '원';
    const chg = rt.price_change || 0;
    const pct = rt.price_change_pct || 0;
    const icon = chg > 0 ? '▲' : chg < 0 ? '▼' : '-';
    const color = chg > 0 ? '#d32f2f' : chg < 0 ? '#1565c0' : '#333';
    const changeEl = document.getElementById('overviewChange');
    changeEl.style.color = color;
    document.getElementById('overviewChangeIcon').textContent = icon;
    document.getElementById('overviewChangeAmt').textContent = Math.abs(chg).toLocaleString();
    document.getElementById('overviewChangePct').textContent = Math.abs(pct).toFixed(2) + '%';

    // 시가총액 재계산 (총주식수 × 실시간가격)
    const totalShares = overviewData.total_shares || overviewData.shares_outstanding;
    if (totalShares) {
      const cap = Math.round(rt.current_price * totalShares / 100000000);
      document.getElementById('overviewMarketCap').textContent =
        cap >= 10000 ? (cap / 10000).toFixed(1) + '조원' : cap.toLocaleString() + '억원';

      // PER/PBR 재계산 (실시간 시가총액 기반)
      if (overviewData.eps && overviewData.eps > 0) {
        const per = rt.current_price / overviewData.eps;
        document.getElementById('indPER').textContent = per.toFixed(2) + '배';
      }
      if (overviewData.bps && overviewData.bps > 0) {
        const pbr = rt.current_price / overviewData.bps;
        document.getElementById('indPBR').textContent = pbr.toFixed(2) + '배';
      }
    } else if (rt.market_cap) {
      const cap = rt.market_cap;
      document.getElementById('overviewMarketCap').textContent =
        cap >= 10000 ? (cap / 10000).toFixed(1) + '조원' : cap.toLocaleString() + '억원';
    }
  } catch(e) {
    // 실시간 조회 실패 시 기존 캐시 데이터 유지
    console.error('실시간 주가 조회 실패:', e);
  }
}

// ── 주가차트 ──
let _priceChartData = [];  // 전체 10년 데이터
let _priceChart = null;    // Chart.js 인스턴스
let _priceChartPeriod = '1y';  // 현재 선택된 기간

async function loadPriceChart(company) {
  try {
    const res = await fetch(`/api/price_chart?company=${encodeURIComponent(company)}`);
    const json = await res.json();
    if (json.error || !json.data) return;

    _priceChartData = json.data;
    renderPriceChart(_priceChartPeriod);
  } catch(e) {
    console.error('주가차트 로딩 오류:', e);
  }
}

function renderPriceChart(period) {
  if (!_priceChartData.length) return;

  // 기간에 따라 데이터 필터링
  const now = new Date();
  let cutoff = new Date();
  switch(period) {
    case '1m':  cutoff.setMonth(now.getMonth() - 1); break;
    case '3m':  cutoff.setMonth(now.getMonth() - 3); break;
    case '6m':  cutoff.setMonth(now.getMonth() - 6); break;
    case '1y':  cutoff.setFullYear(now.getFullYear() - 1); break;
    case '3y':  cutoff.setFullYear(now.getFullYear() - 3); break;
    case '5y':  cutoff.setFullYear(now.getFullYear() - 5); break;
    case '10y': cutoff.setFullYear(now.getFullYear() - 10); break;
    default:    cutoff.setFullYear(now.getFullYear() - 5);
  }
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  const filtered = _priceChartData.filter(d => d.date >= cutoffStr);

  if (!filtered.length) return;

  const labels = filtered.map(d => d.date);
  const prices = filtered.map(d => d.close);

  // 상승/하락 색상 결정
  const firstPrice = prices[0];
  const lastPrice = prices[prices.length - 1];
  const isUp = lastPrice >= firstPrice;
  const lineColor = isUp ? '#d32f2f' : '#1565c0';
  const fillColor = isUp ? 'rgba(211,47,47,0.08)' : 'rgba(21,101,192,0.08)';

  // 기존 차트 파괴
  if (_priceChart) {
    _priceChart.destroy();
    _priceChart = null;
  }

  const ctx = document.getElementById('overviewPriceChart');
  if (!ctx) return;

  _priceChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [{
        data: prices,
        borderColor: lineColor,
        backgroundColor: fillColor,
        borderWidth: 1.5,
        pointRadius: 0,
        pointHoverRadius: 4,
        pointHoverBackgroundColor: lineColor,
        fill: true,
        tension: 0.1
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          mode: 'nearest',
          intersect: false,
          callbacks: {
            title: function(items) {
              return items[0].label;
            },
            label: function(item) {
              return item.raw.toLocaleString() + '원';
            }
          },
          displayColors: false,
          backgroundColor: 'rgba(0,0,0,0.8)',
          titleFont: { size: 12 },
          bodyFont: { size: 14, weight: 'bold' },
          padding: 10,
          cornerRadius: 6
        }
      },
      scales: {
        x: {
          type: 'category',
          ticks: {
            maxTicksLimit: getTicksLimit(period),
            font: { size: 11 },
            color: '#999',
            callback: function(val, idx) {
              const label = this.getLabelForValue(val);
              // 기간에 따라 날짜 표시 형식 변경
              if (['1m', '3m'].includes(period)) {
                return label.slice(5);  // MM-DD
              } else if (['6m', '1y'].includes(period)) {
                return label.slice(2, 7);  // YY-MM
              } else {
                return label.slice(0, 7);  // YYYY-MM
              }
            }
          },
          grid: { display: false }
        },
        y: {
          position: 'right',
          ticks: {
            font: { size: 11 },
            color: '#999',
            callback: function(val) {
              if (val >= 10000) return (val / 10000).toFixed(val >= 100000 ? 0 : 1) + '만';
              return val.toLocaleString();
            }
          },
          grid: { color: 'rgba(0,0,0,0.04)' }
        }
      },
      interaction: {
        mode: 'nearest',
        intersect: false
      },
      hover: {
        mode: 'nearest',
        intersect: false
      }
    }
  });
}

function getTicksLimit(period) {
  switch(period) {
    case '1m': return 8;
    case '3m': return 8;
    case '6m': return 8;
    case '1y': return 12;
    case '3y': return 10;
    case '5y': return 10;
    case '10y': return 12;
    default: return 10;
  }
}

function setOverviewChartPeriod(period) {
  // 탭 전환
  document.querySelectorAll('.overview-chart-tab').forEach(btn => btn.classList.remove('active'));
  event.target.classList.add('active');
  _priceChartPeriod = period;
  renderPriceChart(period);
}

// ── 5년 평균 PER/PBR/ROE/EPS성장률/BPS성장률/배당수익률 (finData + priceData 기반) ──
function update5YearIndicators() {
  if (!finData || !finData.statements || !priceData) return;
  try {
    if (typeof initAcctIdxCache === 'function') initAcctIdxCache();
    const now = new Date().getFullYear();

    // 연간 모드 데이터 가져오기
    const ni = getFinChartData('손익계산서', AI.ni, 'annual', false);
    const eq = getFinChartData('재무상태표', AI.eq, 'annual', true);
    if (!ni || !eq) return;

    // 최근 5년 연간 PER/PBR/ROE 계산
    const perList = [], pbrList = [], roeList = [];
    const epsMap = {}, bpsMap = {};

    for (let i = 0; i < ni.labels.length; i++) {
      const yr = parseInt(ni.labels[i]);
      if (isNaN(yr) || yr < now - 5 || yr >= now) continue;

      const niVal = ni.values[i];  // 억원
      const eqI = eq.labels.indexOf(ni.labels[i]);
      const eqVal = eqI >= 0 ? eq.values[eqI] : null;

      // 연말 주가 찾기 (Q4 우선, 없으면 월별키 fallback)
      let mp = null;
      for (const q of ['Q4','Q3','Q2','Q1']) {
        if (priceData[yr + q]) { mp = yr + q; break; }
      }
      if (!mp) mp = priceData[yr + '-12'] ? yr + '-12' : null;
      if (!mp || !priceData[mp]) continue;
      const pd = priceData[mp];
      const ts = pd.total_shares || pd.shares;
      if (!ts || ts <= 0) continue;

      const mcap = pd.price * ts / 100000000;  // 억원
      const eps = niVal != null ? niVal * 100000000 / ts : null;
      const bps = eqVal != null ? eqVal * 100000000 / ts : null;

      if (eps != null) epsMap[yr] = eps;
      if (bps != null) bpsMap[yr] = bps;

      // PER = 시가총액 / 순이익
      if (niVal != null && niVal > 0 && mcap > 0) {
        perList.push(mcap / niVal);
      }
      // PBR = 시가총액 / 자본총계
      if (eqVal != null && eqVal > 0 && mcap > 0) {
        pbrList.push(mcap / eqVal);
      }
      // ROE = 순이익 / 자본총계
      if (niVal != null && eqVal != null && eqVal > 0) {
        roeList.push(niVal / eqVal * 100);
      }
    }

    // 5년 평균 업데이트
    const avg = arr => arr.length > 0 ? arr.reduce((a, b) => a + b, 0) / arr.length : null;
    const per5y = avg(perList);
    const pbr5y = avg(pbrList);
    const roe5y = avg(roeList);

    document.getElementById('ind5PER').textContent = per5y != null ? per5y.toFixed(2) + '배' : '-';
    document.getElementById('ind5PBR').textContent = pbr5y != null ? pbr5y.toFixed(2) + '배' : '-';
    document.getElementById('ind5ROE').textContent = roe5y != null ? roe5y.toFixed(2) + '%' : '-';

    // EPS CAGR (5년 성장률)
    const epsYears = Object.keys(epsMap).map(Number).sort();
    if (epsYears.length >= 2) {
      const first = epsMap[epsYears[0]], last = epsMap[epsYears[epsYears.length - 1]];
      const n = epsYears[epsYears.length - 1] - epsYears[0];
      if (first > 0 && last > 0 && n > 0) {
        const cagr = (Math.pow(last / first, 1 / n) - 1) * 100;
        document.getElementById('ind5EPS').textContent = cagr.toFixed(1) + '%';
      }
    }

    // BPS CAGR (5년 성장률)
    const bpsYears = Object.keys(bpsMap).map(Number).sort();
    if (bpsYears.length >= 2) {
      const first = bpsMap[bpsYears[0]], last = bpsMap[bpsYears[bpsYears.length - 1]];
      const n = bpsYears[bpsYears.length - 1] - bpsYears[0];
      if (first > 0 && last > 0 && n > 0) {
        const cagr = (Math.pow(last / first, 1 / n) - 1) * 100;
        document.getElementById('ind5BPS').textContent = cagr.toFixed(1) + '%';
      }
    }

  } catch(e) {
    // 5년 지표 계산 실패 시 무시 (overview API 값 유지)
  }
}
'''
