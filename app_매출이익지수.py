# -*- coding: utf-8 -*-
"""
매출·이익지수 차트 모듈 (2개 차트)
- 차트1: 주가(좌축) + 매출지수/영업이익지수(우축, 기준=100)
- 차트2: 주가(좌축) + 순이익지수(우축, 기준=100)
- 첫 해(첫 유효 양수값)를 100으로 놓고 상대적 변동 표시
"""


def get_매출이익지수_html():
    """매출·이익지수 차트 2개 영역의 HTML을 반환"""
    return '''
  <!-- 주가 & 매출·영업이익지수 차트 -->
  <div class="chart-wrapper">
    <div class="chart-header">
      <div class="chart-header-left chart-company-name"></div>
      <div class="chart-header-center">주가 & 매출·영업이익지수</div>
      <div class="chart-header-right">
        <button class="chart-mode-btn active" onclick="setMode(\'trailing\')" data-mode="trailing">연환산</button>
        <button class="chart-mode-btn" onclick="setMode(\'annual\')" data-mode="annual">연간</button>
        <button class="chart-mode-btn" onclick="setMode(\'quarterly\')" data-mode="quarterly">분기</button>
      </div>
    </div>
    <div class="chart-container">
      <canvas id="priceRevChart"></canvas>
    </div>
  </div>

  <!-- 주가 & 순이익지수 차트 -->
  <div class="chart-wrapper">
    <div class="chart-header">
      <div class="chart-header-left chart-company-name"></div>
      <div class="chart-header-center">주가 & 순이익지수</div>
      <div class="chart-header-right">
        <button class="chart-mode-btn active" onclick="setMode(\'trailing\')" data-mode="trailing">연환산</button>
        <button class="chart-mode-btn" onclick="setMode(\'annual\')" data-mode="annual">연간</button>
        <button class="chart-mode-btn" onclick="setMode(\'quarterly\')" data-mode="quarterly">분기</button>
      </div>
    </div>
    <div class="chart-container">
      <canvas id="priceNiChart"></canvas>
    </div>
  </div>
'''


def get_매출이익지수_js():
    """매출·이익지수 차트 관련 JavaScript 코드를 반환"""
    return '''
// ── 기준=100 정규화 함수 ──
function normalizeToBase100(arr) {
  const baseVal = arr.find(v => v !== null && v > 0);
  if (baseVal === undefined) return arr.map(() => null);
  return arr.map(v => v === null ? null : Math.round((v / baseVal) * 1000) / 10);
}

// ── 주가 & 매출·이익지수 데이터 ──
function getPriceChartData(mode) {
  if (finData && finData.statements && finData.statements['손익계산서']) {
    return getPriceChartDataFromFinData(mode);
  }
  return getPriceChartDataFromRawData(mode);
}

// ── 공통: priceData에서 월별 키("YYYY-MM") 목록 추출 ──
function getMonthlyPriceKeys() {
  return Object.keys(priceData)
    .filter(k => k.length === 7 && k[4] === '-')  // "YYYY-MM" 형식
    .sort();
}

// ── 공통: 월별 키를 표시 라벨 "YY.MM"으로 변환 ──
function monthKeyToLabel(mk) {
  // "2024-03" → "24.03"
  return mk.slice(2, 4) + '.' + mk.slice(5, 7);
}

function getPriceChartDataFromFinData(mode) {
  const revIdx_  = findAcctIdx('손익계산서', ['매출액', '수익(매출액)', '영업수익', '매출']);
  const opIdx_   = findAcctIdx('손익계산서', ['영업이익', '영업이익(손실)']);
  let niIdx_ = findAcctIdx('손익계산서', ['지배기업의 소유주에게 귀속되는 당기순이익', '지배기업 소유주지분', '지배기업 소유지분']);
  if (niIdx_ < 0) niIdx_ = findAcctIdx('손익계산서', ['당기순이익', '당기순이익(손실)', '분기순이익', '분기순이익(손실)']);

  const rev = getFinChartData('손익계산서', revIdx_, mode, false);
  const op  = getFinChartData('손익계산서', opIdx_, mode, false);
  const ni  = getFinChartData('손익계산서', niIdx_, mode, false);

  // 연간 모드: 실적 라벨(YYYY.MM) 기준 + 해당 연도 12월 주가
  if (mode === 'annual') {
    const labels = [...rev.labels];
    const revVals = [...rev.values];
    const opVals = [...op.values];
    const niVals = [...ni.values];
    const stockPrices = [];
    labels.forEach(lbl => {
      const y = lbl.slice(0, 4);
      // 먼저 분기키로 조회, 없으면 월별키로 조회
      const pd = priceData[y + 'Q4'] || priceData[y + '-12'];
      stockPrices.push(pd ? pd.price : null);
    });
    // 마지막 실적 연도 이후 최신 주가 추가 (어제 종가)
    if (labels.length > 0 && priceData.latest) {
      const lastYear = labels[labels.length - 1].slice(0, 4);
      const latestDate = priceData.latest.date;  // "YYYY-MM-DD"
      const latestYear = latestDate.slice(0, 4);
      const latestMonth = latestDate.slice(5, 7);
      if (latestYear > lastYear || (latestYear === lastYear && latestMonth !== '12')) {
        labels.push(latestDate.slice(0, 4) + '.' + latestMonth);
        stockPrices.push(priceData.latest.price);
        revVals.push(null);
        opVals.push(null);
        niVals.push(null);
      }
    }
    return {
      labels, stockPrices,
      revIdx: normalizeToBase100(revVals),
      netIncomeIdx: normalizeToBase100(niVals),
      opIncomeIdx: normalizeToBase100(opVals),
    };
  }

  // 분기/연환산 모드: 월별 주가 + 분기별 실적 통합
  // 월별 키: "YYYY-MM" 형식
  const monthlyKeys = getMonthlyPriceKeys();

  // 실적 라벨("YY.MM") → 월별 키("YYYY-MM") 매핑
  const revByMonthKey = {}, opByMonthKey = {}, niByMonthKey = {};

  rev.labels.forEach((lbl, i) => {
    // lbl: "24.03" → "2024-03"
    const yy = parseInt(lbl.slice(0, 2));
    const fullYear = yy >= 50 ? 1900 + yy : 2000 + yy;
    const mm = lbl.slice(3, 5);
    const monthKey = fullYear + '-' + mm;
    revByMonthKey[monthKey] = rev.values[i];
    opByMonthKey[monthKey] = op.values[i];
    niByMonthKey[monthKey] = ni.values[i];
  });

  // 첫 번째 실적 라벨의 월별 키 이후부터 시작 (실적 이전 주가는 표시 불필요)
  let startKey = '';
  if (rev.labels.length > 0) {
    const firstLbl = rev.labels[0];
    const yy = parseInt(firstLbl.slice(0, 2));
    const fullYear = yy >= 50 ? 1900 + yy : 2000 + yy;
    startKey = fullYear + '-' + firstLbl.slice(3, 5);
  }

  // 데이터 배열 구성
  const labels = [], stockPrices = [], revValues = [], opValues = [], niValues = [];

  monthlyKeys.forEach(mk => {
    if (startKey && mk < startKey) return;  // 실적 시작 이전 스킵
    labels.push(monthKeyToLabel(mk));
    const pd = priceData[mk];
    stockPrices.push(pd ? pd.price : null);
    revValues.push(revByMonthKey[mk] !== undefined ? revByMonthKey[mk] : null);
    opValues.push(opByMonthKey[mk] !== undefined ? opByMonthKey[mk] : null);
    niValues.push(niByMonthKey[mk] !== undefined ? niByMonthKey[mk] : null);
  });

  return {
    labels,
    stockPrices,
    revIdx: normalizeToBase100(revValues),
    netIncomeIdx: normalizeToBase100(niValues),
    opIncomeIdx: normalizeToBase100(opValues),
  };
}

// ── rawData 기반 fallback ──
function getAllLabels() {
  const dataLabels = new Set(Object.keys(rawData));
  // 분기 키만 사용 (주간 키 "YYYY-MM-DD" 제외)
  const priceLabels = new Set(
    Object.keys(priceData).filter(k => k.includes('Q'))
  );
  const all = new Set([...dataLabels, ...priceLabels]);
  const sorted = [...all].sort();
  return sorted.filter(label => {
    if (dataLabels.has(label)) return true;
    const pd = priceData[label];
    return pd && pd.price !== null;
  });
}

function getPriceChartDataFromRawData(mode) {
  const labels = getAllLabels();
  const resultLabels = [];
  const stockPrices = [];
  const revIdx = [];
  const netIncomeIdx = [];
  const opIncomeIdx = [];

  // 분기 라벨("2024Q3") → 월별 키("2024-09") 변환 헬퍼
  function qtrToMonthKey(qLabel) {
    const y = qLabel.slice(0, 4);
    const q = parseInt(qLabel.slice(5));
    const endMonth = ((parseInt(String(accMt).padStart(2,'0')) % 12) + q * 3) % 12 || 12;
    return y + '-' + String(endMonth).padStart(2, '0');
  }

  if (mode === 'trailing') {
    // 실적 데이터 (분기키 기반) + 월별 주가 결합
    const monthlyKeys = getMonthlyPriceKeys();
    // 실적 연환산 값을 분기 말월 키에 매핑
    const revByMonth = {}, opByMonth = {}, niByMonth = {};
    for (let i = 3; i < labels.length; i++) {
      const win = labels.slice(i - 3, i + 1);
      const label = labels[i];
      const mk = qtrToMonthKey(label);
      let niSum = 0, opSum = 0, revSum = 0;
      let niOk = true, opOk = true, revOk = true;
      win.forEach(wl => {
        if (!rawData[wl]) { niOk = false; opOk = false; revOk = false; return; }
        const ni = rawData[wl]['지배순이익'], op = rawData[wl]['영업이익'], rev = rawData[wl]['매출액'];
        if (ni === null || ni === undefined) niOk = false; else niSum += ni;
        if (op === null || op === undefined) opOk = false; else opSum += op;
        if (rev === null || rev === undefined) revOk = false; else revSum += rev;
      });
      revByMonth[mk] = revOk ? revSum : null;
      opByMonth[mk] = opOk ? opSum : null;
      niByMonth[mk] = niOk ? niSum : null;
    }
    // 첫 실적 시점 이후 월별로 주가 + 실적
    const firstMk = labels.length > 3 ? qtrToMonthKey(labels[3]) : '';
    monthlyKeys.forEach(mk => {
      if (firstMk && mk < firstMk) return;
      resultLabels.push(monthKeyToLabel(mk));
      const pd = priceData[mk];
      stockPrices.push(pd ? pd.price : null);
      netIncomeIdx.push(niByMonth[mk] !== undefined ? niByMonth[mk] : null);
      opIncomeIdx.push(opByMonth[mk] !== undefined ? opByMonth[mk] : null);
      revIdx.push(revByMonth[mk] !== undefined ? revByMonth[mk] : null);
    });
  } else if (mode === 'annual') {
    const yearMap = {};
    labels.forEach(l => {
      const y = l.slice(0, 4);
      if (!yearMap[y]) yearMap[y] = { labels: [], ni: 0, op: 0, rev: 0, niOk: true, opOk: true, revOk: true };
      yearMap[y].labels.push(l);
      if (!rawData[l]) { yearMap[y].niOk = false; yearMap[y].opOk = false; yearMap[y].revOk = false; return; }
      const ni = rawData[l]['지배순이익'], op = rawData[l]['영업이익'], rev = rawData[l]['매출액'];
      if (ni === null || ni === undefined) yearMap[y].niOk = false; else yearMap[y].ni += ni;
      if (op === null || op === undefined) yearMap[y].opOk = false; else yearMap[y].op += op;
      if (rev === null || rev === undefined) yearMap[y].revOk = false; else yearMap[y].rev += rev;
    });
    const mm = String(accMt).padStart(2, '0');
    Object.keys(yearMap).sort().forEach(y => {
      if (yearMap[y].labels.length < 4) return;
      resultLabels.push(y + '.' + mm);
      const pd = priceData[y + 'Q4'] || priceData[y + '-' + mm];
      stockPrices.push(pd ? pd.price : null);
      netIncomeIdx.push(yearMap[y].niOk ? yearMap[y].ni : null);
      opIncomeIdx.push(yearMap[y].opOk ? yearMap[y].op : null);
      revIdx.push(yearMap[y].revOk ? yearMap[y].rev : null);
    });
    // 최신 주가 추가
    if (priceData.latest && resultLabels.length > 0) {
      const lastYear = resultLabels[resultLabels.length - 1].slice(0, 4);
      const ld = priceData.latest.date;
      const ly = ld.slice(0, 4), lm = ld.slice(5, 7);
      if (ly > lastYear || (ly === lastYear && lm !== mm)) {
        resultLabels.push(ly + '.' + lm);
        stockPrices.push(priceData.latest.price);
        netIncomeIdx.push(null);
        opIncomeIdx.push(null);
        revIdx.push(null);
      }
    }
  } else {
    // quarterly 모드: 분기별 실적 + 월별 주가 결합
    const monthlyKeys = getMonthlyPriceKeys();
    const revByMonth = {}, opByMonth = {}, niByMonth = {};
    labels.forEach(label => {
      const mk = qtrToMonthKey(label);
      if (!rawData[label]) { revByMonth[mk] = null; opByMonth[mk] = null; niByMonth[mk] = null; return; }
      const ni = rawData[label]['지배순이익'], op = rawData[label]['영업이익'], rev = rawData[label]['매출액'];
      niByMonth[mk] = ni !== null && ni !== undefined ? ni * 4 : null;
      opByMonth[mk] = op !== null && op !== undefined ? op * 4 : null;
      revByMonth[mk] = rev !== null && rev !== undefined ? rev * 4 : null;
    });
    const firstMk = labels.length > 0 ? qtrToMonthKey(labels[0]) : '';
    monthlyKeys.forEach(mk => {
      if (firstMk && mk < firstMk) return;
      resultLabels.push(monthKeyToLabel(mk));
      const pd = priceData[mk];
      stockPrices.push(pd ? pd.price : null);
      netIncomeIdx.push(niByMonth[mk] !== undefined ? niByMonth[mk] : null);
      opIncomeIdx.push(opByMonth[mk] !== undefined ? opByMonth[mk] : null);
      revIdx.push(revByMonth[mk] !== undefined ? revByMonth[mk] : null);
    });
  }

  return {
    labels: resultLabels,
    stockPrices,
    revIdx: normalizeToBase100(revIdx),
    netIncomeIdx: normalizeToBase100(netIncomeIdx),
    opIncomeIdx: normalizeToBase100(opIncomeIdx),
  };
}

function formatPrice(v) {
  if (v >= 10000) return (v / 10000).toFixed(1) + '만';
  return v.toLocaleString();
}

// ── 공통 인덱스 차트 빌더 ──
function buildIndexChart(canvasId, chartVarName, data, indexDatasets, yTitle) {
  const noData = !data.labels.length || !Object.keys(priceData).length;
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  if (noData) { canvas.parentElement.parentElement.style.display = 'none'; return; }
  canvas.parentElement.parentElement.style.display = '';

  const datasets = [];

  // 주가 (좌축, 빨간선)
  datasets.push({
    label: '주가[좌]', type: 'line',
    data: data.stockPrices,
    borderColor: 'rgba(220, 53, 69, 1)',
    backgroundColor: 'rgba(220, 53, 69, 0.05)',
    borderWidth: 1.5, pointRadius: 0, pointHoverRadius: 4,
    tension: 0.1, yAxisID: 'y-price', order: 1, fill: false, spanGaps: true,
  });

  // 지수 데이터셋 추가
  indexDatasets.forEach(ds => datasets.push(ds));

  // 기준선 (y=100, 회색 점선)
  datasets.push({
    label: '기준선(100)', type: 'line',
    data: data.labels.map(() => 100),
    borderColor: 'rgba(150, 150, 150, 0.4)',
    borderWidth: 1, borderDash: [4, 4],
    pointRadius: 0, pointHoverRadius: 0,
    yAxisID: 'y-index', order: 10, fill: false,
  });

  // Y축 범위
  const prices = data.stockPrices.filter(v => v !== null);
  const allIdx = indexDatasets.flatMap(ds => ds.data).filter(v => v !== null);

  const priceMin = prices.length ? niceMin(Math.min(...prices) * 0.85) : 0;
  const priceMax = prices.length ? niceMax(Math.max(...prices) * 1.1) : 100000;
  const rawIndexMin = allIdx.length ? Math.min(0, ...allIdx) : 0;
  const rawIndexMax = allIdx.length ? Math.max(...allIdx) : 200;
  const indexMin = niceMin(Math.min(rawIndexMin * 1.2, 0));
  const indexMax = niceMax(Math.max(rawIndexMax * 1.15, 120));

  // 이전 차트 파괴
  if (window[chartVarName]) window[chartVarName].destroy();

  window[chartVarName] = new Chart(canvas, {
    type: 'line',
    data: { labels: data.labels, datasets },
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
            filter: function(item) {
              return item.text !== '기준선(100)';
            },
          },
        },
        tooltip: {
          callbacks: {
            label: function(ctx) {
              const val = ctx.parsed.y;
              if (val === null) return ctx.dataset.label + ': N/A';
              if (ctx.dataset.label === '기준선(100)') return null;
              if (ctx.dataset.yAxisID === 'y-price') {
                return ctx.dataset.label + ': ' + val.toLocaleString('ko-KR', {maximumFractionDigits: 0}) + '원';
              }
              return ctx.dataset.label + ': ' + val.toLocaleString('ko-KR', {maximumFractionDigits: 1});
            }
          }
        }
      },
      scales: {
        'y-price': {
          type: 'linear', position: 'left',
          min: priceMin, max: priceMax,
          title: { display: true, text: '주가 (원)', font: { size: 12 } },
          ticks: { precision: 0, callback: v => formatPrice(v), font: { size: 11 } },
          grid: { color: 'rgba(0,0,0,0.06)' },
        },
        'y-index': {
          type: 'linear', position: 'right',
          min: indexMin, max: indexMax,
          title: { display: true, text: yTitle, font: { size: 11 } },
          ticks: { precision: 0, stepSize: 20, callback: v => v.toLocaleString(), font: { size: 11 } },
          grid: { display: false },
        },
        x: {
          ticks: {
            font: { size: 10 }, maxRotation: 45, autoSkip: false,
            callback: function(value, index, ticks) {
              const lbl = this.getLabelForValue(value);
              if (!lbl) return null;
              // 연간 모드 라벨 ("2016.12" 7자리) → 모든 라벨 표시
              if (lbl.length === 7 && lbl[4] === '.') return lbl;
              // 월별 라벨 ("YY.MM" 5자리)
              if (lbl.length !== 5 || lbl[2] !== '.') return lbl;
              const mm = lbl.slice(3, 5);
              // 이전 tick과 같은 YY.MM이면 숨김
              if (index > 0) {
                const prev = this.getLabelForValue(ticks[index - 1].value);
                if (prev === lbl) return null;
              }
              // 1월 또는 7월의 첫 등장만 표시
              if (mm === '01' || mm === '07') return lbl;
              return null;
            }
          },
          grid: { display: false },
        },
      },
    },
  });
}

// ── 차트1: 주가 & 매출·영업이익지수 ──
function buildPriceRevChart(mode) {
  const data = getPriceChartData(mode);
  const indexDatasets = [
    {
      label: '매출지수[우]', type: 'line',
      data: data.revIdx,
      borderColor: 'rgba(143, 170, 220, 1)',
      backgroundColor: 'rgba(143, 170, 220, 0.05)',
      borderWidth: 2, pointRadius: 3, pointHoverRadius: 5,
      tension: 0.1, yAxisID: 'y-index', order: 4, fill: false, spanGaps: true,
    },
    {
      label: '영업이익지수[우]', type: 'line',
      data: data.opIncomeIdx,
      borderColor: 'rgba(255, 159, 64, 1)',
      backgroundColor: 'rgba(255, 159, 64, 0.05)',
      borderWidth: 2.5, pointRadius: 3, pointHoverRadius: 5,
      tension: 0.1, yAxisID: 'y-index', order: 3, fill: false, spanGaps: true,
    },
  ];
  buildIndexChart('priceRevChart', 'priceRevChartInst', data, indexDatasets, '매출·영업이익지수 (기준=100)');
}

// ── 차트2: 주가 & 순이익지수 ──
function buildPriceNiChart(mode) {
  const data = getPriceChartData(mode);
  const indexDatasets = [
    {
      label: '순이익지수[우]', type: 'line',
      data: data.netIncomeIdx,
      borderColor: 'rgba(33, 102, 172, 1)',
      backgroundColor: 'rgba(33, 102, 172, 0.05)',
      borderWidth: 2.5, pointRadius: 3, pointHoverRadius: 5,
      tension: 0.1, yAxisID: 'y-index', order: 2, fill: false, spanGaps: true,
    },
  ];
  buildIndexChart('priceNiChart', 'priceNiChartInst', data, indexDatasets, '순이익지수 (기준=100)');
}

// ── 2개 차트 통합 빌드 (기존 buildPriceChart 대체) ──
function buildPriceChart(mode) {
  // 회사명은 syncCompanyNames()에서 일괄 처리
  buildPriceRevChart(mode);
  buildPriceNiChart(mode);
}
'''
