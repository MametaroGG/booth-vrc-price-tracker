#!/usr/bin/env python3
"""BoopaDB — ニュース (news.html) and ランキング (ranking.html) templates.
Same construction as build_sale.py: shared CSS extracted from
build_prototype.TEMPLATE, the same payload, product links deep-link to
index.html#item-<id>. Used by build_prod.py."""
from pathlib import Path
from build_prototype import VISIBILITY_JS

here = Path(__file__).parent

_HEAD = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="theme-color" content="#101012"><meta name="color-scheme" content="dark"><script>try{var t=localStorage.getItem("boopadb_theme");if(t!=="dark"&&t!=="light")t=matchMedia("(prefers-color-scheme: light)").matches?"light":"dark";document.documentElement.dataset.theme=t;var m=document.querySelector('meta[name="color-scheme"]');if(m)m.content=t;}catch(e){document.documentElement.dataset.theme="dark"}</script><link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&display=swap" rel="stylesheet"><link rel="preconnect" href="https://booth.pximg.net">
<title>{title} | BoopaDB</title>
<meta property="og:type" content="website">
<meta property="og:site_name" content="BoopaDB">
<meta property="og:title" content="{title} | BoopaDB">
<meta property="og:description" content="BOOTHのVRChat向け商品の価格推移・セール・値下げを追えるデータベース">
<meta property="og:url" content="https://mametarogg.github.io/boopadb/">
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
  html[data-theme="light"] .ptitle{background:radial-gradient(660px 230px at 50% -50px,#e3e3ea,transparent 70%)}
  html[data-theme="light"] .ptitle h1{color:var(--text)}
  html[data-theme="light"] .ptitle p b{color:#4c7a1f}
  html[data-theme="light"] .catbar{background:rgba(244,244,246,.94)}
  html[data-theme="light"] .kind.k-lowest,html[data-theme="light"] .rankno.top{color:#4c7a1f}
  html[data-theme="light"] .kind.k-drop{color:#d64550}
  html[data-theme="light"] .doc a{color:#1c6fd1}
  .stabs{position:relative;display:inline-flex;gap:2px;border-bottom:1px solid var(--border);max-width:100%;overflow-x:auto;overflow-y:hidden;scrollbar-width:none;-webkit-overflow-scrolling:touch}
  .stabs::-webkit-scrollbar{display:none}
  .stabs button{flex:none}
  .stabs button{position:relative;z-index:1;background:none;border:none;color:var(--sub);font-size:13px;padding:7px 13px;cursor:pointer;font-family:inherit;transition:color .2s;border-bottom:2px solid transparent;margin-bottom:-1px;white-space:nowrap}
  .stabs button.on{color:#fff;font-weight:700;border-bottom-color:var(--accent)}
  @media (max-width:899px){.ptitle h1{font-size:31px}}
{extra_css}
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
  <div class="crumb"><a href="index.html" data-i="tab_home">ホーム</a> › <span id="crumbHere">{crumb}</span></div>
  <div class="ptitle">
    <h1 id="pgH1">{h1}</h1>
    <p id="subStats"></p>
  </div>
{body}
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
  ft_terms: "利用規約", ft_priv: "プライバシー",
  ft_tm: "BOOTH は pixiv株式会社の商標です。その他の商標および著作物は、各権利者に帰属します。",
  sale_all: "すべてのセール", sale_big: "割引額の大きなセール",
  sale_sub: "現在セール中（推定）<b>{a} 件</b> · 現在無料（推定） <b>{b} 件</b> · 収録期間 {d1} 〜 {d2}",
  sale_count: "セール中 {n} 件（全 {m} 件）",
  news_sub: "収録期間 {d1} 〜 {d2} · 価格が動いた商品の履歴",
  news_empty: "該当する履歴がありません",
  rk_sub: "現在セール中（推定）<b>{n} 件</b> から集計 · {d} 時点",
  rk_amount_title: "割引額ランキング", rk_pct_title: "割引率ランキング", rk_lowest_title: "過去最安値の商品", rk_pop_title: "人気ランキング", rk_rising_title: "急上昇ランキング", rk_new_title: "新着ランキング",
  rk_tab_amount: "割引額", rk_tab_pct: "割引率", rk_tab_pop: "人気",
  priv_title: "プライバシーポリシー", priv_sub: "BoopaDB のプライバシーポリシー",
  ft_app: "アプリ", app_title: "アプリとして使う", app_sub: "BoopaDB をホーム画面に追加して使う", app_lead: "BoopaDB はアプリとしてインストールできます。ホーム画面から全画面で開けて、ブラウザのバーを気にせず使えます。", app_btn: "アプリをインストール", app_done: "インストール済みです。このままアプリとして使えます。", app_ios_t: "iPhone / iPad", app_ios_s: "共有ボタンから「ホーム画面に追加」を選び、「追加」を押します（Safari・Chrome共通）。", app_and_t: "Android（Chrome）", app_and_s: "右上のメニュー（⋮）から「アプリをインストール」を選びます。上のボタンから直接インストールできる場合もあります。", app_sam_t: "Android（Samsung Internet）", app_sam_s: "メニューから「ページを追加」→「ホーム画面」を選びます。", app_pc_t: "PC（Chrome / Edge）", app_pc_s: "アドレスバー右端のインストールアイコン、またはメニューから「アプリとしてインストール」を選びます。", app_yours: "お使いの環境", app_note: "シークレットモード（プライベートモード）ではホーム画面に追加できません。通常モードで開いてください。",
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
  ft_terms: "Terms", ft_priv: "Privacy",
  ft_tm: "BOOTH is a trademark of pixiv Inc. All other trademarks and works belong to their respective owners.",
  sale_all: "All sales", sale_big: "Biggest savings",
  sale_sub: "On sale now (est.) <b>{a} items</b> · Free now (est.) <b>{b} items</b> · Data from {d1} to {d2}",
  sale_count: "{n} on sale (of {m})",
  news_sub: "Data from {d1} to {d2} · History of products whose price moved",
  news_empty: "No matching history",
  rk_sub: "Aggregated from <b>{n} items</b> on sale now (est.) · as of {d}",
  rk_amount_title: "Biggest savings ranking", rk_pct_title: "Discount rate ranking", rk_lowest_title: "At their lowest price ever", rk_pop_title: "Popularity ranking", rk_rising_title: "Rising ranking", rk_new_title: "Newest ranking",
  rk_tab_amount: "Amount saved", rk_tab_pct: "Discount %", rk_tab_pop: "Popular",
  priv_title: "Privacy Policy", priv_sub: "Privacy policy of BoopaDB",
  ft_app: "App", app_title: "Use as an app", app_sub: "Add BoopaDB to your home screen", app_lead: "BoopaDB can be installed as an app. It opens full-screen from your home screen, without the browser bars.", app_btn: "Install the app", app_done: "Already installed. You are using it as an app.", app_ios_t: "iPhone / iPad", app_ios_s: "Tap the Share button and choose “Add to Home Screen”, then tap “Add” (works in Safari and Chrome).", app_and_t: "Android (Chrome)", app_and_s: "Open the menu (⋮) at the top right and choose “Install app”. The button above may also install it directly.", app_sam_t: "Android (Samsung Internet)", app_sam_s: "From the menu, choose “Add page to” and then “Home screen”.", app_pc_t: "PC (Chrome / Edge)", app_pc_s: "Click the install icon at the right end of the address bar, or choose “Install as app” from the menu.", app_yours: "Your setup", app_note: "You can't add the app in incognito / private mode. Open this page in a regular window.",
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
  ft_terms: "이용약관", ft_priv: "개인정보",
  ft_tm: "BOOTH는 pixiv 주식회사의 상표입니다. 그 밖의 상표 및 저작물은 각 권리자에게 귀속합니다.",
  sale_all: "모든 할인", sale_big: "할인액이 큰 상품",
  sale_sub: "현재 할인 중(추정) <b>{a}건</b> · 현재 무료(추정) <b>{b}건</b> · 수집 기간 {d1} 〜 {d2}",
  sale_count: "할인 중 {n}건(전체 {m}건)",
  news_sub: "수집 기간 {d1} 〜 {d2} · 가격이 변동한 상품 이력",
  news_empty: "해당하는 이력이 없습니다",
  rk_sub: "현재 할인 중(추정) <b>{n}건</b>에서 집계 · {d} 기준",
  rk_amount_title: "할인액 랭킹", rk_pct_title: "할인율 랭킹", rk_lowest_title: "역대 최저가 상품", rk_pop_title: "인기 랭킹", rk_rising_title: "급상승 랭킹", rk_new_title: "신착 랭킹",
  rk_tab_amount: "할인액", rk_tab_pct: "할인율", rk_tab_pop: "인기",
  priv_title: "개인정보 처리방침", priv_sub: "BoopaDB의 개인정보 처리방침",
  ft_app: "앱", app_title: "앱으로 사용하기", app_sub: "BoopaDB를 홈 화면에 추가하기", app_lead: "BoopaDB는 앱으로 설치할 수 있습니다. 홈 화면에서 전체 화면으로 열리며 브라우저 표시줄 없이 사용할 수 있습니다.", app_btn: "앱 설치하기", app_done: "이미 설치되어 있습니다. 앱으로 사용 중입니다.", app_ios_t: "iPhone / iPad", app_ios_s: "공유 버튼에서 「홈 화면에 추가」를 선택하고 「추가」를 누릅니다(Safari·Chrome 공통).", app_and_t: "Android (Chrome)", app_and_s: "오른쪽 위 메뉴(⋮)에서 「앱 설치」를 선택합니다. 위 버튼으로 바로 설치할 수도 있습니다.", app_sam_t: "Android (Samsung Internet)", app_sam_s: "메뉴에서 「페이지 추가」 → 「홈 화면」을 선택합니다.", app_pc_t: "PC (Chrome / Edge)", app_pc_s: "주소 표시줄 오른쪽 끝의 설치 아이콘을 클릭하거나 메뉴에서 「앱으로 설치」를 선택합니다.", app_yours: "사용 중인 환경", app_note: "시크릿 모드(프라이빗 모드)에서는 홈 화면에 추가할 수 없습니다. 일반 모드로 열어 주세요.",
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
  ft_terms: "使用条款", ft_priv: "隐私",
  ft_tm: "BOOTH 是 pixiv 株式会社的商标。其他商标及作品归各权利方所有。",
  sale_all: "全部促销", sale_big: "优惠金额大的促销",
  sale_sub: "当前促销中（估计）<b>{a} 件</b> · 当前免费（估计）<b>{b} 件</b> · 收录期间 {d1} 〜 {d2}",
  sale_count: "促销中 {n} 件（共 {m} 件）",
  news_sub: "收录期间 {d1} 〜 {d2} · 价格有变动的商品记录",
  news_empty: "没有符合条件的记录",
  rk_sub: "从当前促销中（估计）的 <b>{n} 件</b>汇总 · 截至 {d}",
  rk_amount_title: "优惠金额排行", rk_pct_title: "折扣率排行", rk_lowest_title: "历史最低价商品", rk_pop_title: "人气排行", rk_rising_title: "急升排行", rk_new_title: "新品排行",
  rk_tab_amount: "优惠金额", rk_tab_pct: "折扣率", rk_tab_pop: "人气",
  priv_title: "隐私政策", priv_sub: "BoopaDB 的隐私政策",
  ft_app: "应用", app_title: "作为应用使用", app_sub: "将 BoopaDB 添加到主屏幕", app_lead: "BoopaDB 可以安装为应用，从主屏幕以全屏打开，没有浏览器工具栏。", app_btn: "安装应用", app_done: "已安装，正在作为应用使用。", app_ios_t: "iPhone / iPad", app_ios_s: "点击共享按钮，选择“添加到主屏幕”，再点击“添加”（Safari 和 Chrome 均可）。", app_and_t: "Android（Chrome）", app_and_s: "打开右上角菜单（⋮），选择“安装应用”。也可以使用上方按钮直接安装。", app_sam_t: "Android（Samsung Internet）", app_sam_s: "在菜单中选择“添加页面”→“主屏幕”。", app_pc_t: "电脑（Chrome / Edge）", app_pc_s: "点击地址栏右端的安装图标，或在菜单中选择“安装为应用”。", app_yours: "你的环境", app_note: "无痕/隐私模式下无法添加到主屏幕，请在普通模式下打开。",
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
  ft_terms: "使用條款", ft_priv: "隱私",
  ft_tm: "BOOTH 是 pixiv 株式會社的商標。其他商標及作品歸各權利方所有。",
  sale_all: "全部促銷", sale_big: "優惠金額大的促銷",
  sale_sub: "當前促銷中（估計）<b>{a} 件</b> · 當前免費（估計）<b>{b} 件</b> · 收錄期間 {d1} 〜 {d2}",
  sale_count: "促銷中 {n} 件（共 {m} 件）",
  news_sub: "收錄期間 {d1} 〜 {d2} · 價格有變動的商品記錄",
  news_empty: "沒有符合條件的記錄",
  rk_sub: "從當前促銷中（估計）的 <b>{n} 件</b>彙總 · 截至 {d}",
  rk_amount_title: "優惠金額排行", rk_pct_title: "折扣率排行", rk_lowest_title: "歷史最低價商品", rk_pop_title: "人氣排行", rk_rising_title: "急升排行", rk_new_title: "新品排行",
  rk_tab_amount: "優惠金額", rk_tab_pct: "折扣率", rk_tab_pop: "人氣",
  priv_title: "隱私政策", priv_sub: "BoopaDB 的隱私政策",
  ft_app: "應用", app_title: "作為應用使用", app_sub: "將 BoopaDB 新增到主畫面", app_lead: "BoopaDB 可以安裝為應用，從主畫面以全螢幕開啟，沒有瀏覽器工具列。", app_btn: "安裝應用", app_done: "已安裝，正在作為應用使用。", app_ios_t: "iPhone / iPad", app_ios_s: "點選分享按鈕，選擇「新增到主畫面」，再點選「新增」（Safari 與 Chrome 皆可）。", app_and_t: "Android（Chrome）", app_and_s: "開啟右上角選單（⋮），選擇「安裝應用」。也可以使用上方按鈕直接安裝。", app_sam_t: "Android（Samsung Internet）", app_sam_s: "在選單中選擇「新增頁面」→「主畫面」。", app_pc_t: "電腦（Chrome / Edge）", app_pc_s: "點選網址列右端的安裝圖示，或在選單中選擇「安裝為應用」。", app_yours: "你的環境", app_note: "無痕/隱私模式下無法新增到主畫面，請在普通模式下開啟。",
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
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const yen = n => n === 0 ? tr("free") : "¥" + Number(n).toLocaleString(LOCALE);
const wCls = amt => { if (amt == null) return ""; const n = yen(amt).length; return n >= 10 ? " wxl" : n >= 8 ? " wl" : ""; };
const itemLink = id => `index.html#item-${id}`;
const num = n => Number(n).toLocaleString(LOCALE);
{script}
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

_NEWS_CSS = """
  .kind{display:inline-block;font-size:11px;font-weight:800;padding:2px 8px;border-radius:99px;background:#26262c;color:var(--sub);margin-right:7px;vertical-align:1px}
  .kind.k-lowest{color:#c8ec6e}
  .kind.k-drop{color:#ff9d9e}
  .kind.k-sale{color:#ececee}
  .nempty{color:var(--faint);font-size:13px;padding:26px 0;text-align:center}
"""

_NEWS_BODY = """
  <div class="catbar">
    <div class="chips" id="nChips">
      <button class="chip on" data-nf="all" data-i="chip_all">すべて</button>
      <button class="chip" data-nf="drop" data-i="bt_drop">値下げ</button>
      <button class="chip" data-nf="lowest" data-i="chip_lowest">過去最安値</button>
      <button class="chip" data-nf="sale" data-i="chip_onsale">セール中</button>
      <button class="chip" data-nf="new" data-i="bt_new">新着</button>
    </div>
  </div>
  <div id="nFeed"></div>
  <div class="smore"><button id="nMore" type="button"></button></div>
"""

_NEWS_SCRIPT = """
document.title = tr("tab_news") + " | BoopaDB";
document.getElementById("pgH1").textContent = tr("tab_news");
document.getElementById("crumbHere").textContent = tr("tab_news");
document.getElementById("subStats").innerHTML =
  tr("news_sub", {d1: P.stats.min_date, d2: P.stats.max_date});

const BM_SET = new Set((() => { try { return JSON.parse(localStorage.getItem("boopadb_bm") || "[]").map(b => String(b.id)); } catch { return []; } })());
const BM_FLAG_SVG = '<svg viewBox="0 0 24 24"><path d="M17 3H7a2 2 0 0 0-2 2v16l7-4 7 4V5a2 2 0 0 0-2-2z"/></svg>';
const bmFlag = id => BM_SET.has(String(id)) ? `<span class="bmflag">${BM_FLAG_SVG}</span>` : "";

const KIND = { drop: [tr("bt_drop"), "k-drop"], lowest: [tr("chip_lowest"), "k-lowest"], sale: [tr("chip_onsale"), "k-sale"], new: [tr("bt_new"), "k-new"] };
let feed = [];
function buildFeed(D, S, N){
  feed = [];
  const seen = new Set();
  (D || []).forEach(d => {
    feed.push({ id: d.id, name: d.name, shop: d.shop, image: d.image, date: d.date,
      kind: d.at_lowest ? "lowest" : "drop", from: d.from, to: d.to, sale: !!d.sale_event });
    seen.add(d.id + "@" + d.date);
  });
  (S || []).forEach(s => {
    const k = s.id + "@" + s.date;
    if (seen.has(k)) return;
    seen.add(k);
    feed.push({ id: s.id, name: s.name, shop: s.shop, image: s.image, date: s.date, sale: true,
      kind: s.at_lowest ? "lowest" : "sale", from: s.base, to: s.cur, pct: s.pct });
  });
  (N || []).forEach(n => {
    feed.push({ id: n.id, name: n.name, shop: n.shop, image: n.image, date: n.first_date,
      kind: "new", to: n.cur });
  });
  feed.sort((a, b) => b.date.localeCompare(a.date));
}
buildFeed(P.drops, P.on_sale, P.newest);

function cluster(f){
  if (f.kind === "new") return `<span class="bprice"><span class="price">${yen(f.to)}</span></span>`;
  const pct = f.pct != null ? f.pct : (f.from > 0 ? Math.round((1 - f.to / f.from) * 100) : 0);
  // Badge follows the data's is_sale judgment (same as Boopa): sale-start drops get one, repricings do not.
  const badge = f.sale && pct > 0 ? `<span class="discst">-${pct}%</span>` : "";
  return `<span class="bprice">${badge}<span class="bstack"><span class="was${wCls(f.from)}">${yen(f.from)}</span><span class="price">${yen(f.to)}</span></span></span>`;
}
function row(f){
  if (hiddenItem(f.id)) return "";
  const [label, cls] = KIND[f.kind];
  return `<a class="brow" href="${itemLink(f.id)}"><span class="bthw">${f.image ? `<img decoding="async" class="bth" src="${esc(f.image)}" alt="" loading="lazy" onerror="imgPh(this,'bthph')">` : `<span class="bthph" data-fill="${f.id}">${PH_ICON}</span>`}${bmFlag(f.id)}</span><span class="bmain"><span class="bname">${esc(f.name)}</span><span class="bsub"><span class="kind ${cls}">${label}</span>${f.date}${f.shop ? " · " + '<span data-shop="' + esc(f.shop) + '">' + esc(f.shop) + "</span>" : ""}</span></span>${cluster(f)}</a>`;
}
let nf = "all", nShown = 60;
function renderFeed(){
  const arr = visibleItems(feed).filter(f => nf === "all" || f.kind === nf || (nf === "drop" && f.kind === "lowest"));
  document.getElementById("nFeed").innerHTML = arr.slice(0, nShown).map(row).join("") || '<div class="nempty">' + tr("news_empty") + '</div>';
  document.getElementById("nMore").style.display = arr.length > nShown ? "" : "none";
}
document.getElementById("nMore").textContent = tr("more");
document.getElementById("nMore").onclick = () => { nShown += 60; renderFeed(); };
document.getElementById("nChips").addEventListener("click", e => {
  const b = e.target.closest("[data-nf]"); if (!b) return;
  nf = b.dataset.nf;
  document.querySelectorAll("#nChips .chip").forEach(c => c.classList.toggle("on", c === b));
  nShown = 60;
  renderFeed();
});
renderFeed();
loadFull().then(f => { if (f) { buildFeed(f.drops, f.on_sale, f.newest); nShown = 60; renderFeed(); } });
"""

_RANK_CSS = """
  .rankno{flex:none;width:36px;text-align:center;font-size:17px;font-weight:800;color:var(--faint);font-variant-numeric:tabular-nums}
  .rankno.top{color:#c8ec6e}
  @media (max-width:560px){.rankno{width:22px;font-size:14px}}
"""

_RANK_BODY = """
  <div class="shead"><h2 id="rkTitle">割引額ランキング</h2>
    <div class="stabs" id="rkTabs">
      <button class="on" data-rk="amount" data-i="rk_tab_amount">割引額</button>
      <button data-rk="pct" data-i="rk_tab_pct">割引率</button>
      <button data-rk="lowest" data-i="chip_lowest">過去最安値</button>
      <button data-rk="rising" data-i="bt_rising">急上昇</button>
      <button data-rk="new" data-i="bt_new">新着</button>
      <button data-rk="pop" data-i="rk_tab_pop">人気</button>
    </div>
  </div>
  <div id="rkList"></div>
  <div class="smore"><button id="rkMore" type="button"></button></div>
"""

_RANK_SCRIPT = """
document.title = tr("tab_ranking") + " | BoopaDB";
document.getElementById("pgH1").textContent = tr("tab_ranking");
document.getElementById("crumbHere").textContent = tr("tab_ranking");
document.getElementById("subStats").innerHTML =
  tr("rk_sub", {n: num(P.stats.sale_now), d: P.stats.max_date});

const BM_SET = new Set((() => { try { return JSON.parse(localStorage.getItem("boopadb_bm") || "[]").map(b => String(b.id)); } catch { return []; } })());
const BM_FLAG_SVG = '<svg viewBox="0 0 24 24"><path d="M17 3H7a2 2 0 0 0-2 2v16l7-4 7 4V5a2 2 0 0 0-2-2z"/></svg>';
const bmFlag = id => BM_SET.has(String(id)) ? `<span class="bmflag">${BM_FLAG_SVG}</span>` : "";

// Rankings are a curated surface: gag listings with joke base prices
// (¥9,999,999 etc.) are excluded, as in the featured mosaics.
let SALE = P.on_sale || [];
let POP = P.popular || [], RISING = P.rising || [], NEWEST = P.newest || [];
const HEART12 = '<svg class="hico" viewBox="0 0 24 24"><path d="M19.5 12.6 12 20l-7.5-7.4A5 5 0 1 1 12 6.1a5 5 0 1 1 7.5 6.5z"/></svg> ';
const fmtGain = v => { const n = Number(v) || 0; return n >= 10 ? Math.round(n).toLocaleString() : String(Math.round(n * 10) / 10); };
function rkCluster(s){
  const pct = s.base > s.cur ? Math.round((1 - s.cur / s.base) * 100) : 0;
  const badge = s.on_sale && pct > 0 ? `<span class="discst">-${pct}%</span>` : "";
  const stack = s.base > s.cur ? `<span class="bstack"><span class="was${wCls(s.base)}">${yen(s.base)}</span><span class="price">${yen(s.cur)}</span></span>` : `<span class="price">${yen(s.cur)}</span>`;
  return `<span class="bprice">${badge}${stack}</span>`;
}
function rkRow2(s, i, note){
  if (hiddenItem(s.id)) return "";
  const sub = [s.shop ? `<span data-shop="${esc(s.shop)}">${esc(s.shop)}</span>` : "", note || ""].filter(Boolean).join(" · ");
  return `<a class="brow" href="${itemLink(s.id)}"><span class="rankno${i < 3 ? " top" : ""}">${i + 1}</span><span class="bthw">${s.image ? `<img decoding="async" class="bth" src="${esc(s.image)}" alt="" loading="lazy" onerror="imgPh(this,'bthph')">` : `<span class="bthph" data-fill="${s.id}">${PH_ICON}</span>`}${bmFlag(s.id)}</span><span class="bmain"><span class="bname">${esc(s.name)}</span><span class="bsub">${sub}</span></span>${rkCluster(s)}</a>`;
}
const byAmount = (a, b) => (b.base - b.cur) - (a.base - a.cur) || b.pct - a.pct;
const byPct = (a, b) => b.pct - a.pct || (b.base - b.cur) - (a.base - a.cur);
let RK = {};
function rkBuild(){
  const sane = SALE.filter(s => s.base > 0 && s.base <= 100000);
  const saneL = a => (a || []).filter(s => s.base == null || s.base <= 100000);
  RK = {
    amount: { title: tr("rk_amount_title"), arr: [...sane].sort(byAmount) },
    pct: { title: tr("rk_pct_title"), arr: [...sane].sort(byPct) },
    lowest: { title: tr("rk_lowest_title"), arr: sane.filter(s => s.at_lowest).sort(byAmount) },
    rising: { title: tr("rk_rising_title"), arr: saneL(RISING), row: (s, i) => rkRow2(s, i, HEART12 + tr("rising_note", {likes: (s.likes || 0).toLocaleString(), g: fmtGain(s.per_day)})) },
    new: { title: tr("rk_new_title"), arr: saneL(NEWEST), row: (s, i) => rkRow2(s, i, tr("added_on", {d: s.first_date})) },
    pop: { title: tr("rk_pop_title"), arr: saneL(POP), row: (s, i) => rkRow2(s, i, HEART12 + (s.likes || 0).toLocaleString()) }
  };
}
rkBuild();
function rkRow(s, i){
  if (hiddenItem(s.id)) return "";
  return `<a class="brow" href="${itemLink(s.id)}"><span class="rankno${i < 3 ? " top" : ""}">${i + 1}</span><span class="bthw">${s.image ? `<img decoding="async" class="bth" src="${esc(s.image)}" alt="" loading="lazy" onerror="imgPh(this,'bthph')">` : `<span class="bthph" data-fill="${s.id}">${PH_ICON}</span>`}${bmFlag(s.id)}</span><span class="bmain"><span class="bname">${esc(s.name)}</span><span class="bsub">${esc(s.shop || "")}${s.at_lowest ? " · " + tr("chip_lowest") : ""}</span></span><span class="bprice"><span class="discst">-${s.pct}%</span><span class="bstack"><span class="was${wCls(s.base)}">${yen(s.base)}</span><span class="price">${yen(s.cur)}</span></span></span></a>`;
}
let rk = "amount", rkShown = 60;
function renderRk(){
  RK[rk].arr = visibleItems(RK[rk].arr);
  document.getElementById("rkTitle").textContent = RK[rk].title;
  document.getElementById("rkList").innerHTML = RK[rk].arr.slice(0, rkShown).map(RK[rk].row || rkRow).join("");
  document.getElementById("rkMore").style.display = RK[rk].arr.length > rkShown ? "" : "none";
}
document.getElementById("rkMore").textContent = tr("more");
document.getElementById("rkMore").onclick = () => { rkShown += 60; renderRk(); };
document.getElementById("rkTabs").addEventListener("click", e => {
  const b = e.target.closest("[data-rk]"); if (!b) return;
  rk = b.dataset.rk;
  document.querySelectorAll("#rkTabs button").forEach(c => c.classList.toggle("on", c === b));
  rkShown = 60;
  renderRk();
});
renderRk();
loadFull().then(f => { if (!f) return; if (f.on_sale) SALE = f.on_sale; if (f.popular) POP = f.popular; if (f.rising) RISING = f.rising; if (f.newest) NEWEST = f.newest; rkBuild(); rkShown = 60; renderRk(); if (f.stats) document.getElementById("subStats").innerHTML = tr("rk_sub", {n: num(f.stats.sale_now), d: f.stats.max_date}); });
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
"""


def _render(title, crumb, h1, extra_css, body, script, css, payload_json):
    html = _HEAD.replace("{title}", title).replace("{crumb}", crumb).replace("{h1}", h1)
    html = html.replace("{extra_css}", extra_css).replace("{body}", body).replace("{script}", script)
    html = html.replace("/*__CSS__*/", css).replace("/*__PAYLOAD__*/", payload_json).replace("/*__VISIBILITY__*/", VISIBILITY_JS)
    return html


def build_news(out_path, css, payload_json):
    out_path.write_text(_render("ニュース", "ニュース", "ニュース", _NEWS_CSS, _NEWS_BODY, _NEWS_SCRIPT, css, payload_json), encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")


def build_ranking(out_path, css, payload_json):
    out_path.write_text(_render("ランキング", "ランキング", "ランキング", _RANK_CSS, _RANK_BODY, _RANK_SCRIPT, css, payload_json), encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")


_PRIVACY_CSS = """
  .doc{max-width:760px;margin:26px auto 10px;padding:0 4px}
  .doc h3{font-size:16.5px;margin:26px 0 8px;color:var(--text)}
  .doc p,.doc li{font-size:13.5px;line-height:1.85;color:var(--sub)}
  .doc ul{margin:6px 0 6px 18px}
  .doc a{color:#7cc7ff}
  html[data-theme="light"] .doc a{color:#1c6fd1}
.doc a:hover{text-decoration:underline}
  .doc .updated{color:var(--faint);font-size:12px;margin-top:34px}
"""

_PRIVACY_BODY = """
  <div class="doc">
    <h3>このサイトについて</h3>
    <p>BoopaDB（以下「当サイト」）は、BOOTHで販売されているVRChat関連商品の価格履歴を閲覧できる非公式のデータベースサイトです。当サイトは静的なWebページのみで構成されており、アカウント登録機能はありません。当サイトの運営者が、訪問者の個人情報を収集・保存することはありません。</p>
    <h3>ブラウザ内に保存される情報（localStorage）</h3>
    <p>当サイトは、利便性のために次の情報を訪問者のブラウザの localStorage にのみ保存します。これらの情報が当サイトや第三者のサーバーへ送信されることはありません。</p>
    <ul>
      <li>最近見た商品の履歴（最大100件）</li>
      <li>ブックマークした商品</li>
    </ul>
    <p>これらの情報は、ブラウザの設定から当サイトのサイトデータを削除することでいつでも消去できます。当サイトは広告配信やアクセス解析のための Cookie を使用していません。</p>
    <p>アクセス数・インストール数・現在の同時アクセス数の把握のため、運営者のサーバーへ匿名の集計リクエストを送信しています。送信・保存されるのはランダムな端末識別子と集計値のみで、IPアドレスや閲覧したページのURL、個人を特定できる情報は保存されません。</p>
    <p>また、商品ページの「おすすめできる」ボタンを押した場合、その投票が運営者のサーバーに保存されます。保存されるのはランダムな端末識別子と商品IDのみで、二重投票の防止と投票の取り消しのためにのみ使われます。個人を特定できる情報と結び付けることはありません。</p>
    <h3>外部サービスへの接続</h3>
    <p>商品画像は BOOTH の画像サーバー（pximg）から直接読み込まれます。その際、訪問者のブラウザと BOOTH のサーバーとの間で通信が発生し、IPアドレス等の情報の取り扱いには BOOTH／pixiv株式会社のプライバシーポリシーが適用されます。また、当サイトのホスティングには GitHub Pages を利用しており、アクセスに伴う情報の取り扱いには GitHub のプライバシーステートメントが適用されます。</p>
    <h3>掲載データについて</h3>
    <p>当サイトに掲載される価格・商品情報は、公開されている情報を収集したものです。商品画像や商品名の権利は各権利者に帰属します。ショップ運営者の方で、掲載の停止や修正をご希望の場合は、<a href="https://github.com/MametaroGG/boopadb" target="_blank" rel="noopener">GitHub リポジトリ</a>の Issue よりご連絡ください。確認のうえ対応します。</p>
    <h3>お問い合わせ</h3>
    <p>当サイトに関するお問い合わせは、<a href="https://github.com/MametaroGG/boopadb" target="_blank" rel="noopener">GitHub リポジトリ（MametaroGG/boopadb）</a>の Issue よりお願いします。</p>
    <p class="updated">2026年10月23日 制定</p>
  </div>
"""

_PRIVACY_SCRIPT = """
document.title = tr("priv_title") + " | BoopaDB";
document.getElementById("pgH1").textContent = tr("priv_title");
document.getElementById("crumbHere").textContent = tr("ft_priv");
document.getElementById("subStats").textContent = tr("priv_sub");
{ const ln = tr("legal_note"); if (ln) { const d = document.createElement("p"); d.className = "note"; d.textContent = ln; const doc = document.querySelector(".doc"); if (doc) doc.prepend(d); } }
"""


_APP_CSS = """
  .appwrap{max-width:760px;margin:22px auto 10px;padding:0 4px}
  .appicon{width:84px;height:84px;border-radius:20px;display:block;margin:6px 0 14px}
  .applead{font-size:14px;line-height:1.9;color:var(--sub);max-width:560px}
  #appInstallBtn{display:none;margin:18px 0 4px;background:#fc4d50;color:#fff;border:none;font:inherit;font-weight:800;font-size:15px;padding:13px 26px;border-radius:12px;cursor:pointer}
  #appInstallBtn:hover{filter:brightness(1.07)}
  #appDone{display:none;margin:16px 0 4px;font-weight:700;color:#57ab5a;font-size:14.5px}
  .appgrid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:22px}
  @media (max-width:640px){.appgrid{grid-template-columns:1fr}}
  .appcard{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:16px 18px}
  .appcard h3{font-size:14.5px;margin:0 0 7px;color:var(--text)}
  .appcard p{font-size:13px;line-height:1.8;color:var(--sub);margin:0}
  .appcard .yours{display:none;font-size:11px;font-weight:800;color:#fc4d50;letter-spacing:.05em;margin-bottom:6px}
  .appcard.mine{border-color:#fc4d50}
  .appcard.mine .yours{display:block}
"""

_APP_BODY = """
  <div class="appwrap">
    <img decoding="async" class="appicon" src="icon-512.png" alt="BoopaDB">
    <p class="applead" data-i="app_lead"></p>
    <button id="appInstallBtn" type="button" data-i="app_btn"></button>
    <p id="appDone" data-i="app_done"></p>
    <p style="font-size:12.5px;color:var(--faint);margin-top:14px" data-i="app_note"></p>
    <div class="appgrid" id="appGrid">
      <div class="appcard" data-env="ios"><div class="yours" data-i="app_yours"></div><h3 data-i="app_ios_t"></h3><p data-i="app_ios_s"></p></div>
      <div class="appcard" data-env="android"><div class="yours" data-i="app_yours"></div><h3 data-i="app_and_t"></h3><p data-i="app_and_s"></p></div>
      <div class="appcard" data-env="samsung"><div class="yours" data-i="app_yours"></div><h3 data-i="app_sam_t"></h3><p data-i="app_sam_s"></p></div>
      <div class="appcard" data-env="pc"><div class="yours" data-i="app_yours"></div><h3 data-i="app_pc_t"></h3><p data-i="app_pc_s"></p></div>
    </div>
  </div>
"""

_APP_SCRIPT = """
document.title = tr("app_title") + " | BoopaDB";
document.getElementById("pgH1").textContent = tr("app_title");
document.getElementById("crumbHere").textContent = tr("ft_app");
document.getElementById("subStats").textContent = tr("app_sub");
(function () {
  var btn = document.getElementById("appInstallBtn");
  var done = document.getElementById("appDone");
  var standalone = (window.matchMedia && matchMedia("(display-mode: standalone)").matches) || window.navigator.standalone === true;
  if (standalone) { done.style.display = "block"; return; }
  var deferred = null;
  addEventListener("beforeinstallprompt", function (e) { e.preventDefault(); deferred = e; btn.style.display = "inline-block"; });
  addEventListener("appinstalled", function () { btn.style.display = "none"; done.style.display = "block"; });
  btn.addEventListener("click", function () { if (deferred) { deferred.prompt(); } });
  var ua = navigator.userAgent || "";
  var env = /iPhone|iPad|iPod/.test(ua) ? "ios" : /SamsungBrowser/.test(ua) ? "samsung" : /Android/.test(ua) ? "android" : "pc";
  var card = document.querySelector('.appcard[data-env="' + env + '"]');
  if (card) { card.classList.add("mine"); var g = document.getElementById("appGrid"); if (g && card !== g.firstElementChild) g.prepend(card); }
})();
"""


def build_app(out_path, css):
    out_path.write_text(_render("アプリとして使う", "アプリ", "アプリとして使う", _APP_CSS, _APP_BODY, _APP_SCRIPT, css, "{}"), encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")


def build_privacy(out_path, css):
    out_path.write_text(_render("プライバシー", "プライバシー", "プライバシーポリシー", _PRIVACY_CSS, _PRIVACY_BODY, _PRIVACY_SCRIPT, css, "{}"), encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")


_TERMS_BODY = """
  <div class="doc">
    <p>この利用規約（以下「本規約」）は、BoopaDB（以下「当サイト」）の利用条件を定めるものです。当サイトを利用した方は、本規約に同意したものとみなします。</p>
    <h3>第1条（当サイトについて）</h3>
    <p>当サイトは、BOOTHで販売されているVRChat関連商品の価格履歴等の情報を提供する非公式のサービスです。BOOTHおよびpixiv株式会社とは一切関係がありません。商品の購入は BOOTH の公式ページで行ってください。</p>
    <h3>第2条（情報の正確性）</h3>
    <p>当サイトに掲載される価格・在庫等の情報は、公開情報を収集し観測した時点のものであり、その正確性・完全性・最新性を保証するものではありません。実際の販売価格や販売状況は、必ず BOOTH の公式ページでご確認ください。</p>
    <h3>第3条（知的財産権）</h3>
    <p>当サイトに掲載される商品画像・商品名・ショップ名等の権利は、各権利者に帰属します。当サイトのデザイン・プログラムその他のコンテンツの権利は、当サイトの運営者に帰属します。</p>
    <h3>第4条（掲載の停止・修正）</h3>
    <p>権利者またはショップ運営者の方から掲載の停止・修正の申出があった場合、確認のうえ速やかに対応します。申出は<a href="https://github.com/MametaroGG/boopadb" target="_blank" rel="noopener">GitHub リポジトリ</a>の Issue よりご連絡ください。</p>
    <h3>第5条（禁止事項）</h3>
    <ul>
      <li>当サイトまたは関連するサーバー・ネットワークの機能を妨害する行為</li>
      <li>通常の利用範囲を超えた、過度な負荷をかける自動アクセス</li>
      <li>法令または公序良俗に反する行為</li>
      <li>その他、運営者が不適切と判断する行為</li>
    </ul>
    <h3>第6条（サービスの変更・終了）</h3>
    <p>運営者は、事前の予告なく当サイトの内容を変更し、または提供を終了することができます。</p>
    <h3>第7条（免責事項）</h3>
    <p>当サイトの利用または掲載情報の利用によって生じた損害について、運営者に故意または重過失がある場合を除き、運営者は責任を負いません。</p>
    <h3>第8条（本規約の変更）</h3>
    <p>運営者は、必要に応じて本規約を変更できます。変更後の規約は、当サイトに掲載した時点で効力を生じるものとします。</p>
    <h3>第9条（準拠法）</h3>
    <p>本規約の解釈には日本法を適用します。</p>
    <p class="updated">2026年10月23日 制定</p>
  </div>
"""

_TERMS_SCRIPT = """
document.title = tr("ft_terms") + " | BoopaDB";
document.getElementById("pgH1").textContent = tr("ft_terms");
document.getElementById("crumbHere").textContent = tr("ft_terms");
document.getElementById("subStats").textContent = tr("terms_sub");
{ const ln = tr("legal_note"); if (ln) { const d = document.createElement("p"); d.className = "note"; d.textContent = ln; const doc = document.querySelector(".doc"); if (doc) doc.prepend(d); } }
"""


def build_terms(out_path, css):
    out_path.write_text(_render("利用規約", "利用規約", "利用規約", _PRIVACY_CSS, _TERMS_BODY, _TERMS_SCRIPT, css, "{}"), encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")


# ==== Full list pages (new / free / drops / active) + bookmarks ====
_LIST_CSS = """
  .nempty{color:var(--faint);font-size:13px;padding:26px 0;text-align:center}
"""

_LIST_BODY = """
  <div id="pgList"></div>
  <div class="smore"><button id="pgMore" type="button"></button></div>
"""

_ROW_COMMON = """
Object.assign(I18N.ja, {hist_title: "最近見た商品", hist_sub: "このブラウザの閲覧履歴 · {n} 件", hist_empty: "まだ履歴がありません。商品を見るとここに表示されます。", hist_clear: "履歴をすべて消す"});
Object.assign(I18N.en, {hist_title: "Recently viewed", hist_sub: "Browsing history in this browser · {n} items", hist_empty: "No history yet. Products you view will appear here.", hist_clear: "Clear all history"});
Object.assign(I18N.ko, {hist_title: "최근 본 상품", hist_sub: "이 브라우저의 열람 기록 · {n}건", hist_empty: "아직 기록이 없습니다. 상품을 보면 여기에 표시됩니다.", hist_clear: "기록 모두 지우기"});
Object.assign(I18N["zh-Hans"], {hist_title: "最近浏览", hist_sub: "此浏览器中的浏览记录 · {n} 件", hist_empty: "暂无记录。浏览过的商品会显示在这里。", hist_clear: "清除全部记录"});
Object.assign(I18N["zh-Hant"], {hist_title: "最近瀏覽", hist_sub: "此瀏覽器中的瀏覽記錄 · {n} 件", hist_empty: "尚無記錄。瀏覽過的商品會顯示在這裡。", hist_clear: "清除全部記錄"});
const BM_SET = new Set((() => { try { return JSON.parse(localStorage.getItem("boopadb_bm") || "[]").map(b => String(b.id)); } catch { return []; } })());
const BM_FLAG_SVG = '<svg viewBox="0 0 24 24"><path d="M17 3H7a2 2 0 0 0-2 2v16l7-4 7 4V5a2 2 0 0 0-2-2z"/></svg>';
const bmFlag = id => BM_SET.has(String(id)) ? `<span class="bmflag">${BM_FLAG_SVG}</span>` : "";
function clusterCB(cur, base, sale, atLowest){
  const pct = base > cur ? Math.round((1 - cur / base) * 100) : 0;
  const badge = sale && pct > 0 ? `<span class="discst">-${pct}%</span>` : "";
  const stack = base > cur ? `<span class="bstack"><span class="was${wCls(base)}">${yen(base)}</span><span class="price">${yen(cur)}</span></span>` : `<span class="price">${yen(cur)}</span>`;
  return `<span class="bprice">${badge}${stack}</span>`;
}
const HEART12 = '<svg class="hico" viewBox="0 0 24 24"><path d="M19.5 12.6 12 20l-7.5-7.4A5 5 0 1 1 12 6.1a5 5 0 1 1 7.5 6.5z"/></svg> ';
function listRow(x, note, cluster){
  if (hiddenItem(x.id)) return "";
  const sub = [x.shop ? `<span data-shop="${esc(x.shop)}">${esc(x.shop)}</span>` : "", note || ""].filter(Boolean).join(" · ");
  return `<a class="brow" href="${itemLink(x.id)}"><span class="bthw">${x.image ? `<img decoding="async" class="bth" src="${esc(x.image)}" alt="" loading="lazy" onerror="imgPh(this,'bthph')">` : `<span class="bthph" data-fill="${x.id}">${PH_ICON}</span>`}${bmFlag(x.id)}</span><span class="bmain"><span class="bname">${esc(x.name)}</span><span class="bsub">${sub}</span></span>${cluster}</a>`;
}
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
"""

_PG_WIRE = """
document.addEventListener("click", e => {
  const sh = e.target.closest && e.target.closest("[data-shop]");
  if (sh && sh.dataset.shop) { e.preventDefault(); e.stopPropagation(); location.href = "index.html?shop=" + encodeURIComponent(sh.dataset.shop); }
}, true);
let pgShown = 60, pgItems = [], pgRowFn = null;
function pgRender(){
  pgItems = visibleItems(pgItems);
  document.getElementById("pgList").innerHTML = pgItems.slice(0, pgShown).map(pgRowFn).join("") || '<div class="nempty">' + tr("empty_none") + '</div>';
  document.getElementById("pgMore").style.display = pgItems.length > pgShown ? "" : "none";
}
document.getElementById("pgMore").textContent = tr("more");
document.getElementById("pgMore").onclick = () => { pgShown += 60; pgRender(); };
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
"""

_NEWPG_SCRIPT = """
document.title = tr("bt_new") + " | BoopaDB";
document.getElementById("pgH1").textContent = tr("bt_new");
document.getElementById("crumbHere").textContent = tr("bt_new");
document.getElementById("subStats").textContent = tr("pg_new_sub", {d: P.stats.max_date});
""" + _ROW_COMMON + _PG_WIRE + """
pgRowFn = x => listRow(x, tr("added_on", {d: x.first_date}), clusterCB(x.cur, x.base, !!x.on_sale, x.at_lowest));
pgItems = P.newest || [];
pgRender();
loadFull().then(f => { if (f && f.newest) { pgItems = f.newest; pgShown = 60; pgRender(); } });
"""

_FREEPG_SCRIPT = """
document.title = tr("free") + " | BoopaDB";
document.getElementById("pgH1").textContent = tr("free");
document.getElementById("crumbHere").textContent = tr("free");
""" + _ROW_COMMON + _PG_WIRE + """
pgRowFn = x => listRow(x, "", clusterCB(0, x.base, x.on_sale !== false, true));
pgItems = (P.on_sale || []).filter(s => s.cur === 0);
document.getElementById("subStats").textContent = tr("pg_free_sub", {n: pgItems.length});
pgRender();
loadFull().then(f => { if (f && f.free) { pgItems = f.free; pgShown = 60; document.getElementById("subStats").textContent = tr("pg_free_sub", {n: pgItems.length}); pgRender(); } });
"""

_DROPSPG_SCRIPT = """
document.title = tr("bt_drop") + " | BoopaDB";
document.getElementById("pgH1").textContent = tr("bt_drop");
document.getElementById("crumbHere").textContent = tr("bt_drop");
""" + _ROW_COMMON + """
function clusterDrop(x){
  const pct = x.from > x.to ? Math.round((1 - x.to / x.from) * 100) : 0;
  const badge = x.sale_event && pct > 0 ? `<span class="discst">-${pct}%</span>` : "";
  return `<span class="bprice">${badge}<span class="bstack"><span class="was${wCls(x.from)}">${yen(x.from)}</span><span class="price">${yen(x.to)}</span></span></span>`;
}
""" + _PG_WIRE + """
pgRowFn = x => listRow(x, tr("dropped_on", {d: x.date}) + (x.at_lowest ? " · " + tr("chip_lowest") : ""), clusterDrop(x));
pgItems = P.drops || [];
document.getElementById("subStats").textContent = tr("pg_drops_sub", {n: pgItems.length});
pgRender();
loadFull().then(f => { if (f && f.drops) { pgItems = f.drops; pgShown = 60; document.getElementById("subStats").textContent = tr("pg_drops_sub", {n: pgItems.length}); pgRender(); } });
"""

_RISINGPG_SCRIPT = """
document.title = tr("bt_rising") + " | BoopaDB";
document.getElementById("pgH1").textContent = tr("bt_rising");
document.getElementById("crumbHere").textContent = tr("bt_rising");
""" + _ROW_COMMON + """
const fmtGain = v => { const n = Number(v) || 0; return n >= 10 ? Math.round(n).toLocaleString() : String(Math.round(n * 10) / 10); };
""" + _PG_WIRE + """
pgRowFn = x => listRow(x, HEART12 + tr("rising_note", {likes: (x.likes || 0).toLocaleString(), g: fmtGain(x.per_day)}), clusterCB(x.cur, x.base, !!x.on_sale, x.at_lowest));
pgItems = [];
pgRender();
loadFull().then(f => { if (f && f.rising) { pgItems = f.rising; pgShown = 60; document.getElementById("subStats").textContent = tr("pg_rising_sub", {n: pgItems.length}); pgRender(); } });
"""

_BM_CSS = _LIST_CSS + """
  .bmrm{flex:none;background:#26262c;color:var(--sub);border:1px solid var(--border2);border-radius:8px;padding:6px 10px;font-size:12px;cursor:pointer;font-family:inherit;margin-left:10px}
  .bmrm:hover{color:var(--text)}
  .bmrowlink{display:flex;align-items:center;gap:12px;flex:1;min-width:0;color:inherit;text-decoration:none}
  .bmsearch{margin:0 0 10px}
  .bmsearch input{width:100%;box-sizing:border-box;background:#17171a;border:1px solid var(--border2);border-radius:10px;color:var(--text);font-size:14.5px;padding:11px 14px;font-family:inherit;outline:none}
  .bmsearch input:focus{border-color:#3d3d44}
  .bmctl{display:flex;gap:8px;align-items:center;margin:0 0 12px}
  .bmctlbtn{display:inline-flex;align-items:center;gap:8px;background:#17171a;border:1px solid var(--border2);border-radius:8px;color:var(--text);font-size:13px;padding:9px 14px;cursor:pointer;font-family:inherit;white-space:nowrap}
  .bmctlbtn .car{width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;border-top:6px solid var(--sub);flex:none}
  .bmsortdd{margin-left:auto}
  .bmsortlab{color:var(--sub);font-size:13px}
  #bmSortVal{color:var(--text)}
  @media (max-width:560px){.bmsortlab{display:none}}
  .bmdd{position:relative;display:inline-block}
  .bmmenu{position:absolute;right:0;top:calc(100% + 8px);background:#1b1b1f;border:1px solid var(--border2);border-radius:12px;padding:5px;width:218px;box-shadow:0 14px 34px rgba(0,0,0,.5);z-index:300}
  .bmmenu[hidden]{display:none}
  #bmOptPanel{left:0;right:auto}
  .bmmi{display:flex;width:100%;align-items:center;justify-content:space-between;gap:8px;background:none;border:none;color:var(--sub);font-size:13.5px;font-weight:600;padding:8px 10px;border-radius:8px;cursor:pointer;font-family:inherit;text-align:left}
  .bmmi:hover{background:#26262c;color:var(--text)}
  .bmmi.on{color:#fff}
  .bmmi.on::after{content:"✓";color:#c8ec6e;font-weight:800}
  html[data-theme="light"] .ptitle{background:radial-gradient(660px 230px at 50% -50px,#e3e3ea,transparent 70%)}
  html[data-theme="light"] .ptitle p b{color:#4c7a1f}
  html[data-theme="light"] .kind.k-lowest,html[data-theme="light"] .rankno.top{color:#4c7a1f}
  html[data-theme="light"] .kind.k-drop{color:#d64550}
  html[data-theme="light"] .doc a{color:#1c6fd1}
  html[data-theme="light"] .bmrm{background:#e7e7ec}
  html[data-theme="light"] .bmsearch input{background:#ffffff}
  html[data-theme="light"] .bmsearch input:focus{border-color:var(--border2)}
  html[data-theme="light"] .bmctlbtn{background:#ffffff}
  html[data-theme="light"] .bmmenu{background:#ffffff}
  html[data-theme="light"] .bmmi:hover{background:#eef0f2}
  html[data-theme="light"] .bmmi.on{color:var(--text)}
  html[data-theme="light"] .bmmi.on::after{color:#4c7a1f}
  html[data-theme="light"] .bmmenu{box-shadow:0 10px 28px rgba(0,0,0,.16)}
  html[data-theme="light"] .ptitle h1{color:var(--text)}
  html[data-theme="light"] .catbar{background:rgba(244,244,246,.94)}
  .bmsep{height:1px;background:var(--border);margin:5px 4px}
"""

_BM_BODY = """
  <div class="bmsearch"><input id="bmQ" type="search" data-i-ph="bm_search_ph" autocomplete="off"></div>
  <div class="bmctl">
    <span class="bmdd"><button id="bmOptBtn" class="bmctlbtn" type="button"><span data-i="bm_options"></span><span class="car"></span></button><span id="bmOptPanel" class="bmmenu" hidden>
      <button type="button" class="bmmi" data-disc="all"><span data-i="bm_f_all"></span></button>
      <button type="button" class="bmmi" data-disc="sale"><span data-i="bm_f_sale"></span></button>
      <button type="button" class="bmmi" data-disc="50"><span data-i="bm_f_50"></span></button>
      <button type="button" class="bmmi" data-disc="75"><span data-i="bm_f_75"></span></button>
      <span class="bmsep"></span>
      <button type="button" class="bmmi" id="bmFreeRow"><span data-i="bm_f_free"></span></button>
    </span></span>
    <span class="bmdd bmsortdd"><button id="bmSortBtn" class="bmctlbtn" type="button"><span class="bmsortlab" data-i="bm_sort_label"></span><span id="bmSortVal"></span><span class="car"></span></button><span id="bmSortMenu" class="bmmenu" hidden>
      <button type="button" class="bmmi" data-sort="added_desc"><span data-i="bm_sort_added_desc"></span></button>
      <button type="button" class="bmmi" data-sort="added_asc"><span data-i="bm_sort_added_asc"></span></button>
      <button type="button" class="bmmi" data-sort="name"><span data-i="bm_sort_name"></span></button>
      <button type="button" class="bmmi" data-sort="price_asc"><span data-i="bm_sort_price_asc"></span></button>
      <button type="button" class="bmmi" data-sort="price_desc"><span data-i="bm_sort_price_desc"></span></button>
      <button type="button" class="bmmi" data-sort="discount"><span data-i="bm_sort_discount"></span></button>
    </span></span>
  </div>
  <div id="bmList"></div>
"""

_BM_SCRIPT = """
document.title = tr("bm_title") + " | BoopaDB";
document.getElementById("pgH1").textContent = tr("bm_title");
document.getElementById("crumbHere").textContent = tr("bm_title");
""" + _ROW_COMMON + """
const lookup = new Map();
(P.on_sale || []).forEach(s => lookup.set(String(s.id), {cur: s.cur, base: s.base, sale: true, at_lowest: s.at_lowest}));
(P.drops || []).forEach(d => { if (!lookup.has(String(d.id))) lookup.set(String(d.id), {cur: d.to, base: d.from, sale: !!d.on_sale, at_lowest: d.at_lowest}); });
(P.active || []).forEach(a => { if (!lookup.has(String(a.id))) lookup.set(String(a.id), {cur: a.cur, base: a.base, sale: !!a.on_sale, at_lowest: a.at_lowest}); });
(P.newest || []).forEach(a => { if (!lookup.has(String(a.id))) lookup.set(String(a.id), {cur: a.cur, base: a.base, sale: !!a.on_sale, at_lowest: a.at_lowest}); });
function bmLoad(){ try { return JSON.parse(localStorage.getItem("boopadb_bm") || "[]"); } catch { return []; } }
let bmQ = "", bmSort = "added_desc", bmDisc = "all", bmFreeOnly = false;
function bmInfo(b){
  const lk = lookup.get(String(b.id));
  if (lk) return {cur: lk.cur, base: lk.base, sale: !!lk.sale, pct: lk.base > lk.cur ? Math.round((1 - lk.cur / lk.base) * 100) : 0};
  return {cur: b.cur, base: b.cur, sale: false, pct: -1};
}
function bmRender(){
  const all = visibleItems(bmLoad());
  document.getElementById("subStats").textContent = tr("bm_sub", {n: all.length});
  const el = document.getElementById("bmList");
  if (!all.length) { el.innerHTML = '<div class="nempty">' + tr("bm_empty") + '</div>'; return; }
  let bms = all.slice();
  if (bmQ) bms = bms.filter(b => (b.name + " " + (b.shop || "")).toLowerCase().includes(bmQ));
  if (bmDisc !== "all") bms = bms.filter(b => { const i = bmInfo(b); return bmDisc === "sale" ? i.sale : (i.sale && i.pct >= Number(bmDisc)); });
  if (bmFreeOnly) bms = bms.filter(b => bmInfo(b).cur === 0);
  if (bmSort === "added_asc") bms.reverse();
  else if (bmSort === "name") bms.sort((a, b) => a.name.localeCompare(b.name, LOCALE));
  else if (bmSort === "price_asc") bms.sort((a, b) => bmInfo(a).cur - bmInfo(b).cur);
  else if (bmSort === "price_desc") bms.sort((a, b) => bmInfo(b).cur - bmInfo(a).cur);
  else if (bmSort === "discount") bms.sort((a, b) => bmInfo(b).pct - bmInfo(a).pct);
  if (!bms.length) { el.innerHTML = '<div class="nempty">' + tr("bm_nomatch") + '</div>'; return; }
  el.innerHTML = bms.map(b => {
    const cur = lookup.get(String(b.id));
    const price = cur ? clusterCB(cur.cur, cur.base, cur.sale, cur.at_lowest) : `<span class="bprice"><span class="price">${yen(b.cur)}</span></span>`;
    return `<div class="brow"><a class="bmrowlink" href="${itemLink(b.id)}">${b.image ? `<img decoding="async" class="bth" src="${esc(b.image)}" alt="" loading="lazy" onerror="imgPh(this,'bthph')">` : `<span class="bthph" data-fill="${b.id}">${PH_ICON}</span>`}<span class="bmain"><span class="bname">${esc(b.name)}</span><span class="bsub"${b.shop ? ` data-shop="${esc(b.shop)}"` : ""}>${esc(b.shop || "")}</span></span></a>${price}<button class="bmrm" type="button" data-rm="${b.id}">${tr("bm_remove")}</button></div>`;
  }).join("");
  el.querySelectorAll("[data-rm]").forEach(btn => btn.onclick = () => {
    const rest = bmLoad().filter(b => String(b.id) !== btn.dataset.rm);
    try { localStorage.setItem("boopadb_bm", JSON.stringify(rest)); } catch {}
    bmRender();
  });
}
document.getElementById("bmQ").addEventListener("input", e => { bmQ = e.target.value.trim().toLowerCase(); bmRender(); });
const bmOptPanel = document.getElementById("bmOptPanel"), bmOptBtn = document.getElementById("bmOptBtn");
function bmMenuSync(){
  bmOptPanel.querySelectorAll("[data-disc]").forEach(b => b.classList.toggle("on", b.dataset.disc === bmDisc));
  document.getElementById("bmFreeRow").classList.toggle("on", bmFreeOnly);
}
function bmOptSet(open){ bmOptPanel.hidden = !open; }
bmOptBtn.addEventListener("click", e => { e.stopPropagation(); bmMenuSync(); if (typeof bmSortSet === "function") bmSortSet(false); bmOptSet(bmOptPanel.hidden); });
document.addEventListener("click", e => { if (!bmOptPanel.hidden && !bmOptPanel.contains(e.target)) bmOptSet(false); });
document.addEventListener("keydown", e => { if (e.key === "Escape" && !bmOptPanel.hidden) bmOptSet(false); });
bmOptPanel.querySelectorAll("[data-disc]").forEach(b => b.addEventListener("click", () => { bmDisc = b.dataset.disc; bmRender(); bmOptSet(false); }));
document.getElementById("bmFreeRow").addEventListener("click", () => { bmFreeOnly = !bmFreeOnly; bmRender(); bmOptSet(false); });
const BM_SORT_KEYS = { added_desc: "bm_sort_added_desc", added_asc: "bm_sort_added_asc", name: "bm_sort_name", price_asc: "bm_sort_price_asc", price_desc: "bm_sort_price_desc", discount: "bm_sort_discount" };
const bmSortMenu = document.getElementById("bmSortMenu"), bmSortBtn = document.getElementById("bmSortBtn"), bmSortVal = document.getElementById("bmSortVal");
function bmSortSync(){
  bmSortMenu.querySelectorAll("[data-sort]").forEach(b => b.classList.toggle("on", b.dataset.sort === bmSort));
  bmSortVal.textContent = tr(BM_SORT_KEYS[bmSort]);
  bmSortVal.setAttribute("data-i", BM_SORT_KEYS[bmSort]);
}
function bmSortSet(open){ bmSortMenu.hidden = !open; if (open) bmOptSet(false); }
bmSortBtn.addEventListener("click", e => { e.stopPropagation(); bmSortSync(); bmSortSet(bmSortMenu.hidden); });
document.addEventListener("click", e => { if (!bmSortMenu.hidden && !bmSortMenu.contains(e.target)) bmSortSet(false); });
document.addEventListener("keydown", e => { if (e.key === "Escape" && !bmSortMenu.hidden) bmSortSet(false); });
bmSortMenu.querySelectorAll("[data-sort]").forEach(b => b.addEventListener("click", () => { bmSort = b.dataset.sort; bmSortSync(); bmRender(); bmSortSet(false); }));
bmSortSync();
bmRender();
window.addEventListener("boopa:visibility", bmRender);
"""


def build_newpg(out_path, css, payload_json):
    out_path.write_text(_render("新着", "新着", "新着", _LIST_CSS, _LIST_BODY, _NEWPG_SCRIPT, css, payload_json), encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")


def build_freepg(out_path, css, payload_json):
    out_path.write_text(_render("無料", "無料", "無料", _LIST_CSS, _LIST_BODY, _FREEPG_SCRIPT, css, payload_json), encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")


def build_dropspg(out_path, css, payload_json):
    out_path.write_text(_render("値下げ", "値下げ", "値下げ", _LIST_CSS, _LIST_BODY, _DROPSPG_SCRIPT, css, payload_json), encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")


_UPDPG_SCRIPT = """
Object.assign(I18N.ja, {upd_title: "最近のアップデート", upd_newvar: "新バリエーション", pg_upd_sub: "直近30日でバリエーションが増えた商品 · {n} 件"});
Object.assign(I18N.en, {upd_title: "Recent Updates", upd_newvar: "New variation", pg_upd_sub: "Products that gained variations in the last 30 days · {n} items"});
Object.assign(I18N.ko, {upd_title: "최근 업데이트", upd_newvar: "새 배리에이션", pg_upd_sub: "최근 30일간 배리에이션이 추가된 상품 · {n}건"});
Object.assign(I18N["zh-Hans"], {upd_title: "最近更新", upd_newvar: "新增规格", pg_upd_sub: "最近30天新增规格的商品 · {n} 件"});
Object.assign(I18N["zh-Hant"], {upd_title: "最近更新", upd_newvar: "新增規格", pg_upd_sub: "最近30天新增規格的商品 · {n} 件"});
document.title = tr("upd_title") + " | BoopaDB";
document.getElementById("pgH1").textContent = tr("upd_title");
document.getElementById("crumbHere").textContent = tr("upd_title");
""" + _ROW_COMMON + _PG_WIRE + """
function updNote(x){
  const a0 = (x.added || [])[0] || {};
  const more = x.added_n > 1 ? " +" + (x.added_n - 1) : "";
  return tr("upd_newvar") + ": " + (a0.name || "") + more + " · " + tr("added_on", {d: x.date});
}
pgRowFn = x => listRow(x, updNote(x), clusterCB(x.cur, x.base, !!x.on_sale, x.at_lowest));
pgItems = P.updates || [];
function updSub(){ document.getElementById("subStats").textContent = tr("pg_upd_sub", {n: pgItems.length}); }
updSub();
pgRender();
loadFull().then(f => { if (f && f.updates) { pgItems = f.updates; pgShown = 60; updSub(); pgRender(); } });
"""


def build_updpg(out_path, css, payload_json):
    out_path.write_text(_render("最近のアップデート", "最近のアップデート", "最近のアップデート", _LIST_CSS, _LIST_BODY, _UPDPG_SCRIPT, css, payload_json), encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")


_RISING_STUB = """<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><title>BoopaDB</title><meta http-equiv="refresh" content="0; url=rising.html"><script>location.replace("rising.html")</script></head><body></body></html>
"""


def build_risingpg(out_path, stub_path, css, payload_json):
    out_path.write_text(_render("急上昇", "急上昇", "急上昇", _LIST_CSS, _LIST_BODY, _RISINGPG_SCRIPT, css, payload_json), encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")
    stub_path.write_text(_RISING_STUB, encoding="utf-8")
    print(f"wrote {stub_path} (redirect stub)")


_HIST_BODY = """
  <div class="bmctl" id="histCtl"><span style="margin-left:auto"><button id="histClear" class="bmctlbtn" type="button"><span data-i="hist_clear"></span></button></span></div>
  <div id="histList"></div>
"""

_HIST_SCRIPT = """
""" + _ROW_COMMON + """
document.title = tr("hist_title") + " | BoopaDB";
document.getElementById("pgH1").textContent = tr("hist_title");
document.getElementById("crumbHere").textContent = tr("hist_title");
const lookup = new Map();
(P.on_sale || []).forEach(s => lookup.set(String(s.id), {cur: s.cur, base: s.base, sale: true, at_lowest: s.at_lowest}));
(P.drops || []).forEach(d => { if (!lookup.has(String(d.id))) lookup.set(String(d.id), {cur: d.to, base: d.from, sale: !!d.on_sale, at_lowest: d.at_lowest}); });
(P.active || []).forEach(a => { if (!lookup.has(String(a.id))) lookup.set(String(a.id), {cur: a.cur, base: a.base, sale: !!a.on_sale, at_lowest: a.at_lowest}); });
(P.newest || []).forEach(a => { if (!lookup.has(String(a.id))) lookup.set(String(a.id), {cur: a.cur, base: a.base, sale: !!a.on_sale, at_lowest: a.at_lowest}); });
function histLoad(){ try { return JSON.parse(localStorage.getItem("boopadb_hist") || "[]"); } catch { return []; } }
function histRender(){
  const all = visibleItems(histLoad());
  document.getElementById("subStats").textContent = tr("hist_sub", {n: all.length});
  document.getElementById("histCtl").style.display = all.length ? "" : "none";
  const el = document.getElementById("histList");
  if (!all.length) { el.innerHTML = '<div class="nempty">' + tr("hist_empty") + '</div>'; return; }
  el.innerHTML = all.map(h => {
    const lk = lookup.get(String(h.id));
    const price = lk ? clusterCB(lk.cur, lk.base, lk.sale, lk.at_lowest) : `<span class="bprice"><span class="price">${yen(h.cur)}</span></span>`;
    return `<div class="brow"><a class="bmrowlink" href="${itemLink(h.id)}">${h.image ? `<img decoding="async" class="bth" src="${esc(h.image)}" alt="" loading="lazy" onerror="imgPh(this,'bthph')">` : `<span class="bthph" data-fill="${h.id}">${PH_ICON}</span>`}<span class="bmain"><span class="bname">${esc(h.name)}</span><span class="bsub"${h.shop ? ` data-shop="${esc(h.shop)}"` : ""}>${esc(h.shop || "")}</span></span></a>${price}<button class="bmrm" type="button" data-rm="${h.id}">${tr("bm_remove")}</button></div>`;
  }).join("");
  el.querySelectorAll("[data-rm]").forEach(btn => btn.onclick = () => {
    const rest = histLoad().filter(h => String(h.id) !== btn.dataset.rm);
    try { localStorage.setItem("boopadb_hist", JSON.stringify(rest)); } catch {}
    histRender();
  });
}
const hcSpan = document.querySelector("#histClear span"); if (hcSpan) hcSpan.textContent = tr("hist_clear");
document.getElementById("histClear").addEventListener("click", () => { try { localStorage.removeItem("boopadb_hist"); } catch {} histRender(); });
histRender();
window.addEventListener("boopa:visibility", histRender);
"""


def build_history(out_path, css, payload_json):
    out_path.write_text(_render("最近見た商品", "最近見た商品", "最近見た商品", _BM_CSS, _HIST_BODY, _HIST_SCRIPT, css, payload_json), encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")


def build_bookmarks(out_path, css, payload_json):
    out_path.write_text(_render("ブックマーク", "ブックマーク", "ブックマーク", _BM_CSS, _BM_BODY, _BM_SCRIPT, css, payload_json), encoding="utf-8")
    print(f"wrote {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")
