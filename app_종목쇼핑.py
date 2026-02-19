# -*- coding: utf-8 -*-
"""
종목쇼핑 탭 프론트엔드 모듈
- 전 상장사 재무지표 테이블 + 엑셀 다운로드 + 수집 UI
"""


def get_종목쇼핑_html():
    return '''
<div id="shopping-content" style="display:none; overflow:hidden;">
  <!-- 헤더 -->
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
    <div>
      <h2 style="font-size:22px; font-weight:800; color:#222; margin:0;">종목쇼핑</h2>
      <p id="shopSummary" style="font-size:13px; color:#888; margin-top:4px;">데이터 수집 버튼을 눌러주세요</p>
    </div>
    <button onclick="shopDownloadExcel()" style="
      padding:10px 20px; background:var(--primary); color:#fff; border:none; border-radius:8px;
      font-size:14px; font-weight:700; cursor:pointer; display:flex; align-items:center; gap:6px;
    "><span style="font-size:16px;">&#128229;</span> 엑셀 다운로드</button>
  </div>

  <!-- 컨트롤 바 -->
  <div style="display:flex; align-items:center; gap:12px; padding:12px 20px;
    background:var(--primary-light); border-radius:10px; margin-bottom:16px; flex-wrap:wrap;">
    <button onclick="shopStartCollection()" id="shopStartBtn" style="
      padding:8px 20px; background:var(--primary); color:#fff; border:none; border-radius:6px;
      font-size:13px; font-weight:600; cursor:pointer;">&#128202; 데이터 수집</button>
    <button onclick="shopStopCollection()" id="shopStopBtn" style="
      padding:8px 14px; background:#d32f2f; color:#fff; border:none; border-radius:6px;
      font-size:13px; font-weight:600; cursor:pointer; display:none;">&#9724; 중지</button>
    <span style="font-size:12px; color:#888; margin-left:8px;">
      캐시 보유 종목은 즉시 로드, 미보유 종목은 네이버에서 수집합니다
    </span>
  </div>

  <!-- 진행 바 -->
  <div id="shopProgressArea" style="display:none; margin-bottom:16px;
    background:#fff; border-radius:10px; padding:16px 20px; box-shadow:0 1px 4px rgba(0,0,0,0.06);">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
      <span id="shopProgressText" style="font-size:13px; font-weight:600; color:#555;">수집 중...</span>
      <span id="shopProgressPct" style="font-size:13px; font-weight:700; color:var(--primary);">0%</span>
    </div>
    <div style="width:100%; height:8px; background:#e8e8e8; border-radius:4px; overflow:hidden;">
      <div id="shopProgressBar" style="width:0%; height:100%; background:linear-gradient(90deg,var(--primary),var(--accent));
        border-radius:4px; transition:width 0.3s;"></div>
    </div>
    <p id="shopProgressDetail" style="font-size:12px; color:#999; margin-top:6px;"></p>
  </div>

  <!-- 필터 바 -->
  <div style="display:flex; align-items:center; gap:12px; margin-bottom:8px; flex-wrap:wrap;">
    <span style="font-size:12px; color:#666;">시장:</span>
    <select id="shopFilterMarket" onchange="shopRenderTable(true)" style="padding:4px 8px; border:1px solid #ddd; border-radius:4px; font-size:12px;">
      <option value="all">전체</option>
      <option value="코스피">코스피</option>
      <option value="코스닥">코스닥</option>
    </select>
    <span style="font-size:12px; color:#666; margin-left:8px;">PER:</span>
    <input type="number" id="shopFilterPerMin" placeholder="최소" style="width:60px; padding:4px; border:1px solid #ddd; border-radius:4px; font-size:12px;">
    <span style="font-size:11px; color:#999;">~</span>
    <input type="number" id="shopFilterPerMax" placeholder="최대" style="width:60px; padding:4px; border:1px solid #ddd; border-radius:4px; font-size:12px;">
    <span style="font-size:12px; color:#666; margin-left:8px;">ROE:</span>
    <input type="number" id="shopFilterRoeMin" placeholder="최소" style="width:60px; padding:4px; border:1px solid #ddd; border-radius:4px; font-size:12px;">
    <button onclick="shopRenderTable(true)" style="padding:4px 12px; background:var(--primary); color:#fff; border:none; border-radius:4px; font-size:12px; cursor:pointer;">필터</button>
    <button onclick="shopResetFilter()" style="padding:4px 12px; background:#fff; color:#666; border:1px solid #ddd; border-radius:4px; font-size:12px; cursor:pointer;">초기화</button>
    <span style="font-size:12px; color:#999; margin-left:auto;" id="shopRowCount"></span>
  </div>

  <!-- 테이블 -->
  <div id="shopTableWrap" style="background:#fff; border-radius:12px; padding:0; box-shadow:0 1px 4px rgba(0,0,0,0.06); overflow:auto; max-height:70vh;">
    <table id="shopTable" style="width:100%; border-collapse:separate; border-spacing:0; font-size:11px;">
      <thead id="shopTableHead"></thead>
      <tbody id="shopTableBody"></tbody>
    </table>
  </div>

  <!-- 페이지네이션 -->
  <div id="shopPagination" style="display:flex; justify-content:center; align-items:center; gap:4px; margin-top:12px; flex-wrap:wrap;"></div>
</div>
'''


def get_종목쇼핑_js():
    return r'''
// ── 종목쇼핑 탭 ──
let shopData = [];
let shopSortCol = '시가총액(억)';
let shopSortAsc = false;
let shopInitialized = false;
let shopPage = 1;
const SHOP_PAGE_SIZE = 100;

// 엑셀에는 모든 컬럼, 웹 테이블에서는 일부 제외
const SHOP_ALL_COLS = [
  '종목명', '종목코드', '시장', '업종', '세부업종', '회계기준',
  '시가총액(억)', '주가', '현재PER', '5년PER', 'PBR', '5년PBR',
  'PSR', 'PCR', 'ROE', '5년ROE', 'ROA', 'EPS', 'BPS', '배당수익률'
];
// 웹 테이블에서 숨길 컬럼 (엑셀에는 포함)
const SHOP_HIDDEN_COLS = ['종목코드', '시장', '업종', '세부업종', '회계기준'];
const SHOP_WEB_COLS = SHOP_ALL_COLS.filter(c => !SHOP_HIDDEN_COLS.includes(c));

// 숫자 포맷
const SHOP_DECIMAL_COLS = ['현재PER', '5년PER', 'PBR', '5년PBR', 'PSR', 'PCR', 'ROE', '5년ROE', 'ROA', '배당수익률'];
const SHOP_INT_COLS = ['시가총액(억)', '주가', 'EPS', 'BPS'];

// 헤더 색상 (5년 비교 지표는 녹색)
const SHOP_GREEN_COLS = ['5년PER', '5년PBR', '5년ROE'];

// 틀고정: 종목명 컬럼
const SHOP_FREEZE_COL = '종목명';
const SHOP_FREEZE_WIDTH = 100;

function shopInit() {
  if (shopInitialized && shopData.length > 0) {
    shopRenderTable();
    return;
  }
  shopInitialized = true;
  // 서버에 이미 수집된 결과가 있으면 자동 로드
  document.getElementById('shopSummary').textContent = '로딩 중...';
  fetch('/api/shopping/results')
    .then(r => r.json())
    .then(rdata => {
      if (rdata.data && rdata.data.length > 0) {
        shopData = rdata.data;
        document.getElementById('shopSummary').textContent = shopData.length + '개 종목 로드 완료';
        shopRenderTable();
      } else {
        document.getElementById('shopSummary').textContent = '데이터 수집 버튼을 눌러 전 종목 데이터를 수집하세요';
      }
    })
    .catch(() => {
      document.getElementById('shopSummary').textContent = '데이터 수집 버튼을 눌러 전 종목 데이터를 수집하세요';
    });
}

function shopFormatNumber(val, col) {
  if (val === '' || val === null || val === undefined) return '-';
  const num = Number(val);
  if (isNaN(num)) return val;
  if (SHOP_DECIMAL_COLS.includes(col)) return num.toFixed(2);
  if (SHOP_INT_COLS.includes(col)) return num.toLocaleString('ko-KR');
  return val;
}

function shopGetFilteredData() {
  let data = [...shopData];

  // 시장 필터
  const market = document.getElementById('shopFilterMarket').value;
  if (market !== 'all') {
    data = data.filter(r => r['시장'] === market);
  }

  // PER 필터
  const perMin = parseFloat(document.getElementById('shopFilterPerMin').value);
  const perMax = parseFloat(document.getElementById('shopFilterPerMax').value);
  if (!isNaN(perMin)) {
    data = data.filter(r => r['현재PER'] !== null && r['현재PER'] !== undefined && Number(r['현재PER']) >= perMin);
  }
  if (!isNaN(perMax)) {
    data = data.filter(r => r['현재PER'] !== null && r['현재PER'] !== undefined && Number(r['현재PER']) <= perMax);
  }

  // ROE 필터
  const roeMin = parseFloat(document.getElementById('shopFilterRoeMin').value);
  if (!isNaN(roeMin)) {
    data = data.filter(r => r['ROE'] !== null && r['ROE'] !== undefined && Number(r['ROE']) >= roeMin);
  }

  return data;
}

function shopResetFilter() {
  document.getElementById('shopFilterMarket').value = 'all';
  document.getElementById('shopFilterPerMin').value = '';
  document.getElementById('shopFilterPerMax').value = '';
  document.getElementById('shopFilterRoeMin').value = '';
  shopRenderTable(true);
}

function shopRenderTable(resetPage) {
  if (shopData.length === 0) return;
  if (resetPage) shopPage = 1;

  const data = shopGetFilteredData();

  // 정렬
  const sorted = data.sort((a, b) => {
    let va = a[shopSortCol], vb = b[shopSortCol];
    if (va === null || va === undefined) va = shopSortAsc ? Infinity : -Infinity;
    if (vb === null || vb === undefined) vb = shopSortAsc ? Infinity : -Infinity;
    if (typeof va === 'string' && typeof vb === 'string') {
      return shopSortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
    }
    va = Number(va) || 0; vb = Number(vb) || 0;
    return shopSortAsc ? va - vb : vb - va;
  });

  // 페이지네이션 계산
  const totalPages = Math.max(1, Math.ceil(sorted.length / SHOP_PAGE_SIZE));
  if (shopPage > totalPages) shopPage = totalPages;
  const startIdx = (shopPage - 1) * SHOP_PAGE_SIZE;
  const pageData = sorted.slice(startIdx, startIdx + SHOP_PAGE_SIZE);

  const thead = document.getElementById('shopTableHead');
  const tbody = document.getElementById('shopTableBody');

  // 헤더
  let headerHtml = '';
  SHOP_WEB_COLS.forEach(col => {
    const isGreen = SHOP_GREEN_COLS.includes(col);
    const bg = isGreen ? '#028a3d' : '#03c75a';
    const arrow = shopSortCol === col ? (shopSortAsc ? ' \u25b2' : ' \u25bc') : '';
    const isFreeze = col === SHOP_FREEZE_COL;
    const freezeStyle = isFreeze
      ? 'position:sticky; left:0; top:0; z-index:4; min-width:' + SHOP_FREEZE_WIDTH + 'px; max-width:' + SHOP_FREEZE_WIDTH + 'px; box-shadow:2px 0 4px rgba(0,0,0,0.1);'
      : 'position:sticky; top:0; z-index:2;';
    headerHtml += '<th style="background:' + bg + '; color:#fff; padding:6px 3px; text-align:center; cursor:pointer; font-size:10px; white-space:nowrap; border-right:1px solid rgba(255,255,255,0.3); ' + freezeStyle + '"' +
      ' onclick="shopSort(\'' + col + '\')">' + col + arrow + '</th>';
  });
  thead.innerHTML = '<tr>' + headerHtml + '</tr>';

  // 바디 (현재 페이지만)
  tbody.innerHTML = pageData.map((row, ri) => {
    const bgColor = ri % 2 === 0 ? '#fff' : '#f8fcf9';
    let cells = '';

    SHOP_WEB_COLS.forEach(col => {
      const val = shopFormatNumber(row[col], col);
      const isNum = SHOP_DECIMAL_COLS.includes(col) || SHOP_INT_COLS.includes(col);
      const isNeg = isNum && row[col] !== null && Number(row[col]) < 0;
      const align = isNum ? 'right' : (col === '종목명' ? 'left' : 'center');
      const negStyle = isNeg ? ' color:#d32f2f;' : '';
      const isFreeze = col === SHOP_FREEZE_COL;
      const stickyStyle = isFreeze
        ? 'position:sticky; left:0; z-index:1; min-width:' + SHOP_FREEZE_WIDTH + 'px; max-width:' + SHOP_FREEZE_WIDTH + 'px; box-shadow:2px 0 4px rgba(0,0,0,0.1);'
        : '';

      if (col === '종목명') {
        cells += '<td onclick="shopClickStock(\'' + (row['종목코드']||'') + '\', \'' + (row['종목명']||'').replace(/'/g, '') + '\')" style="padding:5px 3px; text-align:left; border-bottom:1px solid #f0f0f0; border-right:1px solid #f5f5f5; cursor:pointer; color:var(--primary); font-weight:700; background:' + bgColor + '; ' + stickyStyle + '" title="' + (row['종목명']||'').replace(/"/g, '&quot;') + '">' + val + '</td>';
      } else {
        cells += '<td style="padding:5px 3px; text-align:' + align + '; border-bottom:1px solid #f0f0f0;' + negStyle + ' background:' + bgColor + '; border-right:1px solid #f5f5f5;">' + val + '</td>';
      }
    });

    return '<tr>' + cells + '</tr>';
  }).join('');

  // 카운트 표시
  const fromN = startIdx + 1;
  const toN = Math.min(startIdx + SHOP_PAGE_SIZE, sorted.length);
  document.getElementById('shopRowCount').textContent =
    fromN + '-' + toN + ' / ' + sorted.length + '개 종목' +
    (sorted.length !== shopData.length ? ' (전체 ' + shopData.length + '개)' : '');

  // 페이지네이션 UI
  shopRenderPagination(totalPages);
}

function shopRenderPagination(totalPages) {
  const wrap = document.getElementById('shopPagination');
  if (totalPages <= 1) { wrap.innerHTML = ''; return; }

  const btnStyle = 'padding:4px 10px; border:1px solid #ddd; border-radius:4px; font-size:12px; cursor:pointer; background:#fff; color:#333;';
  const activeStyle = 'padding:4px 10px; border:1px solid #03c75a; border-radius:4px; font-size:12px; cursor:pointer; background:#03c75a; color:#fff; font-weight:700;';

  let html = '';
  // 이전
  html += '<button onclick="shopGoPage(' + (shopPage - 1) + ')" style="' + btnStyle + '"' + (shopPage <= 1 ? ' disabled style="' + btnStyle + 'opacity:0.4;cursor:default;"' : '') + '>&laquo;</button>';

  // 페이지 번호 (최대 7개 표시)
  let startP = Math.max(1, shopPage - 3);
  let endP = Math.min(totalPages, startP + 6);
  if (endP - startP < 6) startP = Math.max(1, endP - 6);

  if (startP > 1) {
    html += '<button onclick="shopGoPage(1)" style="' + btnStyle + '">1</button>';
    if (startP > 2) html += '<span style="padding:4px 2px; font-size:12px; color:#999;">...</span>';
  }
  for (let p = startP; p <= endP; p++) {
    html += '<button onclick="shopGoPage(' + p + ')" style="' + (p === shopPage ? activeStyle : btnStyle) + '">' + p + '</button>';
  }
  if (endP < totalPages) {
    if (endP < totalPages - 1) html += '<span style="padding:4px 2px; font-size:12px; color:#999;">...</span>';
    html += '<button onclick="shopGoPage(' + totalPages + ')" style="' + btnStyle + '">' + totalPages + '</button>';
  }

  // 다음
  html += '<button onclick="shopGoPage(' + (shopPage + 1) + ')" style="' + btnStyle + '"' + (shopPage >= totalPages ? ' disabled style="' + btnStyle + 'opacity:0.4;cursor:default;"' : '') + '>&raquo;</button>';

  wrap.innerHTML = html;
}

function shopGoPage(p) {
  const totalPages = Math.ceil(shopGetFilteredData().length / SHOP_PAGE_SIZE);
  if (p < 1 || p > totalPages) return;
  shopPage = p;
  shopRenderTable();
  document.getElementById('shopTableWrap').scrollTop = 0;
}

function shopSort(col) {
  if (shopSortCol === col) {
    shopSortAsc = !shopSortAsc;
  } else {
    shopSortCol = col;
    shopSortAsc = false;
  }
  shopRenderTable();
}

function shopClickStock(code, name) {
  if (!code) return;
  switchGlobalMenu('finstate');
  document.getElementById('searchInput').value = name;
  const event = new Event('input', { bubbles: true });
  document.getElementById('searchInput').dispatchEvent(event);
}

function shopDownloadExcel() {
  if (shopData.length === 0) {
    alert('다운로드할 데이터가 없습니다. 먼저 데이터를 수집해주세요.');
    return;
  }
  window.location.href = '/api/shopping/download';
}

let _shopAdminKey = '';
function shopStartCollection() {
  const pw = prompt('관리자 비밀번호를 입력하세요:');
  if (!pw) return;
  _shopAdminKey = pw;
  fetch('/api/shopping/collect', { method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({admin: pw}) })
    .then(r => { if (r.status === 403) { alert('비밀번호가 틀렸습니다.'); throw new Error('403'); } return r.json(); })
    .then(data => {
      if (data.error) {
        alert(data.error);
        return;
      }
      document.getElementById('shopStartBtn').style.display = 'none';
      document.getElementById('shopStopBtn').style.display = 'inline-block';
      document.getElementById('shopProgressArea').style.display = 'block';
      shopPollStatus();
    });
}

function shopStopCollection() {
  fetch('/api/shopping/stop', { method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({admin: _shopAdminKey}) })
    .then(r => r.json())
    .then(() => {
      document.getElementById('shopStopBtn').style.display = 'none';
      document.getElementById('shopStartBtn').style.display = 'inline-block';
    });
}

function shopPollStatus() {
  fetch('/api/shopping/status')
    .then(r => r.json())
    .then(data => {
      const pct = data.total > 0 ? Math.round(data.progress / data.total * 100) : 0;
      document.getElementById('shopProgressBar').style.width = pct + '%';
      document.getElementById('shopProgressPct').textContent = pct + '%';
      document.getElementById('shopProgressText').textContent = data.message || '수집 중...';
      document.getElementById('shopProgressDetail').textContent =
        data.current_stock + ' | 캐시: ' + data.cached_count + ' | 크롤링: ' + data.fetched_count + ' | 오류: ' + data.error_count + ' | ' + data.progress + '/' + data.total;

      if (data.running) {
        setTimeout(shopPollStatus, 2000);
      } else {
        document.getElementById('shopStopBtn').style.display = 'none';
        document.getElementById('shopStartBtn').style.display = 'inline-block';
        // 결과 로드
        fetch('/api/shopping/results')
          .then(r => r.json())
          .then(rdata => {
            shopData = rdata.data || [];
            document.getElementById('shopSummary').textContent =
              shopData.length + '개 종목 수집 완료 | ' + data.message;
            shopRenderTable();
          });
        setTimeout(() => {
          document.getElementById('shopProgressArea').style.display = 'none';
        }, 3000);
      }
    });
}
'''
