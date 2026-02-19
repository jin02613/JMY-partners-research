# -*- coding: utf-8 -*-
"""
실적 그래프 탭 – 모든 서브탭 차트 빌드 JS
finData (10년 데이타)를 활용하여 차트를 그린다.
"""


def get_실적그래프_차트_js():
    return '''
// ========================================
// 실적 그래프 차트 빌드 (finData 기반)
// ========================================

// ── 헬퍼: finData에서 계정 인덱스 찾기 ──
function findAcctIdx(stmtKey, nameList) {
  if (!finData || !finData.statements || !finData.statements[stmtKey]) return -1;
  const accounts = finData.statements[stmtKey].accounts;
  const stmtData = finData.statements[stmtKey].data;
  const periods = Object.keys(stmtData || {});
  // 모든 매칭 후보의 데이터 충실도를 계산하여 가장 완전한 것을 선택
  let bestIdx = -1, bestCount = -1;
  for (let j = 0; j < nameList.length; j++) {
    for (let i = 0; i < accounts.length; i++) {
      if (accounts[i].name === nameList[j]) {
        if (periods.length === 0) return i;
        let validCount = 0;
        periods.forEach(p => {
          const d = stmtData[p];
          if (d && d[i] !== null && d[i] !== undefined) validCount++;
        });
        if (validCount > bestCount) {
          bestCount = validCount;
          bestIdx = i;
        }
      }
    }
  }
  return bestIdx;
}

// ── 주요 계정 인덱스 캐시 (finData 로드 후 1회 초기화) ──
let AI = null;  // Account Index cache
function initAcctIdxCache() {
  AI = {
    // 손익계산서
    revenue:  findAcctIdx('손익계산서', ['매출액', '수익(매출액)', '수익(순매출액)', '매출', '영업수익', 'I. 영업수익', '수익 합계']),
    op:       findAcctIdx('손익계산서', ['영업이익', '영업이익(손실)']),
    ni:       findAcctIdx('손익계산서', ['지배기업 소유주지분', '지배기업소유주지분', '지배기업의 소유주에게 귀속되는 당기순이익(손실)', '당기순이익', '당기순이익(손실)', '분기순이익', '분기순이익(손실)']),
    cogs:     findAcctIdx('손익계산서', ['매출원가']),
    sga:      findAcctIdx('손익계산서', ['판매비와관리비', '판매비와 관리비']),
    // 재무상태표
    ta:       findAcctIdx('재무상태표', ['자산총계']),
    tl:       findAcctIdx('재무상태표', ['부채총계']),
    eq:       findAcctIdx('재무상태표', ['자본총계']),
    ca:       findAcctIdx('재무상태표', ['유동자산']),
    nca:      findAcctIdx('재무상태표', ['비유동자산']),
    cl:       findAcctIdx('재무상태표', ['유동부채']),
    ncl:      findAcctIdx('재무상태표', ['비유동부채']),
    cash:     findAcctIdx('재무상태표', ['현금및현금성자산']),
    stFin:    findAcctIdx('재무상태표', ['단기금융상품']),
    stFv1:    findAcctIdx('재무상태표', ['단기당기손익-공정가치금융자산']),
    stFv2:    findAcctIdx('재무상태표', ['유동 당기손익-공정가치측정금융자산', '유동당기손익-공정가치측정금융자산']),
    stb:      findAcctIdx('재무상태표', ['단기차입금']),
    cpltd:    findAcctIdx('재무상태표', ['유동성장기부채', '유동성장기차입금']),
    ltb:      findAcctIdx('재무상태표', ['장기차입금']),
    bond:     findAcctIdx('재무상태표', ['사채', '장기사채']),
    ar:       findAcctIdx('재무상태표', ['매출채권', '매출채권 및 기타유동채권']),
    inv:      findAcctIdx('재무상태표', ['재고자산']),
    ap:       findAcctIdx('재무상태표', ['매입채무', '매입채무 및 기타유동채무']),
    // 현금흐름표
    cfOp:     findAcctIdx('현금흐름표', ['영업활동현금흐름', '영업활동으로 인한 현금흐름']),
    cfInv:    findAcctIdx('현금흐름표', ['투자활동현금흐름', '투자활동으로 인한 현금흐름']),
    cfFin:    findAcctIdx('현금흐름표', ['재무활동현금흐름', '재무활동으로 인한 현금흐름']),
    tAcq:     findAcctIdx('현금흐름표', ['유형자산의 취득', '유형자산의취득']),
    iAcq:     findAcctIdx('현금흐름표', ['무형자산의 취득', '무형자산의취득']),
    tDisp:    findAcctIdx('현금흐름표', ['유형자산의 처분', '유형자산의처분']),
    iDisp:    findAcctIdx('현금흐름표', ['무형자산의 처분', '무형자산의처분']),
    intPaid:  findAcctIdx('현금흐름표', ['이자의 지급']),
  };
}

// ── 헬퍼: 라벨 → priceData 분기키 매핑 ──
function matchPricePeriod(label, mode) {
  const pricePeriods = Object.keys(priceData).filter(p => p.includes('Q')).sort();
  if (mode === 'annual') {
    const y = label.slice(0, 4);
    // 먼저 분기키로 조회
    for (const q of ['Q4','Q3','Q2','Q1']) {
      if (priceData[y + q]) return y + q;
    }
    // 분기키 없으면 월별키("YYYY-MM")로 fallback (결산월 기준)
    const mm = String(finDataAccMt || accMt || 12).padStart(2, '0');
    if (priceData[y + '-' + mm]) return y + '-' + mm;
    return null;
  }
  for (const p of pricePeriods) {
    if (toDisplayLabel(p, mode === 'trailing' ? 'trailing' : 'quarterly') === label) return p;
  }
  return null;
}

// ── 헬퍼: 기간 라벨 + 값 배열 생성 ──
function getFinChartData(stmtKey, acctIdx, mode, isBS) {
  if (acctIdx < 0 || !finData || !finData.statements[stmtKey]) return { labels: [], values: [] };
  const stmtData = finData.statements[stmtKey].data;
  const allPeriods = Object.keys(stmtData).sort();
  const fm = finDataAccMt || 12;

  const labels = [];
  const values = [];

  if (mode === 'quarterly') {
    allPeriods.forEach(p => {
      labels.push(toDisplayLabel(p, 'quarterly'));
      const d = stmtData[p];
      values.push(d ? d[acctIdx] : null);
    });
  } else if (mode === 'annual') {
    const yearMap = {};
    allPeriods.forEach(p => {
      const y = p.slice(0, 4);
      if (!yearMap[y]) yearMap[y] = [];
      yearMap[y].push(p);
    });
    const mm = String(fm).padStart(2, '0');
    const sortedYears = Object.keys(yearMap).sort();
    sortedYears.forEach(y => {
      if (yearMap[y].length === 4) {
        labels.push(y + '.' + mm);
        if (isBS) {
          const q4 = stmtData[y + 'Q4'];
          values.push(q4 ? q4[acctIdx] : null);
        } else {
          let sum = 0, valid = true;
          ['Q1','Q2','Q3','Q4'].forEach(q => {
            const d = stmtData[y + q];
            if (!d || d[acctIdx] === null || d[acctIdx] === undefined) valid = false;
            else sum += d[acctIdx];
          });
          values.push(valid ? sum : null);
        }
      }
    });
    // 최신 연도가 4분기 미만이면 가용 데이터 추가
    if (sortedYears.length > 0) {
      const lastYear = sortedYears[sortedYears.length - 1];
      const lastPeriods = yearMap[lastYear];
      if (lastPeriods.length < 4 && lastPeriods.length > 0) {
        const latestQ = lastPeriods.sort().pop();
        const qtrNum = parseInt(latestQ.slice(5));
        const qtrMonthMap = {1:'03', 2:'06', 3:'09', 4:'12'};
        labels.push(lastYear + '.' + (qtrMonthMap[qtrNum] || '12'));
        if (isBS) {
          const d = stmtData[latestQ];
          values.push(d ? d[acctIdx] : null);
        } else {
          let sum = 0, count = 0;
          ['Q1','Q2','Q3','Q4'].forEach(q => {
            const d = stmtData[lastYear + q];
            if (d && d[acctIdx] !== null && d[acctIdx] !== undefined) {
              sum += d[acctIdx]; count++;
            }
          });
          values.push(count > 0 ? sum : null);
        }
      }
    }
  } else {
    // trailing
    if (isBS) {
      allPeriods.forEach(p => {
        labels.push(toDisplayLabel(p, 'trailing'));
        const d = stmtData[p];
        values.push(d ? d[acctIdx] : null);
      });
    } else {
      for (let i = 3; i < allPeriods.length; i++) {
        labels.push(toDisplayLabel(allPeriods[i], 'trailing'));
        let sum = 0, nullCount = 0;
        for (let j = i - 3; j <= i; j++) {
          const d = stmtData[allPeriods[j]];
          if (!d || d[acctIdx] === null || d[acctIdx] === undefined) nullCount++;
          else sum += d[acctIdx];
        }
        values.push(nullCount <= 1 ? sum : null);
      }
    }
  }
  return { labels, values };
}

// ── 헬퍼: 현금흐름표 전용 (YTD 누적값 → 개별 분기값 변환) ──
function getCfChartData(acctIdx, mode) {
  if (acctIdx < 0 || !finData || !finData.statements['현금흐름표']) return { labels: [], values: [] };
  const stmtData = finData.statements['현금흐름표'].data;
  const allPeriods = Object.keys(stmtData).sort();
  const fm = finDataAccMt || 12;

  // 1) YTD 누적 → 개별 분기값 변환
  const qtrValues = {};  // { '2024Q1': val, '2024Q2': val, ... }
  allPeriods.forEach(p => {
    const d = stmtData[p];
    const raw = d ? d[acctIdx] : null;
    const year = p.slice(0, 4);
    const qtr = p.slice(4);  // 'Q1','Q2','Q3','Q4'

    if (raw === null || raw === undefined) {
      qtrValues[p] = null;
    } else if (qtr === 'Q1') {
      qtrValues[p] = raw;
    } else {
      // 이전 분기 누적값을 빼서 개별 분기값 산출
      const prevQ = qtr === 'Q2' ? 'Q1' : qtr === 'Q3' ? 'Q2' : 'Q3';
      const prevKey = year + prevQ;
      const prevRaw = stmtData[prevKey] ? stmtData[prevKey][acctIdx] : null;
      if (prevRaw !== null && prevRaw !== undefined) {
        qtrValues[p] = raw - prevRaw;
      } else {
        qtrValues[p] = null;
      }
    }
  });

  const labels = [];
  const values = [];

  if (mode === 'quarterly') {
    allPeriods.forEach(p => {
      labels.push(toDisplayLabel(p, 'quarterly'));
      values.push(qtrValues[p]);
    });
  } else if (mode === 'annual') {
    // 연간: Q4 누적값(= 연간 합계)을 그대로 사용
    const yearMap = {};
    allPeriods.forEach(p => {
      const y = p.slice(0, 4);
      if (!yearMap[y]) yearMap[y] = [];
      yearMap[y].push(p);
    });
    const mm = String(fm).padStart(2, '0');
    const sortedYears = Object.keys(yearMap).sort();
    sortedYears.forEach(y => {
      if (yearMap[y].length < 4) return;
      const q4 = stmtData[y + 'Q4'];
      labels.push(y + '.' + mm);
      values.push(q4 ? q4[acctIdx] : null);
    });
    // 최신 연도가 4분기 미만이면 가용 누적값 추가
    if (sortedYears.length > 0) {
      const lastYear = sortedYears[sortedYears.length - 1];
      const lastPeriods = yearMap[lastYear];
      if (lastPeriods.length < 4 && lastPeriods.length > 0) {
        const latestQ = lastPeriods.sort().pop();
        const qtrNum = parseInt(latestQ.slice(5));
        const qtrMonthMap = {1:'03', 2:'06', 3:'09', 4:'12'};
        labels.push(lastYear + '.' + (qtrMonthMap[qtrNum] || '12'));
        const d = stmtData[latestQ];
        values.push(d ? d[acctIdx] : null);
      }
    }
  } else {
    // trailing: 개별 분기값 4개 합산 (1개 null 허용)
    for (let i = 3; i < allPeriods.length; i++) {
      labels.push(toDisplayLabel(allPeriods[i], 'trailing'));
      let sum = 0, nullCount = 0;
      for (let j = i - 3; j <= i; j++) {
        const v = qtrValues[allPeriods[j]];
        if (v === null || v === undefined) nullCount++;
        else sum += v;
      }
      values.push(nullCount <= 1 ? sum : null);
    }
  }
  return { labels, values };
}

// ── 헬퍼: 비율 계산 (a/b * 100) ──
function calcRatio(aVals, bVals) {
  return aVals.map((a, i) => {
    const b = bVals[i];
    if (a === null || b === null || b === 0) return null;
    return Math.round((a / b) * 10000) / 100;
  });
}

// ── 헬퍼: 차감 (a - b) ──
function calcDiff(aVals, bVals) {
  return aVals.map((a, i) => {
    const b = bVals[i];
    if (a === null || b === null) return null;
    return a - b;
  });
}

// ── 공통 차트 생성 함수 ──
const chartInstances = {};

function buildGenericChart(canvasId, config) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  if (chartInstances[canvasId]) chartInstances[canvasId].destroy();
  if (emptyChartInstances[canvasId]) { emptyChartInstances[canvasId].destroy(); delete emptyChartInstances[canvasId]; }

  const hasData = config.datasets.some(ds => ds.data && ds.data.length > 0);
  if (!hasData) return;

  const chartType = config.chartType || 'line';
  const yAxes = config.yAxes || {
    y: { ticks: { font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } }
  };

  chartInstances[canvasId] = new Chart(canvas, {
    type: chartType,
    data: { labels: config.labels, datasets: config.datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        title: { display: false },
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function(ctx) {
              const val = ctx.parsed.y;
              if (val === null) return ctx.dataset.label + ': N/A';
              const suffix = ctx.dataset.tooltipSuffix || '';
              const dec = ctx.dataset.tooltipDecimals != null ? ctx.dataset.tooltipDecimals : 1;
              return ctx.dataset.label + ': ' + val.toLocaleString('ko-KR', {minimumFractionDigits: dec, maximumFractionDigits: dec}) + suffix;
            }
          }
        }
      },
      scales: Object.assign({
        x: { ticks: { font: { size: 11 }, maxRotation: 45 }, grid: { display: false } }
      }, yAxes),
    },
  });

  // 커스텀 범례 생성 (helpText가 있는 dataset은 ? 버튼 포함)
  let legendEl = canvas.parentElement.querySelector('.custom-legend');
  if (!legendEl) {
    legendEl = document.createElement('div');
    legendEl.className = 'custom-legend';
    canvas.parentElement.appendChild(legendEl);
  }
  const visibleDs = config.datasets.filter(ds => ds.label !== '\uae30\uc900\uc120(100)');
  legendEl.innerHTML = visibleDs.map(ds => {
    const color = ds.borderColor || ds.backgroundColor || '#666';
    const helpHtml = ds.helpText
      ? ' <span class="chart-help-btn" onclick="toggleChartHelp(this)">?</span><div class="chart-help-popup">' + ds.helpText + '</div>'
      : '';
    return '<span class="legend-item">'
      + '<span class="legend-dot" style="background:' + color + ';"></span>'
      + ds.label + helpHtml
      + '</span>';
  }).join('');
}

// ── 색상 팔레트 ──
const CP = {
  blue:    'rgba(47,84,150,1)',
  green:   'rgba(112,173,71,1)',
  red:     'rgba(220,53,69,1)',
  orange:  'rgba(255,159,64,1)',
  skyblue: 'rgba(143,170,220,1)',
  purple:  'rgba(153,102,255,1)',
  teal:    'rgba(0,150,136,1)',
  pink:    'rgba(233,30,99,1)',
  grey:    'rgba(150,150,150,1)',
  navy:    'rgba(26,35,126,1)',
};
function alpha(c, a) { return c.replace(/,[\\d.]+\\)/, ',' + a + ')'); }

// ── 억원 → 단위 변환 헬퍼 ──
function autoUnit(values) {
  const absMax = Math.max(...values.filter(v => v !== null).map(v => Math.abs(v)), 0);
  if (absMax >= 100000) return { divisor: 10000, suffix: '조' };
  return { divisor: 1, suffix: '억' };
}
function applyUnit(values, divisor) {
  return values.map(v => v === null ? null : Math.round(v / divisor * 10) / 10);
}

// ============================================================
// 1. 매출 및 수익성 탭 차트
// ============================================================

// 1-3. 영업이익률, 순이익률
function buildMarginChart(mode) {
  const rev = getFinChartData('손익계산서', AI.revenue, mode, false);
  const op  = getFinChartData('손익계산서', AI.op, mode, false);
  const ni  = getFinChartData('손익계산서', AI.ni, mode, false);

  const opMargin = calcRatio(op.values, rev.values);
  const niMargin = calcRatio(ni.values, rev.values);

  buildGenericChart('marginChart', {
    labels: rev.labels,
    datasets: [
      { label: '영업이익률(%)', data: opMargin, borderColor: CP.blue, backgroundColor: CP.blue,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: '%',
        helpText: '영업이익 \u00f7 매출액 \u00d7 100<br>본업의 수익성을 나타냅니다.' },
      { label: '순이익률(지배)(%)', data: niMargin, borderColor: CP.green, backgroundColor: CP.green,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: '%',
        helpText: '지배순이익 \u00f7 매출액 \u00d7 100<br>세금·이자 등을 모두 반영한 최종 수익성입니다.' },
    ],
    yAxes: { y: { ticks: { callback: v => v + '%', font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } } },
  });
}

// 1-4. 매출원가율, 판관비율
function buildCostRatioChart(mode) {
  const rev  = getFinChartData('손익계산서', AI.revenue, mode, false);
  const cogs = getFinChartData('손익계산서', AI.cogs, mode, false);
  const sga  = getFinChartData('손익계산서', AI.sga, mode, false);

  const cogsRatio = calcRatio(cogs.values, rev.values);
  const sgaRatio  = calcRatio(sga.values, rev.values);

  buildGenericChart('costRatioChart', {
    labels: rev.labels,
    datasets: [
      { label: '매출원가율(%)', data: cogsRatio, borderColor: CP.red, backgroundColor: CP.red,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: '%', yAxisID: 'y',
        helpText: '매출원가 \u00f7 매출액 \u00d7 100<br>제품을 만드는데 들어간 원가 비중입니다.' },
      { label: '판관비율(%)', data: sgaRatio, borderColor: CP.orange, backgroundColor: CP.orange,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: '%', yAxisID: 'y1',
        helpText: '판매비와관리비 \u00f7 매출액 \u00d7 100<br>영업·관리 활동에 쓰인 비용 비중입니다.' },
    ],
    yAxes: {
      y:  { position: 'left',  ticks: { callback: v => v + '%', font: { size: 11 }, color: '#333' }, grid: { color: 'rgba(0,0,0,0.06)' },
            title: { display: true, text: '매출원가율(%)', color: '#333', font: { size: 11 } } },
      y1: { position: 'right', ticks: { callback: v => v + '%', font: { size: 11 }, color: '#333' }, grid: { drawOnChartArea: false },
            title: { display: true, text: '판관비율(%)', color: '#333', font: { size: 11 } } },
    },
  });
}

// ============================================================
// 2. 자산 및 배당 탭 차트
// ============================================================

// 2-1. 자산구조
function buildAssetStructChart(mode) {
  const ca  = getFinChartData('재무상태표', AI.ca, mode, true);
  const nca = getFinChartData('재무상태표', AI.nca, mode, true);
  const cl  = getFinChartData('재무상태표', AI.cl, mode, true);
  const ncl = getFinChartData('재무상태표', AI.ncl, mode, true);
  const eq  = getFinChartData('재무상태표', AI.eq, mode, true);

  const allVals = [...ca.values, ...nca.values, ...cl.values, ...ncl.values, ...eq.values];
  const u = autoUnit(allVals);

  buildGenericChart('assetStructChart', {
    labels: ca.labels,
    datasets: [
      { label: '유동자산', data: applyUnit(ca.values, u.divisor), borderColor: CP.skyblue, backgroundColor: CP.skyblue,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: u.suffix,
        helpText: '1년 이내 현금화 가능한 자산 (현금, 매출채권, 재고 등)' },
      { label: '비유동자산', data: applyUnit(nca.values, u.divisor), borderColor: CP.blue, backgroundColor: CP.blue,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: u.suffix,
        helpText: '1년 이상 장기 보유 자산 (설비, 토지, 투자자산 등)' },
      { label: '유동부채', data: applyUnit(cl.values, u.divisor), borderColor: CP.orange, backgroundColor: CP.orange,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: u.suffix,
        helpText: '1년 이내 갚아야 할 부채 (매입채무, 단기차입금 등)' },
      { label: '비유동부채', data: applyUnit(ncl.values, u.divisor), borderColor: CP.red, backgroundColor: CP.red,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: u.suffix,
        helpText: '1년 이후 갚아야 할 부채 (장기차입금, 사채 등)' },
      { label: '자본총계', data: applyUnit(eq.values, u.divisor), borderColor: CP.green, backgroundColor: CP.green,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: u.suffix,
        helpText: '자산총계 - 부채총계 (주주의 몫)' },
    ],
    yAxes: { y: { ticks: { callback: v => v.toLocaleString('ko-KR', {minimumFractionDigits: 1, maximumFractionDigits: 1}) + u.suffix, font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } } },
  });
}

// 2-2. 조정 순운전자본 (backend_nwc.py 동일 로직 사용)
function buildCashAssetChart(mode) {
  // 백엔드에서 계산된 조정순운전자본 데이터 사용
  const adjNwcSrc = finData.statements._adj_nwc || {};
  const allPeriods = Object.keys(adjNwcSrc).sort();
  if (allPeriods.length === 0) return;

  const fm = finDataAccMt || 12;
  const labels = [];
  const adjCA = [];
  const adjCL = [];
  const adjNWC = [];

  if (mode === 'annual') {
    const yearMap = {};
    allPeriods.forEach(p => { const y = p.slice(0,4); if(!yearMap[y]) yearMap[y]=[]; yearMap[y].push(p); });
    Object.keys(yearMap).sort().forEach(y => {
      if (yearMap[y].length < 4) return;
      const q4key = y + 'Q4';
      const d = adjNwcSrc[q4key];
      const mm = String(fm).padStart(2, '0');
      labels.push(y + '.' + mm);
      if (d) { adjCA.push(d.adj_ca); adjCL.push(d.adj_cl); adjNWC.push(d.adj_nwc); }
      else { adjCA.push(null); adjCL.push(null); adjNWC.push(null); }
    });
  } else {
    // quarterly & trailing: 재무상태표는 시점값이므로 동일
    allPeriods.forEach(p => {
      labels.push(toDisplayLabel(p, mode === 'trailing' ? 'trailing' : 'quarterly'));
      const d = adjNwcSrc[p];
      if (d) { adjCA.push(d.adj_ca); adjCL.push(d.adj_cl); adjNWC.push(d.adj_nwc); }
      else { adjCA.push(null); adjCL.push(null); adjNWC.push(null); }
    });
  }

  // 시가총액 = 주가 × 상장주식수 (priceData 사용, 분기키만)
  const pricePeriods = Object.keys(priceData).filter(p => p.includes('Q')).sort();
  const lastBSp = allPeriods.length > 0 ? allPeriods[allPeriods.length - 1] : '';
  const extraPeriods = pricePeriods.filter(p => p > lastBSp);

  const marketCap = [];
  const finalLabels = [...labels];

  if (mode === 'annual') {
    const yearMap = {};
    allPeriods.forEach(p => { const y = p.slice(0,4); if(!yearMap[y]) yearMap[y]=[]; yearMap[y].push(p); });
    const amm = String(finDataAccMt || accMt || 12).padStart(2, '0');
    Object.keys(yearMap).sort().forEach(y => {
      if (yearMap[y].length < 4) return;
      const pd = priceData[y+'Q4'] || priceData[y+'-'+amm];
      if (pd && pd.price && pd.shares) {
        marketCap.push(pd.price * (pd.total_shares || pd.shares) / 100000000);
      } else { marketCap.push(null); }
    });
  } else {
    allPeriods.forEach(p => {
      const pd = priceData[p];
      if (pd && pd.price && pd.shares) {
        marketCap.push(pd.price * (pd.total_shares || pd.shares) / 100000000);
      } else { marketCap.push(null); }
    });
    // BS 이후 추가 분기 — 시가총액만 연장
    const modeLabel = (mode === 'trailing') ? 'trailing' : 'quarterly';
    extraPeriods.forEach(p => {
      const pd = priceData[p];
      if (pd && pd.price && pd.shares) {
        marketCap.push(pd.price * (pd.total_shares || pd.shares) / 100000000);
        finalLabels.push(toDisplayLabel(p, modeLabel));
        adjCA.push(null);
        adjCL.push(null);
        adjNWC.push(null);
      }
    });
  }

  const allVals = [...adjNWC, ...marketCap];
  const u = autoUnit(allVals);

  buildGenericChart('cashAssetChart', {
    labels: finalLabels,
    datasets: [
      { label: '조정순운전자본', data: applyUnit(adjNWC, u.divisor), borderColor: CP.blue, backgroundColor: CP.blue,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: u.suffix,
        helpText: '조정유동자산 - 조정유동부채' },
      { label: '시가총액', data: applyUnit(marketCap, u.divisor), borderColor: CP.red, backgroundColor: CP.red,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: u.suffix,
        helpText: '주가 \u00d7 상장주식수<br>조정순운전자본과 비교하여 저평가를 판단합니다.' },
    ],
    yAxes: { y: { ticks: { callback: v => v.toLocaleString('ko-KR', {minimumFractionDigits: 1, maximumFractionDigits: 1}) + u.suffix, font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } } },
  });
}

// 2-3. 배당금, 배당성향, 시가배당률 — DART '6. 배당에 관한 사항' 데이터 연동
let _dividendData = null;
let _dividendLoading = false;

async function loadDividendData() {
  if (_dividendData || _dividendLoading) return _dividendData;
  _dividendLoading = true;
  try {
    const company = currentStockCode || currentCompany;
    const res = await fetch('/api/dividend?company=' + encodeURIComponent(company));
    const data = await res.json();
    if (data && data.dividend) {
      _dividendData = data.dividend;
    }
  } catch(e) {
    console.error('배당 데이터 로드 오류:', e);
  }
  _dividendLoading = false;
  return _dividendData;
}

async function buildDividendChart(mode) {
  // 배당 데이터 로드 (비동기)
  const divData = await loadDividendData();
  if (!divData || Object.keys(divData).length === 0) return;

  const years = Object.keys(divData).sort();
  const labels = years.map(y => y);
  const dpsArr = years.map(y => divData[y].dps);
  const payoutArr = years.map(y => divData[y].payout_ratio);
  const yieldArr = years.map(y => divData[y].div_yield);

  buildGenericChart('dividendChart', {
    chartType: 'bar',
    labels: labels,
    datasets: [
      { label: '배당금', data: dpsArr, backgroundColor: alpha(CP.blue,0.7), borderColor: CP.blue, borderWidth: 1, yAxisID: 'y', tooltipSuffix: '원',
        helpText: '주당 현금배당금 (보통주 기준, 원)' },
      { label: '배당성향(%)', data: payoutArr, type: 'line', borderColor: CP.green, backgroundColor: CP.green, borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, yAxisID: 'y1', tooltipSuffix: '%',
        helpText: '현금배당금총액 \u00f7 지배순이익 \u00d7 100<br>이익 중 배당으로 지급하는 비율입니다.' },
      { label: '시가배당률(%)', data: yieldArr, type: 'line', borderColor: CP.red, backgroundColor: CP.red, borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, yAxisID: 'y1', tooltipSuffix: '%',
        helpText: '주당배당금 \u00f7 주가 \u00d7 100<br>투자 대비 배당 수익률입니다.' },
    ],
    yAxes: {
      y:  { position: 'left', ticks: { callback: v => v.toLocaleString() + '원', font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } },
      y1: { position: 'right', ticks: { callback: v => v + '%', font: { size: 11 } }, grid: { display: false } }
    },
  });
}

// ============================================================
// 3. 현금흐름 탭 차트
// ============================================================

// 3-1. 영업/투자/재무 현금흐름
function buildCfChart(mode) {
  // 현금흐름표는 YTD 누적값 → 개별 분기값 변환 후 처리
  const op  = getCfChartData(AI.cfOp, mode);
  const inv = getCfChartData(AI.cfInv, mode);
  const fin = getCfChartData(AI.cfFin, mode);

  const allVals = [...op.values, ...inv.values, ...fin.values];
  const u = autoUnit(allVals);

  buildGenericChart('cfChart', {
    labels: op.labels,
    datasets: [
      { label: '영업활동', data: applyUnit(op.values, u.divisor), borderColor: CP.blue, backgroundColor: CP.blue, borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: u.suffix,
        helpText: '본업에서 벌어들인 현금흐름<br>양수일수록 영업이 잘 되고 있다는 뜻입니다.' },
      { label: '투자활동', data: applyUnit(inv.values, u.divisor), borderColor: CP.red, backgroundColor: CP.red, borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: u.suffix,
        helpText: '설비·자산 취득 등 투자에 사용된 현금<br>음수가 일반적이며, 적극적 투자를 의미합니다.' },
      { label: '재무활동', data: applyUnit(fin.values, u.divisor), borderColor: CP.orange, backgroundColor: CP.orange, borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: u.suffix,
        helpText: '차입·상환·배당 등 재무활동 현금흐름<br>양수=자금조달, 음수=상환·배당 지급.' },
    ],
    yAxes: { y: { ticks: { callback: v => v.toLocaleString('ko-KR', {minimumFractionDigits: 1, maximumFractionDigits: 1}) + u.suffix, font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } } },
  });
}

// 3-2. FCF, 순이익
function buildFcfChart(mode) {
  // FCF = 영업CF - 유형자산취득 - 무형자산취득 + 유형자산처분 + 무형자산처분
  const op    = getCfChartData(AI.cfOp, mode);
  const tAcq  = AI.tAcq >= 0 ? getCfChartData(AI.tAcq, mode) : { labels: [], values: [] };
  const iAcq  = AI.iAcq >= 0 ? getCfChartData(AI.iAcq, mode) : { labels: [], values: [] };
  const tDisp = AI.tDisp >= 0 ? getCfChartData(AI.tDisp, mode) : { labels: [], values: [] };
  const iDisp = AI.iDisp >= 0 ? getCfChartData(AI.iDisp, mode) : { labels: [], values: [] };
  const ni    = getFinChartData('손익계산서', AI.ni, mode, false);

  // FCF = 영업CF + 유형자산취득(음수) + 무형자산취득(음수) + 유형자산처분(양수) + 무형자산처분(양수)
  const fcf = op.values.map((v, i) => {
    if (v === null) return null;
    return v + (tAcq.values[i] || 0) + (iAcq.values[i] || 0) + (tDisp.values[i] || 0) + (iDisp.values[i] || 0);
  });

  // ni의 labels와 op의 labels 길이가 다를 수 있으므로 op 기준
  const niAligned = op.labels.map((lbl, i) => {
    const idx = ni.labels.indexOf(lbl);
    return idx >= 0 ? ni.values[idx] : null;
  });

  const allVals = [...fcf, ...niAligned];
  const u = autoUnit(allVals);

  buildGenericChart('fcfChart', {
    chartType: 'bar',
    labels: op.labels,
    datasets: [
      { label: 'FCF(잉여현금흐름)', data: applyUnit(fcf, u.divisor), backgroundColor: alpha(CP.blue,0.7), borderColor: CP.blue, borderWidth: 1, tooltipSuffix: u.suffix,
        helpText: '영업CF - 유형자산취득 - 무형자산취득<br>+ 유형자산처분 + 무형자산처분<br>기업이 자유롭게 쓸 수 있는 현금입니다.' },
      { label: '순이익(지배)', data: applyUnit(niAligned, u.divisor), type: 'line', borderColor: CP.green, backgroundColor: CP.green, borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: u.suffix,
        helpText: '지배기업 소유주 귀속 순이익<br>FCF와 비교하여 이익의 질을 판단합니다.' },
    ],
    yAxes: { y: { ticks: { callback: v => v.toLocaleString('ko-KR', {minimumFractionDigits: 1, maximumFractionDigits: 1}) + u.suffix, font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } } },
  });
}

// ============================================================
// 4. 부채 및 안전성 탭 차트
// ============================================================

// 4-1. 부채비율, 유동비율
function buildDebtRatioChart(mode) {
  const tl = getFinChartData('재무상태표', AI.tl, mode, true);
  const eq = getFinChartData('재무상태표', AI.eq, mode, true);
  const ca = getFinChartData('재무상태표', AI.ca, mode, true);
  const cl = getFinChartData('재무상태표', AI.cl, mode, true);

  const debtRatio    = calcRatio(tl.values, eq.values);
  const currentRatio = calcRatio(ca.values, cl.values);

  buildGenericChart('debtRatioChart', {
    labels: tl.labels,
    datasets: [
      { label: '부채비율(%)', data: debtRatio, borderColor: CP.red, backgroundColor: CP.red,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: '%',
        helpText: '부채총계 \u00f7 자본총계 \u00d7 100<br>100% 이하가 안정적입니다.' },
      { label: '유동비율(%)', data: currentRatio, borderColor: CP.blue, backgroundColor: CP.blue,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: '%',
        helpText: '유동자산 \u00f7 유동부채 \u00d7 100<br>200% 이상이면 단기 지급능력 양호합니다.' },
    ],
    yAxes: { y: { ticks: { callback: v => v + '%', font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } } },
  });
}

// 4-2. 차입금과 차입금 비중
function buildBorrowingChart(mode) {
  // 단기차입금 + 유동성장기부채 + 장기차입금 + 사채
  const stb   = getFinChartData('재무상태표', AI.stb, mode, true);
  const cpltd = getFinChartData('재무상태표', AI.cpltd, mode, true);
  const ltb   = getFinChartData('재무상태표', AI.ltb, mode, true);
  const bond  = getFinChartData('재무상태표', AI.bond, mode, true);
  const ta    = getFinChartData('재무상태표', AI.ta, mode, true);

  const totalBorrow = stb.values.map((v, i) => {
    let s = 0;
    [v, cpltd.values[i], ltb.values[i], bond.values[i]].forEach(x => { if (x !== null) s += x; });
    return s || null;
  });
  const borrowRatio = calcRatio(totalBorrow, ta.values);

  const u = autoUnit(totalBorrow);
  buildGenericChart('borrowingChart', {
    chartType: 'bar',
    labels: stb.labels,
    datasets: [
      { label: '차입금', data: applyUnit(totalBorrow, u.divisor), backgroundColor: alpha(CP.skyblue,0.7), borderColor: CP.skyblue, borderWidth: 1, tooltipSuffix: u.suffix,
        helpText: '단기차입금 + 유동성장기부채 + 장기차입금 + 사채<br>총 이자부 차입금 규모입니다.' },
      { label: '차입금비중(%)', data: borrowRatio, type: 'line', borderColor: CP.blue, backgroundColor: CP.blue, borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, yAxisID: 'y-right', tooltipSuffix: '%',
        helpText: '차입금 \u00f7 자산총계 \u00d7 100<br>자산 대비 차입 의존도를 나타냅니다.' },
    ],
    yAxes: {
      y: { position: 'left', ticks: { callback: v => v.toLocaleString('ko-KR', {minimumFractionDigits: 1, maximumFractionDigits: 1}) + u.suffix, font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } },
      'y-right': { position: 'right', ticks: { callback: v => v + '%', font: { size: 11 } }, grid: { display: false } },
    },
  });
}

// 4-3. 영업이익, 이자비용 (현금흐름표 '이자의 지급' 기준)
function buildInterestChart(mode) {
  const op  = getFinChartData('손익계산서', AI.op, mode, false);
  const int_ = getCfChartData(AI.intPaid, mode);
  // 현금흐름표 '이자의 지급'은 음수(현금유출) → 절대값으로 변환
  const intAbs = int_.values.map(v => v === null ? null : Math.abs(v));

  const uOp  = autoUnit(op.values);
  const uInt = autoUnit(intAbs);

  buildGenericChart('interestChart', {
    chartType: 'bar',
    labels: op.labels,
    datasets: [
      { label: '영업이익', data: applyUnit(op.values, uOp.divisor), backgroundColor: alpha(CP.blue,0.7), borderColor: CP.blue, borderWidth: 1, yAxisID: 'y', tooltipSuffix: uOp.suffix,
        helpText: '매출액 - 매출원가 - 판관비<br>본업에서 벌어들인 이익입니다.' },
      { label: '이자비용', data: applyUnit(intAbs, uInt.divisor), type: 'line', borderColor: CP.red, backgroundColor: CP.red,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, yAxisID: 'y-right', tooltipSuffix: uInt.suffix,
        helpText: '현금흐름표 "이자의 지급" 기준<br>실제 이자 현금지출액입니다.' },
    ],
    yAxes: {
      y: { position: 'left', ticks: { callback: v => v + uOp.suffix, font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } },
      'y-right': { position: 'right', ticks: { callback: v => v + uInt.suffix, font: { size: 11 } }, grid: { display: false } }
    },
  });
}

// 4-4. 이자보상배율 (현금흐름표 '이자의 지급' 기준)
function buildIcrChart(mode) {
  const op   = getFinChartData('손익계산서', AI.op, mode, false);
  const int_ = getCfChartData(AI.intPaid, mode);
  // 현금흐름표 '이자의 지급'은 음수(현금유출) → 절대값으로 변환
  const intAbs = int_.values.map(v => v === null ? null : Math.abs(v));

  const icr = op.values.map((v, i) => {
    const interest = intAbs[i];
    if (v === null || interest === null || interest === 0) return null;
    return Math.round((v / interest) * 100) / 100;
  });

  const u = autoUnit(op.values);

  buildGenericChart('icrChart', {
    chartType: 'bar',
    labels: op.labels,
    datasets: [
      { label: '영업이익', data: applyUnit(op.values, u.divisor), backgroundColor: alpha(CP.blue,0.7), borderColor: CP.blue, borderWidth: 1, yAxisID: 'y', tooltipSuffix: u.suffix,
        helpText: '매출액 - 매출원가 - 판관비<br>본업에서 벌어들인 이익입니다.' },
      { label: '이자보상배율(배)', data: icr, type: 'line', borderColor: CP.red, backgroundColor: CP.red,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, yAxisID: 'y-right', tooltipSuffix: '배',
        helpText: '영업이익 \u00f7 이자비용(현금)<br>1배 미만이면 이자도 못 내는 위험 수준입니다.' },
    ],
    yAxes: {
      y: { position: 'left', ticks: { callback: v => v + u.suffix, font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } },
      'y-right': { position: 'right', ticks: { callback: v => v + '배', font: { size: 11 } }, grid: { display: false } }
    },
  });
}

// 4-5. 순현금 비중
function buildNetCashChart(mode) {
  // 현금성자산 구성 + 총차입금 → 캐시된 인덱스 사용

  const cash   = getFinChartData('재무상태표', AI.cash, mode, true);
  const stFin  = getFinChartData('재무상태표', AI.stFin, mode, true);
  const stFv1  = getFinChartData('재무상태표', AI.stFv1, mode, true);
  const stFv2  = getFinChartData('재무상태표', AI.stFv2, mode, true);
  const stb    = getFinChartData('재무상태표', AI.stb, mode, true);
  const cpltd  = getFinChartData('재무상태표', AI.cpltd, mode, true);
  const ltb    = getFinChartData('재무상태표', AI.ltb, mode, true);
  const bond   = getFinChartData('재무상태표', AI.bond, mode, true);

  // 순현금 = (현금 + 단기금융상품 + 단기FV금융자산1 + 단기FV금융자산2) - 총차입금
  const netCash = cash.values.map((v, i) => {
    let cashTotal = 0;
    [v, stFin.values[i], stFv1.values[i], stFv2.values[i]].forEach(x => { if (x !== null && x !== undefined) cashTotal += x; });
    let borrow = 0;
    [stb.values[i], cpltd.values[i], ltb.values[i], bond.values[i]].forEach(x => { if (x !== null && x !== undefined) borrow += x; });
    return cashTotal - borrow;
  });

  // 시총대비 순현금 비중 = 순현금 / 시가총액 × 100
  const pricePeriods = Object.keys(priceData).filter(p => p.includes('Q')).sort();
  const netCashMcapRatio = cash.labels.map((lbl, i) => {
    if (netCash[i] === null) return null;
    // 라벨에서 해당 분기 키 찾기
    let matchedPeriod = null;
    if (mode === 'annual') {
      // 연간: 라벨 'YYYY.MM' → 해당 연도 Q4 또는 최신 분기
      const y = lbl.slice(0, 4);
      ['Q4','Q3','Q2','Q1'].forEach(q => {
        if (!matchedPeriod && priceData[y + q]) matchedPeriod = y + q;
      });
    } else {
      // 분기/연환산: 라벨 'YY.MM' → 분기키 매핑
      pricePeriods.forEach(p => {
        const pLabel = toDisplayLabel(p, mode === 'trailing' ? 'trailing' : 'quarterly');
        if (pLabel === lbl) matchedPeriod = p;
      });
    }
    if (!matchedPeriod || !priceData[matchedPeriod]) return null;
    const pd = priceData[matchedPeriod];
    const mcap = pd.price * (pd.total_shares || pd.shares) / 100000000;  // 억원
    if (mcap === 0) return null;
    return Math.round((netCash[i] / mcap) * 10000) / 100;
  });

  // 최근 거래일 시총대비 순현금 비중 추가
  const finalLabels2 = [...cash.labels];
  const finalNetCash = [...netCash];
  const finalMcapRatio = [...netCashMcapRatio];
  if (priceData.latest && netCash.length > 0) {
    const lastNetCash = netCash[netCash.length - 1];
    if (lastNetCash !== null) {
      const lp = priceData.latest;
      const latestMcap = lp.price * (lp.total_shares || lp.shares) / 100000000;
      const latestRatio = latestMcap !== 0 ? Math.round((lastNetCash / latestMcap) * 10000) / 100 : null;
      const dateStr = lp.date || '';
      finalLabels2.push(dateStr.slice(2,4) + '.' + dateStr.slice(5,7));
      finalNetCash.push(lastNetCash);  // 순현금은 최근 분기와 동일
      finalMcapRatio.push(latestRatio);
    }
  }

  const u = autoUnit(finalNetCash);

  buildGenericChart('netCashChart', {
    chartType: 'bar',
    labels: finalLabels2,
    datasets: [
      { label: '순현금', data: applyUnit(finalNetCash, u.divisor), backgroundColor: alpha(CP.teal,0.7), borderColor: CP.teal, borderWidth: 1, yAxisID: 'y', tooltipSuffix: u.suffix,
        helpText: '(현금및현금성자산 + 단기금융상품 + 단기FV금융자산) - 총차입금<br>양수면 무차입 경영, 음수면 순차입 상태입니다.' },
      { label: '시총대비 순현금비중(%)', data: finalMcapRatio, type: 'line', borderColor: CP.blue, backgroundColor: CP.blue,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, yAxisID: 'y-right', tooltipSuffix: '%',
        helpText: '순현금 \u00f7 시가총액 \u00d7 100<br>높을수록 시가총액 대비 보유 현금이 풍부합니다.' },
    ],
    yAxes: {
      y: { position: 'left', ticks: { callback: v => v + u.suffix, font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } },
      'y-right': { position: 'right', ticks: { callback: v => v + '%', font: { size: 11 } }, grid: { display: false } }
    },
  });
}

// ============================================================
// 5. ROE 및 효율성 탭 차트
// ============================================================

// 5-1. ROE, PBR — PBR은 주가 데이터 필요, 우선 ROE만
function buildRoePbrChart(mode) {
  const ni = getFinChartData('손익계산서', AI.ni, mode, false);
  const eq = getFinChartData('재무상태표', AI.eq, mode, true);

  // ROE = 순이익 / 자본총계 × 100
  const roe = ni.labels.map((lbl, i) => {
    const eqI = eq.labels.indexOf(lbl);
    if (ni.values[i] === null || eqI < 0 || eq.values[eqI] === null || eq.values[eqI] === 0) return null;
    return Math.round((ni.values[i] / eq.values[eqI]) * 10000) / 100;
  });

  // PBR = 시가총액 / 자본총계 (ni.labels 기준으로 매핑하여 ROE와 길이 일치)
  const pricePeriods = Object.keys(priceData).filter(p => p.includes('Q')).sort();
  const pbr = ni.labels.map((lbl, i) => {
    const eqI = eq.labels.indexOf(lbl);
    if (eqI < 0 || eq.values[eqI] === null || eq.values[eqI] === 0) return null;
    let matchedPeriod = null;
    if (mode === 'annual') {
      const y = lbl.slice(0, 4);
      ['Q4','Q3','Q2','Q1'].forEach(q => {
        if (!matchedPeriod && priceData[y + q]) matchedPeriod = y + q;
      });
    } else {
      pricePeriods.forEach(p => {
        const pLabel = toDisplayLabel(p, mode === 'trailing' ? 'trailing' : 'quarterly');
        if (pLabel === lbl) matchedPeriod = p;
      });
    }
    if (!matchedPeriod || !priceData[matchedPeriod]) return null;
    const pd = priceData[matchedPeriod];
    const mcap = pd.price * (pd.total_shares || pd.shares) / 100000000;  // 억원
    return Math.round((mcap / eq.values[eqI]) * 100) / 100;
  });

  // 최근 거래일 PBR 추가 (어제 주가 / 최근 분기 자본총계)
  const finalLabels = [...ni.labels];
  const finalRoe = [...roe];
  const finalPbr = [...pbr];
  if (priceData.latest && eq.values.length > 0) {
    const latestEq = eq.values[eq.values.length - 1];
    if (latestEq !== null && latestEq !== 0) {
      const lp = priceData.latest;
      const latestMcap = lp.price * (lp.total_shares || lp.shares) / 100000000;
      const latestPbr = Math.round((latestMcap / latestEq) * 100) / 100;
      const dateStr = lp.date || '';
      // '2025-02-09' → '25.02'
      finalLabels.push(dateStr.slice(2,4) + '.' + dateStr.slice(5,7));
      finalRoe.push(null);
      finalPbr.push(latestPbr);
    }
  }

  buildGenericChart('roePbrChart', {
    labels: finalLabels,
    datasets: [
      { label: 'ROE(지배)(%)', data: finalRoe, borderColor: CP.blue, backgroundColor: CP.blue,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, yAxisID: 'y', tooltipSuffix: '%', spanGaps: true,
        helpText: '지배순이익 \u00f7 자본총계 \u00d7 100<br>주주 자본 대비 수익률입니다.' },
      { label: 'PBR(배)', data: finalPbr, borderColor: CP.red, backgroundColor: CP.red,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, yAxisID: 'y-right', tooltipSuffix: '배', tooltipDecimals: 2,
        helpText: '시가총액 \u00f7 자본총계<br>1배 미만이면 순자산 대비 저평가 상태입니다.' },
    ],
    yAxes: {
      y: { position: 'left', ticks: { callback: v => v + '%', font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } },
      'y-right': { position: 'right', ticks: { callback: v => parseFloat(v.toFixed(2)) + '배', font: { size: 11 } }, grid: { display: false } }
    },
  });
}

// ────────────────────────────────────────────
// 가치평가 탭 전용 차트
// ────────────────────────────────────────────

// V-1. 주가 vs. 주당순자산(BPS)
function buildPriceBpsChart(mode) {
  const eq = getFinChartData('재무상태표', AI.eq, mode, true);
  if (eq.labels.length === 0) return;

  const prices = [];
  const bpsArr = [];
  const labels = [];

  eq.labels.forEach((lbl, i) => {
    const mp = matchPricePeriod(lbl, mode);
    if (!mp || !priceData[mp]) { prices.push(null); }
    else { prices.push(priceData[mp].price); }

    // BPS = 자본총계(억원) × 1억 ÷ 주식총수(보통주+우선주)
    const ts = (mp && priceData[mp]) ? (priceData[mp].total_shares || priceData[mp].shares) : (priceData.latest ? (priceData.latest.total_shares || priceData.latest.shares) : null);
    if (eq.values[i] !== null && ts && ts > 0) {
      bpsArr.push(Math.round(eq.values[i] * 100000000 / ts));
    } else {
      bpsArr.push(null);
    }
    labels.push(lbl);
  });

  // latest 데이터 포인트 추가
  if (priceData.latest && eq.values.length > 0) {
    const latestEq = eq.values[eq.values.length - 1];
    const lp = priceData.latest;
    const lts = lp.total_shares || lp.shares;
    if (latestEq !== null && lts > 0) {
      const dateStr = lp.date || '';
      labels.push(dateStr.slice(2,4) + '.' + dateStr.slice(5,7));
      prices.push(lp.price);
      bpsArr.push(Math.round(latestEq * 100000000 / lts));
    }
  }

  buildGenericChart('priceBpsChart', {
    labels: labels,
    datasets: [
      { label: '주가(원)', data: prices, borderColor: CP.red, backgroundColor: CP.red,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, yAxisID: 'y',
        tooltipSuffix: '원', spanGaps: true,
        helpText: '분기말 종가 기준 주가' },
      { label: 'BPS(원)', data: bpsArr, borderColor: CP.blue, backgroundColor: CP.blue,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, yAxisID: 'y',
        tooltipSuffix: '원', spanGaps: true,
        helpText: '자본총계 ÷ 상장주식수<br>주당 순자산가치입니다.' },
    ],
    yAxes: {
      y: { position: 'left', ticks: { callback: v => v.toLocaleString('ko-KR') + '원', font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } },
    },
  });
}

// V-2. 주가 vs. 주당순이익(EPS)
function buildPriceEpsChart(mode) {
  const ni = getFinChartData('손익계산서', AI.ni, mode, false);
  if (ni.labels.length === 0) return;

  const prices = [];
  const epsArr = [];
  const labels = [];

  ni.labels.forEach((lbl, i) => {
    const mp = matchPricePeriod(lbl, mode);
    if (!mp || !priceData[mp]) { prices.push(null); }
    else { prices.push(priceData[mp].price); }

    // EPS = 지배순이익(억원) × 1억 ÷ 주식총수(보통주+우선주)
    const ts = (mp && priceData[mp]) ? (priceData[mp].total_shares || priceData[mp].shares) : (priceData.latest ? (priceData.latest.total_shares || priceData.latest.shares) : null);
    if (ni.values[i] !== null && ts && ts > 0) {
      epsArr.push(Math.round(ni.values[i] * 100000000 / ts));
    } else {
      epsArr.push(null);
    }
    labels.push(lbl);
  });

  // latest 데이터 포인트 추가
  if (priceData.latest && ni.values.length > 0) {
    const latestNi = ni.values[ni.values.length - 1];
    const lp = priceData.latest;
    const lts = lp.total_shares || lp.shares;
    if (latestNi !== null && lts > 0) {
      const dateStr = lp.date || '';
      labels.push(dateStr.slice(2,4) + '.' + dateStr.slice(5,7));
      prices.push(lp.price);
      epsArr.push(Math.round(latestNi * 100000000 / lts));
    }
  }

  buildGenericChart('priceEpsChart', {
    labels: labels,
    datasets: [
      { label: '주가(원)', data: prices, borderColor: CP.red, backgroundColor: CP.red,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, yAxisID: 'y',
        tooltipSuffix: '원', spanGaps: true,
        helpText: '분기말 종가 기준 주가' },
      { label: 'EPS(원)', data: epsArr, borderColor: CP.blue, backgroundColor: CP.blue,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, yAxisID: 'y-right',
        tooltipSuffix: '원', spanGaps: true,
        helpText: '지배순이익 ÷ 상장주식수<br>주당 순이익입니다.' },
    ],
    yAxes: {
      y: { position: 'left', ticks: { callback: v => v.toLocaleString('ko-KR') + '원', font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } },
      'y-right': { position: 'right', ticks: { callback: v => v.toLocaleString('ko-KR') + '원', font: { size: 11 } }, grid: { display: false } }
    },
  });
}

// V-3. PER (주가수익배수)
function buildPerChart(mode) {
  const ni = getFinChartData('손익계산서', AI.ni, mode, false);
  if (ni.labels.length === 0) return;

  const perArr = ni.labels.map((lbl, i) => {
    if (ni.values[i] === null || ni.values[i] === 0) return null;
    const mp = matchPricePeriod(lbl, mode);
    if (!mp || !priceData[mp]) return null;
    const pd = priceData[mp];
    const mcap = pd.price * (pd.total_shares || pd.shares) / 100000000;  // 억원
    return Math.round((mcap / ni.values[i]) * 100) / 100;
  });

  // latest PER 추가
  const finalLabels = [...ni.labels];
  const finalPer = [...perArr];
  if (priceData.latest && ni.values.length > 0) {
    const latestNi = ni.values[ni.values.length - 1];
    if (latestNi !== null && latestNi !== 0) {
      const lp = priceData.latest;
      const latestMcap = lp.price * (lp.total_shares || lp.shares) / 100000000;
      const latestPer = Math.round((latestMcap / latestNi) * 100) / 100;
      const dateStr = lp.date || '';
      finalLabels.push(dateStr.slice(2,4) + '.' + dateStr.slice(5,7));
      finalPer.push(latestPer);
    }
  }

  buildGenericChart('perChart', {
    labels: finalLabels,
    datasets: [
      { label: 'PER(배)', data: finalPer, borderColor: CP.blue, backgroundColor: alpha(CP.blue, 0.1),
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: true, tooltipSuffix: '배', tooltipDecimals: 2, spanGaps: true,
        helpText: '시가총액 ÷ 지배순이익<br>주가가 순이익의 몇 배인지 나타냅니다.' },
    ],
    yAxes: {
      y: { ticks: { callback: v => parseFloat(v.toFixed(2)) + '배', font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } },
    },
  });
}

// V-4. PBR (주가순자산배수)
function buildPbrChart(mode) {
  const eq = getFinChartData('재무상태표', AI.eq, mode, true);
  if (eq.labels.length === 0) return;

  const pbrArr = eq.labels.map((lbl, i) => {
    if (eq.values[i] === null || eq.values[i] === 0) return null;
    const mp = matchPricePeriod(lbl, mode);
    if (!mp || !priceData[mp]) return null;
    const pd = priceData[mp];
    const mcap = pd.price * (pd.total_shares || pd.shares) / 100000000;  // 억원
    return Math.round((mcap / eq.values[i]) * 100) / 100;
  });

  // latest PBR 추가
  const finalLabels = [...eq.labels];
  const finalPbr = [...pbrArr];
  if (priceData.latest && eq.values.length > 0) {
    const latestEq = eq.values[eq.values.length - 1];
    if (latestEq !== null && latestEq !== 0) {
      const lp = priceData.latest;
      const latestMcap = lp.price * (lp.total_shares || lp.shares) / 100000000;
      const latestPbr = Math.round((latestMcap / latestEq) * 100) / 100;
      const dateStr = lp.date || '';
      finalLabels.push(dateStr.slice(2,4) + '.' + dateStr.slice(5,7));
      finalPbr.push(latestPbr);
    }
  }

  buildGenericChart('pbrChart', {
    labels: finalLabels,
    datasets: [
      { label: 'PBR(배)', data: finalPbr, borderColor: CP.red, backgroundColor: alpha(CP.red, 0.1),
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: true, tooltipSuffix: '배', tooltipDecimals: 2, spanGaps: true,
        helpText: '시가총액 ÷ 자본총계<br>1배 미만이면 순자산 대비 저평가 상태입니다.' },
    ],
    yAxes: {
      y: { ticks: { callback: v => parseFloat(v.toFixed(2)) + '배', font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } },
    },
  });
}

// 5-2. 듀퐁분석
function buildDupontChart(mode) {
  const rev = getFinChartData('손익계산서', AI.revenue, mode, false);
  const ni  = getFinChartData('손익계산서', AI.ni, mode, false);
  const ta  = getFinChartData('재무상태표', AI.ta, mode, true);
  const eq  = getFinChartData('재무상태표', AI.eq, mode, true);

  const niMargin = calcRatio(ni.values, rev.values);
  const assetTurnover = rev.labels.map((lbl, i) => {
    const taI = ta.labels.indexOf(lbl);
    if (rev.values[i] === null || taI < 0 || ta.values[taI] === null || ta.values[taI] === 0) return null;
    return Math.round((rev.values[i] / ta.values[taI]) * 100) / 100;
  });
  const leverage = rev.labels.map((lbl, i) => {
    const taI = ta.labels.indexOf(lbl);
    const eqI = eq.labels.indexOf(lbl);
    if (taI < 0 || eqI < 0 || ta.values[taI] === null || eq.values[eqI] === null || eq.values[eqI] === 0) return null;
    return Math.round((ta.values[taI] / eq.values[eqI]) * 100) / 100;
  });

  buildGenericChart('dupontChart', {
    labels: rev.labels,
    datasets: [
      { label: '순이익률(지배)(%)', data: niMargin, borderColor: CP.blue, backgroundColor: CP.blue,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, yAxisID: 'y-left', tooltipSuffix: '%',
        helpText: '지배순이익 \u00f7 매출액 \u00d7 100<br>듀퐁분석 1단계: 수익성 지표입니다.' },
      { label: '총자산회전률(회)', data: assetTurnover, borderColor: CP.green, backgroundColor: CP.green,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, yAxisID: 'y-right', tooltipSuffix: '회',
        helpText: '매출액 \u00f7 자산총계<br>듀퐁분석 2단계: 자산 활용 효율성입니다.' },
      { label: '재무레버리지(배)', data: leverage, borderColor: CP.red, backgroundColor: CP.red,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, yAxisID: 'y-right', tooltipSuffix: '배',
        helpText: '자산총계 \u00f7 자본총계<br>듀퐁분석 3단계: 차입 활용도입니다.' },
    ],
    yAxes: {
      'y-left':  { position: 'left', ticks: { callback: v => v + '%', font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } },
      'y-right': { position: 'right', ticks: { font: { size: 11 } }, grid: { display: false } },
    },
  });
}

// 5-3. ROA, ROIC, ROE
function buildRoaRoicChart(mode) {
  const ni = getFinChartData('손익계산서', AI.ni, mode, false);
  const op = getFinChartData('손익계산서', AI.op, mode, false);
  const ta = getFinChartData('재무상태표', AI.ta, mode, true);
  const eq = getFinChartData('재무상태표', AI.eq, mode, true);
  const tl = getFinChartData('재무상태표', AI.tl, mode, true);
  const cl = getFinChartData('재무상태표', AI.cl, mode, true);

  const roa = ni.labels.map((lbl, i) => {
    const taI = ta.labels.indexOf(lbl);
    if (ni.values[i] === null || taI < 0 || ta.values[taI] === null || ta.values[taI] === 0) return null;
    return Math.round((ni.values[i] / ta.values[taI]) * 10000) / 100;
  });

  // ROIC = 영업이익*(1-세율추정25%) / (자본총계 + 부채총계 - 유동부채) 근사
  const roic = ni.labels.map((lbl, i) => {
    const eqI = eq.labels.indexOf(lbl);
    const tlI = tl.labels.indexOf(lbl);
    const clI = cl.labels.indexOf(lbl);
    if (op.values[i] === null || eqI < 0 || tlI < 0 || clI < 0) return null;
    const investedCap = eq.values[eqI] + tl.values[tlI] - cl.values[clI];
    if (investedCap === 0) return null;
    const nopat = op.values[i] * 0.75; // 세후영업이익 근사
    return Math.round((nopat / investedCap) * 10000) / 100;
  });

  const roe = ni.labels.map((lbl, i) => {
    const eqI = eq.labels.indexOf(lbl);
    if (ni.values[i] === null || eqI < 0 || eq.values[eqI] === null || eq.values[eqI] === 0) return null;
    return Math.round((ni.values[i] / eq.values[eqI]) * 10000) / 100;
  });

  buildGenericChart('roaRoicChart', {
    labels: ni.labels,
    datasets: [
      { label: 'ROA(지배)(%)', data: roa, borderColor: CP.orange, backgroundColor: CP.orange,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: '%',
        helpText: '지배순이익 \u00f7 자산총계 \u00d7 100<br>총자산 대비 수익률입니다.' },
      { label: 'ROIC(%)', data: roic, borderColor: CP.green, backgroundColor: CP.green,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: '%',
        helpText: '세후영업이익(NOPAT) \u00f7 투하자본 \u00d7 100<br>투하자본 대비 수익률입니다.' },
      { label: 'ROE(지배)(%)', data: roe, borderColor: CP.blue, backgroundColor: CP.blue,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: '%',
        helpText: '지배순이익 \u00f7 자본총계 \u00d7 100<br>주주 자본 대비 수익률입니다.' },
    ],
    yAxes: { y: { ticks: { callback: v => v + '%', font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } } },
  });
}

// 5-4. 운전자본 회전일수
function buildWcTurnChart(mode) {
  const rev  = getFinChartData('손익계산서', AI.revenue, mode, false);
  const cogs = getFinChartData('손익계산서', AI.cogs, mode, false);
  const ar   = getFinChartData('재무상태표', AI.ar, mode, true);
  const inv  = getFinChartData('재무상태표', AI.inv, mode, true);
  const ap   = getFinChartData('재무상태표', AI.ap, mode, true);

  const arDays = rev.labels.map((lbl, i) => {
    const arI = ar.labels.indexOf(lbl);
    if (rev.values[i] === null || rev.values[i] === 0 || arI < 0 || ar.values[arI] === null) return null;
    return Math.round((ar.values[arI] / rev.values[i]) * 365);
  });
  const invDays = rev.labels.map((lbl, i) => {
    const invI = inv.labels.indexOf(lbl);
    const cogsVal = cogs.values[i];
    const denominator = cogsVal !== null && cogsVal !== 0 ? cogsVal : rev.values[i];
    if (!denominator || denominator === 0 || invI < 0 || inv.values[invI] === null) return null;
    return Math.round((inv.values[invI] / Math.abs(denominator)) * 365);
  });
  const apDays = rev.labels.map((lbl, i) => {
    const apI = ap.labels.indexOf(lbl);
    const cogsVal = cogs.values[i];
    const denominator = cogsVal !== null && cogsVal !== 0 ? cogsVal : rev.values[i];
    if (!denominator || denominator === 0 || apI < 0 || ap.values[apI] === null) return null;
    return Math.round((ap.values[apI] / Math.abs(denominator)) * 365);
  });
  const wcDays = arDays.map((v, i) => {
    if (v === null || invDays[i] === null || apDays[i] === null) return null;
    return v + invDays[i] - apDays[i];
  });

  buildGenericChart('wcTurnChart', {
    labels: rev.labels,
    datasets: [
      { label: '매출채권(일)', data: arDays, borderColor: CP.blue, backgroundColor: CP.blue,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: '일',
        helpText: '매출채권 \u00f7 매출액 \u00d7 365<br>매출채권을 회수하는 데 걸리는 평균 일수입니다.' },
      { label: '재고자산(일)', data: invDays, borderColor: CP.orange, backgroundColor: CP.orange,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: '일',
        helpText: '재고자산 \u00f7 매출원가 \u00d7 365<br>재고가 판매되기까지 걸리는 평균 일수입니다.' },
      { label: '매입채무(일)', data: apDays, borderColor: CP.red, backgroundColor: CP.red,
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: false, tooltipSuffix: '일',
        helpText: '매입채무 \u00f7 매출원가 \u00d7 365<br>매입대금을 지급하기까지 걸리는 평균 일수입니다.' },
      { label: '운전자본(일)', data: wcDays, borderColor: CP.green, backgroundColor: CP.green,
        borderWidth: 2.5, pointRadius: 3, tension: 0.3, fill: false, tooltipSuffix: '일',
        helpText: '매출채권일 + 재고자산일 - 매입채무일<br>영업에 묶이는 자금의 회전 기간입니다.' },
    ],
    yAxes: { y: { ticks: { callback: v => v + '일', font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } } },
  });
}

// 5-5. 현금회전일수
function buildCashTurnChart(mode) {
  const rev  = getFinChartData('손익계산서', AI.revenue, mode, false);
  const cogs = getFinChartData('손익계산서', AI.cogs, mode, false);
  const ar   = getFinChartData('재무상태표', AI.ar, mode, true);
  const inv  = getFinChartData('재무상태표', AI.inv, mode, true);
  const ap   = getFinChartData('재무상태표', AI.ap, mode, true);

  // CCC = 매출채권회전일 + 재고자산회전일 - 매입채무회전일
  const ccc = rev.labels.map((lbl, i) => {
    const arI = ar.labels.indexOf(lbl);
    const invI = inv.labels.indexOf(lbl);
    const apI = ap.labels.indexOf(lbl);
    const cogsVal = cogs.values[i];
    const denominator = cogsVal !== null && cogsVal !== 0 ? cogsVal : rev.values[i];
    if (rev.values[i] === null || rev.values[i] === 0 || !denominator) return null;
    if (arI < 0 || invI < 0 || apI < 0) return null;
    if (ar.values[arI] === null || inv.values[invI] === null || ap.values[apI] === null) return null;

    const arD = (ar.values[arI] / rev.values[i]) * 365;
    const invD = (inv.values[invI] / Math.abs(denominator)) * 365;
    const apD = (ap.values[apI] / Math.abs(denominator)) * 365;
    return Math.round(arD + invD - apD);
  });

  buildGenericChart('cashTurnChart', {
    labels: rev.labels,
    datasets: [
      { label: '현금회전일수(일)', data: ccc, borderColor: CP.teal, backgroundColor: alpha(CP.teal, 0.1),
        borderWidth: 2.5, pointRadius: 2, tension: 0.3, fill: true, tooltipSuffix: '일',
        helpText: '매출채권일 + 재고자산일 - 매입채무일 (CCC)<br>현금이 영업에 묶여 있는 기간입니다. 짧을수록 좋습니다.' },
    ],
    yAxes: { y: { ticks: { callback: v => v + '일', font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.06)' } } },
  });
}

// ============================================================
// 통합 빌드 함수 (finData 기반 차트 전체)
// ============================================================
function buildAllFinCharts(mode) {
  if (!finData || !finData.statements) return;
  if (!AI) initAcctIdxCache();

  // 매출 및 수익성
  buildMarginChart(mode);
  buildCostRatioChart(mode);
  // 자산 및 배당
  buildAssetStructChart(mode);
  buildDividendChart(mode);
  // 현금흐름
  buildCfChart(mode);
  buildFcfChart(mode);
  // 부채 및 안전성
  buildDebtRatioChart(mode);
  buildBorrowingChart(mode);
  buildInterestChart(mode);
  buildIcrChart(mode);
  buildNetCashChart(mode);
  // ROE 및 효율성
  buildRoePbrChart(mode);
  buildDupontChart(mode);
  buildRoaRoicChart(mode);
  buildWcTurnChart(mode);
  buildCashTurnChart(mode);
  // 가치평가
  buildCashAssetChart(mode);
  buildPriceBpsChart(mode);
  buildPriceEpsChart(mode);
  buildPerChart(mode);
  buildPbrChart(mode);
}
'''
