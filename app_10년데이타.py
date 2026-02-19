# -*- coding: utf-8 -*-
"""
10년 데이타 탭 모듈
- 손익계산서 / 재무상태표 / 현금흐름표 / 순운전자본 / 포괄손익계산서 서브탭
- 연결/개별, 연환산/연간/분기 컨트롤
- 대항목/소항목 접기/펼치기 (+/- 버튼) — 백엔드 is_header 기반
"""


def get_10년데이타_html():
    """10년 데이타 탭의 HTML을 반환"""
    return '''
    <!-- 서브탭 -->
    <div class="data-sub-tabs">
      <button class="data-sub-tab active" onclick="switchDataTab('income')" id="data-tab-income">손익계산서</button>
      <button class="data-sub-tab" onclick="switchDataTab('balance')" id="data-tab-balance">재무상태표</button>
      <button class="data-sub-tab" onclick="switchDataTab('cashflow')" id="data-tab-cashflow">현금흐름표</button>
    </div>

    <!-- 컨트롤: 연결/개별, 연환산/연간/분기 -->
    <div class="controls" id="data-controls">
      <div class="btn-group">
        <button class="btn-toggle active" onclick="setDataFs('CFS')" id="data-btn-CFS">연결</button>
        <button class="btn-toggle" onclick="setDataFs('OFS')" id="data-btn-OFS">개별</button>
      </div>

      <div class="separator"></div>

      <div class="btn-group">
        <button class="btn-toggle" onclick="setDataMode('trailing')" id="data-btn-trailing">연환산</button>
        <button class="btn-toggle active" onclick="setDataMode('annual')" id="data-btn-annual">연간</button>
        <button class="btn-toggle" onclick="setDataMode('quarterly')" id="data-btn-quarterly">분기</button>
      </div>
    </div>

    <!-- 테이블 영역 -->
    <div class="chart-wrapper" style="position: relative; min-height: 200px;">
      <div class="loading-overlay" id="dataLoadingOverlay">
        <div class="spinner"></div>
        <span class="loading-text" id="dataLoadingText">데이터를 불러오는 중...</span>
      </div>
      <div class="table-section" style="box-shadow: none; padding: 0; margin-top: 0;">
        <h2 id="dataTableTitle">손익계산서<span class="unit">(단위: 억원)</span></h2>
        <div id="dataTableContainer">
          <p style="text-align: center; color: #888; padding: 40px 0;">
            10년 데이타 탭을 클릭하면 데이터를 불러옵니다.
          </p>
        </div>
      </div>
    </div>
'''


def get_10년데이타_js():
    """10년 데이타 탭 관련 JavaScript 코드를 반환"""
    return '''
// ── 10년 데이타 탭 상태 ──
let finData = null;
let currentDataTab = 'income';
let currentDataMode = 'annual';
let currentDataFs = 'CFS';
let finDataLoaded = false;
let finDataAccMt = 12;

// ── 서브탭 전환 ──
function switchDataTab(tab) {
  currentDataTab = tab;
  document.querySelectorAll('.data-sub-tab').forEach(t => t.classList.remove('active'));
  document.getElementById('data-tab-' + tab).classList.add('active');
  if (finDataLoaded) buildDataTable();
}

// ── 연결/개별 전환 ──
function setDataFs(fs) {
  currentDataFs = fs;
  document.querySelectorAll('#data-btn-CFS, #data-btn-OFS').forEach(b => b.classList.remove('active'));
  document.getElementById('data-btn-' + fs).classList.add('active');
  finDataLoaded = false;
  finData = null;
  loadFinData();
}

// ── 연환산/연간/분기 전환 ──
function setDataMode(mode) {
  currentDataMode = mode;
  document.querySelectorAll('#data-btn-trailing, #data-btn-annual, #data-btn-quarterly').forEach(b => b.classList.remove('active'));
  document.getElementById('data-btn-' + mode).classList.add('active');
  if (finDataLoaded) buildDataTable();
}

// ── 데이터 로딩 ──
async function loadFinData(refresh) {
  if (finDataLoaded && !refresh) {
    buildDataTable();
    return;
  }

  document.getElementById('dataLoadingOverlay').classList.add('show');
  document.getElementById('dataLoadingText').textContent = '재무제표 데이터를 불러오는 중... (최대 2~3분 소요)';

  const startYear = document.getElementById('startYear').value;
  const endYear = document.getElementById('endYear').value;
  const queryName = currentStockCode || currentCompany;

  let url = '/api/finstate?company=' + encodeURIComponent(queryName)
    + '&start=' + startYear + '&end=' + endYear + '&fs=' + currentDataFs;
  if (refresh) url += '&refresh=1';

  try {
    const res = await fetch(url);
    const result = await res.json();
    if (result.error) {
      alert('오류: ' + result.error);
      document.getElementById('dataLoadingOverlay').classList.remove('show');
      return;
    }
    finData = result;
    finDataAccMt = parseInt(result.acc_mt) || 12;
    finDataLoaded = true;
    if (typeof initAcctIdxCache === 'function') initAcctIdxCache();
    if (typeof update5YearIndicators === 'function') update5YearIndicators();
    buildDataTable();
  } catch(e) {
    alert('재무제표 로드 실패: ' + e.message);
  }
  document.getElementById('dataLoadingOverlay').classList.remove('show');
}

// ── 단위 결정 ──
function decideDataUnit(allValues) {
  let absMax = 0;
  allValues.forEach(v => {
    if (v !== null && v !== undefined) absMax = Math.max(absMax, Math.abs(v));
  });
  if (absMax >= 100000) return { unit: '조', divisor: 10000, suffix: '조', decimals: 2 };
  return { unit: '억', divisor: 1, suffix: '억', decimals: 0 };
}

// ── 접기/펼치기 토글 (복수 그룹 지원) ──
function toggleGroup(groupId) {
  // data-group 속성에 해당 groupId를 포함하는 모든 행 찾기
  const allGroupRows = document.querySelectorAll('[data-group]');
  const rows = [];
  allGroupRows.forEach(r => {
    const groups = r.getAttribute('data-group').split(' ');
    if (groups.includes(groupId)) rows.push(r);
  });
  const btn = document.getElementById('toggle-' + groupId);
  if (!btn) return;
  const isExpanded = btn.textContent === '\\u2212';
  rows.forEach(r => {
    r.style.display = isExpanded ? 'none' : '';
    // 접을 때: 하위 그룹의 토글 버튼도 + 로 리셋
    if (isExpanded) {
      const subBtn = r.querySelector('.toggle-btn');
      if (subBtn) {
        subBtn.textContent = '+';
        // 하위 그룹의 sub도 숨김
        const subGroupId = subBtn.id.replace('toggle-', '');
        const subRows = document.querySelectorAll('[data-group]');
        subRows.forEach(sr => {
          const sg = sr.getAttribute('data-group').split(' ');
          if (sg.includes(subGroupId)) sr.style.display = 'none';
        });
      }
    }
  });
  btn.textContent = isExpanded ? '+' : '\\u2212';
}

// ── 테이블 빌드 ──
function buildDataTable() {
  if (!finData || !finData.statements) return;

  const stmtMap = {
    income: '손익계산서',
    balance: '재무상태표',
    cashflow: '현금흐름표',
    nwc: '순운전자본',
  };
  const stmtKey = stmtMap[currentDataTab];

  if (currentDataTab === 'nwc') {
    document.getElementById('dataTableTitle').innerHTML =
      '순운전자본<span class="unit">(준비 중)</span>';
    document.getElementById('dataTableContainer').innerHTML =
      '<p style="text-align:center;color:#888;padding:40px 0;">순운전자본 기능은 준비 중입니다.</p>';
    return;
  }

  const stmt = finData.statements[stmtKey];
  if (!stmt) {
    document.getElementById('dataTableTitle').innerHTML =
      stmtKey + '<span class="unit"></span>';
    document.getElementById('dataTableContainer').innerHTML =
      '<p style="text-align:center;color:#888;padding:40px 0;">데이터가 없습니다.</p>';
    return;
  }

  // accounts는 이제 [{name, is_header}, ...] 구조
  const accounts = stmt.accounts;
  const stmtData = stmt.data;
  const isBS = (currentDataTab === 'balance');
  const isCF = (currentDataTab === 'cashflow');

  // 기간 계산
  const allPeriods = Object.keys(stmtData).sort();
  let displayPeriods = [];
  let periodLabels = [];

  if (currentDataMode === 'quarterly') {
    displayPeriods = allPeriods;
    periodLabels = allPeriods.map(p => toDisplayLabel(p, 'quarterly'));
  } else if (currentDataMode === 'annual') {
    const yearMap = {};
    allPeriods.forEach(p => {
      const y = p.slice(0, 4);
      if (!yearMap[y]) yearMap[y] = [];
      yearMap[y].push(p);
    });
    const sortedYears = Object.keys(yearMap).sort();
    sortedYears.forEach(y => {
      if (yearMap[y].length === 4) {
        displayPeriods.push(y);
        const mm = String(finDataAccMt).padStart(2, '0');
        periodLabels.push(y + '.' + mm);
      }
    });
    // 가장 최근 연도가 4분기 미만이면, 최신 분기를 추가 표시
    if (sortedYears.length > 0) {
      const lastYear = sortedYears[sortedYears.length - 1];
      const lastYearPeriods = yearMap[lastYear];
      if (lastYearPeriods.length < 4 && lastYearPeriods.length > 0) {
        // 가장 최근 분기 찾기
        const latestPeriod = lastYearPeriods.sort().pop();
        const qtrNum = parseInt(latestPeriod.slice(5));  // Q1=1, Q2=2, Q3=3
        const qtrMonthMap = {1: '03', 2: '06', 3: '09', 4: '12'};
        const mm = qtrMonthMap[qtrNum] || '12';
        displayPeriods.push('latest_' + latestPeriod);
        periodLabels.push(lastYear + '.' + mm);
      }
    }
  } else {
    if (isBS) {
      displayPeriods = allPeriods;
      periodLabels = allPeriods.map(p => toDisplayLabel(p, 'trailing'));
    } else {
      for (let i = 3; i < allPeriods.length; i++) {
        displayPeriods.push(allPeriods[i]);
        periodLabels.push(toDisplayLabel(allPeriods[i], 'trailing'));
      }
    }
  }

  // 최신 데이터가 왼쪽에 오도록 역순 정렬
  displayPeriods.reverse();
  periodLabels.reverse();

  if (!displayPeriods.length) {
    document.getElementById('dataTableContainer').innerHTML =
      '<p style="text-align:center;color:#888;padding:40px 0;">표시할 기간이 없습니다.</p>';
    return;
  }

  // 값 계산 함수
  // 현금흐름표(isCF)는 thstrm_amount가 누적값이므로 BS와 동일하게 처리
  function getValue(acctIdx, period) {
    if (currentDataMode === 'quarterly') {
      const d = stmtData[period];
      return d ? d[acctIdx] : null;
    }
    if (currentDataMode === 'annual') {
      // 최신 분기 데이터 (latest_2025Q3 등)
      if (period.startsWith('latest_')) {
        const rawPeriod = period.slice(7);  // e.g. '2025Q3'
        if (isBS || isCF) {
          // BS/CF: 최신 분기의 값을 그대로 사용 (누적값)
          const d = stmtData[rawPeriod];
          return d ? d[acctIdx] : null;
        }
        // 손익계산서: 해당 연도의 존재하는 분기 합산
        const y = rawPeriod.slice(0, 4);
        let sum = 0, count = 0;
        ['Q1','Q2','Q3','Q4'].forEach(q => {
          const d = stmtData[y + q];
          if (d && d[acctIdx] !== null && d[acctIdx] !== undefined) {
            sum += d[acctIdx];
            count++;
          }
        });
        return count > 0 ? sum : null;
      }
      if (isBS || isCF) {
        // BS/CF: Q4(사업보고서)의 연간 누적값 사용
        const q4 = stmtData[period + 'Q4'];
        return q4 ? q4[acctIdx] : null;
      }
      let sum = 0, valid = true;
      ['Q1','Q2','Q3','Q4'].forEach(q => {
        const d = stmtData[period + q];
        if (!d || d[acctIdx] === null || d[acctIdx] === undefined) valid = false;
        else sum += d[acctIdx];
      });
      return valid ? sum : null;
    }
    if (isBS || isCF) {
      // trailing 모드에서도 BS/CF는 해당 분기 값 그대로
      const d = stmtData[period];
      return d ? d[acctIdx] : null;
    }
    const idx = allPeriods.indexOf(period);
    if (idx < 3) return null;
    let sum = 0, valid = true;
    for (let j = idx - 3; j <= idx; j++) {
      const d = stmtData[allPeriods[j]];
      if (!d || d[acctIdx] === null || d[acctIdx] === undefined) valid = false;
      else sum += d[acctIdx];
    }
    return valid ? sum : null;
  }

  // 단위 결정
  const allVals = [];
  accounts.forEach((acct, i) => {
    if (!acct.is_header) {
      displayPeriods.forEach(p => {
        const v = getValue(i, p);
        if (v !== null) allVals.push(v);
      });
    }
  });
  const unitInfo = decideDataUnit(allVals);

  // 타이틀
  document.getElementById('dataTableTitle').innerHTML =
    stmtKey + '<span class="unit">(단위: ' + unitInfo.suffix + '원)</span>';

  // 대항목/소항목 구조 빌드
  const structure = [];
  let groupCounter = 0;
  let currentL1GroupId = null;  // Level 1의 그룹 ID
  let currentL2GroupId = null;  // Level 2의 그룹 ID
  const isBSonly = (stmtKey === '재무상태표');

  for (let i = 0; i < accounts.length; i++) {
    const acct = accounts[i];
    if (acct.is_header && acct.level === 1) {
      currentL2GroupId = null;
      if (!isBSonly) {
        // 현금흐름표/손익계산서(포괄손익 부분): Level 1에 +버튼 있음, 하위 접기/펼치기
        groupCounter++;
        currentL1GroupId = 'g' + groupCounter;
        structure.push({ type: 'level1', acctIdx: i, groupId: currentL1GroupId });
      } else {
        // 재무상태표: Level 1은 항상 표시, +버튼 없음
        currentL1GroupId = null;
        structure.push({ type: 'level1', acctIdx: i });
      }
    } else if (acct.is_header && acct.level === 2) {
      groupCounter++;
      currentL2GroupId = 'g' + groupCounter;
      if (!isBSonly && currentL1GroupId) {
        // L2는 L1 아래 sub, 자체 +버튼으로 L3 펼침
        structure.push({ type: 'level2', acctIdx: i, groupId: currentL2GroupId, parentGroupId: currentL1GroupId });
      } else {
        // 재무상태표: L2는 항상 표시, +버튼 있음
        structure.push({ type: 'level2', acctIdx: i, groupId: currentL2GroupId });
      }
    } else if (acct.is_header) {
      // 기타 헤더 (손익계산서 등): +버튼 있음
      groupCounter++;
      currentL1GroupId = null;
      currentL2GroupId = 'g' + groupCounter;
      structure.push({ type: 'header', acctIdx: i, groupId: 'g' + groupCounter });
    } else if (acct.is_total) {
      currentL1GroupId = null;
      currentL2GroupId = null;
      structure.push({ type: 'total', acctIdx: i });
    } else if (acct.level === 3 && currentL2GroupId !== null) {
      // Level 3: L2 아래 접기 대상
      structure.push({ type: 'sub', acctIdx: i, groupId: currentL2GroupId });
    } else if (currentL1GroupId !== null && !isBSonly) {
      // L1 아래 일반 sub (현금흐름표, 손익계산서 포괄손익 부분)
      currentL2GroupId = null;
      structure.push({ type: 'sub', acctIdx: i, groupId: currentL1GroupId });
    } else if (currentL2GroupId !== null) {
      // 재무상태표: L2 아래 sub
      structure.push({ type: 'sub', acctIdx: i, groupId: currentL2GroupId });
    } else {
      structure.push({ type: 'main', acctIdx: i });
    }
  }

  // 값 포맷팅 헬퍼
  function fmtVal(val, bold) {
    if (val === null || val === undefined) {
      return '<td' + (bold ? ' style="font-weight:700;"' : '') + '>-</td>';
    }
    const dv = val / unitInfo.divisor;
    const formatted = unitInfo.decimals > 0
      ? dv.toLocaleString('ko-KR', {minimumFractionDigits: unitInfo.decimals, maximumFractionDigits: unitInfo.decimals})
      : Math.round(dv).toLocaleString('ko-KR');
    const neg = dv < 0 ? ' class="negative"' : '';
    const bld = bold ? 'font-weight:700;' : '';
    return '<td style="' + bld + '"' + neg + '>' + formatted + '</td>';
  }

  // 테이블 HTML 생성
  let html = '<table><thead><tr><th>계정과목</th>';
  periodLabels.forEach(l => { html += '<th>' + l + '</th>'; });
  html += '</tr></thead><tbody>';

  structure.forEach(item => {
    const acctName = accounts[item.acctIdx].name;
    const i = item.acctIdx;
    const hasData = accounts[item.acctIdx].has_data;

    if (item.type === 'level1') {
      // Level 1: 항상 표시, +버튼 있음 (하위 항목 접기/펼치기)
      const toggleBtn = item.groupId
        ? '<span id="toggle-' + item.groupId + '" class="toggle-btn" '
          + 'onclick="toggleGroup(\\'' + item.groupId + '\\')" '
          + 'style="cursor:pointer; display:inline-flex; align-items:center; justify-content:center; '
          + 'width:20px; height:20px; border:1.5px solid #90a4ae; border-radius:3px; '
          + 'font-size:14px; font-weight:bold; color:#1a237e; margin-right:6px; margin-left:-4px; '
          + 'background:#fff; user-select:none; vertical-align:middle;">+</span>'
        : '';
      const l1Border = hasData ? 'border-top:2px solid #1a237e; border-bottom:1.5px solid #1a237e;' : 'border-top:2px solid #1a237e;';
      html += '<tr style="background:#e8edf8; ' + l1Border + '">';
      html += '<td style="font-weight:800; color:#1a237e; font-size:13px;">' + toggleBtn + acctName + '</td>';
      displayPeriods.forEach(p => { html += fmtVal(getValue(i, p), true); });
      html += '</tr>';

    } else if (item.type === 'level2') {
      // Level 2: parentGroupId 있으면 L1 아래 sub (현금흐름표), 없으면 항상 표시 (재무상태표/포괄손익)
      const l2Border = hasData ? 'border-bottom:1.5px solid #1a237e;' : '';
      if (item.parentGroupId) {
        html += '<tr class="row-header" data-group="' + item.parentGroupId + '" style="display:none; background:#f4f6fa; ' + l2Border + '">';
      } else {
        html += '<tr class="row-header" style="background:#f4f6fa; ' + l2Border + '">';
      }
      const l2Padding = 'padding-left:14px;';
      html += '<td style="font-weight:700; color:#1a237e; ' + l2Padding + '">';
      html += '<span id="toggle-' + item.groupId + '" class="toggle-btn" '
        + 'onclick="toggleGroup(\\'' + item.groupId + '\\')" '
        + 'style="cursor:pointer; display:inline-flex; align-items:center; justify-content:center; '
        + 'width:20px; height:20px; border:1.5px solid #90a4ae; border-radius:3px; '
        + 'font-size:14px; font-weight:bold; color:#1a237e; margin-right:6px; margin-left:-4px; '
        + 'background:#fff; user-select:none; vertical-align:middle;">+</span>';
      html += acctName + '</td>';
      if (hasData) {
        displayPeriods.forEach(p => { html += fmtVal(getValue(i, p), true); });
      } else {
        displayPeriods.forEach(() => { html += '<td></td>'; });
      }
      html += '</tr>';

    } else if (item.type === 'header') {
      // 기존 헤더 (손익계산서 등): +버튼 있음
      html += '<tr class="row-header" style="background:#f4f6fa;">';
      html += '<td style="font-weight:700; color:#1a237e;">';
      html += '<span id="toggle-' + item.groupId + '" class="toggle-btn" '
        + 'onclick="toggleGroup(\\'' + item.groupId + '\\')" '
        + 'style="cursor:pointer; display:inline-flex; align-items:center; justify-content:center; '
        + 'width:20px; height:20px; border:1.5px solid #90a4ae; border-radius:3px; '
        + 'font-size:14px; font-weight:bold; color:#1a237e; margin-right:6px; '
        + 'background:#fff; user-select:none; vertical-align:middle;">+</span>';
      html += acctName + '</td>';
      if (hasData) {
        displayPeriods.forEach(p => { html += fmtVal(getValue(i, p), true); });
      } else {
        displayPeriods.forEach(() => { html += '<td></td>'; });
      }
      html += '</tr>';

    } else if (item.type === 'sub') {
      // 소항목: 기본 숨김, 복수 그룹 지원 (L1 접으면 L2/L3 모두 숨김)
      const dataGroups = item.parentGroupId
        ? item.parentGroupId + ' ' + item.groupId
        : item.groupId;
      const indent = accounts[item.acctIdx].level === 3 ? '52px' : '36px';
      html += '<tr data-group="' + dataGroups + '" style="display:none;">';
      html += '<td style="padding-left:' + indent + '; color:#555;">' + acctName + '</td>';
      displayPeriods.forEach(p => { html += fmtVal(getValue(i, p), false); });
      html += '</tr>';

    } else if (item.type === 'total') {
      // 총계 항목
      html += '<tr style="border-top:1.5px solid #333;">';
      html += '<td style="font-weight:700;">' + acctName + '</td>';
      displayPeriods.forEach(p => { html += fmtVal(getValue(i, p), true); });
      html += '</tr>';

    } else {
      // 일반 대항목 — 매출액/영업이익/당기순이익 하이라이트
      const highlightNames = ['매출액', '영업이익', '영업이익(손실)', '지배기업 소유주지분', '지배기업소유주지분', '당기순이익', '당기순이익(손실)', '분기순이익', '분기순이익(손실)'];
      const isHighlight = highlightNames.includes(acctName);
      if (isHighlight) {
        html += '<tr style="border-top:1.5px solid #1a237e; border-bottom:1.5px solid #1a237e; background:#f8f9ff;">';
        html += '<td style="font-weight:800;">' + acctName + '</td>';
        displayPeriods.forEach(p => { html += fmtVal(getValue(i, p), true); });
      } else {
        html += '<tr>';
        html += '<td>' + acctName + '</td>';
        displayPeriods.forEach(p => { html += fmtVal(getValue(i, p), false); });
      }
      html += '</tr>';
    }
  });

  html += '</tbody></table>';
  document.getElementById('dataTableContainer').innerHTML = html;

  // "당기순이익의 귀속" / "주당이익" 그룹 자동 펼침
  structure.forEach(item => {
    if (item.type === 'header') {
      const nm = accounts[item.acctIdx].name;
      if (nm === '당기순이익의 귀속' || nm === '주당이익') {
        toggleGroup(item.groupId);
      }
    }
  });
}
'''
