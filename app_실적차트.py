# -*- coding: utf-8 -*-
"""
실적 차트 모듈
- 매출액/영업이익/순이익(지배) 막대+꺾은선 차트
- HTML canvas 영역 + Chart.js 기반 JavaScript 반환
- finData (10년 데이타) 기반으로 데이터 로드
"""


def get_실적차트_html():
    """실적 차트 영역의 HTML을 반환"""
    return '''
  <!-- 실적 차트 -->
  <div class="chart-wrapper">
    <div class="loading-overlay" id="loadingOverlay">
      <div class="spinner"></div>
      <span class="loading-text" id="loadingText">데이터를 불러오는 중...</span>
    </div>
    <div class="chart-header">
      <div class="chart-header-left" id="mainChartCompany"></div>
      <div class="chart-header-center">매출, 영업이익, 순이익</div>
      <div class="chart-header-right">
        <button class="chart-mode-btn active" onclick="setMode(\'trailing\')" id="chartBtn-trailing">연환산</button>
        <button class="chart-mode-btn" onclick="setMode(\'annual\')" id="chartBtn-annual">연간</button>
        <button class="chart-mode-btn" onclick="setMode(\'quarterly\')" id="chartBtn-quarterly">분기</button>
      </div>
    </div>
    <div class="chart-container">
      <canvas id="mainChart"></canvas>
    </div>
  </div>
'''


def get_실적차트_js():
    """실적 차트 관련 JavaScript 코드를 반환"""
    return '''
// ── finData 기반 데이터 변환 ──
function getMainChartData(mode) {
  // finData 있으면 사용, 없으면 rawData fallback
  if (finData && finData.statements && finData.statements['손익계산서']) {
    return getMainChartDataFromFinData(mode);
  }
  return getMainChartDataFromRawData(mode);
}

function getMainChartDataFromFinData(mode) {
  const revIdx = findAcctIdx('손익계산서', ['매출액', '수익(매출액)', '영업수익', '매출']);
  const opIdx  = findAcctIdx('손익계산서', ['영업이익', '영업이익(손실)']);
  // 지배순이익 우선, 없으면 당기순이익 fallback
  let niIdx = findAcctIdx('손익계산서', ['지배기업의 소유주에게 귀속되는 당기순이익', '지배기업 소유주지분', '지배기업 소유지분']);
  if (niIdx < 0) niIdx = findAcctIdx('손익계산서', ['당기순이익', '당기순이익(손실)', '분기순이익', '분기순이익(손실)']);

  const rev = getFinChartData('손익계산서', revIdx, mode, false);
  const op  = getFinChartData('손익계산서', opIdx, mode, false);
  const ni  = getFinChartData('손익계산서', niIdx, mode, false);

  return {
    labels: rev.labels,
    datasets: {
      '매출액': rev.values,
      '영업이익': op.values,
      '지배순이익': ni.values,
    }
  };
}

function getMainChartDataFromRawData(mode) {
  if (!Object.keys(rawData).length) return { labels: [], datasets: { '매출액': [], '영업이익': [], '지배순이익': [] } };
  if (mode === 'quarterly') return getQuarterlyData();
  if (mode === 'annual') return getAnnualData();
  return getTrailingData();
}

// ── rawData fallback 함수 (기존 호환) ──
function getQuarterlyData() {
  const labels = Object.keys(rawData).sort();
  const displayLabels = labels.map(l => toDisplayLabel(l, 'quarterly'));
  const datasets = {};
  ITEMS.forEach(item => { datasets[item] = []; });
  labels.forEach(label => {
    ITEMS.forEach(item => { datasets[item].push(rawData[label][item]); });
  });
  return { labels: displayLabels, datasets };
}

function getAnnualData() {
  const labels = Object.keys(rawData).sort();
  const yearMap = {};
  labels.forEach(label => {
    const year = label.slice(0,4);
    if (!yearMap[year]) yearMap[year] = {};
    ITEMS.forEach(item => {
      const val = rawData[label][item];
      if (val !== null) yearMap[year][item] = (yearMap[year][item] || 0) + val;
    });
  });
  const completeYears = [];
  Object.keys(yearMap).sort().forEach(year => {
    const qCount = labels.filter(l => l.startsWith(year)).length;
    if (qCount === 4) completeYears.push(year);
  });
  const datasets = {};
  ITEMS.forEach(item => { datasets[item] = []; });
  completeYears.forEach(year => {
    ITEMS.forEach(item => {
      const val = yearMap[year][item];
      datasets[item].push(val !== undefined ? Math.round(val) : null);
    });
  });
  const mm = String(accMt).padStart(2, '0');
  const displayLabels = completeYears.map(y => y + '.' + mm);
  return { labels: displayLabels, datasets };
}

function getTrailingData() {
  const labels = Object.keys(rawData).sort();
  const resultLabels = [];
  const datasets = {};
  ITEMS.forEach(item => { datasets[item] = []; });
  for (let i = 3; i < labels.length; i++) {
    const win = labels.slice(i - 3, i + 1);
    const label = labels[i];
    resultLabels.push(toDisplayLabel(label, 'trailing'));
    ITEMS.forEach(item => {
      let sum = 0, nullCount = 0;
      win.forEach(wl => {
        const val = rawData[wl][item];
        if (val === null || val === undefined) nullCount++;
        else sum += val;
      });
      datasets[item].push(nullCount <= 1 ? Math.round(sum) : null);
    });
  }
  return { labels: resultLabels, datasets };
}

// ── Y축 깔끔한 눈금 계산 ──
function niceMax(v) {
  if (v <= 0) return 0;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const step = mag >= 10000 ? 10000 : mag >= 1000 ? 1000 : mag >= 100 ? 100 : mag >= 10 ? 10 : 1;
  return Math.ceil(v / step) * step;
}
function niceMin(v) {
  if (v >= 0) return 0;
  const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(v))));
  const step = mag >= 10000 ? 10000 : mag >= 1000 ? 1000 : mag >= 100 ? 100 : mag >= 10 ? 10 : 1;
  return Math.floor(v / step) * step;
}

// ── 단위 결정 (억원 데이터 기준) ──
function decideUnit(values) {
  const absMax = Math.max(...values.filter(v => v !== null).map(v => Math.abs(v)), 0);
  if (absMax >= 100000) return { unit: '조', divisor: 10000, suffix: '조' };
  return { unit: '억', divisor: 1, suffix: '억' };
}

function convertValues(arr, divisor) {
  return arr.map(v => v === null ? null : Math.round(v / divisor * 10) / 10);
}

// ── 실적 차트 빌드 ──
function buildMainChart(mode) {
  // 헤더 회사명 업데이트
  const mainChartCo = document.getElementById('mainChartCompany');
  if (mainChartCo) mainChartCo.textContent = currentCompany;

  const result = getMainChartData(mode);

  if (!result.labels.length) return;

  // 영업이익 기준으로 좌축/우축 단위를 함께 결정
  const unitBase = decideUnit(result.datasets['영업이익']);
  const leftUnit = unitBase;
  const rightUnit = unitBase;

  // 단위 변환
  const leftData = convertValues(result.datasets['매출액'], leftUnit.divisor);
  const rightData1 = convertValues(result.datasets['영업이익'], rightUnit.divisor);
  const rightData2 = convertValues(result.datasets['지배순이익'], rightUnit.divisor);

  const datasets = [];

  // 매출액 (막대, 좌축)
  datasets.push({
    label: '매출[좌]', type: 'bar',
    data: leftData,
    backgroundColor: COLORS['매출액'].bar,
    borderColor: COLORS['매출액'].border,
    borderWidth: 1, yAxisID: 'y-left', order: 3,
  });

  // 영업이익 (꺾은선, 우축)
  datasets.push({
    label: '영업이익[우]', type: 'line',
    data: rightData1,
    borderColor: COLORS['영업이익'].line,
    backgroundColor: COLORS['영업이익'].line,
    borderWidth: 3, pointRadius: 2, pointHoverRadius: 5,
    tension: 0.3, yAxisID: 'y-right', order: 1, fill: false,
  });

  // 순이익 (꺾은선, 우축)
  datasets.push({
    label: '순이익(지배)[우]', type: 'line',
    data: rightData2,
    borderColor: COLORS['지배순이익'].line,
    backgroundColor: COLORS['지배순이익'].line,
    borderWidth: 3, pointRadius: 2, pointHoverRadius: 5,
    tension: 0.3, yAxisID: 'y-right', order: 2, fill: false,
  });

  const allLeft = leftData.filter(v => v !== null);
  const allRight = [...rightData1, ...rightData2].filter(v => v !== null);
  const leftMax = allLeft.length ? niceMax(Math.max(...allLeft) * 1.15) : 100;
  const rightMin = allRight.length ? niceMin(Math.min(0, ...allRight) * 1.2) : 0;
  const rightMax = allRight.length ? niceMax(Math.max(...allRight) * 1.3) : 50;

  const lSuffix = leftUnit.suffix + '원';
  const rSuffix = rightUnit.suffix + '원';

  if (chart) chart.destroy();

  chart = new Chart(document.getElementById('mainChart'), {
    type: 'bar',
    data: { labels: result.labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        title: { display: false },
        legend: {
          position: 'bottom',
          labels: {
            usePointStyle: true, padding: 16, font: { size: 12 },
            sort: function(a, b) {
              const order = ['매출[좌]', '영업이익[우]', '순이익(지배)[우]'];
              return order.indexOf(a.text) - order.indexOf(b.text);
            },
          },
        },
        tooltip: {
          callbacks: {
            title: function(items) { return items[0].label; },
            label: function(ctx) {
              const val = ctx.parsed.y;
              if (val === null) return ctx.dataset.label + ': N/A';
              const isLeft = ctx.dataset.yAxisID === 'y-left';
              const sfx = isLeft ? leftUnit.suffix : rightUnit.suffix;
              return ctx.dataset.label + ': ' + val.toLocaleString('ko-KR', {minimumFractionDigits: 1, maximumFractionDigits: 1}) + sfx;
            }
          },
          itemSort: function(a, b) {
            const order = ['매출[좌]', '영업이익[우]', '순이익(지배)[우]'];
            return order.indexOf(a.dataset.label) - order.indexOf(b.dataset.label);
          }
        }
      },
      scales: {
        'y-left': {
          type: 'linear', position: 'left', beginAtZero: true,
          max: leftMax,
          title: { display: true, text: '매출 (' + lSuffix + ')', font: { size: 12 } },
          ticks: { precision: 0, callback: v => v.toLocaleString('ko-KR', {minimumFractionDigits: 1, maximumFractionDigits: 1}) + leftUnit.suffix, font: { size: 11 } },
          grid: { color: 'rgba(0,0,0,0.06)' },
        },
        'y-right': {
          type: 'linear', position: 'right',
          min: rightMin, max: rightMax,
          title: { display: true, text: '영업이익 / 순이익 (' + rSuffix + ')', font: { size: 11 } },
          ticks: { precision: 0, callback: v => v.toLocaleString('ko-KR', {minimumFractionDigits: 1, maximumFractionDigits: 1}) + rightUnit.suffix, font: { size: 11 } },
          grid: { display: false },
        },
        x: {
          ticks: { font: { size: 11 }, maxRotation: 45 },
          grid: { display: false },
        },
      },
    },
  });

}
'''
