# -*- coding: utf-8 -*-
"""
순운전자본 탭 프론트엔드 모듈
- HTML 테이블 + 엑셀 그룹별 +버튼 접기/펼치기 + 엑셀 다운로드 + 스크리닝 UI
"""


def get_순운전자본_html():
    return '''
<div id="nwc-content" style="display:none; overflow:hidden;">
  <!-- 헤더 -->
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
    <div>
      <h2 style="font-size:22px; font-weight:800; color:#222; margin:0;">조정순운전자본 스크리닝</h2>
      <p id="nwcSummary" style="font-size:13px; color:#888; margin-top:4px;">데이터를 로드해주세요</p>
    </div>
    <button onclick="nwcDownloadExcel()" style="
      padding:10px 20px; background:#5dd39e; color:#fff; border:none; border-radius:8px;
      font-size:14px; font-weight:700; cursor:pointer; display:flex; align-items:center; gap:6px;
    "><span style="font-size:16px;">&#128229;</span> 엑셀 다운로드</button>
  </div>

  <!-- 컨트롤 바 -->
  <div style="display:flex; align-items:center; gap:12px; padding:12px 20px;
    background:#f5f7f5; border-radius:10px; margin-bottom:16px; flex-wrap:wrap;">
    <button onclick="nwcStartScreening()" id="nwcScreenBtn" style="
      padding:8px 20px; background:var(--primary); color:#fff; border:none; border-radius:6px;
      font-size:13px; font-weight:600; cursor:pointer;">&#128260; 스크리닝 시작</button>
    <button onclick="nwcStopScreening()" id="nwcStopBtn" style="
      padding:8px 14px; background:#d32f2f; color:#fff; border:none; border-radius:6px;
      font-size:13px; font-weight:600; cursor:pointer; display:none;">&#9724; 중지</button>
  </div>

  <!-- 스크리닝 진행 바 -->
  <div id="nwcProgressArea" style="display:none; margin-bottom:16px;
    background:#fff; border-radius:10px; padding:16px 20px; box-shadow:0 1px 4px rgba(0,0,0,0.06);">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
      <span id="nwcProgressText" style="font-size:13px; font-weight:600; color:#555;">분석 중...</span>
      <span id="nwcProgressPct" style="font-size:13px; font-weight:700; color:var(--primary);">0%</span>
    </div>
    <div style="width:100%; height:8px; background:#e8e8e8; border-radius:4px; overflow:hidden;">
      <div id="nwcProgressBar" style="width:0%; height:100%; background:linear-gradient(90deg,var(--primary),var(--accent));
        border-radius:4px; transition:width 0.3s;"></div>
    </div>
    <p id="nwcProgressDetail" style="font-size:12px; color:#999; margin-top:6px;"></p>
  </div>

  <!-- 종목수 + 모두 펼치기/접기 -->
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
    <div style="display:flex; gap:6px;">
      <button onclick="nwcExpandAll()" style="padding:4px 12px; background:var(--primary); color:#fff; border:none; border-radius:4px; font-size:12px; cursor:pointer;">모두 펼치기</button>
      <button onclick="nwcCollapseAll()" style="padding:4px 12px; background:#fff; color:#666; border:1px solid #ddd; border-radius:4px; font-size:12px; cursor:pointer;">모두 접기</button>
    </div>
    <span style="font-size:12px; color:#999;" id="nwcRowCount"></span>
  </div>

  <!-- 테이블 -->
  <div id="nwcTableWrap" style="background:#fff; border-radius:12px; padding:0; box-shadow:0 1px 4px rgba(0,0,0,0.06); overflow:auto; max-height:75vh;">
    <table id="nwcTable" style="border-collapse:separate; border-spacing:0; font-size:11px; white-space:nowrap;">
      <thead id="nwcTableHead"></thead>
      <tbody id="nwcTableBody"></tbody>
    </table>
  </div>
</div>
'''


def get_순운전자본_js():
    return r'''
// ── 순운전자본 탭 ──
let nwcData = [];
let nwcSortCol = '\uc870\uc815\uc21c\uc6b4\uc804\uc790\ubcf8/\uc2dc\ucd1d(\ubc30)';
let nwcSortAsc = false;

// 엑셀 그대로 전체 컬럼 순서 (28개)
const NWC_ALL_COLS = [
  '\uc885\ubaa9\uba85', '\uc138\ubd80\uc5c5\uc885', '\ub9e4\ucd9c\ube44\uc911',
  '\uc885\ubaa9\ucf54\ub4dc', '\uc2dc\uc7a5', '\uc0ac\uc6a9\ubcf4\uace0\uc11c', '\uc7ac\ubb34\uc81c\ud45c\uc720\ud615',
  '\uc2dc\uac00\ucd1d\uc561',
  '\uc720\ub3d9\uc790\uc0b0', '\uc720\ub3d9\ubd80\ucc44', '\uc21c\uc6b4\uc804\uc790\ubcf8',
  '\uc21c\uc6b4\uc804\uc790\ubcf8/\uc2dc\ucd1d(\ubc30)',
  '\ub9e4\ucd9c\ucc44\uad8c', '\uc7ac\uace0\uc790\uc0b0', '\ube44\uc720\ub3d9\uae08\uc735\uc790\uc0b0',
  '\uc870\uc815\uc720\ub3d9\uc790\uc0b0',
  '\ub9e4\uc785\ucc44\ubb34', '\uc7a5\uae30\ucc28\uc785\uae08', '\uc0ac\ucc44',
  '\uc870\uc815\uc720\ub3d9\ubd80\ucc44',
  '\uc870\uc815\uc21c\uc6b4\uc804\uc790\ubcf8',
  '\uc870\uc815\uc21c\uc6b4\uc804\uc790\ubcf8/\uc2dc\ucd1d(\ubc30)',
  '\ud22c\uc790\ubd80\ub3d9\uc0b0', '\uad00\uacc4\uc885\uc18d\uae30\uc5c5\ud22c\uc790',
  '\ub300\uc8fc\uc8fc\uc9c0\ubd84\uc728',
  '\uc790\uc0ac\uc8fc\ube44\uc728', '\ubc1c\ud589\uc8fc\uc2dd\uc218', '\uc790\uae30\uc8fc\uc2dd\uc218'
];

// 그룹 정의: { name, buttonAfter(기준컬럼), cols(숨겨지는 컬럼들) }
const NWC_GROUPS = [
  {
    id: 'grp1',
    buttonAfter: '\ub9e4\ucd9c\ube44\uc911',
    cols: ['\uc885\ubaa9\ucf54\ub4dc', '\uc2dc\uc7a5', '\uc0ac\uc6a9\ubcf4\uace0\uc11c', '\uc7ac\ubb34\uc81c\ud45c\uc720\ud615']
  },
  {
    id: 'grp2',
    buttonAfter: '\uc2dc\uac00\ucd1d\uc561',
    cols: ['\uc720\ub3d9\uc790\uc0b0', '\uc720\ub3d9\ubd80\ucc44', '\uc21c\uc6b4\uc804\uc790\ubcf8']
  },
  {
    id: 'grp3',
    buttonAfter: '\uc21c\uc6b4\uc804\uc790\ubcf8/\uc2dc\ucd1d(\ubc30)',
    cols: ['\ub9e4\ucd9c\ucc44\uad8c', '\uc7ac\uace0\uc790\uc0b0', '\ube44\uc720\ub3d9\uae08\uc735\uc790\uc0b0']
  },
  {
    id: 'grp4',
    buttonAfter: '\uc870\uc815\uc720\ub3d9\uc790\uc0b0',
    cols: ['\ub9e4\uc785\ucc44\ubb34', '\uc7a5\uae30\ucc28\uc785\uae08', '\uc0ac\ucc44']
  },
  {
    id: 'grp5',
    buttonAfter: '\ub300\uc8fc\uc8fc\uc9c0\ubd84\uc728',
    cols: ['\uc790\uc0ac\uc8fc\ube44\uc728', '\ubc1c\ud589\uc8fc\uc2dd\uc218', '\uc790\uae30\uc8fc\uc2dd\uc218']
  }
];

// 그룹 펼침 상태
let nwcGroupState = {};
NWC_GROUPS.forEach(g => { nwcGroupState[g.id] = false; });

// 숫자/소수 컬럼 정의
const NWC_NUMBER_COLS = [
  '\uc2dc\uac00\ucd1d\uc561', '\uc720\ub3d9\uc790\uc0b0', '\uc720\ub3d9\ubd80\ucc44', '\uc21c\uc6b4\uc804\uc790\ubcf8',
  '\ub9e4\ucd9c\ucc44\uad8c', '\uc7ac\uace0\uc790\uc0b0', '\ube44\uc720\ub3d9\uae08\uc735\uc790\uc0b0', '\uc870\uc815\uc720\ub3d9\uc790\uc0b0',
  '\ub9e4\uc785\ucc44\ubb34', '\uc7a5\uae30\ucc28\uc785\uae08', '\uc0ac\ucc44', '\uc870\uc815\uc720\ub3d9\ubd80\ucc44',
  '\uc870\uc815\uc21c\uc6b4\uc804\uc790\ubcf8', '\ud22c\uc790\ubd80\ub3d9\uc0b0', '\uad00\uacc4\uc885\uc18d\uae30\uc5c5\ud22c\uc790',
  '\ubc1c\ud589\uc8fc\uc2dd\uc218', '\uc790\uae30\uc8fc\uc2dd\uc218'
];
const NWC_DECIMAL_COLS = [
  '\uc21c\uc6b4\uc804\uc790\ubcf8/\uc2dc\ucd1d(\ubc30)', '\uc870\uc815\uc21c\uc6b4\uc804\uc790\ubcf8/\uc2dc\ucd1d(\ubc30)',
  '\ub300\uc8fc\uc8fc\uc9c0\ubd84\uc728', '\uc790\uc0ac\uc8fc\ube44\uc728'
];

// 강조 컬럼 (주황/초록 배경)
const NWC_ORANGE_COLS = ['\uc21c\uc6b4\uc804\uc790\ubcf8/\uc2dc\ucd1d(\ubc30)', '\uc870\uc815\uc720\ub3d9\uc790\uc0b0', '\uc870\uc815\uc720\ub3d9\ubd80\ucc44'];
const NWC_GREEN_COLS = ['\uc870\uc815\uc21c\uc6b4\uc804\uc790\ubcf8', '\uc870\uc815\uc21c\uc6b4\uc804\uc790\ubcf8/\uc2dc\ucd1d(\ubc30)'];

// 틀고정 컬럼 (종목명만)
const NWC_FREEZE_COLS = ['\uc885\ubaa9\uba85'];
const NWC_FREEZE_WIDTHS = [90];  // 각 고정 컬럼의 픽셀 너비
function nwcFreezeLeft(ci) {
  // ci번째 고정 컬럼의 left 오프셋 계산
  let left = 0;
  for (let k = 0; k < ci; k++) left += NWC_FREEZE_WIDTHS[k];
  return left;
}
const NWC_FREEZE_TOTAL = NWC_FREEZE_WIDTHS.reduce((a,b) => a+b, 0);

function nwcGetVisibleCols() {
  // buttonAfter 매핑: col → group (서브컬럼은 buttonAfter 뒤에 삽입)
  const buttonAfterMap = {};
  NWC_GROUPS.forEach(g => { buttonAfterMap[g.buttonAfter] = g; });

  // 그룹 컬럼 set
  const groupCols = new Set();
  NWC_GROUPS.forEach(g => { g.cols.forEach(c => groupCols.add(c)); });

  const result = [];
  for (let i = 0; i < NWC_ALL_COLS.length; i++) {
    const col = NWC_ALL_COLS[i];
    if (groupCols.has(col)) continue;
    // buttonAfter 컬럼이면 그룹 정보 포함 (서브컬럼 삽입 위치)
    const grp = buttonAfterMap[col] || null;
    result.push({ type: 'data', col: col, group: grp });
  }
  return result;
}

function nwcInit() {
  document.getElementById('nwcSummary').textContent = '\ub85c\ub529 \uc911...';
  fetch('/api/nwc/latest')
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        nwcData = data.data;
        document.getElementById('nwcSummary').textContent =
          data.file + ' | ' + data.count + '\uac1c \uc885\ubaa9 | \uc870\uc815\uc21c\uc6b4\uc804\uc790\ubcf8 >= \uc2dc\ucd1d';
        nwcRenderTable();
      } else {
        document.getElementById('nwcSummary').textContent = data.error || '\uacb0\uacfc \ud30c\uc77c\uc774 \uc5c6\uc2b5\ub2c8\ub2e4';
      }
    });
}

function nwcFormatNumber(val, col) {
  if (val === '' || val === null || val === undefined) return '-';
  const num = Number(val);
  if (isNaN(num)) return val;
  if (NWC_DECIMAL_COLS.includes(col)) return num.toFixed(2);
  if (NWC_NUMBER_COLS.includes(col)) return num.toLocaleString('ko-KR');
  return val;
}

function nwcToggleGroup(groupId) {
  nwcGroupState[groupId] = !nwcGroupState[groupId];
  nwcRenderTable();
}

function nwcExpandAll() {
  NWC_GROUPS.forEach(g => { nwcGroupState[g.id] = true; });
  nwcRenderTable();
}

function nwcCollapseAll() {
  NWC_GROUPS.forEach(g => { nwcGroupState[g.id] = false; });
  nwcRenderTable();
}

function nwcRenderTable() {
  const layout = nwcGetVisibleCols();
  const thead = document.getElementById('nwcTableHead');
  const tbody = document.getElementById('nwcTableBody');

  // 정렬
  const sortedData = [...nwcData].sort((a, b) => {
    let va = a[nwcSortCol], vb = b[nwcSortCol];
    if (typeof va === 'string' && typeof vb === 'string') {
      return nwcSortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
    }
    va = Number(va) || 0; vb = Number(vb) || 0;
    return nwcSortAsc ? va - vb : vb - va;
  });

  // 넓이 제한 컬럼
  const NWC_TRUNCATE_COLS = ['\uc138\ubd80\uc5c5\uc885', '\ub9e4\ucd9c\ube44\uc911'];

  // === 1단계: 실제 표시할 전체 컬럼 목록 구성 (Row2 = 컬럼명 = Body 컬럼) ===
  // flatCols: 화면에 실제 표시되는 모든 컬럼의 순서 배열
  const flatCols = [];
  layout.forEach(item => {
    flatCols.push(item.col);
    if (item.group && nwcGroupState[item.group.id]) {
      item.group.cols.forEach(gc => flatCols.push(gc));
    }
  });

  // === 2단계: Row1 구성 (버튼 행) ===
  // Row1의 셀 수 합(colspan 포함) = flatCols.length 와 일치해야 함
  //
  // 규칙:
  //   - 닫힌 그룹: buttonAfter 컬럼 위 = 빈칸, 다음 컬럼 위 = +버튼
  //   - 열린 그룹: buttonAfter 컬럼 위 = 빈칸, 서브컬럼 전체 위 = −버튼(colspan=서브컬럼수)
  //     → 다음 컬럼 위 = −버튼의 colspan에 포함되지 않음 (독립 셀)
  //   - 나머지: 빈 회색칸

  // 먼저 닫힌 그룹의 +버튼 위치 결정: buttonAfter의 다음 flatCols 인덱스
  const closedBtnAt = new Set();   // flatCols 인덱스 중 +버튼을 표시할 위치
  const closedBtnGroup = {};       // flatCols 인덱스 → 그룹
  const openBtnAt = new Set();     // flatCols 인덱스 중 −버튼 시작 위치
  const openBtnGroup = {};         // flatCols 인덱스 → 그룹
  const openBtnSpan = {};          // flatCols 인덱스 → colspan

  let fi = 0;  // flatCols 인덱스 추적
  layout.forEach(item => {
    const g = item.group;
    if (g) {
      if (nwcGroupState[g.id]) {
        // 열린 그룹: buttonAfter(fi) 위 = 빈칸, fi+1부터 g.cols.length개 = −버튼 colspan
        openBtnAt.add(fi + 1);
        openBtnGroup[fi + 1] = g;
        openBtnSpan[fi + 1] = g.cols.length;
        fi += 1 + g.cols.length;  // buttonAfter + 서브컬럼들
      } else {
        // 닫힌 그룹: 다음 컬럼이 있으면 fi+1 위에, 없으면 fi 자체에 +버튼
        if (fi + 1 < flatCols.length) {
          closedBtnAt.add(fi + 1);
          closedBtnGroup[fi + 1] = g;
        } else {
          closedBtnAt.add(fi);
          closedBtnGroup[fi] = g;
        }
        fi += 1;  // buttonAfter만
      }
    } else {
      fi += 1;
    }
  });

  // Row1 HTML 생성 (버튼 행 - sticky top:0)
  let row1Html = '';
  let i = 0;
  while (i < flatCols.length) {
    const freezeIdx = NWC_FREEZE_COLS.indexOf(flatCols[i]);
    const isFreeze = freezeIdx >= 0;
    const stickyTop = 'position:sticky; top:0; z-index:' + (isFreeze ? '5' : '3') + ';';
    const stickyLeft = isFreeze
      ? ' left:' + nwcFreezeLeft(freezeIdx) + 'px; min-width:' + NWC_FREEZE_WIDTHS[freezeIdx] + 'px; max-width:' + NWC_FREEZE_WIDTHS[freezeIdx] + 'px;'
      : '';
    if (openBtnAt.has(i)) {
      const og = openBtnGroup[i];
      const span = openBtnSpan[i];
      row1Html += '<th colspan="' + span + '" style="background:#f0f0f0; border:1px solid #d0d0d0; padding:4px 6px; text-align:center; cursor:pointer; font-size:14px; font-weight:bold; color:#333; ' + stickyTop + stickyLeft + '"' +
        ' onclick="nwcToggleGroup(\'' + og.id + '\')">\u2212</th>';
      i += span;
    } else if (closedBtnAt.has(i)) {
      const cg = closedBtnGroup[i];
      row1Html += '<th style="background:#f0f0f0; border:1px solid #d0d0d0; padding:4px 6px; text-align:center; cursor:pointer; font-size:14px; font-weight:bold; color:#333; ' + stickyTop + stickyLeft + '"' +
        ' onclick="nwcToggleGroup(\'' + cg.id + '\')">+</th>';
      i++;
    } else {
      row1Html += '<th style="background:#f0f0f0; border-bottom:1px solid #d0d0d0; padding:4px 6px; ' + stickyTop + stickyLeft + '"></th>';
      i++;
    }
  }

  // === 3단계: Row2 구성 (컬럼명 행 - sticky top:30px, Row1 아래) ===
  // Row1 높이를 측정하기 어려우므로 JS에서 렌더 후 보정
  let row2Html = '';
  flatCols.forEach((col, ci) => {
    const isOrange = NWC_ORANGE_COLS.includes(col);
    const isGreen = NWC_GREEN_COLS.includes(col);
    const bg = isGreen ? '#03c75a' : (isOrange ? '#e67e22' : '#5dd39e');
    const arrow = nwcSortCol === col ? (nwcSortAsc ? ' \u25b2' : ' \u25bc') : '';
    const freezeIdx = NWC_FREEZE_COLS.indexOf(col);
    const isFreeze = freezeIdx >= 0;
    let wrapStyle, stickyStyle;
    if (isFreeze) {
      wrapStyle = 'white-space:nowrap; min-width:' + NWC_FREEZE_WIDTHS[freezeIdx] + 'px; max-width:' + NWC_FREEZE_WIDTHS[freezeIdx] + 'px; overflow:hidden; text-overflow:ellipsis;';
      stickyStyle = 'position:sticky; left:' + nwcFreezeLeft(freezeIdx) + 'px; z-index:5;';
    } else {
      wrapStyle = col.length > 5 ? 'white-space:normal; word-break:keep-all; min-width:52px; max-width:90px;' : 'white-space:nowrap;';
      stickyStyle = 'position:sticky; z-index:3;';
    }
    row2Html += '<th class="nwc-row2-th" style="background:' + bg + '; color:#fff; padding:6px 4px; text-align:center; cursor:pointer; font-size:11px; ' + wrapStyle + ' border-right:1px solid rgba(255,255,255,0.3); line-height:1.3; ' + stickyStyle + '"' +
      ' onclick="nwcSort(\'' + col + '\')">' + col + arrow + '</th>';
  });

  thead.innerHTML = '<tr>' + row1Html + '</tr><tr>' + row2Html + '</tr>';

  // Row2의 sticky top 값을 Row1 실제 높이로 설정
  setTimeout(() => {
    const row1 = thead.querySelector('tr:first-child');
    if (row1) {
      const row1H = row1.offsetHeight;
      thead.querySelectorAll('.nwc-row2-th').forEach(th => {
        th.style.top = row1H + 'px';
      });
      // Row1 th에도 top:0 보장
      row1.querySelectorAll('th').forEach(th => {
        th.style.top = '0px';
      });
    }
  }, 0);

  // === 4단계: 바디 ===
  tbody.innerHTML = sortedData.map((row, ri) => {
    const bgColor = ri % 2 === 0 ? '#fff' : '#f8faf8';
    let cells = '';

    flatCols.forEach((col, ci) => {
      const val = nwcFormatNumber(row[col], col);
      const isNum = NWC_NUMBER_COLS.includes(col) || NWC_DECIMAL_COLS.includes(col);
      const isNeg = isNum && Number(row[col]) < 0;
      const isTrunc = NWC_TRUNCATE_COLS.includes(col);
      const align = isNum ? 'right' : (col === '\uc885\ubaa9\uba85' ? 'left' : (isTrunc ? 'left' : 'center'));
      const negStyle = isNeg ? ' color:#d32f2f;' : '';
      const freezeIdx = NWC_FREEZE_COLS.indexOf(col);
      const isFreeze = freezeIdx >= 0;
      const isLastFreeze = freezeIdx === NWC_FREEZE_COLS.length - 1;
      const freezeShadow = isLastFreeze ? ' box-shadow:2px 0 4px rgba(0,0,0,0.1);' : '';
      const stickyStyle = isFreeze
        ? 'position:sticky; left:' + nwcFreezeLeft(freezeIdx) + 'px; z-index:1; min-width:' + NWC_FREEZE_WIDTHS[freezeIdx] + 'px; max-width:' + NWC_FREEZE_WIDTHS[freezeIdx] + 'px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;' + freezeShadow
        : '';
      const truncStyle = (isTrunc && !isFreeze) ? ' max-width:120px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;' : '';
      const titleAttr = (isTrunc || isFreeze) && val ? ' title="' + String(val).replace(/"/g, '&quot;') + '"' : '';

      if (col === '\uc885\ubaa9\uba85') {
        cells += '<td onclick="nwcClickStock(\'' + (row['\uc885\ubaa9\ucf54\ub4dc']||'') + '\', \'' + (row['\uc885\ubaa9\uba85']||'').replace(/'/g, '') + '\')" style="padding:7px 6px; text-align:left; border-bottom:1px solid #f0f0f0; border-right:1px solid #f5f5f5; cursor:pointer; color:var(--primary); font-weight:700; background:' + bgColor + '; ' + stickyStyle + '"' + titleAttr + '>' + val + '</td>';
      } else {
        cells += '<td style="padding:7px 6px; text-align:' + align + '; border-bottom:1px solid #f0f0f0;' + negStyle + truncStyle + ' background:' + bgColor + '; ' + stickyStyle + ' border-right:1px solid #f5f5f5;"' + titleAttr + '>' + val + '</td>';
      }
    });

    return '<tr>' + cells + '</tr>';
  }).join('');

  document.getElementById('nwcRowCount').textContent = sortedData.length + '\uac1c \uc885\ubaa9';
}

function nwcSort(col) {
  if (nwcSortCol === col) {
    nwcSortAsc = !nwcSortAsc;
  } else {
    nwcSortCol = col;
    nwcSortAsc = false;
  }
  nwcRenderTable();
}

function nwcClickStock(code, name) {
  if (!code) return;
  switchGlobalMenu('finstate');
  document.getElementById('searchInput').value = name;
  const event = new Event('input', { bubbles: true });
  document.getElementById('searchInput').dispatchEvent(event);
}

function nwcDownloadExcel() {
  if (nwcData.length === 0) {
    alert('\ub2e4\uc6b4\ub85c\ub4dc\ud560 \ub370\uc774\ud130\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.');
    return;
  }
  window.location.href = '/api/nwc/download';
}

let _nwcAdminKey = '';
function nwcStartScreening() {
  const pw = prompt('관리자 비밀번호를 입력하세요:');
  if (!pw) return;
  _nwcAdminKey = pw;
  fetch('/api/nwc/screening', { method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({admin: pw}) })
    .then(r => { if (r.status === 403) { alert('비밀번호가 틀렸습니다.'); throw new Error('403'); } return r.json(); })
    .then(data => {
      if (data.success) {
        document.getElementById('nwcScreenBtn').style.display = 'none';
        document.getElementById('nwcStopBtn').style.display = 'inline-block';
        document.getElementById('nwcProgressArea').style.display = 'block';
        nwcPollStatus();
      } else {
        alert(data.message);
      }
    });
}

function nwcStopScreening() {
  fetch('/api/nwc/screening/stop', { method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({admin: _nwcAdminKey}) })
    .then(r => r.json())
    .then(() => {
      document.getElementById('nwcStopBtn').style.display = 'none';
      document.getElementById('nwcScreenBtn').style.display = 'inline-block';
    });
}

function nwcPollStatus() {
  fetch('/api/nwc/screening/status')
    .then(r => r.json())
    .then(data => {
      const pct = data.total > 0 ? Math.round(data.progress / data.total * 100) : 0;
      document.getElementById('nwcProgressBar').style.width = pct + '%';
      document.getElementById('nwcProgressPct').textContent = pct + '%';
      document.getElementById('nwcProgressText').textContent = data.message || '\ubd84\uc11d \uc911...';
      document.getElementById('nwcProgressDetail').textContent =
        data.current_stock + ' | \ubc1c\uacac: ' + data.found_count + '\uac1c | \uc9c4\ud589: ' + data.progress + '/' + data.total;

      if (data.running) {
        setTimeout(nwcPollStatus, 2000);
      } else {
        document.getElementById('nwcStopBtn').style.display = 'none';
        document.getElementById('nwcScreenBtn').style.display = 'inline-block';
        if (data.found_count > 0) {
          fetch('/api/nwc/screening/results')
            .then(r => r.json())
            .then(rdata => {
              nwcData = rdata.data || [];
              document.getElementById('nwcSummary').textContent =
                '\uc2e4\uc2dc\uac04 \uc2a4\ud06c\ub9ac\ub2dd | ' + nwcData.length + '\uac1c \uc885\ubaa9 | ' + data.message;
              nwcRenderTable();
            });
        }
        setTimeout(() => {
          document.getElementById('nwcProgressArea').style.display = 'none';
        }, 3000);
      }
    });
}
'''
