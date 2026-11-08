#!/usr/bin/env python3
"""BoopaDB prototype — 割引＆イベント特設ページ (sale.html) template.
Shares the home page's CSS (extracted from build_prototype.TEMPLATE at build
time) and the same embedded payload. Product links go to
index.html#item-<id>, where the home page opens its product view."""
import importlib.util, json
from pathlib import Path
from build_prototype import VISIBILITY_JS

here = Path(__file__).parent

SALE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="theme-color" content="#101012"><meta name="color-scheme" content="dark"><script>try{var t=localStorage.getItem("boopadb_theme");if(t!=="dark"&&t!=="light")t=matchMedia("(prefers-color-scheme: light)").matches?"light":"dark";document.documentElement.dataset.theme=t;var m=document.querySelector('meta[name="color-scheme"]');if(m)m.content=t;}catch(e){document.documentElement.dataset.theme="dark"}</script><link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&display=swap" rel="stylesheet"><link rel="preconnect" href="https://booth.pximg.net">
<title>セール中の商品 | BoopaDB</title>
<meta property="og:type" content="website">
<meta property="og:site_name" content="BoopaDB">
<meta property="og:title" content="セール中の商品 | BoopaDB">
<meta property="og:description" content="BOOTHのVRChat向け商品の価格推移・セール・値下げを追えるデータベース">
<meta property="og:url" content="https://mametarogg.github.io/boopadb/sale.html">
<meta property="og:image" content="https://mametarogg.github.io/boopadb/ogp-16x9.png">
<meta property="og:image:width" content="1920">
<meta property="og:image:height" content="1080">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="https://mametarogg.github.io/boopadb/ogp-16x9.png">
<link rel="icon" href="favicon.ico?v=3" sizes="any">
<link rel="icon" type="image/png" href="favicon-192.png?v=3" sizes="192x192">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="manifest" href="manifest.webmanifest">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="BoopaDB">
<script>if("serviceWorker" in navigator){navigator.serviceWorker.register("sw.js").catch(function(){})}</script>
<style>/*__CSS__*/</style>
<style>
  @media (min-width:900px){body{padding-left:118px}header{margin-left:-118px;padding-left:118px}}
  .crumb{font-size:12px;color:var(--faint)}
  .crumb a{color:var(--sub);text-decoration:none}
  .crumb a:hover{color:var(--text)}
  .ptitle{text-align:center;padding:36px 12px 10px;background:radial-gradient(660px 230px at 50% -50px,#26262c,transparent 70%)}
  .ptitle h1{font-size:42px;font-weight:900;letter-spacing:.06em;color:#fff;line-height:1.15}
  .ptitle p{color:var(--sub);font-size:13px;margin-top:12px}
  .ptitle p b{color:#c8ec6e;font-weight:800}
  .catbar{position:sticky;top:0;z-index:40;background:rgba(16,16,18,.94);backdrop-filter:blur(8px);border-top:1px solid var(--border);border-bottom:1px solid var(--border);margin:24px 0 4px;padding:10px 0}
  .catbar .chips{margin:0;justify-content:center}
  .capgrid .card{border-radius:0}
  .stabs{position:relative;display:inline-flex;gap:2px;border-bottom:1px solid var(--border);max-width:100%;overflow-x:auto;overflow-y:hidden;scrollbar-width:none;-webkit-overflow-scrolling:touch}
  .stabs::-webkit-scrollbar{display:none}
  .stabs button{flex:none}
  .stabs button{position:relative;z-index:1;background:none;border:none;color:var(--sub);font-size:13px;padding:7px 13px;cursor:pointer;font-family:inherit;transition:color .2s;border-bottom:2px solid transparent;margin-bottom:-1px}
  .stabs button.on{color:#fff;font-weight:700;border-bottom-color:var(--accent)}
  .moswrap{position:relative}
  .mosvp{overflow:hidden}
  .mostrack{display:flex;transition:transform .45s cubic-bezier(.4,0,.2,1)}
  .mpage{flex:0 0 100%;display:grid;grid-template-columns:repeat(4,1fr);gap:10px;min-width:0}
  .mosdots{display:none}
  @media (min-width:900px){
    .moswrap{margin:0 54px}
    .mosdots{display:flex;gap:6px;justify-content:center;margin-top:10px}
    .mosdots span{width:22px;height:4px;border-radius:2px;background:#33333a;cursor:pointer}
    .mosdots span.on{background:#e8e8ec}
  }
  html[data-theme="light"] .ptitle{background:radial-gradient(660px 230px at 50% -50px,#e3e3ea,transparent 70%)}
  html[data-theme="light"] .ptitle p b{color:#4c7a1f}
  html[data-theme="light"] .mosdots span{background:#cfcfd8}
  html[data-theme="light"] .mosdots span.on{background:#55555f}
  html[data-theme="light"] .ptitle h1{color:var(--text)}
  html[data-theme="light"] .catbar{background:rgba(244,244,246,.94)}
  @media (max-width:899px){
    .mosvp{overflow-x:auto;overflow-y:hidden;scrollbar-width:none}
    .mosvp::-webkit-scrollbar{display:none}
    .mostrack{transition:none}
    .mpage{flex-basis:calc(100% - 22px);grid-template-columns:1fr 1fr}
    .mpage.clone{display:none}
  }
  .scount{font-size:12.5px;color:var(--faint);margin:10px 0 2px}
  @media (max-width:899px){.ptitle h1{font-size:31px}}
</style>
</head>
<body>
<header>
  <div class="hwrap">
  <a class="logo" href="index.html" style="text-decoration:none;color:inherit">Boopa<span>DB</span></a>
  <nav><a href="index.html#sale" data-i="nav_sale">セール中の商品</a><a href="index.html#feat" data-i="nav_feat">注目の商品</a><a href="index.html#browse2" data-i="nav_browse">新着・値下げ</a></nav>
  <button id="themeBtn" class="themebtn" type="button" data-i-al="th_toggle" aria-label="テーマ切替"><svg class="ic-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg><svg class="ic-moon" viewBox="0 0 24 24"><path d="M20 13.5A8.5 8.5 0 1 1 10.5 4a7 7 0 0 0 9.5 9.5z"/></svg></button><div class="langsw"><button id="langBtn" type="button"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.7 3.8 9S14.5 18.4 12 21c-2.5-2.6-3.8-5.7-3.8-9S9.5 5.6 12 3z"/></svg><span id="langCur">日本語</span><svg class="lchev" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg></button><div class="langmenu" id="langMenu"></div></div>
  <div class="badge">PROTOTYPE</div>
  </div>
</header>
<main>
  <div class="crumb"><a href="index.html" data-i="tab_home">ホーム</a> › <span id="crumbHere">セール中の商品</span></div>
  <div class="ptitle">
    <h1 id="pgH1">セール中の商品</h1>
    <p id="subStats"></p>
  </div>
  <div class="moswrap"><button class="sarrow prev" id="mosPrev" data-i-al="al_prev" aria-label="前へ">‹</button><div class="salepanel"><div class="mosvp" id="spMosVp"><div class="mostrack" id="spMosaic"></div></div></div><button class="sarrow next" id="mosNext" data-i-al="al_next" aria-label="次へ">›</button></div>
  <div class="mosdots" id="mosDots"></div>
  <div class="railbar" id="mosBar"><span></span></div>
  <div class="catbar">
    <div class="chips" id="spChips">
      <button class="chip on" data-sf="all" data-i="chip_all">すべて</button>
      <button class="chip" data-sf="lowest" data-i="chip_lowest">過去最安値</button>
      <button class="chip" data-sf="free" data-i="free">無料</button>
      <button class="chip" data-sf="half" data-i="chip_half">50%OFF以上</button>
    </div>
  </div>
  <div class="shead"><h2 data-i="sale_all">すべてのセール</h2>
    <div class="stabs" id="spSort">
      <button class="on" data-s="new" data-i="sort_new">新着順</button>
      <button data-s="pop" data-i="sort_pop">人気順</button>
      <button data-s="pct" data-i="sort_pct">割引率順</button>
      <button data-s="amount" data-i="sort_amount">割引額順</button>
    </div>
  </div>
  <div class="scount" id="spCount"></div>
  <div class="capgrid" id="spGrid"></div>
  <div class="smore"><button id="spMore" type="button"></button></div>
  <div class="shead"><h2 data-i="sale_big">割引額の大きなセール</h2></div>
  <div id="spSaleList"></div>
  <div class="smore"><button id="spListMore" type="button"></button></div>
</main>
<footer>
  <div data-i="ft_data">データは Boopa（BOOTH Price Tracker for VRChat）の収集基盤による実データです。価格は観測時点のもので、現在のBOOTH上の価格と異なる場合があります。</div>
  <div class="flegal">
    <span data-i="ft_legal">BoopaDB は BOOTH および pixiv株式会社とは関係のない非公式プロジェクトです。表示される時刻はすべて日本時間（JST）です。</span><a class="flink" href="terms.html" data-i="ft_terms">利用規約</a> · <a class="flink" href="privacy.html" data-i="ft_priv">プライバシー</a> · <a class="flink" href="app.html" data-i="ft_app">アプリ</a><br>
    <span data-i="ft_tm">BOOTH は pixiv株式会社の商標です。その他の商標および著作物は、各権利者に帰属します。</span>
  </div>
</footer>
<script>
const P = /*__PAYLOAD__*/;
/*__VISIBILITY__*/
// ==== i18n (sub-pages): BOOTH locales ja / en / ko / zh-Hans / zh-Hant ====
const LANGS = [["ja", "日本語"], ["en", "English"], ["ko", "한국어"], ["zh-Hans", "简体中文"], ["zh-Hant", "繁體中文"]];
const I18N = {
ja: {
  nav_sale: "セール中の商品", nav_feat: "注目の商品", nav_browse: "新着・値下げ", tab_home: "ホーム",
  chip_all: "すべて", chip_lowest: "過去最安値", chip_half: "50%OFF以上", chip_onsale: "セール中",
  sort_pct: "割引率順", sort_amount: "割引額順", sort_cheap: "安い順", sort_pop: "人気順", sort_new: "新着順",
  empty_none: "該当する商品がありません", free: "無料",
  bt_new: "新着", bt_drop: "値下げ", tab_news: "ニュース", tab_ranking: "ランキング",
  ft_data: "データは Boopa（BOOTH Price Tracker for VRChat）の収集基盤による実データです。価格は観測時点のもので、現在のBOOTH上の価格と異なる場合があります。",
  ft_legal: "BoopaDB は BOOTH および pixiv株式会社とは関係のない非公式プロジェクトです。表示される時刻はすべて日本時間（JST）です。",
  ft_terms: "利用規約", ft_priv: "プライバシー", ft_app: "アプリ",
  ft_tm: "BOOTH は pixiv株式会社の商標です。その他の商標および著作物は、各権利者に帰属します。",
  sale_all: "すべてのセール", sale_big: "割引額の大きなセール",
  sale_sub: "現在セール中（推定）<b>{a} 件</b> · 現在無料（推定） <b>{b} 件</b> · 収録期間 {d1} 〜 {d2}",
  sale_count: "セール中 {n} 件（全 {m} 件）",
  news_sub: "収録期間 {d1} 〜 {d2} · 価格が動いた商品の履歴",
  news_empty: "該当する履歴がありません",
  rk_sub: "現在セール中（推定）<b>{n} 件</b> から集計 · {d} 時点",
  rk_amount_title: "割引額ランキング", rk_pct_title: "割引率ランキング", rk_lowest_title: "過去最安値の商品",
  rk_tab_amount: "割引額", rk_tab_pct: "割引率",
  priv_title: "プライバシーポリシー", priv_sub: "BoopaDB のプライバシーポリシー",
  terms_sub: "BoopaDB の利用規約",
  bt_active: "価格変更が活発", bt_rising: "急上昇", pg_rising_sub: "新着30日以内でいいねが急上昇中 · {n} 件", rising_note: "{likes} · +{g}/日", pg_new_sub: "最近収録された商品 · {d} 時点", pg_free_sub: "現在無料の商品（元¥100以上） · {n} 件", pg_drops_sub: "直近3週間の値下げ · {n} 件", pg_active_sub: "直近3週間に価格変更があった商品 · {n} 件", bm_title: "ブックマーク", bm_sub: "このブラウザに保存されたブックマーク · {n} 件", bm_empty: "ブックマークはまだありません。商品ページのブックマークボタンから追加できます。", bm_remove: "解除", bm_search_ph: "名前・ショップ名で検索", bm_nomatch: "一致するブックマークがありません", bm_options: "オプション", al_close: "閉じる", th_toggle: "テーマ切替", al_prev: "前へ", al_next: "次へ", bm_sort_label: "並べ替え条件", bm_sort_added_desc: "追加日（新しい順）", bm_sort_added_asc: "追加日（古い順）", bm_sort_name: "名前", bm_sort_price_asc: "価格（安い順）", bm_sort_price_desc: "価格（高い順）", bm_sort_discount: "割引率", bm_f_discount: "割引", bm_f_all: "すべてのアイテム", bm_f_sale: "セール中のみ", bm_f_50: "50%以上", bm_f_75: "75%以上", bm_f_price_t: "価格", bm_f_free: "無料のみ",  added_on: "{d} 収録", recent3w: "直近3週間で {n} 回の価格変更", dropped_on: "{d} に値下げ", more: "もっと見る", loading: "読み込み中…",
  legal_note: "",
},
en: {
  nav_sale: "On Sale", nav_feat: "Featured", nav_browse: "New & Price Drops", tab_home: "Home",
  chip_all: "All", chip_lowest: "Lowest ever", chip_half: "50% off or more", chip_onsale: "On sale",
  sort_pct: "By discount %", sort_amount: "By amount saved", sort_cheap: "Price: low to high", sort_pop: "Most popular", sort_new: "Newest",
  empty_none: "No matching products", free: "Free",
  bt_new: "New", bt_drop: "Price drops", tab_news: "News", tab_ranking: "Rankings",
  ft_data: "Data is real, collected by Boopa (BOOTH Price Tracker for VRChat). Prices are as observed and may differ from current BOOTH prices.",
  ft_legal: "BoopaDB is an unofficial project, not affiliated with BOOTH or pixiv Inc. All times are Japan Standard Time (JST).",
  ft_terms: "Terms", ft_priv: "Privacy", ft_app: "App",
  ft_tm: "BOOTH is a trademark of pixiv Inc. All other trademarks and works belong to their respective owners.",
  sale_all: "All sales", sale_big: "Biggest savings",
  sale_sub: "On sale now (est.) <b>{a} items</b> · Free now (est.) <b>{b} items</b> · Data from {d1} to {d2}",
  sale_count: "{n} on sale (of {m})",
  news_sub: "Data from {d1} to {d2} · History of products whose price moved",
  news_empty: "No matching history",
  rk_sub: "Aggregated from <b>{n} items</b> on sale now (est.) · as of {d}",
  rk_amount_title: "Biggest savings ranking", rk_pct_title: "Discount rate ranking", rk_lowest_title: "At their lowest price ever",
  rk_tab_amount: "Amount saved", rk_tab_pct: "Discount %",
  priv_title: "Privacy Policy", priv_sub: "Privacy policy of BoopaDB",
  terms_sub: "Terms of use of BoopaDB",
  bt_active: "Frequently repriced", bt_rising: "Trending", pg_rising_sub: "New in the last 30 days, likes rising fast · {n} items", rising_note: "{likes} · +{g}/day", pg_new_sub: "Recently tracked products · as of {d}", pg_free_sub: "Free now (originally ¥100+) · {n} items", pg_drops_sub: "Price drops in the last 3 weeks · {n} items", pg_active_sub: "Products with price changes in the last 3 weeks · {n} items", bm_title: "Bookmarks", bm_sub: "Bookmarks saved in this browser · {n} items", bm_empty: "No bookmarks yet. Add them from the bookmark button on a product page.", bm_remove: "Remove", bm_search_ph: "Search by name or shop", bm_nomatch: "No matching bookmarks.", bm_options: "Options", al_close: "Close", th_toggle: "Toggle theme", al_prev: "Previous", al_next: "Next", bm_sort_label: "Sort by", bm_sort_added_desc: "Date added (newest)", bm_sort_added_asc: "Date added (oldest)", bm_sort_name: "Name", bm_sort_price_asc: "Price (low to high)", bm_sort_price_desc: "Price (high to low)", bm_sort_discount: "Discount", bm_f_discount: "Discount", bm_f_all: "All items", bm_f_sale: "On sale only", bm_f_50: "50% or more", bm_f_75: "75% or more", bm_f_price_t: "Price", bm_f_free: "Free only",  added_on: "Tracked {d}", recent3w: "{n} price changes in the last 3 weeks", dropped_on: "Dropped on {d}", more: "Show more", loading: "Loading…",
  legal_note: "This document is provided in Japanese only; the Japanese version is authoritative.",
},
ko: {
  nav_sale: "할인 중인 상품", nav_feat: "주목 상품", nav_browse: "신착·가격 인하", tab_home: "홈",
  chip_all: "전체", chip_lowest: "역대 최저가", chip_half: "50% 이상 할인", chip_onsale: "할인 중",
  sort_pct: "할인율순", sort_amount: "할인액순", sort_cheap: "가격 낮은순", sort_pop: "인기순", sort_new: "최신순",
  empty_none: "해당하는 상품이 없습니다", free: "무료",
  bt_new: "신착", bt_drop: "가격 인하", tab_news: "뉴스", tab_ranking: "랭킹",
  ft_data: "데이터는 Boopa(BOOTH Price Tracker for VRChat)의 수집 인프라로 모은 실제 데이터입니다. 가격은 관측 시점 기준이며 현재 BOOTH 가격과 다를 수 있습니다.",
  ft_legal: "BoopaDB는 BOOTH 및 pixiv 주식회사와 관계없는 비공식 프로젝트입니다. 모든 시간은 일본 시간(JST)입니다.",
  ft_terms: "이용약관", ft_priv: "개인정보", ft_app: "앱",
  ft_tm: "BOOTH는 pixiv 주식회사의 상표입니다. 그 밖의 상표 및 저작물은 각 권리자에게 귀속합니다.",
  sale_all: "모든 할인", sale_big: "할인액이 큰 상품",
  sale_sub: "현재 할인 중(추정) <b>{a}건</b> · 현재 무료(추정) <b>{b}건</b> · 수집 기간 {d1} 〜 {d2}",
  sale_count: "할인 중 {n}건(전체 {m}건)",
  news_sub: "수집 기간 {d1} 〜 {d2} · 가격이 변동한 상품 이력",
  news_empty: "해당하는 이력이 없습니다",
  rk_sub: "현재 할인 중(추정) <b>{n}건</b>에서 집계 · {d} 기준",
  rk_amount_title: "할인액 랭킹", rk_pct_title: "할인율 랭킹", rk_lowest_title: "역대 최저가 상품",
  rk_tab_amount: "할인액", rk_tab_pct: "할인율",
  priv_title: "개인정보 처리방침", priv_sub: "BoopaDB의 개인정보 처리방침",
  terms_sub: "BoopaDB의 이용약관",
  bt_active: "가격 변동 활발", bt_rising: "급상승", pg_rising_sub: "최근 30일 신착, 좋아요 급상승 · {n}건", rising_note: "{likes} · +{g}/일", pg_new_sub: "최근 수집된 상품 · {d} 기준", pg_free_sub: "현재 무료 상품(기존 ¥100 이상) · {n}건", pg_drops_sub: "최근 3주간 가격 인하 · {n}건", pg_active_sub: "최근 3주간 가격 변동이 있던 상품 · {n}건", bm_title: "북마크", bm_sub: "이 브라우저에 저장된 북마크 · {n}건", bm_empty: "아직 북마크가 없습니다. 상품 페이지의 북마크 버튼으로 추가할 수 있습니다.", bm_remove: "해제", bm_search_ph: "이름·샵 이름으로 검색", bm_nomatch: "일치하는 북마크가 없습니다.", bm_options: "옵션", al_close: "닫기", th_toggle: "테마 전환", al_prev: "이전", al_next: "다음", bm_sort_label: "정렬 조건", bm_sort_added_desc: "추가일(최신순)", bm_sort_added_asc: "추가일(오래된순)", bm_sort_name: "이름", bm_sort_price_asc: "가격(낮은순)", bm_sort_price_desc: "가격(높은순)", bm_sort_discount: "할인율", bm_f_discount: "할인", bm_f_all: "모든 아이템", bm_f_sale: "세일 중만", bm_f_50: "50% 이상", bm_f_75: "75% 이상", bm_f_price_t: "가격", bm_f_free: "무료만",  added_on: "{d} 수집", recent3w: "최근 3주간 가격 변경 {n}회", dropped_on: "{d} 가격 인하", more: "더 보기", loading: "로딩 중…",
  legal_note: "이 문서는 일본어로만 제공되며, 일본어 버전이 정본입니다.",
},
"zh-Hans": {
  nav_sale: "促销中的商品", nav_feat: "精选商品", nav_browse: "新品·降价", tab_home: "首页",
  chip_all: "全部", chip_lowest: "历史最低", chip_half: "5折及以上", chip_onsale: "促销中",
  sort_pct: "按折扣率", sort_amount: "按优惠金额", sort_cheap: "价格从低到高", sort_pop: "按人气", sort_new: "最新上架",
  empty_none: "没有符合条件的商品", free: "免费",
  bt_new: "新品", bt_drop: "降价", tab_news: "动态", tab_ranking: "排行榜",
  ft_data: "数据为 Boopa（BOOTH Price Tracker for VRChat）采集的真实数据。价格为观测时点的价格，可能与 BOOTH 当前价格不同。",
  ft_legal: "BoopaDB 是与 BOOTH 及 pixiv 株式会社无关的非官方项目。所有时间均为日本时间（JST）。",
  ft_terms: "使用条款", ft_priv: "隐私", ft_app: "应用",
  ft_tm: "BOOTH 是 pixiv 株式会社的商标。其他商标及作品归各权利方所有。",
  sale_all: "全部促销", sale_big: "优惠金额大的促销",
  sale_sub: "当前促销中（估计）<b>{a} 件</b> · 当前免费（估计）<b>{b} 件</b> · 收录期间 {d1} 〜 {d2}",
  sale_count: "促销中 {n} 件（共 {m} 件）",
  news_sub: "收录期间 {d1} 〜 {d2} · 价格有变动的商品记录",
  news_empty: "没有符合条件的记录",
  rk_sub: "从当前促销中（估计）的 <b>{n} 件</b>汇总 · 截至 {d}",
  rk_amount_title: "优惠金额排行", rk_pct_title: "折扣率排行", rk_lowest_title: "历史最低价商品",
  rk_tab_amount: "优惠金额", rk_tab_pct: "折扣率",
  priv_title: "隐私政策", priv_sub: "BoopaDB 的隐私政策",
  terms_sub: "BoopaDB 的使用条款",
  bt_active: "价格变动频繁", bt_rising: "急升", pg_rising_sub: "近30天新品，点赞急升 · {n} 件", rising_note: "{likes} · +{g}/日", pg_new_sub: "最近收录的商品 · 截至 {d}", pg_free_sub: "当前免费的商品（原价 ¥100 以上）· {n} 件", pg_drops_sub: "近 3 周的降价 · {n} 件", pg_active_sub: "近 3 周有价格变动的商品 · {n} 件", bm_title: "收藏", bm_sub: "保存在此浏览器中的收藏 · {n} 件", bm_empty: "还没有收藏。可在商品页面点击收藏按钮添加。", bm_remove: "取消", bm_search_ph: "按名称·店铺搜索", bm_nomatch: "没有匹配的收藏。", bm_options: "选项", al_close: "关闭", th_toggle: "切换主题", al_prev: "上一个", al_next: "下一个", bm_sort_label: "排序条件", bm_sort_added_desc: "添加日期（最新）", bm_sort_added_asc: "添加日期（最早）", bm_sort_name: "名称", bm_sort_price_asc: "价格（从低到高）", bm_sort_price_desc: "价格（从高到低）", bm_sort_discount: "折扣", bm_f_discount: "折扣", bm_f_all: "全部商品", bm_f_sale: "仅促销中", bm_f_50: "50% 以上", bm_f_75: "75% 以上", bm_f_price_t: "价格", bm_f_free: "仅免费",  added_on: "{d} 收录", recent3w: "近 3 周价格变动 {n} 次", dropped_on: "{d} 降价", more: "查看更多", loading: "加载中…",
  legal_note: "本文档仅提供日文版，以日文版为准。",
},
"zh-Hant": {
  nav_sale: "促銷中的商品", nav_feat: "精選商品", nav_browse: "新品·降價", tab_home: "首頁",
  chip_all: "全部", chip_lowest: "歷史最低", chip_half: "5折及以上", chip_onsale: "促銷中",
  sort_pct: "按折扣率", sort_amount: "按優惠金額", sort_cheap: "價格從低到高", sort_pop: "按人氣", sort_new: "最新上架",
  empty_none: "沒有符合條件的商品", free: "免費",
  bt_new: "新品", bt_drop: "降價", tab_news: "動態", tab_ranking: "排行榜",
  ft_data: "數據為 Boopa（BOOTH Price Tracker for VRChat）採集的真實數據。價格為觀測時點的價格，可能與 BOOTH 當前價格不同。",
  ft_legal: "BoopaDB 是與 BOOTH 及 pixiv 株式會社無關的非官方項目。所有時間均為日本時間（JST）。",
  ft_terms: "使用條款", ft_priv: "隱私", ft_app: "應用",
  ft_tm: "BOOTH 是 pixiv 株式會社的商標。其他商標及作品歸各權利方所有。",
  sale_all: "全部促銷", sale_big: "優惠金額大的促銷",
  sale_sub: "當前促銷中（估計）<b>{a} 件</b> · 當前免費（估計）<b>{b} 件</b> · 收錄期間 {d1} 〜 {d2}",
  sale_count: "促銷中 {n} 件（共 {m} 件）",
  news_sub: "收錄期間 {d1} 〜 {d2} · 價格有變動的商品記錄",
  news_empty: "沒有符合條件的記錄",
  rk_sub: "從當前促銷中（估計）的 <b>{n} 件</b>彙總 · 截至 {d}",
  rk_amount_title: "優惠金額排行", rk_pct_title: "折扣率排行", rk_lowest_title: "歷史最低價商品",
  rk_tab_amount: "優惠金額", rk_tab_pct: "折扣率",
  priv_title: "隱私政策", priv_sub: "BoopaDB 的隱私政策",
  terms_sub: "BoopaDB 的使用條款",
  bt_active: "價格變動頻繁", bt_rising: "急升", pg_rising_sub: "近30天新品，讚數急升 · {n} 件", rising_note: "{likes} · +{g}/日", pg_new_sub: "最近收錄的商品 · 截至 {d}", pg_free_sub: "目前免費的商品（原價 ¥100 以上）· {n} 件", pg_drops_sub: "近 3 週的降價 · {n} 件", pg_active_sub: "近 3 週有價格變動的商品 · {n} 件", bm_title: "收藏", bm_sub: "儲存在此瀏覽器中的收藏 · {n} 件", bm_empty: "還沒有收藏。可在商品頁面點擊收藏按鈕添加。", bm_remove: "取消", bm_search_ph: "按名稱·店鋪搜尋", bm_nomatch: "沒有符合的收藏。", bm_options: "選項", al_close: "關閉", th_toggle: "切換主題", al_prev: "上一個", al_next: "下一個", bm_sort_label: "排序條件", bm_sort_added_desc: "新增日期（最新）", bm_sort_added_asc: "新增日期（最早）", bm_sort_name: "名稱", bm_sort_price_asc: "價格（由低到高）", bm_sort_price_desc: "價格（由高到低）", bm_sort_discount: "折扣", bm_f_discount: "折扣", bm_f_all: "全部商品", bm_f_sale: "僅促銷中", bm_f_50: "50% 以上", bm_f_75: "75% 以上", bm_f_price_t: "價格", bm_f_free: "僅免費",  added_on: "{d} 收錄", recent3w: "近 3 週價格變動 {n} 次", dropped_on: "{d} 降價", more: "查看更多", loading: "載入中…",
  legal_note: "本文件僅提供日文版，以日文版為準。",
},
};
let LANG = "ja";
try { for (const [o, n] of [["boothdb_bm","boopadb_bm"],["boothdb_hist","boopadb_hist"],["boothdb_lang","boopadb_lang"]]) { const v = localStorage.getItem(o); if (v !== null) { if (localStorage.getItem(n) === null) localStorage.setItem(n, v); localStorage.removeItem(o); } } } catch {}
try { const s = localStorage.getItem("boopadb_lang"); if (s && I18N[s]) LANG = s; else { const n = (navigator.language || "ja").toLowerCase(); if (n.startsWith("en")) LANG = "en"; else if (n.startsWith("ko")) LANG = "ko"; else if (n.startsWith("zh")) LANG = (n.includes("tw") || n.includes("hk") || n.includes("hant")) ? "zh-Hant" : "zh-Hans"; } } catch {}
try { const m = document.querySelector('meta[name="color-scheme"]'); if (m) m.content = document.documentElement.dataset.theme || "dark"; } catch {}
const LOCALES = { ja: "ja-JP", en: "en-US", ko: "ko-KR", "zh-Hans": "zh-CN", "zh-Hant": "zh-TW" };
const LOCALE = LOCALES[LANG];
function tr(k, v){
  let s = (I18N[LANG] && I18N[LANG][k]) ?? I18N.ja[k] ?? k;
  if (v) for (const key in v) s = s.split("{" + key + "}").join(String(v[key]));
  return s;
}
document.documentElement.lang = LANG;
document.querySelectorAll("[data-i]").forEach(el => { el.textContent = tr(el.dataset.i); });
document.querySelectorAll("[data-i-ph]").forEach(el => { el.placeholder = tr(el.dataset.iPh); });
{
  const menu = document.getElementById("langMenu");
  const cur = document.getElementById("langCur");
  if (menu && cur) {
    cur.textContent = LANGS.find(l => l[0] === LANG)[1];
    menu.innerHTML = LANGS.map(([c, n]) => `<button type="button" data-lang="${c}" class="${c === LANG ? "on" : ""}">${n}</button>`).join("");
    menu.querySelectorAll("button").forEach(b => b.onclick = () => {
      try { localStorage.setItem("boopadb_lang", b.dataset.lang); } catch {}
      location.reload();
    });
    document.getElementById("langBtn").onclick = e => { e.stopPropagation(); menu.classList.toggle("open"); };
    document.getElementById("themeBtn").onclick = () => { const n = document.documentElement.dataset.theme === "light" ? "dark" : "light"; document.documentElement.dataset.theme = n; try { localStorage.setItem("boopadb_theme", n); } catch {} const m = document.querySelector('meta[name="color-scheme"]'); if (m) m.content = n; };
    document.addEventListener("click", e => { if (!e.target.closest(".langsw")) menu.classList.remove("open"); });
  }
}

// ==== full (uncapped) lists: fetched lazily; pages fall back to the inlined sample ====
async function loadFull(){
  try { const r = await fetch("lists_full.json"); if (r.ok) return filterVisibleLists(await r.json()); } catch {}
  return null;
}

const PH_ICON = '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="1.5"/><path d="M3 16l5-4 4 3 3-2 6 4"/></svg>';
function imgPh(el, cls){ var s = document.createElement('span'); s.className = cls; s.innerHTML = PH_ICON; el.replaceWith(s); }
const META_BASE = "https://mametarogg.github.io/booth-vrc-price-tracker/meta/";
const _metaCache = new Map();
function fetchMeta(id){ id = String(id); if (hiddenItem(id)) return Promise.resolve(null); if (!_metaCache.has(id)) _metaCache.set(id, fetch(META_BASE + id.slice(0, 3) + "/" + id + ".json").then(r => r.ok ? r.json() : null).catch(() => null).then(meta => acceptVisibilityMeta(id, meta))); return _metaCache.get(id); }
async function fillImgs(){
  if (window._filling) return;
  const els = [...document.querySelectorAll("[data-fill]")];
  if (!els.length) return;
  window._filling = true;
  try {
    await Promise.all(els.map(async el => {
      const id = el.getAttribute("data-fill");
      el.removeAttribute("data-fill");
      const m = await fetchMeta(id).catch(() => null);
      const img = m && (m.image_resized || m.image);
      if (img && el.isConnected) {
        const cls = el.classList.contains("bthph") ? "bthph" : el.classList.contains("pph") ? "pph" : "phcard";
        const im = document.createElement("img");
        if (cls === "bthph") im.className = "bth";
        im.src = img; im.alt = ""; im.loading = "lazy"; im.referrerPolicy = "no-referrer";
        im.onerror = () => imgPh(im, cls);
        el.replaceWith(im);
      }
    }));
  } finally { window._filling = false; if (document.querySelector("[data-fill]")) fillImgs(); }
}
new MutationObserver(() => { if (document.querySelector("[data-fill]")) fillImgs(); }).observe(document.body, {childList: true, subtree: true});
// ---- image stall watchdog: a hung image request never fires load or
// error, leaving a half-painted or blank image forever (seen on iPad).
// A pximg image that stays incomplete 9s+ while near the viewport is
// restarted by swapping in a fresh clone of itself. Elements sharing one
// URL join the same fetch, so a plain restart can rejoin the hung fetch;
// the second restart therefore fetches under a throwaway query key,
// which forces a genuinely new request. At most 2 restarts.
(function startImageWatchdog(){
  if (window.__wdOn) return;
  window.__wdOn = 1;
  const _wdImgs = new Map();
  function wdReg(img){
    if (_wdImgs.has(img)) return;
    const s = img.getAttribute && img.getAttribute("src");
    if (s && s.includes("pximg.net")) _wdImgs.set(img, { t: Date.now(), n: 0 });
  }
  function wdScanAll(root){
    if (!root || root.nodeType !== 1) return;
    if (root.tagName === "IMG") wdReg(root);
    if (root.querySelectorAll) root.querySelectorAll("img").forEach(wdReg);
  }
  setInterval(() => {
    const now = Date.now(), vh = innerHeight || 900;
    _wdImgs.forEach((st, img) => {
      if (!img.isConnected || img.complete) { _wdImgs.delete(img); return; }
      if (now - st.t < 9000 || st.n >= 2) return;
      const r = img.getBoundingClientRect();
      if (r.bottom < -vh || r.top > vh * 2 || r.width === 0) return;
      const c = img.cloneNode(false);
      if (st.n >= 1) {
        const s = c.getAttribute("src");
        if (s && !s.includes("wd=1")) c.setAttribute("src", s + (s.includes("?") ? "&" : "?") + "wd=1");
      }
      st.n++; st.t = now;
      _wdImgs.delete(img); _wdImgs.set(c, st);
      img.replaceWith(c);
    });
  }, 3000);
  new MutationObserver(ms => { for (const m of ms) if (m.addedNodes) m.addedNodes.forEach(wdScanAll); }).observe(document.documentElement, { childList: true, subtree: true });
  wdScanAll(document.body);
})();

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const yen = n => n == null ? "" : "¥" + Number(n).toLocaleString(LOCALE);
const wCls = amt => { if (amt == null) return ""; const n = yen(amt).length; return n >= 10 ? " wxl" : n >= 8 ? " wl" : ""; };
const itemLink = id => `index.html#item-${id}`;
const num = n => Number(n).toLocaleString(LOCALE);

document.title = tr("nav_sale") + " | BoopaDB";
document.getElementById("pgH1").textContent = tr("nav_sale");
document.getElementById("crumbHere").textContent = tr("nav_sale");
document.getElementById("subStats").innerHTML =
  tr("sale_sub", {a: num(P.stats.sale_now), b: num(P.stats.free_now), d1: P.stats.min_date, d2: P.stats.max_date});

const BM_SET = new Set((() => { try { return JSON.parse(localStorage.getItem("boopadb_bm") || "[]").map(b => String(b.id)); } catch { return []; } })());
const BM_FLAG_SVG = '<svg viewBox="0 0 24 24"><path d="M17 3H7a2 2 0 0 0-2 2v16l7-4 7 4V5a2 2 0 0 0-2-2z"/></svg>';
const bmFlag = (id, cls) => BM_SET.has(String(id)) ? `<span class="bmflag${cls ? " " + cls : ""}">${BM_FLAG_SVG}</span>` : "";
function mosaicCell(s, i){
  return `<a class="card mcell m${i + 1}" href="${itemLink(s.id)}">
    <span class="mimg">${s.image ? `<img decoding="async" src="${s.image}" alt="" loading="lazy" onerror="imgPh(this,'phcard')">` : `<span class="phcard" data-fill="${s.id}">${PH_ICON}</span>`}</span>
    ${s.at_lowest ? '<span class="mlab">' + tr("chip_lowest") + '</span>' : (s.cur === 0 ? '<span class="mlab">' + tr("free") + '</span>' : "")}
    ${bmFlag(s.id, (s.at_lowest || s.cur === 0) ? "u2" : "")}
    <span class="scrim"><span class="discst">-${s.pct}%</span><span class="was${wCls(s.base)}"><span class="wasx">${yen(s.base)}</span></span><span class="price">${s.cur === 0 ? tr("free") : yen(s.cur)}</span></span>
  </a>`;
}
function capCard(s){
  if (hiddenItem(s.id)) return "";
  return `<div class="card">
    <a class="capimg" href="${itemLink(s.id)}">${s.image ? `<img decoding="async" src="${s.image}" alt="" loading="lazy" onerror="imgPh(this,'phcard')">` : `<span class="phcard" data-fill="${s.id}">${PH_ICON}</span>`}${bmFlag(s.id)}</a>
    <div class="capbody">
      <div class="capname"><a href="${itemLink(s.id)}">${esc(s.name)}</a></div>
      <div class="capshop">${esc(s.shop || "")}</div>
      <div class="capbtm">${s.at_lowest ? '<div class="lowtx">' + tr("chip_lowest") + '</div>' : ""}<div class="caprow"><span class="bprice"><span class="discst">-${s.pct}%</span><span class="bstack"><span class="was${wCls(s.base)}">${yen(s.base)}</span><span class="price">${s.cur === 0 ? tr("free") : yen(s.cur)}</span></span></span></div></div>
    </div>
  </div>`;
}

const byPct = (a, b) => b.pct - a.pct || (b.base - b.cur) - (a.base - a.cur);
// Featured picks skip gag listings (joke base prices like ¥9,999,999): only
// plausible prices, preferring all-time-low deals. Fill from the full list
// if too few qualify so the mosaic never breaks.
const featPick = arr => {
  const sane = arr.filter(s => s.base > 0 && s.base <= 100000)
    .sort((a, b) => ((b.image ? 1 : 0) - (a.image ? 1 : 0)) || (b.at_lowest - a.at_lowest) || byPct(a, b));
  const rest = arr.filter(s => !sane.includes(s)).sort(byPct);
  return [...sane, ...rest].slice(0, 12);
};
let SALE = P.on_sale || [];
function bindRailBar(railId, barId){
  const rail = document.getElementById(railId), bar = document.getElementById(barId);
  if (!rail || !bar) return () => {};
  const thumb = bar.querySelector("span");
  function update(){
    if (window.innerWidth >= 900) return;
    const sw = rail.scrollWidth, cw = rail.clientWidth;
    if (sw <= cw + 1) { bar.style.display = "none"; return; }
    bar.style.display = "";
    const bw = bar.clientWidth;
    const tw = Math.max(28, bw * cw / sw);
    const maxX = bw - tw;
    thumb.style.width = tw + "px";
    thumb.style.transform = `translateX(${maxX * (rail.scrollLeft / (sw - cw))}px)`;
  }
  rail.addEventListener("scroll", () => requestAnimationFrame(update), { passive: true });
  let dragging = false;
  function seek(e){
    const rect = bar.getBoundingClientRect();
    const sw = rail.scrollWidth, cw = rail.clientWidth;
    if (sw <= cw) return;
    const tw = Math.max(28, rect.width * cw / sw);
    const frac = Math.min(1, Math.max(0, (e.clientX - rect.left - tw / 2) / (rect.width - tw)));
    rail.scrollLeft = frac * (sw - cw);
  }
  bar.addEventListener("pointerdown", e => { dragging = true; bar.setPointerCapture(e.pointerId); seek(e); e.preventDefault(); });
  bar.addEventListener("pointermove", e => { if (dragging) seek(e); });
  bar.addEventListener("pointerup", () => { dragging = false; });
  bar.addEventListener("pointercancel", () => { dragging = false; });
  window.addEventListener("resize", () => setTimeout(update, 160));
  return update;
}
let mosPage = 0, mosPos = 1, mosJumpT = null;
const mosBarUpdate = bindRailBar("spMosVp", "mosBar");
function mosNPages(){ return document.getElementById("spMosaic").querySelectorAll(".mpage:not(.clone)").length; }
function mosApply(anim){
  const track = document.getElementById("spMosaic");
  track.style.transition = anim ? "" : "none";
  track.style.transform = window.innerWidth >= 900 ? `translateX(${-mosPos * 100}%)` : "";
  if (!anim) requestAnimationFrame(() => { track.style.transition = ""; });
}
function mosSync(){
  const n = mosNPages();
  if (!n) return;
  mosPage = ((mosPos - 1) % n + n) % n;
  document.querySelectorAll("#mosDots span").forEach((d, i) => d.classList.toggle("on", i === mosPage));
}
function mosSnap(){
  const n = mosNPages();
  if (mosPos === 0) { mosPos = n; mosApply(false); }
  else if (mosPos === n + 1) { mosPos = 1; mosApply(false); }
}
function mosStep(dir){
  const n = mosNPages();
  if (n <= 1) return;
  clearTimeout(mosJumpT);
  mosSnap();
  mosPos += dir;
  mosApply(true);
  mosSync();
  mosJumpT = setTimeout(mosSnap, 480);
}
function renderMosaic(){
  const items = featPick(visibleItems(SALE));
  const pages = [];
  for (let i = 0; i < items.length; i += 4) pages.push(items.slice(i, i + 4));
  const pageHTML = (pg, pi, clone) => `<div class="mpage${clone ? " clone" : ""}">${pg.map((x, i) => mosaicCell(x, pi * 4 + i)).join("")}</div>`;
  let html = pages.map((pg, pi) => pageHTML(pg, pi, false)).join("");
  if (pages.length > 1) html = pageHTML(pages[pages.length - 1], pages.length - 1, true) + html + pageHTML(pages[0], 0, true);
  document.getElementById("spMosaic").innerHTML = html;
  document.getElementById("mosDots").innerHTML = pages.map((_, i) => `<span data-p="${i}"></span>`).join("");
  const multi = pages.length > 1, pv = document.getElementById("mosPrev"), nx = document.getElementById("mosNext"), dt = document.getElementById("mosDots");
  if (pv) pv.style.display = multi ? "" : "none";
  if (nx) nx.style.display = multi ? "" : "none";
  if (dt) dt.style.display = multi ? "" : "none";
  mosPos = 1; mosPage = 0;
  mosApply(false);
  mosSync();
  mosBarUpdate();
}
document.getElementById("mosPrev").addEventListener("click", () => mosStep(-1));
document.getElementById("mosNext").addEventListener("click", () => mosStep(1));
document.getElementById("mosDots").addEventListener("click", e => { const d = e.target.closest("[data-p]"); if (d) { clearTimeout(mosJumpT); mosSnap(); mosPos = +d.dataset.p + 1; mosApply(true); mosSync(); } });
window.addEventListener("resize", () => mosApply(false));
renderMosaic();

let spSf = "all", spSort = "new";
function spHit(s){
  if (spSf === "lowest") return !!s.at_lowest;
  if (spSf === "free") return s.cur === 0;
  if (spSf === "half") return s.pct >= 50;
  return true;
}
let gridShown = 60;
function renderGrid(){
  let arr = visibleItems(SALE).filter(spHit);
  if (spSort === "new") arr.sort((a, b) => (Number(b.id) - Number(a.id)) || ((b.likes ?? -1) - (a.likes ?? -1)));
  else if (spSort === "pop") arr.sort((a, b) => ((b.likes ?? -1) - (a.likes ?? -1)) || byPct(a, b));
  else if (spSort === "amount") arr.sort((a, b) => (b.base - b.cur) - (a.base - a.cur));
  else arr.sort(byPct);
  document.getElementById("spCount").textContent = tr("sale_count", {n: arr.length, m: SALE.length});
  document.getElementById("spGrid").innerHTML = arr.slice(0, gridShown).map(capCard).join("") || '<div class="sres-empty">' + tr("empty_none") + '</div>';
  document.getElementById("spMore").style.display = arr.length > gridShown ? "" : "none";
}
document.getElementById("spMore").textContent = tr("more");
document.getElementById("spMore").onclick = () => { gridShown += 60; renderGrid(); };
document.getElementById("spChips").addEventListener("click", e => {
  const b = e.target.closest("[data-sf]"); if (!b) return;
  spSf = b.dataset.sf;
  document.querySelectorAll("#spChips .chip").forEach(c => c.classList.toggle("on", c === b));
  gridShown = 60;
  renderGrid();
});
document.getElementById("spSort").addEventListener("click", e => {
  const b = e.target.closest("[data-s]"); if (!b) return;
  spSort = b.dataset.s;
  document.querySelectorAll("#spSort button").forEach(c => c.classList.toggle("on", c === b));
  gridShown = 60;
  renderGrid();
});
renderGrid();
window.addEventListener("boopa:visibility", () => { renderMosaic(); renderGrid(); renderSaleList(); });

// On-sale list in row form, biggest yen discount first. Gag listings
// (joke base prices like ¥9,999,999) are excluded here too; the grid
// above remains the complete, unfiltered data.
let listShown = 60;
function renderSaleList(){
  const arr = visibleItems(SALE)
    .filter(s => s.base > 0 && s.base <= 100000)
    .sort((a, b) => (b.base - b.cur) - (a.base - a.cur) || b.pct - a.pct);
  document.getElementById("spSaleList").innerHTML = arr.slice(0, listShown).map(s =>
  `<a class="brow" href="${itemLink(s.id)}">${s.image ? `<img decoding="async" class="bth" src="${esc(s.image)}" alt="" loading="lazy" onerror="imgPh(this,'bthph')">` : `<span class="bthph" data-fill="${s.id}">${PH_ICON}</span>`}${bmFlag(s.id)}<span class="bmain"><span class="bname">${esc(s.name)}</span><span class="bsub">${esc(s.shop || "")}${s.at_lowest ? " · " + tr("chip_lowest") : ""}</span></span><span class="bprice"><span class="discst">-${s.pct}%</span><span class="bstack"><span class="was${wCls(s.base)}">${yen(s.base)}</span><span class="price">${s.cur === 0 ? tr("free") : yen(s.cur)}</span></span></span></a>`
  ).join("");
  document.getElementById("spListMore").style.display = arr.length > listShown ? "" : "none";
}
document.getElementById("spListMore").textContent = tr("more");
document.getElementById("spListMore").onclick = () => { listShown += 60; renderSaleList(); };
renderSaleList();
loadFull().then(f => { if (f && f.on_sale) { SALE = f.on_sale; renderMosaic(); gridShown = 60; listShown = 60; renderGrid(); renderSaleList(); } if (f && f.stats) document.getElementById("subStats").innerHTML = tr("sale_sub", {a: num(f.stats.sale_now), b: num(f.stats.free_now), d1: f.stats.min_date, d2: f.stats.max_date}); });
</script>
<!-- stats snippet: keep the three copies in sync (build_prototype.py, build_pages_extra.py, build_sale.py) -->
<style>
.site-stats{padding:16px 12px 6px}
.site-stats .ss-box{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:var(--border,#26262c);border:1px solid var(--border,#26262c);border-radius:10px;overflow:hidden;max-width:1080px;margin:0 auto;text-align:left}
.site-stats .ss-item{background:var(--panel,#151517);padding:13px 16px}
.site-stats .ss-num{display:block;font-family:'Orbitron',sans-serif;font-size:22px;font-weight:700;color:#f2f2f5;line-height:1.3;font-variant-numeric:tabular-nums;white-space:nowrap}
.site-stats .ss-label{display:block;font-size:11px;color:var(--faint,#8b8b94);letter-spacing:.05em;margin-top:2px;white-space:nowrap}
.site-stats .ss-live{display:inline-block;width:8px;height:8px;border-radius:50%;background:#7ee787;margin-right:6px;vertical-align:3px;animation:ssPulse 2s ease-out infinite}
@keyframes ssPulse{0%{box-shadow:0 0 0 0 rgba(126,231,135,.45)}70%{box-shadow:0 0 0 7px rgba(126,231,135,0)}100%{box-shadow:0 0 0 0 rgba(126,231,135,0)}}
@media (prefers-reduced-motion: reduce){.site-stats .ss-live{animation:none}}
html[data-theme="light"] .site-stats .ss-num{color:#17171c}
</style>
<script>
(function () {
  var API = "https://nucbox-m7.tailb48431.ts.net";
  var vid = null;
  try {
    vid = localStorage.getItem("boopadb_vid");
    if (!vid) {
      vid = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : "v" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
      localStorage.setItem("boopadb_vid", vid);
    }
  } catch (e) {}
  function post(path) {
    try {
      var body = JSON.stringify({ v: vid });
      if (navigator.sendBeacon) {
        navigator.sendBeacon(API + path, new Blob([body], { type: "text/plain;charset=UTF-8" }));
      } else {
        fetch(API + path, { method: "POST", body: body, headers: { "Content-Type": "text/plain" }, keepalive: true }).catch(function () {});
      }
    } catch (e) {}
  }
  post("/pv");
  function ping() { if (!document.hidden) post("/ping"); }
  ping();
  setInterval(ping, 25000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) ping(); });
  window.addEventListener("pagehide", function () { post("/ping"); });
  function markInstall() {
    try {
      if (localStorage.getItem("boopadb_installed")) return;
      localStorage.setItem("boopadb_installed", "1");
    } catch (e) {}
    post("/install");
  }
  window.addEventListener("appinstalled", markInstall);
  try {
    if ((window.matchMedia && matchMedia("(display-mode: standalone)").matches) || window.navigator.standalone) markInstall();
  } catch (e) {}
  var L = {
    ja: ["総アクセス", "今日", "現在オンライン", "インストール"],
    en: ["Total views", "Today", "Online now", "Installs"],
    ko: ["총 조회수", "오늘", "현재 접속", "설치"],
    "zh-Hans": ["总访问量", "今日", "当前在线", "安装"],
    "zh-Hant": ["總瀏覽量", "今日", "目前線上", "安裝"]
  };
  var lang = "ja";
  try { lang = localStorage.getItem("boopadb_lang") || navigator.language || "ja"; } catch (e) {}
  if (!L[lang]) {
    if (lang.indexOf("zh") === 0) lang = (lang.indexOf("TW") > -1 || lang.indexOf("HK") > -1 || lang.indexOf("Hant") > -1) ? "zh-Hant" : "zh-Hans";
    else lang = L[lang.slice(0, 2)] ? lang.slice(0, 2) : "ja";
  }
  var lab = L[lang] || L.ja;
  function fmt(n) { return Number(n || 0).toLocaleString("en-US"); }
  function item(i, numHtml) {
    return '<div class="ss-item"><span class="ss-num">' + numHtml + '</span><span class="ss-label">' + lab[i] + '</span></div>';
  }
  function render() {
    fetch(API + "/stats").then(function (r) { return r.json(); }).then(function (s) {
      var el = document.getElementById("siteStats");
      if (!el) {
        el = document.createElement("div");
        el.id = "siteStats";
        el.className = "site-stats";
        var f = document.querySelector("footer");
        if (f) f.appendChild(el); else document.body.appendChild(el);
      }
      el.innerHTML = '<div class="ss-box">'
        + item(0, fmt(s.total_pv))
        + item(1, fmt(s.today_pv))
        + item(2, '<span class="ss-live"></span>' + fmt(s.online))
        + item(3, fmt(s.installs))
        + '</div>';
    }).catch(function () {});
  }
  render();
  setTimeout(render, 3000);
  setInterval(render, 20000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) render(); });
})();
</script>
</body>
</html>
"""


SALE_TEMPLATE = SALE_TEMPLATE.replace("/*__VISIBILITY__*/", VISIBILITY_JS)

def build(out_path):
    spec = importlib.util.spec_from_file_location("bp", here / "build_prototype.py")
    bp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bp)
    css = bp.TEMPLATE.split("<style>", 1)[1].split("</style>", 1)[0]
    payload = json.load(open(here / "payload_embedded.json", encoding="utf-8"))
    html = SALE_TEMPLATE.replace("/*__CSS__*/", css)
    html = html.replace("/*__PAYLOAD__*/", json.dumps(payload, ensure_ascii=False))
    out_path.write_text(html, encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size / 1024 / 1024:.1f} MB)")
