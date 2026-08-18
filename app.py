from __future__ import annotations

import json
import http.cookiejar
import math
import os
import re
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
DATA_DIR = PROJECT_ROOT / "data" / "sec_filings"
DEFAULT_SEC_USER_AGENT = "Valuation Dashboard local-research@example.com"
DEFAULT_EQUITY_COST = 0.10
CURRENT_INFLATION_RATE = 0.035
CURRENT_INFLATION_LABEL = "美国 CPI-U 同比 3.5%（BLS 2026-06，2026-08-09 可得的最新月度数据）"
IMPLIED_NI_FORECAST_YEARS = 10
CAPITAL_RETURN_HISTORY_PERIODS = 5
LINEAR_NI_GROWTH_EXTENSION_YEARS = 10
DEFAULT_NI_FADE_RHO = 0.75
BASELINE_PE_MULTIPLE = 15.0
RHO_MIN = 0.90
RHO_RANGE = 0.08
RHO_SALES_GROWTH_CHANGE_FULL_PENALTY = 0.08
RHO_GROSS_MARGIN_CHANGE_FULL_PENALTY = 0.02
NI_BASE_GROWTH_FLOOR = -0.20
NI_BASE_GROWTH_CEILING = 0.25

sys.path.insert(0, str(SCRIPTS_DIR))

from fetch_sec_filings import (  # noqa: E402
    SecFetchError,
    fetch_json,
    filing_from_block,
    find_company,
    load_all_filing_blocks,
    load_companies,
    load_company_submissions,
    quarter_from_date,
    safe_path_part,
    write_filing,
    write_index,
)


SEC_COMPANY_FACTS_BASE = "https://data.sec.gov/api/xbrl/companyfacts"
YAHOO_QUOTE_SUMMARY_BASE = "https://query1.finance.yahoo.com/v10/finance/quoteSummary"
YAHOO_QUOTE_BASE = "https://query1.finance.yahoo.com/v7/finance/quote"
YAHOO_SEARCH_BASE = "https://query1.finance.yahoo.com/v1/finance/search"
GOOGLE_TRANSLATE_BASE = "https://translate.googleapis.com/translate_a/single"
YAHOO_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36"
)

FINANCIAL_METRICS = [
    {
        "category": "利润表",
        "label": "收入",
        "concepts": [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "SalesRevenueNet",
            "Revenues",
        ],
        "unit": "USD",
        "duration_preference": "shortest",
    },
    {
        "category": "利润表",
        "label": "毛利润",
        "concepts": ["GrossProfit"],
        "unit": "USD",
        "duration_preference": "shortest",
    },
    {
        "category": "利润表",
        "label": "营业利润",
        "concepts": ["OperatingIncomeLoss"],
        "unit": "USD",
        "duration_preference": "shortest",
    },
    {
        "category": "利润表",
        "label": "净利润",
        "concepts": ["NetIncomeLoss"],
        "unit": "USD",
        "duration_preference": "shortest",
    },
    {
        "category": "利润表",
        "label": "摊薄每股收益",
        "concepts": ["EarningsPerShareDiluted"],
        "unit": "USD/shares",
        "duration_preference": "shortest",
    },
    {
        "category": "资产负债表",
        "label": "现金及等价物",
        "concepts": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
        "unit": "USD",
        "duration_preference": "instant",
    },
    {
        "category": "资产负债表",
        "label": "总资产",
        "concepts": ["Assets"],
        "unit": "USD",
        "duration_preference": "instant",
    },
    {
        "category": "资产负债表",
        "label": "总负债",
        "concepts": ["Liabilities"],
        "unit": "USD",
        "duration_preference": "instant",
    },
    {
        "category": "资产负债表",
        "label": "股东权益",
        "concepts": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
        "unit": "USD",
        "duration_preference": "instant",
    },
    {
        "category": "资产负债表",
        "label": "流动资产",
        "concepts": ["AssetsCurrent"],
        "unit": "USD",
        "duration_preference": "instant",
    },
    {
        "category": "资产负债表",
        "label": "流动负债",
        "concepts": ["LiabilitiesCurrent"],
        "unit": "USD",
        "duration_preference": "instant",
    },
    {
        "category": "现金流量表",
        "label": "经营现金流",
        "concepts": ["NetCashProvidedByUsedInOperatingActivities"],
        "unit": "USD",
        "duration_preference": "longest",
    },
    {
        "category": "现金流量表",
        "label": "资本开支",
        "concepts": ["PaymentsToAcquirePropertyPlantAndEquipment"],
        "unit": "USD",
        "duration_preference": "longest",
    },
    {
        "category": "股本数据",
        "label": "普通股股数",
        "concepts": ["EntityCommonStockSharesOutstanding", "CommonStocksIncludingAdditionalPaidInCapital"],
        "unit": "shares",
        "duration_preference": "instant",
    },
]


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>财报读取控制面板</title>
  <style>
    :root {
      --bg: #0b1020;
      --panel: rgba(255, 255, 255, 0.08);
      --panel-strong: rgba(255, 255, 255, 0.12);
      --text: #eef2ff;
      --muted: #a7b0c6;
      --accent: #80d8ff;
      --accent-2: #9cffc7;
      --danger: #ff9a9a;
      --border: rgba(255, 255, 255, 0.14);
      --shadow: 0 24px 80px rgba(0, 0, 0, 0.38);
    }

    * { box-sizing: border-box; }

    [hidden] { display: none !important; }

    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(128, 216, 255, 0.22), transparent 32rem),
        radial-gradient(circle at bottom right, rgba(156, 255, 199, 0.14), transparent 28rem),
        var(--bg);
      min-height: 100vh;
    }

    header {
      padding: 28px 32px 18px;
      border-bottom: 1px solid var(--border);
      background: rgba(11, 16, 32, 0.72);
      backdrop-filter: blur(18px);
      position: sticky;
      top: 0;
      z-index: 5;
    }

    .eyebrow {
      color: var(--accent-2);
      font-size: 13px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      margin-bottom: 8px;
    }

    h1 {
      margin: 0;
      font-size: clamp(28px, 4vw, 46px);
      line-height: 1.08;
    }

    header p {
      max-width: 820px;
      margin: 12px 0 0;
      color: var(--muted);
      line-height: 1.65;
    }

    main {
      display: grid;
      grid-template-columns: 390px minmax(0, 1fr);
      gap: 22px;
      padding: 24px 32px 32px;
    }

    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 24px;
      box-shadow: var(--shadow);
    }

    .controls {
      padding: 22px;
      align-self: start;
      position: sticky;
      top: 146px;
    }

    label {
      display: block;
      margin: 16px 0 8px;
      color: #dbe4ff;
      font-weight: 650;
      font-size: 14px;
    }

    input, select, button {
      width: 100%;
      border-radius: 14px;
      border: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.09);
      color: var(--text);
      padding: 13px 14px;
      font: inherit;
      outline: none;
    }

    select option { color: #101827; }

    input:focus, select:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 4px rgba(128, 216, 255, 0.12);
    }

    .grid-two {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }

    .hint {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
      margin-top: 8px;
    }

    button {
      margin-top: 20px;
      border: 0;
      color: #06111f;
      font-weight: 800;
      cursor: pointer;
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
      transition: transform 0.16s ease, filter 0.16s ease;
    }

    button:hover { transform: translateY(-1px); filter: brightness(1.04); }
    button:disabled { cursor: not-allowed; opacity: 0.68; transform: none; }

    .result {
      min-height: 680px;
      overflow: hidden;
    }

    .result-top {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      padding: 18px;
      border-bottom: 1px solid var(--border);
    }

    .metric {
      background: rgba(255, 255, 255, 0.07);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 14px;
      min-height: 94px;
    }

    .metric span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 8px;
    }

    .metric strong {
      display: block;
      font-size: 17px;
      word-break: break-word;
    }

    .workspace {
      display: flex;
      flex-direction: column;
      min-height: 0;
    }

    .details {
      padding: 16px;
      border-bottom: 1px solid var(--border);
      background: rgba(0, 0, 0, 0.13);
    }

    .details h2, .viewer h2 {
      margin: 0 0 12px;
      font-size: 18px;
    }

    .status {
      margin-top: 16px;
      border-radius: 16px;
      padding: 14px;
      color: var(--muted);
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid var(--border);
      line-height: 1.55;
    }

    .status.error {
      color: #ffe2e2;
      border-color: rgba(255, 154, 154, 0.5);
      background: rgba(255, 154, 154, 0.11);
    }

    .kv {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 12px;
    }

    .kv div {
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      padding-bottom: 10px;
    }

    .kv span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 4px;
    }

    .kv code, .path {
      color: #dff7ff;
      font-family: "Cascadia Code", "SFMono-Regular", Consolas, monospace;
      font-size: 12px;
      word-break: break-all;
    }

    .viewer {
      padding: 16px;
      min-width: 0;
      overflow: auto;
    }

    .extract-panel {
      display: grid;
      gap: 16px;
      margin-bottom: 18px;
    }

    .extract-card {
      border: 1px solid var(--border);
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.06);
      overflow: hidden;
    }

    .extract-card h3 {
      margin: 0;
      padding: 14px 16px;
      font-size: 15px;
      border-bottom: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.05);
    }

    .table-wrap {
      overflow: auto;
      max-height: 260px;
    }

    .chart-box {
      padding: 14px 14px 16px;
    }

    .chart-scroll {
      overflow-x: auto;
      overflow-y: hidden;
      padding-bottom: 4px;
      scrollbar-color: rgba(156, 255, 199, 0.42) rgba(255, 255, 255, 0.08);
    }

    .chart-scroll::-webkit-scrollbar {
      height: 10px;
    }

    .chart-scroll::-webkit-scrollbar-track {
      background: rgba(255, 255, 255, 0.08);
      border-radius: 999px;
    }

    .chart-scroll::-webkit-scrollbar-thumb {
      background: rgba(156, 255, 199, 0.42);
      border-radius: 999px;
    }

    .chart-svg {
      width: 100%;
      height: 300px;
      display: block;
    }

    .chart-scroll .chart-svg {
      width: auto;
      max-width: none;
    }

    .chart-empty {
      color: var(--muted);
      padding: 18px 4px 4px;
      line-height: 1.6;
    }

    .chart-note {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
      margin-top: 8px;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 720px;
      font-size: 13px;
    }

    th, td {
      padding: 10px 12px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.09);
      text-align: left;
      vertical-align: top;
    }

    th {
      color: #cfe3ff;
      font-size: 12px;
      background: rgba(255, 255, 255, 0.04);
      position: sticky;
      top: 0;
      z-index: 1;
    }

    td {
      color: #edf3ff;
    }

    td.muted-cell {
      color: var(--muted);
      font-family: "Cascadia Code", "SFMono-Regular", Consolas, monospace;
      font-size: 12px;
      word-break: break-word;
    }

    .pill {
      display: inline-block;
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 12px;
      border: 1px solid rgba(255, 255, 255, 0.16);
      color: var(--accent-2);
      background: rgba(156, 255, 199, 0.09);
    }

    .pill.missing {
      color: var(--danger);
      background: rgba(255, 154, 154, 0.1);
    }

    .filing-preview {
      min-height: 0;
      background: rgba(0, 0, 0, 0.08);
    }

    .result-split {
      display: grid;
      grid-template-columns: minmax(420px, 1.06fr) minmax(420px, 0.94fr);
      min-height: 760px;
    }

    .preview-column {
      min-width: 0;
      border-right: 1px solid var(--border);
      background: rgba(0, 0, 0, 0.08);
    }

    .data-column {
      min-width: 0;
      max-height: 760px;
      overflow: auto;
      background: rgba(255, 255, 255, 0.02);
    }

    .preview-toolbar {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.06);
      flex-wrap: wrap;
    }

    .tool-group {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .tool-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }

    .tool-button {
      width: auto;
      min-width: 38px;
      height: 34px;
      margin: 0;
      padding: 0 11px;
      border: 1px solid var(--border);
      border-radius: 10px;
      color: var(--text);
      background: rgba(255, 255, 255, 0.09);
      font-weight: 800;
    }

    .tool-button:hover {
      transform: none;
      filter: brightness(1.08);
    }

    .zoom-value, .search-count {
      min-width: 58px;
      color: #dff7ff;
      font-family: "Cascadia Code", "SFMono-Regular", Consolas, monospace;
      font-size: 12px;
      text-align: center;
    }

    .search-input {
      width: min(320px, 42vw);
      height: 34px;
      padding: 7px 10px;
      border-radius: 10px;
    }

    .preview-frame {
      width: 100%;
      height: 704px;
      display: block;
      border: 0;
      background: white;
    }

    .empty {
      display: grid;
      place-items: center;
      min-height: 520px;
      text-align: center;
      color: var(--muted);
      padding: 32px;
    }

    .empty strong {
      color: var(--text);
      display: block;
      font-size: 24px;
      margin-bottom: 10px;
    }

    @media (max-width: 1050px) {
      main, .workspace {
        grid-template-columns: 1fr;
      }
      .controls { position: static; }
      .result-split { grid-template-columns: 1fr; }
      .preview-column { border-right: 0; border-bottom: 1px solid var(--border); }
      .data-column { max-height: none; }
      .details { border-bottom: 1px solid var(--border); }
      .kv { grid-template-columns: 1fr; }
      .result-top { grid-template-columns: 1fr 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div class="eyebrow">财报研究工作台</div>
    <h1>财报读取控制面板</h1>
    <p>输入公司名称或股票代码，选择年份和季度/年报，系统会从 SEC EDGAR 下载对应 10-K 或 10-Q，并把原始财报保存到本地后展示在右侧。</p>
  </header>

  <main>
    <section class="card controls">
      <form id="filing-form">
        <label for="company">公司名称 / 股票代码</label>
        <input id="company" name="company" value="Apple" placeholder="例如 Apple、AAPL、Microsoft、NVDA" required />

        <div class="grid-two">
          <div>
            <label for="year">年份</label>
            <input id="year" name="year" type="number" min="1994" max="2100" value="2026" required />
          </div>
          <div>
            <label for="period">季度 / 年报</label>
            <select id="period" name="period">
              <option value="10-Q:Q1">Q1 季报 / 10-Q</option>
              <option value="10-Q:Q2" selected>Q2 季报 / 10-Q</option>
              <option value="10-Q:Q3">Q3 季报 / 10-Q</option>
              <option value="10-Q:Q4">Q4 季报 / 10-Q（很多公司没有）</option>
              <option value="10-K:FY">全年年报 / 10-K</option>
            </select>
          </div>
        </div>

        <label for="user-agent">SEC User-Agent</label>
        <input id="user-agent" name="user_agent" value="Valuation Dashboard local-research@example.com" placeholder="Your Name your.email@example.com" />
        <div class="hint">可选。SEC 要求请求带 User-Agent；不填时会使用默认本地研究标识。你也可以在环境变量 <code>SEC_USER_AGENT</code> 里设置。</div>

        <label for="continuous-quarter-view">历史对比模式</label>
        <div class="hint">
          <label style="display:flex;align-items:center;gap:10px;margin:0;color:#dbe4ff;font-weight:650;">
            <input id="continuous-quarter-view" name="continuous_quarter_view" type="checkbox" style="width:auto;margin:0;" />
            连续季度视图：显示过去五年所有 Q1/Q2/Q3/FY 节点
          </label>
        </div>

        <button id="submit-button" type="submit">读取并展示财报</button>
      </form>

      <div id="status" class="status">等待输入。建议先用 AAPL / 2026 / Q2 测试。</div>
    </section>

    <section class="card result">
      <div class="result-top">
        <div class="metric"><span>匹配公司</span><strong id="matched-company">—</strong></div>
        <div class="metric"><span>报表类型</span><strong id="form-type">—</strong></div>
        <div class="metric"><span>报告期</span><strong id="report-date">—</strong></div>
        <div class="metric"><span>提交日期</span><strong id="filing-date">—</strong></div>
      </div>

      <div class="result-split">
        <section class="preview-column">
          <div class="filing-preview">
            <div id="preview-tools" class="preview-toolbar" hidden>
              <div class="tool-group">
                <span class="tool-label">缩放</span>
                <button id="zoom-out" class="tool-button" type="button">-</button>
                <span id="zoom-value" class="zoom-value">100%</span>
                <button id="zoom-in" class="tool-button" type="button">+</button>
                <button id="zoom-reset" class="tool-button" type="button">重置</button>
              </div>
              <div class="tool-group">
                <span class="tool-label">搜索</span>
                <input id="preview-search" class="search-input" type="search" placeholder="输入要查找的文字" />
                <button id="search-prev" class="tool-button" type="button">上一个</button>
                <button id="search-next" class="tool-button" type="button">下一个</button>
                <span id="search-count" class="search-count">0/0</span>
              </div>
            </div>
            <div id="empty-state" class="empty">
              <div>
                <strong>财报会显示在这里</strong>
                <p>提交表单后，这里会嵌入本地保存的 SEC 原始 HTML 文件。</p>
              </div>
            </div>
            <iframe id="filing-frame" class="preview-frame" title="SEC filing preview" hidden></iframe>
          </div>
        </section>

        <section class="data-column">
          <div id="workspace" class="workspace" hidden>
            <section class="viewer">
              <div class="extract-panel">
            <div class="extract-card">
              <h3>非财务信息</h3>
              <div class="table-wrap">
                <table>
                  <tbody id="company-profile-rows"></tbody>
                </table>
              </div>
            </div>
            <div class="extract-card">
              <h3>净利润对比</h3>
              <div id="net-income-chart" class="chart-box"></div>
            </div>
            <div class="extract-card">
              <h3>ROE 对比</h3>
              <div id="roa-chart" class="chart-box"></div>
            </div>
            <div class="extract-card">
              <h3>有息负债杠杆检查</h3>
              <div id="leverage-chart" class="chart-box"></div>
            </div>
            <div class="extract-card">
              <h3>动态 PE 与股价走势</h3>
              <div id="pe-growth-review-chart" class="chart-box"></div>
            </div>
            <div class="extract-card">
              <h3>成熟公司：基于收益基准的 PE 隐含净利润路径模型</h3>
              <div class="table-wrap">
                <table>
                  <tbody id="implied-growth-rows"></tbody>
                </table>
              </div>
            </div>
            <div class="extract-card">
              <h3>Altman Z-Score</h3>
              <div id="altman-chart" class="chart-box"></div>
            </div>
              </div>
            </section>
          </div>
        </section>
      </div>
    </section>
  </main>

  <script>
    const form = document.getElementById("filing-form");
    const button = document.getElementById("submit-button");
    const statusBox = document.getElementById("status");
    const emptyState = document.getElementById("empty-state");
    const workspace = document.getElementById("workspace");

    const fields = {
      matchedCompany: document.getElementById("matched-company"),
      formType: document.getElementById("form-type"),
      reportDate: document.getElementById("report-date"),
      filingDate: document.getElementById("filing-date"),
      frame: document.getElementById("filing-frame"),
      previewTools: document.getElementById("preview-tools"),
      zoomOut: document.getElementById("zoom-out"),
      zoomIn: document.getElementById("zoom-in"),
      zoomReset: document.getElementById("zoom-reset"),
      zoomValue: document.getElementById("zoom-value"),
      previewSearch: document.getElementById("preview-search"),
      searchPrev: document.getElementById("search-prev"),
      searchNext: document.getElementById("search-next"),
      searchCount: document.getElementById("search-count"),
      companyProfileRows: document.getElementById("company-profile-rows"),
      netIncomeChart: document.getElementById("net-income-chart"),
      roeChart: document.getElementById("roa-chart"),
      leverageChart: document.getElementById("leverage-chart"),
      altmanChart: document.getElementById("altman-chart"),
      peGrowthReviewChart: document.getElementById("pe-growth-review-chart"),
      impliedGrowthRows: document.getElementById("implied-growth-rows")
    };

    function setStatus(message, isError = false) {
      statusBox.textContent = message;
      statusBox.classList.toggle("error", isError);
    }

    function escapeHtml(value) {
      return String(value ?? "—")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function renderCompanyProfileRows(rows) {
      fields.companyProfileRows.innerHTML = rows.map((row) => `
        <tr>
          <td>${escapeHtml(row.field)}</td>
          <td class="muted-cell">${escapeHtml(row.value)}</td>
        </tr>
      `).join("");
    }

    function renderImpliedGrowthRows(rows) {
      if (!rows || !rows.length) {
        fields.impliedGrowthRows.innerHTML = `<tr><td class="muted-cell">暂无足够数据生成收益基准 PE 隐含净利润路径模型。</td></tr>`;
        return;
      }
      fields.impliedGrowthRows.innerHTML = rows.map((row) => `
        <tr>
          <td>${escapeHtml(row.item)}</td>
          <td class="muted-cell">${escapeHtml(row.value)}</td>
        </tr>
      `).join("");
    }

    function renderLeverageChart(rows) {
      const points = (rows || []).filter((row) => Number.isFinite(Number(row.debt_to_assets_percent)));
      if (!points.length) {
        fields.leverageChart.innerHTML = `<div class="chart-empty">暂无足够数据生成有息负债/总资产趋势图。</div>`;
        return;
      }

      const scale = buildTimeScale(points, { fixedWidth: 720, fixedHeight: 320 });
      const { width, height, margin, plotHeight, xAtMonth } = scale;
      const values = points.map((row) => Number(row.debt_to_assets_percent));
      const maxValue = Math.max(80, Math.max(...values) * 1.15);
      const yMin = 0;
      const yMax = Math.ceil(maxValue / 10) * 10;
      const ySpan = yMax - yMin || 1;
      const yAt = (value) => margin.top + ((yMax - value) / ySpan) * plotHeight;
      const band = (from, to, fill, label) => {
        const yTop = yAt(Math.min(to, yMax));
        const yBottom = yAt(Math.max(from, yMin));
        if (to <= yMin || from >= yMax) return "";
        return `
          <rect x="${margin.left}" y="${yTop.toFixed(1)}" width="${(width - margin.left - margin.right).toFixed(1)}" height="${Math.max(0, yBottom - yTop).toFixed(1)}" fill="${fill}" />
          <text x="${(width - margin.right - 6).toFixed(1)}" y="${(yTop + 14).toFixed(1)}" text-anchor="end" fill="rgba(223,247,255,0.72)" font-size="10">${label}</text>
        `;
      };
      const bands = [
        band(0, 20, "rgba(156,255,199,0.08)", "低 <20%"),
        band(20, 40, "rgba(128,216,255,0.08)", "中 20%-40%"),
        band(40, 60, "rgba(255,211,106,0.09)", "高 40%-60%"),
        band(60, yMax, "rgba(255,143,168,0.10)", "超高 >60%")
      ].join("");
      const axis = renderYAxisTicks({
        ticks: fiveTicks(yMin, yMax),
        yAt,
        margin,
        width,
        right: margin.right,
        formatter: (value) => `${value.toFixed(0)}%`
      });
      const yearAxis = renderYearAxis(scale);
      const path = points.map((row, index) => {
        const x = xAtMonth(row.month);
        return `${index === 0 ? "M" : "L"} ${x.toFixed(1)} ${yAt(Number(row.debt_to_assets_percent)).toFixed(1)}`;
      }).join(" ");
      const dots = points.map((row) => {
        const x = xAtMonth(row.month);
        const y = yAt(Number(row.debt_to_assets_percent));
        return `
          <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" fill="#9cffc7" stroke="#102018" stroke-width="2">
            <title>${escapeHtml(row.period_label || row.month)} | 有息负债/总资产 ${formatPercent(row.debt_to_assets_percent)} | ${escapeHtml(row.debt_concepts || "")}</title>
          </circle>
        `;
      }).join("");
      const ticks = points.map((row) => `
        <line x1="${xAtMonth(row.month).toFixed(1)}" y1="${height - margin.bottom}" x2="${xAtMonth(row.month).toFixed(1)}" y2="${(height - margin.bottom + 5).toFixed(1)}" stroke="rgba(255,255,255,0.14)" />
      `).join("");

      fields.leverageChart.innerHTML = `
        <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="有息负债除以总资产趋势图">
          ${bands}
          <line x1="${margin.left}" y1="${height - margin.bottom}" x2="${width - margin.right}" y2="${height - margin.bottom}" stroke="rgba(255,255,255,0.18)" />
          <line x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}" stroke="rgba(255,255,255,0.18)" />
          ${axis}
          ${yearAxis}
          ${ticks}
          ${path ? `<path d="${path}" fill="none" stroke="#9cffc7" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" />` : ""}
          ${dots}
          <text x="${margin.left}" y="18" fill="#9cffc7" font-size="12">有息负债 / 总资产</text>
          <text x="${width - margin.right}" y="18" text-anchor="end" fill="#dff7ff" font-size="12">${points[0].month} 至 ${points[points.length - 1].month}</text>
        </svg>
        <div class="chart-note">按财报节点展示有息负债/总资产。分区为经验阈值：低 <20%，中 20%-40%，高 40%-60%，超高 >60%；实际判断仍应结合行业和现金流覆盖能力。</div>
      `;
    }

    function renderAltmanChart(rows) {
      const points = (rows || []).filter((row) => Number.isFinite(Number(row.z_score)));
      if (!points.length) {
        fields.altmanChart.innerHTML = `<div class="chart-empty">暂无足够数据生成 Altman Z-Score 趋势图。</div>`;
        return;
      }

      const scale = buildTimeScale(points, { fixedWidth: 720, fixedHeight: 320 });
      const { width, height, margin, plotHeight, xAtMonth } = scale;
      const values = points.map((row) => Number(row.z_score));
      const yMin = Math.min(0, Math.floor(Math.min(...values) - 0.5));
      const yMax = Math.max(5, Math.ceil(Math.max(...values) + 0.5));
      const ySpan = yMax - yMin || 1;
      const yAt = (value) => margin.top + ((yMax - value) / ySpan) * plotHeight;
      const band = (from, to, fill, label) => {
        if (to <= yMin || from >= yMax) return "";
        const yTop = yAt(Math.min(to, yMax));
        const yBottom = yAt(Math.max(from, yMin));
        return `
          <rect x="${margin.left}" y="${yTop.toFixed(1)}" width="${(width - margin.left - margin.right).toFixed(1)}" height="${Math.max(0, yBottom - yTop).toFixed(1)}" fill="${fill}" />
          <text x="${(width - margin.right - 6).toFixed(1)}" y="${(yTop + 14).toFixed(1)}" text-anchor="end" fill="rgba(223,247,255,0.72)" font-size="10">${label}</text>
        `;
      };
      const bands = [
        band(yMin, 1.81, "rgba(255,143,168,0.11)", "Distress <1.81"),
        band(1.81, 2.99, "rgba(255,211,106,0.10)", "Grey 1.81-2.99"),
        band(2.99, yMax, "rgba(156,255,199,0.08)", "Safe >2.99")
      ].join("");
      const axis = renderYAxisTicks({
        ticks: fiveTicks(yMin, yMax),
        yAt,
        margin,
        width,
        right: margin.right,
        formatter: (value) => `${value.toFixed(1)}`
      });
      const yearAxis = renderYearAxis(scale);
      const path = points.map((row, index) => {
        const x = xAtMonth(row.month);
        return `${index === 0 ? "M" : "L"} ${x.toFixed(1)} ${yAt(Number(row.z_score)).toFixed(1)}`;
      }).join(" ");
      const ticks = points.map((row) => `
        <line x1="${xAtMonth(row.month).toFixed(1)}" y1="${height - margin.bottom}" x2="${xAtMonth(row.month).toFixed(1)}" y2="${(height - margin.bottom + 5).toFixed(1)}" stroke="rgba(255,255,255,0.14)" />
      `).join("");
      const dots = points.map((row) => {
        const x = xAtMonth(row.month);
        const y = yAt(Number(row.z_score));
        return `
          <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" fill="#9cffc7" stroke="#102018" stroke-width="2">
            <title>${escapeHtml(row.period_label || row.month)} | Altman Z ${Number(row.z_score).toFixed(2)} | X1 ${Number(row.x1).toFixed(2)}, X2 ${Number(row.x2).toFixed(2)}, X3 ${Number(row.x3).toFixed(2)}, X4 ${Number(row.x4).toFixed(2)}, X5 ${Number(row.x5).toFixed(2)}</title>
          </circle>
        `;
      }).join("");

      fields.altmanChart.innerHTML = `
        <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Altman Z-Score 趋势图">
          ${bands}
          <line x1="${margin.left}" y1="${height - margin.bottom}" x2="${width - margin.right}" y2="${height - margin.bottom}" stroke="rgba(255,255,255,0.18)" />
          <line x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}" stroke="rgba(255,255,255,0.18)" />
          ${axis}
          ${yearAxis}
          ${ticks}
          ${path ? `<path d="${path}" fill="none" stroke="#9cffc7" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" />` : ""}
          ${dots}
          <text x="${margin.left}" y="18" fill="#9cffc7" font-size="12">Z = 1.2X1 + 1.4X2 + 3.3X3 + 0.6X4 + X5</text>
          <text x="${width - margin.right}" y="18" text-anchor="end" fill="#dff7ff" font-size="12">${points[0].month} 至 ${points[points.length - 1].month}</text>
        </svg>
        <div class="chart-note">Altman 原始上市公司 Z-score：X1=营运资本/总资产，X2=留存收益/总资产，X3=EBIT/总资产，X4=市值/总负债，X5=收入/总资产。分区：Distress <1.81，Grey 1.81-2.99，Safe >2.99；该模型最初面向上市制造业，非金融/科技公司使用时应作为压力筛查而非信用结论。</div>
      `;
    }

    function renderGenericRows(target, rows, columns) {
      target.innerHTML = rows.map((row) => `
        <tr>
          ${columns.map((column) => `<td class="muted-cell">${escapeHtml(row[column])}</td>`).join("")}
        </tr>
      `).join("");
    }

    function formatPercent(value) {
      return value === null || value === undefined ? "—" : `${Number(value).toFixed(1)}%`;
    }

    function monthIndex(month) {
      const match = String(month || "").match(/^(\d{4})-(\d{2})$/);
      if (!match) return null;
      return Number(match[1]) * 12 + Number(match[2]) - 1;
    }

    function monthFromIndex(index) {
      const year = Math.floor(index / 12);
      const month = (index % 12) + 1;
      return `${year}-${String(month).padStart(2, "0")}`;
    }

    function buildTimeScale(points, options = {}) {
      const monthIndexes = points
        .map((row) => monthIndex(row.month))
        .filter((value) => Number.isFinite(value));
      const startMonth = Math.min(...monthIndexes);
      const endMonth = Math.max(...monthIndexes);
      const monthSpan = Math.max(1, endMonth - startMonth);
      const width = options.fixedWidth || Math.max(720, 128 + (monthSpan + 1) * 18);
      const height = options.fixedHeight || 330;
      const margin = options.margin || { top: 30, right: 36, bottom: 74, left: 64 };
      const plotWidth = width - margin.left - margin.right;
      const xAtMonth = (month) => {
        const index = monthIndex(month);
        if (!Number.isFinite(index)) return margin.left;
        return margin.left + ((index - startMonth) / monthSpan) * plotWidth;
      };
      return { startMonth, endMonth, width, height, margin, plotWidth, plotHeight: height - margin.top - margin.bottom, xAtMonth };
    }

    function renderYearAxis(scale) {
      const startYear = Math.floor(scale.startMonth / 12);
      const endYear = Math.floor(scale.endMonth / 12);
      const ticks = [];
      for (let year = startYear; year <= endYear; year += 1) {
        const january = year * 12;
        const tickMonth = Math.min(Math.max(january, scale.startMonth), scale.endMonth);
        const x = scale.xAtMonth(monthFromIndex(tickMonth));
        ticks.push(`
          <line x1="${x.toFixed(1)}" y1="${scale.height - scale.margin.bottom}" x2="${x.toFixed(1)}" y2="${(scale.height - scale.margin.bottom + 5).toFixed(1)}" stroke="rgba(255,255,255,0.24)" />
          <text x="${x.toFixed(1)}" y="${scale.height - 36}" text-anchor="middle" fill="#a7b0c6" font-size="11">${year}</text>
        `);
      }
      return ticks.join("");
    }

    function renderYAxisTicks({ ticks, yAt, margin, width, right, formatter }) {
      return ticks.map((tick) => {
        const y = yAt(tick);
        return `
          <line x1="${margin.left}" y1="${y.toFixed(1)}" x2="${width - right}" y2="${y.toFixed(1)}" stroke="rgba(255,255,255,0.08)" />
          <text x="${(margin.left - 8).toFixed(1)}" y="${(y + 4).toFixed(1)}" text-anchor="end" fill="#a7b0c6" font-size="10">${escapeHtml(formatter(tick))}</text>
        `;
      }).join("");
    }

    function renderRightYAxisTicks({ ticks, yAt, margin, width, formatter }) {
      return ticks.map((tick) => {
        const y = yAt(tick);
        return `
          <text x="${(width - margin.right + 8).toFixed(1)}" y="${(y + 4).toFixed(1)}" text-anchor="start" fill="#80d8ff" font-size="10">${escapeHtml(formatter(tick))}</text>
        `;
      }).join("");
    }

    function fiveTicks(minValue, maxValue) {
      const span = maxValue - minValue || 1;
      return [0, 0.25, 0.5, 0.75, 1].map((ratio) => minValue + span * ratio);
    }

    function renderComparisonChart(target, rows, config) {
      const points = (rows || []).filter((row) => Number.isFinite(Number(row.raw_value)));
      if (!points.length) {
        target.innerHTML = `<div class="chart-empty">${escapeHtml(config.emptyText)}</div>`;
        return;
      }

      const width = Math.max(720, 120 + points.length * 78);
      const height = 300;
      const margin = { top: 28, right: 56, bottom: 54, left: 64 };
      const plotWidth = width - margin.left - margin.right;
      const plotHeight = height - margin.top - margin.bottom;
      const values = points.map((row) => Number(row.raw_value));
      const minValue = Math.min(0, ...values);
      const maxValue = Math.max(0, ...values);
      const valueSpan = maxValue - minValue || 1;
      const yoyValues = points
        .map((row) => Number(row.yoy_growth_percent))
        .filter((value) => Number.isFinite(value));
      const yoyMin = Math.min(-10, ...yoyValues);
      const yoyMax = Math.max(10, ...yoyValues);
      const yoySpan = yoyMax - yoyMin || 1;
      const xStep = plotWidth / points.length;
      const barWidth = Math.min(50, xStep * 0.5);
      const yValue = (value) => margin.top + ((maxValue - value) / valueSpan) * plotHeight;
      const yYoy = (value) => margin.top + ((yoyMax - value) / yoySpan) * plotHeight;
      const zeroY = yValue(0);
      const yoyPathPoints = points
        .map((row, index) => ({ row, index, yoy: Number(row.yoy_growth_percent) }))
        .filter((item) => Number.isFinite(item.yoy));
      const yoyPath = yoyPathPoints
        .map((item, pathIndex) => {
          const x = margin.left + xStep * item.index + xStep / 2;
          return `${pathIndex === 0 ? "M" : "L"} ${x.toFixed(1)} ${yYoy(item.yoy).toFixed(1)}`;
        })
        .join(" ");

      const bars = points.map((row, index) => {
        const value = Number(row.raw_value);
        const x = margin.left + xStep * index + (xStep - barWidth) / 2;
        const y = Math.min(yValue(value), zeroY);
        const h = Math.max(2, Math.abs(zeroY - yValue(value)));
        const labelX = margin.left + xStep * index + xStep / 2;
        const yoy = Number(row.yoy_growth_percent);
        return `
          <rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${h.toFixed(1)}" rx="6" fill="rgba(128,216,255,0.78)" />
          <text x="${labelX.toFixed(1)}" y="${(y - 8).toFixed(1)}" text-anchor="middle" fill="#dff7ff" font-size="12" font-weight="700">${escapeHtml(row.value)}</text>
          <text x="${labelX.toFixed(1)}" y="${height - 30}" text-anchor="middle" fill="#a7b0c6" font-size="12">${escapeHtml(row.period_label)}</text>
          <text x="${labelX.toFixed(1)}" y="${height - 13}" text-anchor="middle" fill="#9cffc7" font-size="11">${escapeHtml(formatPercent(Number.isFinite(yoy) ? yoy : null))}</text>
        `;
      }).join("");

      const yoyDots = points.map((row, index) => {
        const yoy = Number(row.yoy_growth_percent);
        if (!Number.isFinite(yoy)) return "";
        const x = margin.left + xStep * index + xStep / 2;
        const y = yYoy(yoy);
        return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4.5" fill="#9cffc7" stroke="#102018" stroke-width="2" />`;
      }).join("");

      target.innerHTML = `
        <div class="chart-scroll">
          <svg class="chart-svg" style="width:${width}px; min-width:${width}px;" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(config.ariaLabel)}">
            <line x1="${margin.left}" y1="${zeroY.toFixed(1)}" x2="${width - margin.right}" y2="${zeroY.toFixed(1)}" stroke="rgba(255,255,255,0.18)" />
            <line x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}" stroke="rgba(255,255,255,0.18)" />
            <line x1="${width - margin.right}" y1="${margin.top}" x2="${width - margin.right}" y2="${height - margin.bottom}" stroke="rgba(156,255,199,0.22)" />
            ${bars}
            ${yoyPath ? `<path d="${yoyPath}" fill="none" stroke="#9cffc7" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />` : ""}
            ${yoyDots}
            <text x="${margin.left}" y="18" fill="#dff7ff" font-size="12">柱：${escapeHtml(config.barLabel)}</text>
            <text x="${width - margin.right}" y="18" text-anchor="end" fill="#9cffc7" font-size="12">线：同比增长率</text>
          </svg>
        </div>
        <div class="chart-note">${escapeHtml(config.note)}</div>
      `;
    }

    function renderNetIncomeChart(rows) {
      renderComparisonChart(fields.netIncomeChart, rows, {
        emptyText: "未从这五份同类型财报中提取到可比净利润。",
        ariaLabel: "五期净利润和同比增长率对比图",
        barLabel: "净利润",
        note: "净利润来自 SEC XBRL NetIncomeLoss；增长率统一按上一财年同一财政期间同比计算。"
      });
    }

    function renderRoeChart(rows) {
      renderComparisonChart(fields.roeChart, rows, {
        emptyText: "未从这五份同类型财报中提取到可比 ROE。",
        ariaLabel: "五期 ROE 和同比增长率对比图",
        barLabel: "ROE",
        note: "年度 ROE = 净利润 / 平均股东权益；季度 ROE = 当季净利润 / 期末股东权益。增长率统一按上一财年同一财政期间同比计算。"
      });
    }

    function renderPeGrowthReviewChart(monthlyRows, reviewRows) {
      const chartStartMonth = "2022-01";
      const points = (monthlyRows || [])
        .filter((row) => String(row.month || "") >= chartStartMonth)
        .filter((row) => Number.isFinite(Number(row.pe)) && Number(row.pe) > 0 && Number.isFinite(Number(row.close)) && Number(row.close) > 0)
        .map((row) => ({ ...row, pe: Number(row.pe), close: Number(row.close) }));
      if (!points.length) {
        fields.peGrowthReviewChart.innerHTML = `<div class="chart-empty">暂无足够数据生成动态 PE 与股价走势。</div>`;
        return;
      }

      const finiteNumber = (value) => typeof value === "number" && Number.isFinite(value);
      const chartScaleOptions = {
        fixedWidth: 860,
        fixedHeight: 300,
        margin: { top: 30, right: 82, bottom: 74, left: 64 }
      };
      const forecastScale = buildTimeScale(points, chartScaleOptions);
      const { width, height, margin, plotHeight, xAtMonth } = forecastScale;
      const pathFor = (seriesPoints, key, xScale, yScale) => seriesPoints
        .map((row) => ({ value: row[key], month: row.month }))
        .filter((item) => finiteNumber(item.value))
        .map((item, pathIndex) => `${pathIndex === 0 ? "M" : "L"} ${xScale(item.month).toFixed(1)} ${yScale(item.value).toFixed(1)}`)
        .join(" ");
      const peValues = points.map((row) => row.pe);
      const peFloor = Math.min(...peValues);
      const peCeiling = Math.max(...peValues);
      const peRange = Math.max(1, peCeiling - peFloor);
      const peMin = Math.max(0, Math.floor((peFloor - peRange * 0.15) / 5) * 5);
      const peMax = Math.ceil((peCeiling + peRange * 0.15) / 5) * 5;
      const peSpan = peMax - peMin || 1;
      const yAtPe = (value) => margin.top + ((peMax - value) / peSpan) * plotHeight;
      const pePath = pathFor(points, "pe", xAtMonth, yAtPe);
      const priceValues = points.map((row) => row.close);
      const priceFloor = priceValues.length ? Math.min(...priceValues) : 0;
      const priceCeiling = priceValues.length ? Math.max(...priceValues) : 1;
      const priceRange = Math.max(1, priceCeiling - priceFloor);
      const priceMin = Math.max(0, priceFloor - priceRange * 0.15);
      const priceMax = priceCeiling + priceRange * 0.15;
      const priceSpan = priceMax - priceMin || 1;
      const yAtPrice = (value) => margin.top + ((priceMax - value) / priceSpan) * plotHeight;
      const pricePath = pathFor(points, "close", xAtMonth, yAtPrice);
      const peAxis = renderYAxisTicks({
        ticks: fiveTicks(peMin, peMax),
        yAt: yAtPe,
        margin,
        width,
        right: margin.right,
        formatter: (value) => `${value.toFixed(1)}x`
      });
      const priceAxis = renderRightYAxisTicks({
        ticks: fiveTicks(priceMin, priceMax),
        yAt: yAtPrice,
        margin,
        width,
        formatter: (value) => `$${value.toFixed(value >= 100 ? 0 : 2)}`
      });
      const yearAxis = renderYearAxis(forecastScale);
      const ticks = points.map((row) => `
        <line x1="${xAtMonth(row.month).toFixed(1)}" y1="${height - margin.bottom}" x2="${xAtMonth(row.month).toFixed(1)}" y2="${(height - margin.bottom + 5).toFixed(1)}" stroke="rgba(255,255,255,0.14)" />
      `).join("");
      const peDots = points.map((row) => {
        const x = xAtMonth(row.month);
        const y = yAtPe(row.pe);
        return `
          <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" fill="#9cffc7" stroke="#102018" stroke-width="2">
            <title>${escapeHtml(row.month)} | 动态 PE ${row.pe.toFixed(1)}x | 股价 $${row.close.toFixed(2)}</title>
          </circle>
          ${points.length <= 18 ? `<text x="${x.toFixed(1)}" y="${(y - 10).toFixed(1)}" text-anchor="middle" fill="#dfffe9" font-size="10">${row.pe.toFixed(1)}x</text>` : ""}
        `;
      }).join("");
      const priceDots = points.map((row) => {
        const x = xAtMonth(row.month);
        const y = yAtPrice(row.close);
        return `
          <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.2" fill="#80d8ff" stroke="#10212a" stroke-width="1.8">
            <title>${escapeHtml(row.month)} | 股价 $${row.close.toFixed(2)} | 动态 PE ${row.pe.toFixed(1)}x</title>
          </circle>
        `;
      }).join("");
      const reviewPoints = (reviewRows || [])
        .filter((row) => String(row.month || "") >= chartStartMonth)
        .filter((row) => Number.isFinite(Number(row.implied_growth_percent)));
      const errorPoints = reviewPoints
        .filter((row) => finiteNumber(row.actual_growth_percent))
        .map((row) => ({
          ...row,
          forecast_error_percent: row.actual_growth_percent - row.implied_growth_percent
        }));
      const errorValues = errorPoints
        .map((row) => row.forecast_error_percent)
        .filter((value) => finiteNumber(value));
      const predictedValues = reviewPoints
        .map((row) => row.implied_growth_percent)
        .filter((value) => finiteNumber(value));
      const errorScale = buildTimeScale(points, chartScaleOptions);
      const errorWidth = errorScale.width;
      const errorHeight = errorScale.height;
      const errorMargin = errorScale.margin;
      const errorPlotHeight = errorScale.plotHeight;
      const xAtErrorMonth = errorScale.xAtMonth;
      const combinedReviewValues = [...predictedValues, ...errorValues, 0];
      const reviewFloor = Math.min(...combinedReviewValues);
      const reviewCeiling = Math.max(...combinedReviewValues);
      const reviewRange = Math.max(10, reviewCeiling - reviewFloor);
      const errorMin = Math.floor((reviewFloor - reviewRange * 0.15) / 5) * 5;
      const errorMax = Math.ceil((reviewCeiling + reviewRange * 0.15) / 5) * 5;
      const errorSpan = errorMax - errorMin || 1;
      const yAtError = (value) => errorMargin.top + ((errorMax - value) / errorSpan) * errorPlotHeight;
      const predictedPath = pathFor(reviewPoints, "implied_growth_percent", xAtErrorMonth, yAtError);
      const errorPath = pathFor(errorPoints, "forecast_error_percent", xAtErrorMonth, yAtError);
      const maxErrorPoint = errorPoints.length
        ? errorPoints.reduce((best, row) => row.forecast_error_percent > best.forecast_error_percent ? row : best, errorPoints[0])
        : null;
      const minErrorPoint = errorPoints.length
        ? errorPoints.reduce((best, row) => row.forecast_error_percent < best.forecast_error_percent ? row : best, errorPoints[0])
        : null;
      const errorAxis = renderYAxisTicks({
        ticks: fiveTicks(errorMin, errorMax),
        yAt: yAtError,
        margin: errorMargin,
        width: errorWidth,
        right: errorMargin.right,
        formatter: (value) => `${value.toFixed(1)}%`
      });
      const errorYearAxis = renderYearAxis(errorScale);
      const errorTicks = points.map((row) => `
        <line x1="${xAtErrorMonth(row.month).toFixed(1)}" y1="${errorHeight - errorMargin.bottom}" x2="${xAtErrorMonth(row.month).toFixed(1)}" y2="${(errorHeight - errorMargin.bottom + 5).toFixed(1)}" stroke="rgba(255,255,255,0.14)" />
      `).join("");
      const zeroErrorY = yAtError(0);
      const predictedDots = reviewPoints.map((row) => {
        const x = xAtErrorMonth(row.month);
        const y = yAtError(row.implied_growth_percent);
        return `
          <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.6" fill="#9cffc7" stroke="#102018" stroke-width="2">
            <title>${escapeHtml(row.period_label || row.month)} | PE日期 ${escapeHtml(row.price_date || row.month)} | PE预测值 ${formatPercent(row.implied_growth_percent)}</title>
          </circle>
        `;
      }).join("");
      const errorDots = errorPoints.map((row) => {
        const x = xAtErrorMonth(row.month);
        const y = yAtError(row.forecast_error_percent);
        const positive = row.forecast_error_percent >= 0;
        return `
          <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" fill="${positive ? "#ffd36a" : "#ff8fa8"}" stroke="#20190a" stroke-width="2">
            <title>${escapeHtml(row.period_label || row.month)} | PE日期 ${escapeHtml(row.price_date || row.month)} | 预测误差 = 实际 ${formatPercent(row.actual_growth_percent)} - PE预测值 ${formatPercent(row.implied_growth_percent)} = ${formatPercent(row.forecast_error_percent)}</title>
          </circle>
        `;
      }).join("");
      const errorCallouts = [maxErrorPoint, minErrorPoint].filter(Boolean).map((row) => {
        const x = xAtErrorMonth(row.month);
        const y = yAtError(row.forecast_error_percent);
        const high = row.forecast_error_percent >= 0;
        const label = high ? "实际显著超预期" : "实际低于预期";
        const labelY = high ? Math.max(errorMargin.top + 14, y - 13) : Math.min(errorHeight - errorMargin.bottom - 8, y + 19);
        return `
          <text x="${x.toFixed(1)}" y="${labelY.toFixed(1)}" text-anchor="middle" fill="${high ? "#ffd36a" : "#ff8fa8"}" font-size="10">${label}</text>
        `;
      }).join("");

      fields.peGrowthReviewChart.innerHTML = `
        <svg class="chart-svg" style="width:${width}px; min-width:${width}px; height:${height}px;" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMinYMin meet" role="img" aria-label="动态 PE 与股价走势叠加图">
          <line x1="${margin.left}" y1="${height - margin.bottom}" x2="${width - margin.right}" y2="${height - margin.bottom}" stroke="rgba(255,255,255,0.18)" />
          <line x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}" stroke="rgba(255,255,255,0.18)" />
          <line x1="${width - margin.right}" y1="${margin.top}" x2="${width - margin.right}" y2="${height - margin.bottom}" stroke="rgba(128,216,255,0.25)" />
          ${peAxis}
          ${priceAxis}
          ${yearAxis}
          ${ticks}
          ${pricePath ? `<path d="${pricePath}" fill="none" stroke="#80d8ff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="5 5" />` : ""}
          ${pePath ? `<path d="${pePath}" fill="none" stroke="#9cffc7" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" />` : ""}
          ${priceDots}
          ${peDots}
          <text x="${margin.left}" y="18" fill="#9cffc7" font-size="12">动态 PE 与股价走势</text>
          <text x="${margin.left + 136}" y="18" fill="#9cffc7" font-size="11">● 动态 PE</text>
          <text x="${margin.left + 224}" y="18" fill="#80d8ff" font-size="11">-- 股价</text>
          <text x="${width - margin.right}" y="18" text-anchor="end" fill="#dff7ff" font-size="12">${points[0].month} 至 ${points[points.length - 1].month}</text>
        </svg>
        ${errorPoints.length ? `
        <svg class="chart-svg" style="width:${width}px; min-width:${width}px; height:${height}px;" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMinYMin meet" role="img" aria-label="PE预测值与预测误差折线图">
          <line x1="${errorMargin.left}" y1="${errorHeight - errorMargin.bottom}" x2="${errorWidth - errorMargin.right}" y2="${errorHeight - errorMargin.bottom}" stroke="rgba(255,255,255,0.18)" />
          <line x1="${errorMargin.left}" y1="${errorMargin.top}" x2="${errorMargin.left}" y2="${errorHeight - errorMargin.bottom}" stroke="rgba(255,255,255,0.18)" />
          <line x1="${errorMargin.left}" y1="${zeroErrorY.toFixed(1)}" x2="${errorWidth - errorMargin.right}" y2="${zeroErrorY.toFixed(1)}" stroke="rgba(255,255,255,0.24)" stroke-dasharray="4 5" />
          ${errorAxis}
          ${errorYearAxis}
          ${errorTicks}
          ${predictedPath ? `<path d="${predictedPath}" fill="none" stroke="#9cffc7" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />` : ""}
          ${errorPath ? `<path d="${errorPath}" fill="none" stroke="#ffd36a" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="5 5" />` : ""}
          ${predictedDots}
          ${errorDots}
          ${errorCallouts}
          <text x="${errorMargin.left}" y="18" fill="#9cffc7" font-size="12">PE预测值与预测误差</text>
          <text x="${errorMargin.left + 128}" y="18" fill="#9cffc7" font-size="11">● PE预测值</text>
          <text x="${errorMargin.left + 220}" y="18" fill="#ffd36a" font-size="11">-- 预测误差</text>
          <text x="${errorWidth - errorMargin.right}" y="18" text-anchor="end" fill="#dff7ff" font-size="12">单位：%</text>
        </svg>
        ` : ""}
        <div class="chart-note">上图：动态 PE = 月度股价 / 当时可得 TTM diluted EPS；左轴为 PE，右轴为股价。下图：预测使用披露日前一交易日 PE；PE预测值为该 PE 隐含的单季 NI 同比，预测误差 = 实际单季 NI 同比 - PE预测值。</div>
      `;
    }

    const previewState = {
      zoom: 100,
      matches: [],
      currentMatch: -1,
      searchTimer: null
    };

    function getFrameDocument() {
      try {
        return fields.frame.contentDocument || fields.frame.contentWindow.document;
      } catch {
        return null;
      }
    }

    function applyPreviewZoom() {
      fields.zoomValue.textContent = `${previewState.zoom}%`;
      const doc = getFrameDocument();
      if (!doc || !doc.body) return;
      doc.documentElement.style.zoom = `${previewState.zoom}%`;
    }

    function injectSearchStyle(doc) {
      if (!doc || doc.getElementById("valuation-search-style")) return;
      const style = doc.createElement("style");
      style.id = "valuation-search-style";
      style.textContent = `
        mark.valuation-search-hit {
          background: #ffe66d;
          color: #111827;
          padding: 0 2px;
        }
        mark.valuation-search-hit.current {
          background: #ff8f3d;
          outline: 2px solid #111827;
        }
      `;
      doc.head.appendChild(style);
    }

    function clearSearchHighlights(doc) {
      const marks = Array.from(doc.querySelectorAll("mark.valuation-search-hit"));
      for (const mark of marks) {
        const text = doc.createTextNode(mark.textContent || "");
        mark.replaceWith(text);
        text.parentNode?.normalize();
      }
      previewState.matches = [];
      previewState.currentMatch = -1;
    }

    function updateSearchCount() {
      const total = previewState.matches.length;
      fields.searchCount.textContent = total ? `${previewState.currentMatch + 1}/${total}` : "0/0";
    }

    function selectSearchMatch(index) {
      const total = previewState.matches.length;
      if (!total) {
        updateSearchCount();
        return;
      }
      if (previewState.currentMatch >= 0) {
        previewState.matches[previewState.currentMatch]?.classList.remove("current");
      }
      previewState.currentMatch = (index + total) % total;
      const match = previewState.matches[previewState.currentMatch];
      match.classList.add("current");
      match.scrollIntoView({ block: "center", inline: "center" });
      updateSearchCount();
    }

    function runPreviewSearch() {
      const doc = getFrameDocument();
      if (!doc || !doc.body) return;
      injectSearchStyle(doc);
      clearSearchHighlights(doc);

      const term = fields.previewSearch.value.trim();
      if (!term) {
        updateSearchCount();
        return;
      }

      const lowerTerm = term.toLowerCase();
      const nodes = [];
      const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT, {
        acceptNode(node) {
          const parent = node.parentElement;
          if (!parent) return NodeFilter.FILTER_REJECT;
          if (["SCRIPT", "STYLE", "NOSCRIPT", "MARK"].includes(parent.tagName)) return NodeFilter.FILTER_REJECT;
          return node.nodeValue.toLowerCase().includes(lowerTerm)
            ? NodeFilter.FILTER_ACCEPT
            : NodeFilter.FILTER_REJECT;
        }
      });

      while (walker.nextNode()) nodes.push(walker.currentNode);

      for (const node of nodes) {
        const text = node.nodeValue;
        const lowerText = text.toLowerCase();
        const fragment = doc.createDocumentFragment();
        let start = 0;
        let index = lowerText.indexOf(lowerTerm);
        while (index !== -1) {
          if (index > start) fragment.appendChild(doc.createTextNode(text.slice(start, index)));
          const mark = doc.createElement("mark");
          mark.className = "valuation-search-hit";
          mark.textContent = text.slice(index, index + term.length);
          fragment.appendChild(mark);
          previewState.matches.push(mark);
          start = index + term.length;
          index = lowerText.indexOf(lowerTerm, start);
        }
        if (start < text.length) fragment.appendChild(doc.createTextNode(text.slice(start)));
        node.replaceWith(fragment);
      }

      selectSearchMatch(0);
    }

    function queuePreviewSearch() {
      clearTimeout(previewState.searchTimer);
      previewState.searchTimer = setTimeout(runPreviewSearch, 180);
    }

    fields.zoomOut.addEventListener("click", () => {
      previewState.zoom = Math.max(50, previewState.zoom - 10);
      applyPreviewZoom();
    });

    fields.zoomIn.addEventListener("click", () => {
      previewState.zoom = Math.min(200, previewState.zoom + 10);
      applyPreviewZoom();
    });

    fields.zoomReset.addEventListener("click", () => {
      previewState.zoom = 100;
      applyPreviewZoom();
    });

    fields.previewSearch.addEventListener("input", queuePreviewSearch);
    fields.previewSearch.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        selectSearchMatch(previewState.currentMatch + (event.shiftKey ? -1 : 1));
      }
    });
    fields.searchPrev.addEventListener("click", () => selectSearchMatch(previewState.currentMatch - 1));
    fields.searchNext.addEventListener("click", () => selectSearchMatch(previewState.currentMatch + 1));

    fields.frame.addEventListener("load", () => {
      applyPreviewZoom();
      runPreviewSearch();
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(form);
      const [formType, quarter] = String(formData.get("period")).split(":");

      const payload = {
        company: formData.get("company"),
        year: Number(formData.get("year")),
        form: formType,
        quarter: quarter === "FY" ? null : quarter,
        continuous_quarter_view: formData.get("continuous_quarter_view") === "on",
        user_agent: formData.get("user_agent")
      };

      button.disabled = true;
      button.textContent = "正在读取 SEC 财报…";
      const selectedPeriodLabel = quarter === "FY" ? formType : `${formType} ${quarter}`;
      const modeText = payload.continuous_quarter_view ? "连续季度视图" : "同季度横向对比";
      setStatus(`正在匹配公司并读取 ${payload.year} ${selectedPeriodLabel}，历史对比使用${modeText}。第一次请求可能需要几秒钟。`);

      try {
        const response = await fetch("/api/fetch-filing", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok) {
          throw new Error(result.error || "读取失败");
        }

        fields.matchedCompany.textContent = `${result.company_name} (${result.ticker})`;
        fields.formType.textContent = result.form;
        fields.reportDate.textContent = result.report_date;
        fields.filingDate.textContent = result.filing_date;
        fields.frame.src = result.preview_url;
        fields.previewTools.hidden = false;
        renderCompanyProfileRows(result.tables.company_profile_rows || []);
        renderNetIncomeChart(result.tables.net_income_comparison_rows || []);
        renderRoeChart(result.tables.roe_comparison_rows || []);
        renderLeverageChart(result.tables.leverage_rows || []);
        renderAltmanChart(result.tables.altman_rows || []);
        renderPeGrowthReviewChart(result.tables.monthly_pe_rows || [], result.tables.pe_growth_review_rows || []);
        renderImpliedGrowthRows(result.tables.implied_growth_rows || []);

        emptyState.hidden = true;
        fields.frame.hidden = false;
        workspace.hidden = false;
        const downloadedCount = (result.comparison_filings || []).length;
        const missingCount = (result.missing_comparison_periods || []).length;
        const missingText = missingCount ? `，${missingCount} 个历史期间未找到同类财报` : "";
        setStatus(`读取完成。默认展示当期财报；后台已下载 ${downloadedCount} 份同类型历史财报用于纵向对比${missingText}。`);
      } catch (error) {
        setStatus(error.message, true);
      } finally {
        button.disabled = false;
        button.textContent = "读取并展示财报";
      }
    });
  </script>
</body>
</html>
"""


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def html_response(handler: BaseHTTPRequestHandler, body: str) -> None:
    encoded = body.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


def relative_to_data_dir(path: Path) -> str:
    return path.resolve().relative_to(DATA_DIR.resolve()).as_posix()


class FilingHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self._current_table = []
        elif tag == "tr" and self._current_table is not None:
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._current_cell is not None and self._current_row is not None:
            cell = normalize_space(" ".join(self._current_cell))
            self._current_row.append(cell)
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None and self._current_table is not None:
            if any(cell for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._current_table is not None:
            if self._current_table:
                self.tables.append(self._current_table)
            self._current_table = None

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)
        text = normalize_space(data)
        if text:
            self._text_parts.append(text)

    @property
    def text(self) -> str:
        return normalize_space(" ".join(self._text_parts))


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_filing_html(document_path: Path) -> tuple[list[list[list[str]]], str]:
    raw = document_path.read_bytes()
    html = raw.decode("utf-8", errors="ignore")
    parser = FilingHTMLParser()
    parser.feed(html)
    return parser.tables, parser.text


def load_company_facts(cik: str, user_agent: str) -> dict[str, Any]:
    return fetch_json(f"{SEC_COMPANY_FACTS_BASE}/CIK{cik}.json", user_agent)


def parse_iso_date(value: str) -> Any:
    if not value:
        return None
    try:
        from datetime import date

        return date.fromisoformat(value)
    except ValueError:
        return None


def duration_days(entry: dict[str, Any]) -> int | None:
    start = parse_iso_date(str(entry.get("start", "")))
    end = parse_iso_date(str(entry.get("end", "")))
    if not start or not end:
        return None
    return (end - start).days


def pick_fact_entry(entries: list[dict[str, Any]], filing: Any, duration_preference: str) -> dict[str, Any] | None:
    exact = [
        entry
        for entry in entries
        if entry.get("accn") == filing.accession_number and entry.get("end") == filing.report_date
    ]
    if not exact:
        exact = [entry for entry in entries if entry.get("accn") == filing.accession_number]
    if not exact:
        return None

    if duration_preference == "instant":
        instant = [entry for entry in exact if not entry.get("start")]
        if instant:
            return sorted(instant, key=lambda item: str(item.get("filed", "")), reverse=True)[0]

    duration_entries = [(entry, duration_days(entry)) for entry in exact if duration_days(entry) is not None]
    if duration_entries:
        if duration_preference == "longest":
            return sorted(duration_entries, key=lambda item: item[1], reverse=True)[0][0]
        if duration_preference == "shortest":
            return sorted(duration_entries, key=lambda item: item[1])[0][0]

    return sorted(exact, key=lambda item: str(item.get("filed", "")), reverse=True)[0]


def format_fact_value(value: Any, unit: str) -> str:
    if value is None:
        return "—"
    if not isinstance(value, (int, float)):
        return str(value)

    if unit == "USD":
        absolute = abs(value)
        if absolute >= 1_000_000_000:
            return f"${value / 1_000_000_000:,.2f}B"
        if absolute >= 1_000_000:
            return f"${value / 1_000_000:,.2f}M"
        return f"${value:,.0f}"

    if unit == "shares":
        absolute = abs(value)
        if absolute >= 1_000_000_000:
            return f"{value / 1_000_000_000:,.2f}B"
        if absolute >= 1_000_000:
            return f"{value / 1_000_000:,.2f}M"
        return f"{value:,.0f}"

    if unit == "USD/shares":
        return f"${value:,.2f}"

    return f"{value:,.2f}"


def extract_financial_rows(company_facts: dict[str, Any], filing: Any) -> list[dict[str, Any]]:
    facts = company_facts.get("facts", {}).get("us-gaap", {})
    rows: list[dict[str, Any]] = []

    for metric in FINANCIAL_METRICS:
        row = {
            "category": metric["category"],
            "metric": metric["label"],
            "value": "—",
            "raw_value": None,
            "unit": metric["unit"],
            "period": "—",
            "concept": "—",
            "status": "缺失",
        }

        for concept in metric["concepts"]:
            concept_payload = facts.get(concept)
            if not concept_payload:
                continue

            units = concept_payload.get("units", {})
            unit = metric["unit"]
            unit_entries = units.get(unit)
            if not unit_entries and units:
                unit, unit_entries = next(iter(units.items()))

            if not unit_entries:
                continue

            entry = pick_fact_entry(unit_entries, filing, metric["duration_preference"])
            if not entry:
                continue

            start = entry.get("start")
            end = entry.get("end")
            row.update(
                {
                    "value": format_fact_value(entry.get("val"), unit),
                    "raw_value": entry.get("val"),
                    "unit": unit,
                    "period": f"{start} → {end}" if start else str(end or "—"),
                    "concept": concept,
                    "status": "已披露",
                }
            )
            break

        rows.append(row)

    return rows


def yahoo_headers(accept: str = "application/json,text/plain,*/*") -> dict[str, str]:
    return {
        "User-Agent": YAHOO_USER_AGENT,
        "Accept": accept,
    }


def build_yahoo_opener() -> urllib.request.OpenerDirector:
    cookie_jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))


def prime_yahoo_cookie(opener: urllib.request.OpenerDirector) -> None:
    request = urllib.request.Request("https://fc.yahoo.com", headers=yahoo_headers("*/*"))
    try:
        opener.open(request, timeout=20).close()
    except urllib.error.HTTPError:
        return


def load_yahoo_crumb(opener: urllib.request.OpenerDirector) -> str | None:
    prime_yahoo_cookie(opener)
    request = urllib.request.Request(
        "https://query1.finance.yahoo.com/v1/test/getcrumb",
        headers=yahoo_headers("*/*"),
    )
    with opener.open(request, timeout=20) as response:
        crumb = response.read().decode("utf-8", errors="ignore").strip()
    return crumb or None


def fetch_yahoo_json(url: str, opener: urllib.request.OpenerDirector | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers=yahoo_headers(),
    )
    active_opener = opener or urllib.request.build_opener()
    with active_opener.open(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_yahoo_monthly_prices(ticker: str, start_date: date, end_date: date) -> list[dict[str, Any]]:
    period1 = int(datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    period2 = int(datetime.combine(end_date + timedelta(days=35), datetime.min.time(), tzinfo=timezone.utc).timestamp())
    encoded_ticker = urllib.parse.quote(ticker)
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_ticker}"
        f"?period1={period1}&period2={period2}&interval=1mo&events=history&includeAdjustedClose=true"
    )
    payload = fetch_yahoo_json(url)
    result = (payload.get("chart", {}).get("result") or [{}])[0]
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    rows: list[dict[str, Any]] = []
    for timestamp, close in zip(timestamps, closes):
        if not isinstance(close, (int, float)):
            continue
        month_date = datetime.fromtimestamp(timestamp, timezone.utc).date()
        if month_date < start_date or month_date > end_date + timedelta(days=31):
            continue
        rows.append({"month": month_date.strftime("%Y-%m"), "date": month_date, "close": float(close)})
    return rows


def fetch_yahoo_daily_prices(ticker: str, start_date: date, end_date: date) -> list[dict[str, Any]]:
    period1 = int(datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    period2 = int(datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).timestamp())
    encoded_ticker = urllib.parse.quote(ticker)
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_ticker}"
        f"?period1={period1}&period2={period2}&interval=1d&events=history&includeAdjustedClose=true"
    )
    payload = fetch_yahoo_json(url)
    result = (payload.get("chart", {}).get("result") or [{}])[0]
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    rows: list[dict[str, Any]] = []
    for timestamp, close in zip(timestamps, closes):
        if not isinstance(close, (int, float)):
            continue
        price_date = datetime.fromtimestamp(timestamp, timezone.utc).date()
        if price_date < start_date or price_date > end_date:
            continue
        rows.append({"date": price_date, "close": float(close)})
    return rows


def yahoo_raw_value(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("fmt") or value.get("longFmt") or value.get("raw")
    return value


def format_market_cap(value: Any, currency: str | None) -> str:
    raw = value.get("raw") if isinstance(value, dict) else value
    if not isinstance(raw, (int, float)):
        return str(yahoo_raw_value(value) or "—")

    prefix = f"{currency} " if currency else ""
    absolute = abs(raw)
    if absolute >= 1_000_000_000_000:
        return f"{prefix}{raw / 1_000_000_000_000:,.2f}T"
    if absolute >= 1_000_000_000:
        return f"{prefix}{raw / 1_000_000_000:,.2f}B"
    if absolute >= 1_000_000:
        return f"{prefix}{raw / 1_000_000:,.2f}M"
    return f"{prefix}{raw:,.0f}"


def compact_summary(value: Any, max_length: int | None = None) -> str:
    text = normalize_space(str(value or ""))
    if max_length is None:
        return text or "—"
    if len(text) <= max_length:
        return text or "—"
    return f"{text[:max_length].rstrip()}..."


def translate_to_chinese(text: str) -> str:
    clean_text = normalize_space(text)
    if not clean_text or clean_text == "—":
        return "—"

    params = urllib.parse.urlencode(
        {
            "client": "gtx",
            "sl": "en",
            "tl": "zh-CN",
            "dt": "t",
            "q": clean_text,
        }
    )
    request = urllib.request.Request(
        f"{GOOGLE_TRANSLATE_BASE}?{params}",
        headers={"User-Agent": YAHOO_USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        return clean_text

    translated_parts = []
    for part in payload[0] if payload else []:
        if isinstance(part, list) and part:
            translated_parts.append(str(part[0]))
    return normalize_space("".join(translated_parts)) or clean_text


def load_yahoo_company_profile(ticker: str) -> dict[str, Any]:
    encoded_ticker = urllib.parse.quote(ticker)
    opener = build_yahoo_opener()
    try:
        crumb = load_yahoo_crumb(opener)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        crumb = None
    crumb_query = f"&crumb={urllib.parse.quote(crumb, safe='')}" if crumb else ""
    modules = urllib.parse.quote("assetProfile,price", safe="")
    summary_url = f"{YAHOO_QUOTE_SUMMARY_BASE}/{encoded_ticker}?modules={modules}{crumb_query}"
    profile: dict[str, Any] = {}
    price: dict[str, Any] = {}

    try:
        summary = fetch_yahoo_json(summary_url, opener)
        result = summary.get("quoteSummary", {}).get("result") or []
        if result:
            payload = result[0]
            profile = payload.get("assetProfile") or {}
            price = payload.get("price") or {}
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        profile = {}
        price = {}

    quote_url = f"{YAHOO_QUOTE_BASE}?symbols={encoded_ticker}{crumb_query}"
    try:
        quote_payload = fetch_yahoo_json(quote_url, opener)
        quote_result = quote_payload.get("quoteResponse", {}).get("result") or []
        quote = quote_result[0] if quote_result else {}
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        quote = {}

    search_url = f"{YAHOO_SEARCH_BASE}?q={encoded_ticker}&quotesCount=1&newsCount=0"
    try:
        search_payload = fetch_yahoo_json(search_url, opener)
        search_result = search_payload.get("quotes") or []
        search = search_result[0] if search_result else {}
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        search = {}

    return {
        "profile": profile,
        "price": price,
        "quote": quote,
        "search": search,
    }


def sentence_window(text: str, marker_start: int, marker_end: int, radius: int = 520) -> str:
    start = max(0, marker_start - radius)
    end = min(len(text), marker_end + radius)
    left_boundaries = [text.rfind(boundary, 0, marker_start) for boundary in [". ", "? ", "! ", "\n"]]
    right_boundaries = [text.find(boundary, marker_end) for boundary in [". ", "? ", "! ", "\n"]]
    left = max([boundary + 1 for boundary in left_boundaries if boundary >= start] or [start])
    right = min([boundary + 1 for boundary in right_boundaries if boundary != -1 and boundary <= end] or [end])
    return normalize_space(text[left:right])


def is_noisy_filing_text(value: str) -> bool:
    text = normalize_space(value)
    if not text:
        return True

    if re.search(r"\b[a-z]{2,8}-?[a-z]*:[A-Za-z]", text):
        return True
    if len(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)) >= 2:
        return True
    if len(re.findall(r"\b\d{7,}\b", text)) >= 2:
        return True
    if len(re.findall(r"\b[A-Za-z]+(?:[A-Z][a-z]+){2,}\b", text)) >= 4:
        return True

    words = re.findall(r"\b[a-zA-Z]{2,}\b", text)
    if len(words) < 8:
        return True

    natural_words = re.findall(
        r"\b(the|and|company|we|our|to|of|in|for|with|customers|business|strategy|mission|believe|committed|focus|future)\b",
        text,
        flags=re.IGNORECASE,
    )
    return len(natural_words) < 3


def clean_positioning_candidate(value: str) -> str | None:
    candidate = normalize_space(value)
    if is_noisy_filing_text(candidate):
        return None
    if len(candidate) > 1600:
        candidate = candidate[:1600].rsplit(". ", 1)[0].strip()
    return candidate or None


def extract_company_positioning(filing_text: str) -> str | None:
    text = normalize_space(filing_text)
    if not text:
        return None

    executive_terms = r"(chief executive officer|ceo|president|chairman and ceo|chairman, president and ceo)"
    positioning_terms = r"(mission|strategy|strategic|position|positioning|purpose|vision|believe|committed|focus|aim|goal|opportunity|future)"

    quoted_candidates = re.finditer(
        rf"[\"“](.{{40,1200}}?)[\"”][^\"”]{{0,260}}{executive_terms}",
        text,
        flags=re.IGNORECASE,
    )
    for match in quoted_candidates:
        quote = clean_positioning_candidate(match.group(1))
        if quote and re.search(positioning_terms, quote, flags=re.IGNORECASE):
            return quote

    title_candidates = re.finditer(executive_terms, text, flags=re.IGNORECASE)
    for match in title_candidates:
        window = sentence_window(text, match.start(), match.end())
        if re.search(positioning_terms, window, flags=re.IGNORECASE) and 40 <= len(window) <= 1400:
            cleaned = clean_positioning_candidate(window)
            if cleaned:
                return cleaned

    return None


def build_company_profile_rows(filing: Any, filing_text: str) -> list[dict[str, str]]:
    yahoo_data = load_yahoo_company_profile(filing.ticker)
    profile = yahoo_data["profile"]
    summary = profile.get("longBusinessSummary")
    company_intro = compact_summary(summary)
    rows = [{"field": "公司简介", "value": translate_to_chinese(company_intro)}]

    company_positioning = extract_company_positioning(filing_text)
    if company_positioning:
        rows.append({"field": "公司定位", "value": translate_to_chinese(company_positioning)})

    return rows


def extract_statement_entry(
    company_facts: dict[str, Any],
    filing: Any,
    concept: str,
) -> dict[str, Any] | None:
    facts = company_facts.get("facts", {}).get("us-gaap", {})
    concept_payload = facts.get(concept)
    if not concept_payload:
        return None

    units = concept_payload.get("units", {})
    unit = "USD"
    entries = units.get(unit)
    if not entries and units:
        unit, entries = next(iter(units.items()))
    if not entries:
        return None

    duration_preference = "longest" if filing.form == "10-K" else "shortest"
    entry = pick_fact_entry(entries, filing, duration_preference)
    if not entry or not isinstance(entry.get("val"), (int, float)):
        return None

    return {
        "raw_value": float(entry["val"]),
        "unit": unit,
        "period": f"{entry.get('start')} → {entry.get('end')}" if entry.get("start") else str(entry.get("end") or "—"),
        "concept": concept,
        "fy": entry.get("fy"),
        "fp": str(entry.get("fp", "")).upper(),
    }


def filing_period_label(filing: Any, selected_quarter: str | None = None, entry: dict[str, Any] | None = None) -> str:
    if entry:
        fy = entry.get("fy")
        fp = str(entry.get("fp") or "").upper()
        if isinstance(fy, int) and fp in {"Q1", "Q2", "Q3"}:
            return f"{fy} {fp}"
        if isinstance(fy, int) and fp == "FY":
            return f"{fy} Q4/FY"
    report_date = parse_iso_date(filing.report_date)
    year = report_date.year if report_date else int(str(filing.report_date)[:4])
    if filing.form == "10-K":
        return f"{year} FY"
    if selected_quarter:
        return f"{year} {selected_quarter}"
    quarter = quarter_from_date(filing.filing_date)
    return f"{year} {quarter}"


def build_statement_comparison_rows(
    company_facts: dict[str, Any],
    filings: list[Any],
    quarter: str | None,
    concept: str,
    continuous_quarter_view: bool = False,
) -> list[dict[str, Any]]:
    chronological_filings = sorted(filings, key=lambda item: item.report_date)
    rows: list[dict[str, Any]] = []
    previous_values_by_period: dict[tuple[int, str], float] = {}
    quarterly_net_income_by_accn: dict[str, dict[str, Any]] = {}
    use_quarterly_net_income = concept == "NetIncomeLoss" and (
        continuous_quarter_view or any(filing.form == "10-Q" for filing in chronological_filings)
    )
    if use_quarterly_net_income:
        report_dates = [parse_iso_date(filing.report_date) for filing in chronological_filings]
        valid_report_dates = [value for value in report_dates if value is not None]
        quarterly_net_income_by_accn = {
            str(point["accn"]): point
            for point in build_quarterly_net_income_points(
                company_facts,
                latest_end=max(valid_report_dates) if valid_report_dates else None,
                earliest_end=min(valid_report_dates) if valid_report_dates else None,
            )
        }

    for filing in chronological_filings:
        if use_quarterly_net_income and (continuous_quarter_view or filing.form == "10-Q"):
            point = quarterly_net_income_by_accn.get(filing.accession_number)
            entry = (
                {
                    "raw_value": float(point["quarter_net_income"]),
                    "unit": point["unit"],
                    "period": point["period"],
                    "concept": point["concept"],
                    "fy": point["fiscal_year"],
                    "fp": point["fiscal_period"],
                    "yoy_growth_percent": point["yoy_growth_percent"],
                }
                if point
                else None
            )
        else:
            entry = extract_statement_entry(company_facts, filing, concept)
        raw_value = entry["raw_value"] if entry else None
        yoy_growth = None
        if entry and isinstance(entry.get("yoy_growth_percent"), (int, float)):
            yoy_growth = float(entry["yoy_growth_percent"])
        elif isinstance(raw_value, (int, float)) and entry:
            fy = entry.get("fy")
            fp = str(entry.get("fp") or "").upper()
            if isinstance(fy, int) and fp:
                prior_value = previous_values_by_period.get((fy - 1, fp))
                if isinstance(prior_value, (int, float)) and prior_value != 0:
                    yoy_growth = ((raw_value - prior_value) / abs(prior_value)) * 100

        period_label = filing_period_label(filing, None if continuous_quarter_view else quarter, entry if continuous_quarter_view else None)
        rows.append(
            {
                "period_label": period_label,
                "report_date": filing.report_date,
                "filing_date": filing.filing_date,
                "accession_number": filing.accession_number,
                "value": format_fact_value(raw_value, entry["unit"] if entry else "USD"),
                "raw_value": raw_value,
                "unit": entry["unit"] if entry else "USD",
                "xbrl_concept": entry["concept"] if entry else concept,
                "xbrl_period": entry["period"] if entry else "—",
                "yoy_growth_percent": yoy_growth,
            }
        )

        if isinstance(raw_value, (int, float)) and entry:
            fy = entry.get("fy")
            fp = str(entry.get("fp") or "").upper()
            if isinstance(fy, int) and fp:
                previous_values_by_period[(fy, fp)] = raw_value

    return rows


def build_net_income_comparison_rows(
    company_facts: dict[str, Any],
    filings: list[Any],
    quarter: str | None,
    continuous_quarter_view: bool = False,
) -> list[dict[str, Any]]:
    return build_statement_comparison_rows(company_facts, filings, quarter, "NetIncomeLoss", continuous_quarter_view)


def extract_equity_entry(company_facts: dict[str, Any], filing: Any) -> dict[str, Any] | None:
    for concept in ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]:
        entry = extract_statement_entry(company_facts, filing, concept)
        if entry:
            return entry
    return None


def extract_first_statement_value(company_facts: dict[str, Any], filing: Any, concepts: list[str]) -> tuple[float | None, str | None]:
    for concept in concepts:
        entry = extract_statement_entry(company_facts, filing, concept)
        if entry and isinstance(entry.get("raw_value"), (int, float)):
            return float(entry["raw_value"]), concept
    return None, None


def extract_total_debt(company_facts: dict[str, Any], filing: Any) -> tuple[float | None, str]:
    current_debt, current_concept = extract_first_statement_value(
        company_facts,
        filing,
        [
            "ShortTermBorrowings",
            "ShortTermDebt",
            "LongTermDebtCurrent",
            "FinanceLeaseLiabilityCurrent",
            "LongTermDebtAndFinanceLeaseObligationsCurrent",
        ],
    )
    noncurrent_debt, noncurrent_concept = extract_first_statement_value(
        company_facts,
        filing,
        [
            "LongTermDebtNoncurrent",
            "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
            "FinanceLeaseLiabilityNoncurrent",
        ],
    )
    values = [value for value in [current_debt, noncurrent_debt] if isinstance(value, (int, float))]
    if values:
        concepts = " + ".join(concept for concept in [current_concept, noncurrent_concept] if concept)
        return sum(values), concepts
    fallback, fallback_concept = extract_first_statement_value(
        company_facts,
        filing,
        ["LongTermDebtAndFinanceLeaseObligations", "LongTermDebt", "DebtCurrent"],
    )
    return fallback, fallback_concept or "—"


def build_leverage_rows(company_facts: dict[str, Any], filings: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for filing in sorted(filings, key=lambda item: item.report_date):
        report_date = parse_iso_date(filing.report_date)
        assets_entry = extract_statement_entry(company_facts, filing, "Assets")
        assets = float(assets_entry["raw_value"]) if assets_entry and isinstance(assets_entry.get("raw_value"), (int, float)) else None
        assets_concept = assets_entry["concept"] if assets_entry else None
        debt, debt_concepts = extract_total_debt(company_facts, filing)
        debt_to_assets = safe_divide(debt, assets)
        if not isinstance(debt_to_assets, (int, float)):
            continue
        rows.append(
            {
                "period_label": filing_period_label(filing, None, assets_entry),
                "report_date": filing.report_date,
                "filing_date": filing.filing_date,
                "month": month_key(report_date) if report_date else filing.report_date[:7],
                "debt_to_assets": debt_to_assets,
                "debt_to_assets_percent": debt_to_assets * 100,
                "debt": debt,
                "assets": assets,
                "assets_concept": assets_concept,
                "debt_concepts": debt_concepts,
            }
        )
    return rows


def build_altman_rows(
    company_facts: dict[str, Any],
    filings: list[Any],
    monthly_pe_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    market_by_month = {
        str(row.get("month")): row
        for row in monthly_pe_rows
        if isinstance(row.get("pe"), (int, float)) and row["pe"] > 0
    }
    rows: list[dict[str, Any]] = []
    for filing in sorted(filings, key=lambda item: item.report_date):
        report_date = parse_iso_date(filing.report_date)
        month = month_key(report_date) if report_date else filing.report_date[:7]
        market_row = market_by_month.get(month)
        pe = float(market_row["pe"]) if market_row and isinstance(market_row.get("pe"), (int, float)) else None

        assets, _ = extract_first_statement_value(company_facts, filing, ["Assets"])
        liabilities, _ = extract_first_statement_value(company_facts, filing, ["Liabilities"])
        current_assets, _ = extract_first_statement_value(company_facts, filing, ["AssetsCurrent"])
        current_liabilities, _ = extract_first_statement_value(company_facts, filing, ["LiabilitiesCurrent"])
        retained_earnings, _ = extract_first_statement_value(
            company_facts,
            filing,
            ["RetainedEarningsAccumulatedDeficit", "AccumulatedDeficit"],
        )
        operating_income_ttm, _ = extract_ttm_value(company_facts, filing, ["OperatingIncomeLoss"])
        revenue_ttm, _ = extract_ttm_value(
            company_facts,
            filing,
            ["RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "Revenues"],
        )
        net_income_ttm, _ = extract_ttm_value(company_facts, filing, ["NetIncomeLoss"])

        if not all(
            isinstance(value, (int, float)) and value != 0
            for value in [assets, liabilities, current_assets, current_liabilities, retained_earnings, operating_income_ttm, revenue_ttm, net_income_ttm, pe]
        ):
            continue
        if assets <= 0 or liabilities <= 0 or net_income_ttm <= 0 or pe <= 0:
            continue

        working_capital = float(current_assets) - float(current_liabilities)
        market_value_equity = float(pe) * float(net_income_ttm)
        x1 = working_capital / float(assets)
        x2 = float(retained_earnings) / float(assets)
        x3 = float(operating_income_ttm) / float(assets)
        x4 = market_value_equity / float(liabilities)
        x5 = float(revenue_ttm) / float(assets)
        z_score = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + x5

        rows.append(
            {
                "period_label": filing_period_label(filing),
                "report_date": filing.report_date,
                "filing_date": filing.filing_date,
                "month": month,
                "z_score": z_score,
                "x1": x1,
                "x2": x2,
                "x3": x3,
                "x4": x4,
                "x5": x5,
                "pe": pe,
                "market_value_equity": market_value_equity,
            }
        )
    return rows


def build_roe_comparison_rows(
    company_facts: dict[str, Any],
    filings: list[Any],
    quarter: str | None,
    continuous_quarter_view: bool = False,
) -> list[dict[str, Any]]:
    chronological_filings = sorted(filings, key=lambda item: item.report_date)
    rows: list[dict[str, Any]] = []
    previous_roe_by_period: dict[tuple[int, str], float] = {}
    previous_equity: float | None = None
    quarterly_net_income_by_accn: dict[str, dict[str, Any]] = {}
    use_quarterly_net_income = continuous_quarter_view or any(filing.form == "10-Q" for filing in chronological_filings)
    if use_quarterly_net_income:
        report_dates = [parse_iso_date(filing.report_date) for filing in chronological_filings]
        valid_report_dates = [value for value in report_dates if value is not None]
        quarterly_net_income_by_accn = {
            str(point["accn"]): point
            for point in build_quarterly_net_income_points(
                company_facts,
                latest_end=max(valid_report_dates) if valid_report_dates else None,
                earliest_end=min(valid_report_dates) if valid_report_dates else None,
            )
        }

    for filing in chronological_filings:
        if use_quarterly_net_income and (continuous_quarter_view or filing.form == "10-Q"):
            point = quarterly_net_income_by_accn.get(filing.accession_number)
            net_income_entry = (
                {
                    "raw_value": float(point["quarter_net_income"]),
                    "unit": point["unit"],
                    "period": point["period"],
                    "concept": point["concept"],
                    "fy": point["fiscal_year"],
                    "fp": point["fiscal_period"],
                }
                if point
                else None
            )
        else:
            net_income_entry = extract_statement_entry(company_facts, filing, "NetIncomeLoss")
        equity_entry = extract_equity_entry(company_facts, filing)
        net_income = net_income_entry["raw_value"] if net_income_entry else None
        ending_equity = equity_entry["raw_value"] if equity_entry else None
        equity_base = None
        if isinstance(ending_equity, (int, float)):
            if filing.form == "10-K" and isinstance(previous_equity, (int, float)):
                equity_base = (previous_equity + ending_equity) / 2
            else:
                equity_base = ending_equity

        roe = None
        if isinstance(net_income, (int, float)) and isinstance(equity_base, (int, float)) and equity_base != 0:
            roe = (net_income / equity_base) * 100

        yoy_growth = None
        if isinstance(roe, (int, float)) and net_income_entry:
            fy = net_income_entry.get("fy")
            fp = str(net_income_entry.get("fp") or "").upper()
            if isinstance(fy, int) and fp:
                prior_roe = previous_roe_by_period.get((fy - 1, fp))
                if isinstance(prior_roe, (int, float)) and prior_roe != 0:
                    yoy_growth = ((roe - prior_roe) / abs(prior_roe)) * 100

        period_label = filing_period_label(
            filing,
            None if continuous_quarter_view else quarter,
            net_income_entry if continuous_quarter_view else None,
        )
        rows.append(
            {
                "period_label": period_label,
                "report_date": filing.report_date,
                "filing_date": filing.filing_date,
                "accession_number": filing.accession_number,
                "value": "—" if roe is None else f"{roe:,.1f}%",
                "raw_value": roe,
                "unit": "percent",
                "xbrl_concept": "NetIncomeLoss / StockholdersEquity",
                "xbrl_period": net_income_entry["period"] if net_income_entry else "—",
                "yoy_growth_percent": yoy_growth,
            }
        )

        if isinstance(roe, (int, float)):
            if net_income_entry:
                fy = net_income_entry.get("fy")
                fp = str(net_income_entry.get("fp") or "").upper()
                if isinstance(fy, int) and fp:
                    previous_roe_by_period[(fy, fp)] = roe
        if isinstance(ending_equity, (int, float)):
            previous_equity = ending_equity

    return rows


def concept_unit_entries(company_facts: dict[str, Any], concept: str, unit: str = "USD") -> list[dict[str, Any]]:
    payload = company_facts.get("facts", {}).get("us-gaap", {}).get(concept)
    if not payload:
        return []
    units = payload.get("units", {})
    entries = units.get(unit)
    if not entries and units:
        _, entries = next(iter(units.items()))
    return list(entries or [])


def normalized_duration_entries(
    company_facts: dict[str, Any],
    concept: str,
    unit: str = "USD",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in concept_unit_entries(company_facts, concept, unit):
        value = entry.get("val")
        start = parse_iso_date(str(entry.get("start", "")))
        end = parse_iso_date(str(entry.get("end", "")))
        filed = parse_iso_date(str(entry.get("filed", "")))
        days = duration_days(entry)
        if not isinstance(value, (int, float)) or not start or not end or not filed or days is None:
            continue
        rows.append(
            {
                "value": float(value),
                "start": start,
                "end": end,
                "filed": filed,
                "days": days,
                "accn": str(entry.get("accn", "")),
                "form": str(entry.get("form", "")).upper(),
                "fp": str(entry.get("fp", "")).upper(),
                "fy": entry.get("fy"),
            }
        )
    return rows


def pick_current_ytd_entry(entries: list[dict[str, Any]], filing: Any) -> dict[str, Any] | None:
    report_date = parse_iso_date(filing.report_date)
    exact = [
        entry
        for entry in entries
        if entry["accn"] == filing.accession_number and entry["end"] == report_date
    ]
    if not exact:
        return None
    return sorted(exact, key=lambda item: (item["days"], item["filed"]), reverse=True)[0]


def pick_prior_annual_entry(entries: list[dict[str, Any]], current_ytd: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [
        entry
        for entry in entries
        if 330 <= entry["days"] <= 380 and entry["end"] < current_ytd["start"]
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (item["end"], item["filed"]), reverse=True)[0]


def pick_prior_ytd_entry(entries: list[dict[str, Any]], current_ytd: dict[str, Any]) -> dict[str, Any] | None:
    target_end = shift_year(current_ytd["end"], -1)
    candidates = [
        entry
        for entry in entries
        if entry["end"] < current_ytd["end"] and abs(entry["days"] - current_ytd["days"]) <= 12
    ]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (abs((item["end"] - target_end).days), -item["filed"].toordinal()),
    )[0]


def extract_ttm_value(company_facts: dict[str, Any], filing: Any, concepts: list[str]) -> tuple[float | None, str | None]:
    for concept in concepts:
        entries = normalized_duration_entries(company_facts, concept)
        current_ytd = pick_current_ytd_entry(entries, filing)
        if not current_ytd:
            continue
        if filing.form == "10-K" or 330 <= current_ytd["days"] <= 380:
            return current_ytd["value"], concept

        prior_annual = pick_prior_annual_entry(entries, current_ytd)
        prior_ytd = pick_prior_ytd_entry(entries, current_ytd)
        if prior_annual and prior_ytd:
            return prior_annual["value"] + current_ytd["value"] - prior_ytd["value"], concept

    return None, None


def latest_market_pe(monthly_pe_rows: list[dict[str, Any]]) -> float | None:
    valid_rows = [row for row in monthly_pe_rows if isinstance(row.get("pe"), (int, float)) and row["pe"] > 0]
    if not valid_rows:
        return None
    return float(valid_rows[-1]["pe"])


def normalized_instant_entries(
    company_facts: dict[str, Any],
    concept: str,
    unit: str = "USD",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in concept_unit_entries(company_facts, concept, unit):
        value = entry.get("val")
        end = parse_iso_date(str(entry.get("end", "")))
        filed = parse_iso_date(str(entry.get("filed", "")))
        if not isinstance(value, (int, float)) or not end or not filed:
            continue
        rows.append(
            {
                "value": float(value),
                "end": end,
                "filed": filed,
                "accn": str(entry.get("accn", "")),
                "form": str(entry.get("form", "")).upper(),
                "fp": str(entry.get("fp", "")).upper(),
                "fy": entry.get("fy"),
            }
        )
    return rows


def ttm_net_income_from_ytd_entry(entries: list[dict[str, Any]], current_ytd: dict[str, Any]) -> float | None:
    if 330 <= int(current_ytd["days"]) <= 380:
        return float(current_ytd["value"])

    prior_annual = pick_prior_annual_entry(entries, current_ytd)
    prior_ytd = pick_prior_ytd_entry(entries, current_ytd)
    if not prior_annual or not prior_ytd:
        return None
    return float(prior_annual["value"]) + float(current_ytd["value"]) - float(prior_ytd["value"])


def equity_value_for_reporting_node(company_facts: dict[str, Any], node: dict[str, Any]) -> float | None:
    for concept in ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]:
        entries = normalized_instant_entries(company_facts, concept)
        exact = [
            entry
            for entry in entries
            if entry["accn"] == node["accn"] and entry["end"] == node["end"]
        ]
        if exact:
            return float(sorted(exact, key=lambda item: item["filed"], reverse=True)[0]["value"])
    return None


def month_key(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def shift_year(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def reporting_node_label(entry: dict[str, Any]) -> str:
    fp = str(entry.get("fp") or "").upper()
    raw_fy = entry.get("fy")
    year = int(raw_fy) if isinstance(raw_fy, int) else entry["end"].year
    if fp in {"Q1", "Q2", "Q3"}:
        return f"{year} {fp}"
    return f"{year} Q4/FY"


def expected_ytd_days_for_fp(fp: str) -> tuple[int, int] | None:
    if fp == "Q1":
        return 70, 110
    if fp == "Q2":
        return 150, 210
    if fp == "Q3":
        return 230, 300
    if fp == "FY":
        return 330, 380
    return None


def build_quarterly_net_income_points(
    company_facts: dict[str, Any],
    latest_end: date | None = None,
    earliest_end: date | None = None,
) -> list[dict[str, Any]]:
    entries = normalized_duration_entries(company_facts, "NetIncomeLoss")
    calculation_earliest_end = shift_year(earliest_end, -1) if earliest_end else None
    ytd_by_period: dict[tuple[int, str], dict[str, Any]] = {}
    for entry in entries:
        fp = str(entry.get("fp") or "").upper()
        fy = entry.get("fy")
        if entry["form"] not in {"10-Q", "10-K"} or fp not in {"Q1", "Q2", "Q3", "FY"}:
            continue
        if not isinstance(fy, int):
            continue
        if latest_end and entry["end"] > latest_end:
            continue
        if calculation_earliest_end and entry["end"] < calculation_earliest_end:
            continue
        expected_days = expected_ytd_days_for_fp(fp)
        if expected_days is None or not (expected_days[0] <= int(entry["days"]) <= expected_days[1]):
            continue
        filing_lag_days = (entry["filed"] - entry["end"]).days
        max_lag_days = 180 if fp == "FY" else 120
        if filing_lag_days < 0 or filing_lag_days > max_lag_days:
            continue

        key = (fy, fp)
        current = ytd_by_period.get(key)
        if current is None or (entry["end"], entry["filed"]) > (current["end"], current["filed"]):
            ytd_by_period[key] = entry

    points: list[dict[str, Any]] = []
    for (fy, fp), entry in sorted(ytd_by_period.items(), key=lambda item: (item[1]["end"], item[1]["filed"])):
        prior_entry = None
        if fp == "Q1":
            quarter_value = float(entry["value"])
            source = "Q1 YTD"
        elif fp == "Q2":
            prior_entry = ytd_by_period.get((fy, "Q1"))
            if not prior_entry:
                continue
            quarter_value = float(entry["value"]) - float(prior_entry["value"])
            source = "Q2 YTD - Q1 YTD"
        elif fp == "Q3":
            prior_entry = ytd_by_period.get((fy, "Q2"))
            if not prior_entry:
                continue
            quarter_value = float(entry["value"]) - float(prior_entry["value"])
            source = "Q3 YTD - Q2 YTD"
        elif fp == "FY":
            prior_entry = ytd_by_period.get((fy, "Q3"))
            if not prior_entry:
                continue
            quarter_value = float(entry["value"]) - float(prior_entry["value"])
            source = "FY - Q3 YTD"
        else:
            continue

        points.append(
            {
                "period_label": reporting_node_label(entry),
                "report_date": entry["end"].isoformat(),
                "filing_date": entry["filed"].isoformat(),
                "end": entry["end"],
                "filed": entry["filed"],
                "accn": entry["accn"],
                "form": entry["form"],
                "fiscal_year": fy,
                "fiscal_period": fp,
                "quarter_net_income": quarter_value,
                "ytd_net_income": float(entry["value"]),
                "ytd_entry": entry,
                "prior_ytd_entry": prior_entry,
                "unit": "USD",
                "concept": f"NetIncomeLoss single quarter derived from {source}",
                "period": source,
            }
        )

    point_by_period = {
        (point["fiscal_year"], point["fiscal_period"]): point
        for point in points
    }
    for point in points:
        prior_point = None
        fiscal_year = int(point["fiscal_year"])
        fiscal_period = str(point["fiscal_period"])
        for prior_year in range(fiscal_year - 1, fiscal_year - 6, -1):
            candidate = point_by_period.get((prior_year, fiscal_period))
            if candidate and float(candidate["quarter_net_income"]) != 0:
                prior_point = candidate
                break
        if prior_point:
            point["yoy_growth_percent"] = (
                (float(point["quarter_net_income"]) - float(prior_point["quarter_net_income"]))
                / abs(float(prior_point["quarter_net_income"]))
            ) * 100
            point["yoy_base_period_label"] = prior_point["period_label"]
        else:
            point["yoy_growth_percent"] = None
            point["yoy_base_period_label"] = None
    return points


def reporting_period_pe_review_rows(
    company_facts: dict[str, Any],
    monthly_pe_rows: list[dict[str, Any]],
    daily_price_rows: list[dict[str, Any]],
    target_filing: Any,
    current_market_pe: float,
    current_market_value: float,
    buyback_base: float,
    dividend_ttm: float,
    equity_cost: float,
    terminal_growth: float,
    buyback_growth: float,
    dividend_growth: float,
    fade_rho: float,
    forecast_years: int,
    extension_years: int,
) -> list[dict[str, Any]]:
    price_rows = sorted(
        [
            {"date": row["date"], "close": float(row["close"])}
            for row in daily_price_rows
            if isinstance(row.get("date"), date) and isinstance(row.get("close"), (int, float)) and row["close"] > 0
        ],
        key=lambda row: row["date"],
    )
    if not price_rows:
        return []
    eps_entries = collect_diluted_eps_entries(company_facts)

    def previous_trading_price(filing_date: date) -> dict[str, Any] | None:
        cutoff = filing_date - timedelta(days=1)
        for row in reversed(price_rows):
            if row["date"] <= cutoff:
                return row
        return None

    net_income_entries = normalized_duration_entries(company_facts, "NetIncomeLoss")
    latest_end = parse_iso_date(target_filing.report_date)
    earliest_end = shift_year(latest_end, -5) if latest_end else date(1900, 1, 1)
    if latest_end is None:
        earliest_end = date(1900, 1, 1)

    candidates: list[dict[str, Any]] = []
    for point in build_quarterly_net_income_points(company_facts, latest_end=latest_end, earliest_end=earliest_end):
        entry = point["ytd_entry"]
        if point["end"] < earliest_end:
            continue
        ttm_net_income = ttm_net_income_from_ytd_entry(net_income_entries, entry)
        book_equity = equity_value_for_reporting_node(company_facts, entry)
        market_row = previous_trading_price(point["filed"])
        price_date = market_row["date"] if market_row else None
        close = market_row["close"] if market_row else None
        ttm_eps = latest_ttm_eps_as_of(eps_entries, price_date) if isinstance(price_date, date) else None
        pe = close / ttm_eps if isinstance(close, (int, float)) and isinstance(ttm_eps, (int, float)) and ttm_eps > 0 else None
        if not (
            isinstance(ttm_net_income, (int, float))
            and ttm_net_income > 0
            and isinstance(book_equity, (int, float))
            and book_equity > 0
            and isinstance(point.get("quarter_net_income"), (int, float))
            and isinstance(pe, (int, float))
            and pe > 0
            and isinstance(close, (int, float))
            and close > 0
        ):
            continue
        candidates.append(
            {
                "end": point["end"],
                "filed": point["filed"],
                "accn": point["accn"],
                "period_label": point["period_label"],
                "month": month_key(price_date),
                "price_date": price_date.isoformat(),
                "pe_source": "previous_trading_day",
                "pe": float(pe),
                "close": float(close),
                "ttm_eps": float(ttm_eps),
                "net_income_ttm": float(ttm_net_income),
                "quarter_net_income": float(point["quarter_net_income"]),
                "actual_growth_percent": point.get("yoy_growth_percent"),
                "fiscal_year": int(point["fiscal_year"]),
                "fiscal_period": str(point["fiscal_period"]),
                "book_equity": float(book_equity),
            }
        )

    deduped: dict[tuple[date, str], dict[str, Any]] = {}
    for candidate in sorted(candidates, key=lambda item: (item["end"], item["filed"])):
        key = (candidate["end"], candidate["period_label"])
        if key not in deduped:
            deduped[key] = candidate

    rows: list[dict[str, Any]] = []
    for row in list(deduped.values())[-20:]:
        pe = float(row["pe"])
        node_net_income_ttm = float(row["net_income_ttm"])
        node_book_equity = float(row["book_equity"])
        implied_market_value = pe * node_net_income_ttm
        node_decomposition_rows = build_historical_ni_decomposition_rows(company_facts, [], max_report_date=row["end"])
        node_fade_rho, _, _ = estimate_ni_fade_rho(node_decomposition_rows, terminal_growth)
        implied_spread, earnings_benchmark_path, _ = solve_pe_implied_earnings_benchmark_model(
            market_value=implied_market_value,
            net_income_ttm=node_net_income_ttm,
            book_equity=node_book_equity,
            buyback_base=buyback_base,
            dividend_ttm=dividend_ttm,
            equity_cost=equity_cost,
            terminal_growth=terminal_growth,
            buyback_growth=buyback_growth,
            dividend_growth=dividend_growth,
            fade_rho=node_fade_rho,
            forecast_years=forecast_years,
            extension_years=extension_years,
        )
        earnings_benchmark_growth = (
            float(earnings_benchmark_path[0]["net_income_growth"])
            if earnings_benchmark_path
            else None
        )
        rows.append(
            {
                "month": str(row.get("month", "")),
                "period_label": row.get("period_label"),
                "report_date": row["end"].isoformat(),
                "filing_date": row["filed"].isoformat(),
                "price_date": row.get("price_date"),
                "pe_source": row.get("pe_source"),
                "pe": pe,
                "close": row.get("close"),
                "ttm_eps": row.get("ttm_eps"),
                "pe_vs_current": pe / current_market_pe - 1 if current_market_pe else None,
                "market_value": implied_market_value,
                "market_value_vs_current": implied_market_value / current_market_value - 1 if current_market_value else None,
                "net_income_ttm": node_net_income_ttm,
                "quarter_net_income": float(row["quarter_net_income"]),
                "actual_growth_percent": row.get("actual_growth_percent"),
                "fiscal_year": row.get("fiscal_year"),
                "fiscal_period": row.get("fiscal_period"),
                "book_equity": node_book_equity,
                "buyback_yield": buyback_base / implied_market_value if implied_market_value else None,
                "fade_rho": node_fade_rho,
                "implied_roe_spread": implied_spread,
                "implied_growth": earnings_benchmark_growth,
                "pe_implied_growth": None,
            }
        )
    return rows


def annual_net_income_by_year(company_facts: dict[str, Any]) -> dict[int, dict[str, Any]]:
    entries = normalized_duration_entries(company_facts, "NetIncomeLoss")
    annual_entries = [
        entry
        for entry in entries
        if 330 <= int(entry["days"]) <= 380 and isinstance(entry.get("value"), (int, float))
    ]
    by_year: dict[int, dict[str, Any]] = {}
    for entry in annual_entries:
        fiscal_year = int(entry["end"].year)
        current = by_year.get(fiscal_year)
        if current is None or entry["filed"] > current["filed"]:
            by_year[fiscal_year] = entry
    return {
        year: {
            "value": float(entry["value"]),
            "end": entry["end"],
        }
        for year, entry in by_year.items()
    }


def annual_diluted_eps_by_year(company_facts: dict[str, Any]) -> dict[int, dict[str, Any]]:
    entries = collect_diluted_eps_entries(company_facts)
    annual_entries = [
        entry
        for entry in entries
        if 330 <= int(entry["days"]) <= 380 and isinstance(entry.get("value"), (int, float))
    ]
    by_year: dict[int, dict[str, Any]] = {}
    for entry in annual_entries:
        filing_lag_days = (entry["filed"] - entry["end"]).days
        if filing_lag_days < 0 or filing_lag_days > 180:
            continue
        fiscal_year = int(entry["end"].year)
        current = by_year.get(fiscal_year)
        if current is None or entry["filed"] > current["filed"]:
            by_year[fiscal_year] = entry
    return {
        year: {
            "value": float(entry["value"]),
            "end": entry["end"],
        }
        for year, entry in by_year.items()
    }


def pe_growth_review_chart_rows(
    company_facts: dict[str, Any],
    review_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in review_rows:
        fiscal_year = row.get("fiscal_year")
        if isinstance(fiscal_year, int) and fiscal_year < 2022:
            continue
        month = str(row.get("month", ""))
        actual_growth = row.get("actual_growth_percent")
        quarter_net_income = row.get("quarter_net_income")
        implied_growth = row.get("implied_growth")
        implied_roe_spread = row.get("implied_roe_spread")
        pe_implied_growth = row.get("pe_implied_growth")
        rows.append(
            {
                "month": month,
                "period_label": row.get("period_label"),
                "report_date": row.get("report_date"),
                "filing_date": row.get("filing_date"),
                "price_date": row.get("price_date"),
                "pe_source": row.get("pe_source"),
                "pe": row.get("pe"),
                "close": row.get("close"),
                "ttm_eps": row.get("ttm_eps"),
                "quarter_net_income": quarter_net_income,
                "implied_growth_percent": float(implied_growth) * 100 if isinstance(implied_growth, (int, float)) else None,
                "implied_roe_spread_percent": float(implied_roe_spread) * 100 if isinstance(implied_roe_spread, (int, float)) else None,
                "pe_implied_growth_percent": float(pe_implied_growth) * 100 if isinstance(pe_implied_growth, (int, float)) else None,
                "actual_growth_percent": float(actual_growth) if isinstance(actual_growth, (int, float)) else None,
                "actual_year": fiscal_year,
            }
        )
    return rows


def build_roe_wacc_accounting_path(
    net_income_ttm: float,
    book_equity: float,
    buyback_base: float,
    dividend_ttm: float,
    equity_cost: float,
    buyback_growth: float,
    dividend_growth: float,
    fade_rho: float,
    forecast_years: int,
) -> tuple[float, list[dict[str, float]]]:
    current_roe = net_income_ttm / book_equity
    current_spread = current_roe - equity_cost
    previous_net_income = net_income_ttm
    book_value = book_equity
    path: list[dict[str, float]] = []
    for year in range(1, forecast_years + 1):
        effective_spread = current_spread * (fade_rho ** year)
        roe = equity_cost + effective_spread
        net_income = roe * book_value
        net_income_growth = net_income / previous_net_income - 1 if previous_net_income else 0.0
        buyback = buyback_base * ((1 + buyback_growth) ** year)
        dividend = dividend_ttm * ((1 + dividend_growth) ** year)
        ending_book_value = book_value + net_income - buyback - dividend
        path.append(
            {
                "year": float(year),
                "current_roe": current_roe,
                "current_spread": current_spread,
                "effective_spread": effective_spread,
                "roe": roe,
                "net_income": net_income,
                "net_income_growth": net_income_growth,
                "beginning_book_value": book_value,
                "buyback": buyback,
                "dividend": dividend,
                "ending_book_value": ending_book_value,
            }
        )
        previous_net_income = net_income
        book_value = ending_book_value
    return current_spread, path


def clamp_growth(value: float, floor: float = NI_BASE_GROWTH_FLOOR, ceiling: float = NI_BASE_GROWTH_CEILING) -> float:
    return min(ceiling, max(floor, value))


def estimate_accounting_ni_base_growth(
    decomposition_rows: list[dict[str, float | str]],
    terminal_growth: float,
) -> tuple[float, dict[str, float]]:
    growths = [
        float(row["ni_growth"])
        for row in decomposition_rows
        if isinstance(row.get("ni_growth"), (int, float)) and math.isfinite(float(row["ni_growth"]))
    ]
    if not growths:
        return terminal_growth, {
            "observations": 0.0,
            "raw_average": terminal_growth,
            "winsorized_average": terminal_growth,
            "weighted_average": terminal_growth,
        }

    recent_growths = growths[-min(8, len(growths)) :]
    winsorized = [clamp_growth(value) for value in recent_growths]
    weights = list(range(1, len(winsorized) + 1))
    weighted_average = sum(value * weight for value, weight in zip(winsorized, weights)) / sum(weights)
    raw_average = sum(recent_growths) / len(recent_growths)
    winsorized_average = sum(winsorized) / len(winsorized)
    return weighted_average, {
        "observations": float(len(recent_growths)),
        "raw_average": raw_average,
        "winsorized_average": winsorized_average,
        "weighted_average": weighted_average,
    }


def build_accounting_ni_growth_path(
    net_income_ttm: float,
    book_equity: float,
    buyback_base: float,
    dividend_ttm: float,
    equity_cost: float,
    terminal_growth: float,
    buyback_growth: float,
    dividend_growth: float,
    fade_rho: float,
    base_growth: float,
    forecast_years: int,
) -> list[dict[str, float]]:
    previous_net_income = net_income_ttm
    book_value = book_equity
    path: list[dict[str, float]] = []
    for year in range(1, forecast_years + 1):
        growth = terminal_growth + (base_growth - terminal_growth) * (fade_rho ** (year - 1))
        net_income = previous_net_income * (1 + growth)
        buyback = buyback_base * ((1 + buyback_growth) ** year)
        dividend = dividend_ttm * ((1 + dividend_growth) ** year)
        roe = net_income / book_value if book_value else 0.0
        abnormal_earnings = net_income - equity_cost * book_value
        effective_spread = roe - equity_cost
        ending_book_value = book_value + net_income - buyback - dividend
        path.append(
            {
                "year": float(year),
                "base_growth": base_growth,
                "net_income_growth": growth,
                "net_income": net_income,
                "beginning_book_value": book_value,
                "roe": roe,
                "effective_spread": effective_spread,
                "abnormal_earnings": abnormal_earnings,
                "buyback": buyback,
                "dividend": dividend,
                "ending_book_value": ending_book_value,
            }
        )
        previous_net_income = net_income
        book_value = ending_book_value
    return path


def pe_premium_growth_from_multiple(pe: float, baseline_pe: float = BASELINE_PE_MULTIPLE) -> float:
    return (pe - baseline_pe) / 100.0


def build_pe_premium_ni_growth_path(
    net_income_ttm: float,
    pe: float,
    terminal_growth: float,
    fade_rho: float,
    forecast_years: int,
) -> tuple[float, float, list[dict[str, float]]]:
    premium_points = pe - BASELINE_PE_MULTIPLE
    base_growth = pe_premium_growth_from_multiple(pe)
    previous_net_income = net_income_ttm
    path: list[dict[str, float]] = []
    for year in range(1, forecast_years + 1):
        growth = terminal_growth + (base_growth - terminal_growth) * (fade_rho ** (year - 1))
        net_income = previous_net_income * (1 + growth)
        path.append(
            {
                "year": float(year),
                "pe": pe,
                "baseline_pe": BASELINE_PE_MULTIPLE,
                "premium_points": premium_points,
                "base_growth": base_growth,
                "net_income_growth": growth,
                "net_income": net_income,
            }
        )
        previous_net_income = net_income
    return premium_points, base_growth, path


def solve_pe_implied_earnings_benchmark_model(
    market_value: float,
    net_income_ttm: float,
    book_equity: float,
    buyback_base: float,
    dividend_ttm: float,
    equity_cost: float,
    terminal_growth: float,
    buyback_growth: float,
    dividend_growth: float,
    fade_rho: float,
    forecast_years: int = 10,
    extension_years: int = 10,
) -> tuple[float | None, list[dict[str, float]], dict[str, float] | None]:
    def faded_spread(initial_spread: float, year: int) -> float:
        return initial_spread * (fade_rho ** (year - 1))

    def explicit_spread(initial_spread: float, year: int) -> tuple[float, str]:
        if year <= forecast_years:
            return faded_spread(initial_spread, year), "rho"
        if extension_years <= 0:
            return faded_spread(initial_spread, forecast_years), "terminal"
        extension_start_spread = faded_spread(initial_spread, forecast_years)
        extension_step = year - forecast_years
        extension_weight = min(1.0, extension_step / extension_years)
        spread = extension_start_spread * (1 - extension_weight)
        return spread, "linear_to_wacc"

    def value_for(initial_spread: float) -> tuple[float, list[dict[str, float]], dict[str, float]] | None:
        book_value = book_equity
        previous_net_income = net_income_ttm
        pv_excess_earnings = 0.0
        path: list[dict[str, float]] = []
        explicit_years = forecast_years + max(0, extension_years)
        for year in range(1, explicit_years + 1):
            effective_spread, spread_stage = explicit_spread(initial_spread, year)
            abnormal_earnings = effective_spread * book_value
            net_income = equity_cost * book_value + abnormal_earnings
            net_income_growth = net_income / previous_net_income - 1 if previous_net_income else 0.0
            roe = net_income / book_value if book_value else 0.0
            buyback = buyback_base * ((1 + buyback_growth) ** year)
            dividend = dividend_ttm * ((1 + dividend_growth) ** year)
            pv_excess_earnings += abnormal_earnings / ((1 + equity_cost) ** year)
            ending_book_value = book_value + net_income - buyback - dividend
            path.append(
                {
                    "year": float(year),
                    "growth_stage": spread_stage,
                    "base_spread": initial_spread,
                    "base_abnormal_earnings": initial_spread * book_equity,
                    "allocation_weight": effective_spread / initial_spread if initial_spread else 0.0,
                    "effective_spread": effective_spread,
                    "roe": roe,
                    "net_income_growth": net_income_growth,
                    "net_income": net_income,
                    "beginning_book_value": book_value,
                    "buyback": buyback,
                    "dividend": dividend,
                    "ending_book_value": ending_book_value,
                    "abnormal_earnings": abnormal_earnings,
                }
            )
            if not all(math.isfinite(value) for value in [net_income, abnormal_earnings, ending_book_value]):
                return None
            previous_net_income = net_income
            book_value = ending_book_value

        terminal_spread = path[-1]["effective_spread"] if path else initial_spread
        terminal_abnormal_earnings = terminal_spread * book_value
        terminal_value = terminal_abnormal_earnings / (equity_cost - terminal_growth)
        terminal = {
            "year": float(explicit_years + 1),
            "growth": terminal_growth,
            "base_spread": initial_spread,
            "base_abnormal_earnings": initial_spread * book_equity,
            "fade_rho": fade_rho,
            "rho_years": float(forecast_years),
            "extension_years": float(max(0, extension_years)),
            "explicit_years": float(explicit_years),
            "beginning_book_value": book_value,
            "allocation_weight": terminal_spread / initial_spread if initial_spread else 0.0,
            "effective_spread": terminal_spread,
            "roe": equity_cost + terminal_spread,
            "abnormal_earnings": terminal_abnormal_earnings,
            "terminal_value": terminal_value,
            "pv_terminal": terminal_value / ((1 + equity_cost) ** explicit_years),
        }
        value = book_equity + pv_excess_earnings + terminal["pv_terminal"]
        if not math.isfinite(value):
            return None
        return value, path, terminal

    if equity_cost <= terminal_growth or book_equity <= 0:
        return None, [], None

    candidates: list[tuple[float, float]] = []
    search_low, search_high = -equity_cost + 0.0001, 5.00
    for index in range(1501):
        candidate_spread = search_low + (search_high - search_low) * index / 1500
        result = value_for(candidate_spread)
        if result is not None:
            candidates.append((candidate_spread, result[0]))

    bracket: tuple[float, float] | None = None
    for left, right in zip(candidates, candidates[1:]):
        if (left[1] - market_value) * (right[1] - market_value) <= 0:
            bracket = (left[0], right[0])
            break
    if bracket is None:
        return None, [], None

    low, high = bracket
    for _ in range(120):
        mid = (low + high) / 2
        result = value_for(mid)
        if result is None:
            low = mid
            continue
        mid_value = result[0]
        if mid_value < market_value:
            low = mid
        else:
            high = mid

    solved_initial_spread = (low + high) / 2
    solved_result = value_for(solved_initial_spread)
    if solved_result is None:
        return None, [], None
    _, path, terminal = solved_result
    terminal["model_value"] = market_value
    return solved_initial_spread, path, terminal


def historical_ttm_capital_returns(
    company_facts: dict[str, Any],
    filings: list[Any],
    concepts: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for historical_filing in sorted(filings, key=lambda item: item.report_date):
        value, concept = extract_ttm_value(company_facts, historical_filing, concepts)
        if isinstance(value, (int, float)):
            rows.append(
                {
                    "report_date": historical_filing.report_date,
                    "value": abs(float(value)),
                    "concept": concept,
                }
            )
    return rows[-CAPITAL_RETURN_HISTORY_PERIODS:]


def average_growth_rate(rows: list[dict[str, Any]]) -> float | None:
    if len(rows) < CAPITAL_RETURN_HISTORY_PERIODS:
        return None
    growth_rates: list[float] = []
    for prior, current in zip(rows, rows[1:]):
        prior_value = float(prior["value"])
        if prior_value <= 0:
            return None
        growth_rates.append(float(current["value"]) / prior_value - 1)
    return sum(growth_rates) / len(growth_rates) if growth_rates else None


def format_historical_amounts(rows: list[dict[str, Any]]) -> str:
    return "；".join(
        f"{row['report_date']} {format_fact_value(row['value'], 'USD')}"
        for row in rows
    )


def format_pp(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    return f"{value * 100:+,.1f}pp"


def format_abs_pp(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    return f"{abs(value) * 100:,.1f}pp"


def format_score(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    return f"{value:.2f}"


def median(values: list[float]) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    midpoint = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[midpoint]
    return (sorted_values[midpoint - 1] + sorted_values[midpoint]) / 2


def population_stdev(values: list[float]) -> float | None:
    if not values:
        return None
    average = sum(values) / len(values)
    variance = sum((value - average) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def ttm_value_from_ytd_entry(entries: list[dict[str, Any]], current_ytd: dict[str, Any]) -> float | None:
    if 330 <= int(current_ytd["days"]) <= 380:
        return float(current_ytd["value"])

    prior_annual = pick_prior_annual_entry(entries, current_ytd)
    prior_ytd = pick_prior_ytd_entry(entries, current_ytd)
    if prior_annual and prior_ytd:
        return float(prior_annual["value"]) + float(current_ytd["value"]) - float(prior_ytd["value"])
    return None


def pick_reporting_ytd_entry(
    company_facts: dict[str, Any],
    node: dict[str, Any],
    concepts: list[str],
) -> tuple[float | None, str | None]:
    for concept in concepts:
        entries = normalized_duration_entries(company_facts, concept)
        exact = [
            entry
            for entry in entries
            if entry["accn"] == node["accn"]
            and entry["end"] == node["end"]
            and entry.get("fy") == node.get("fy")
            and entry.get("fp") == node.get("fp")
        ]
        if not exact:
            exact = [
                entry
                for entry in entries
                if entry["accn"] == node["accn"]
                and entry["end"] == node["end"]
            ]
        if not exact:
            continue
        current_ytd = sorted(exact, key=lambda item: (int(item["days"]), item["filed"]), reverse=True)[0]
        ttm_value = ttm_value_from_ytd_entry(entries, current_ytd)
        if isinstance(ttm_value, (int, float)):
            return ttm_value, concept
    return None, None


def build_reporting_nodes_from_company_facts(
    company_facts: dict[str, Any],
    max_report_date: date | None,
    lookback_years: int = 5,
) -> list[dict[str, Any]]:
    net_income_entries = normalized_duration_entries(company_facts, "NetIncomeLoss")
    if max_report_date is None:
        dated_entries = [entry for entry in net_income_entries if entry["form"] in {"10-Q", "10-K"}]
        max_report_date = max((entry["end"] for entry in dated_entries), default=None)
    if max_report_date is None:
        return []
    earliest_end = shift_year(max_report_date, -lookback_years)

    nodes: dict[tuple[date, int, str], dict[str, Any]] = {}
    for entry in net_income_entries:
        if entry["form"] not in {"10-Q", "10-K"}:
            continue
        if entry["end"] < earliest_end or entry["end"] > max_report_date:
            continue
        if entry.get("fp") not in {"Q1", "Q2", "Q3", "FY"}:
            continue
        if not isinstance(entry.get("fy"), int):
            continue
        expected_days = expected_ytd_days_for_fp(str(entry["fp"]))
        if expected_days is None or not (expected_days[0] <= int(entry["days"]) <= expected_days[1]):
            continue
        filing_lag_days = (entry["filed"] - entry["end"]).days
        max_lag_days = 180 if entry["fp"] == "FY" else 120
        if filing_lag_days < 0 or filing_lag_days > max_lag_days:
            continue
        key = (entry["end"], int(entry["fy"]), str(entry["fp"]))
        current = nodes.get(key)
        if current is None or entry["filed"] < current["filed"]:
            nodes[key] = entry

    return sorted(nodes.values(), key=lambda item: (item["end"], item["filed"]))[-20:]


def build_historical_ni_decomposition_rows(
    company_facts: dict[str, Any],
    filings: list[Any],
    max_report_date: date | None = None,
) -> list[dict[str, float | str]]:
    snapshots: list[dict[str, Any]] = []
    if max_report_date is None:
        report_dates = [
            report_date
            for report_date in (parse_iso_date(filing.report_date) for filing in filings)
            if report_date is not None
        ]
        max_report_date = max(report_dates, default=None)
    reporting_nodes = build_reporting_nodes_from_company_facts(company_facts, max_report_date)
    for node in reporting_nodes:
        revenue, _ = pick_reporting_ytd_entry(
            company_facts,
            node,
            ["RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "Revenues"],
        )
        gross_profit, _ = pick_reporting_ytd_entry(company_facts, node, ["GrossProfit"])
        operating_income, _ = pick_reporting_ytd_entry(company_facts, node, ["OperatingIncomeLoss"])
        net_income, _ = pick_reporting_ytd_entry(company_facts, node, ["NetIncomeLoss"])
        if not all(
            isinstance(value, (int, float)) and value > 0
            for value in [revenue, gross_profit, operating_income, net_income]
        ):
            continue
        snapshots.append(
            {
                "report_date": node["end"].isoformat(),
                "period_label": reporting_node_label(node),
                "revenue": float(revenue),
                "gross_margin": float(gross_profit) / float(revenue),
                "operating_to_gross": float(operating_income) / float(gross_profit),
                "net_income_conversion": float(net_income) / float(operating_income),
                "net_income": float(net_income),
            }
        )

    rows: list[dict[str, float | str]] = []
    for prior, current in zip(snapshots, snapshots[1:]):
        revenue_growth = float(current["revenue"]) / float(prior["revenue"]) - 1
        gross_margin_delta = float(current["gross_margin"]) - float(prior["gross_margin"])
        revenue_contribution = math.log(float(current["revenue"]) / float(prior["revenue"]))
        gross_margin_contribution = math.log(float(current["gross_margin"]) / float(prior["gross_margin"]))
        operating_conversion_contribution = math.log(
            float(current["operating_to_gross"]) / float(prior["operating_to_gross"])
        )
        net_conversion_contribution = math.log(
            float(current["net_income_conversion"]) / float(prior["net_income_conversion"])
        )
        ni_log_growth = math.log(float(current["net_income"]) / float(prior["net_income"]))
        ni_growth = float(current["net_income"]) / float(prior["net_income"]) - 1
        rows.append(
            {
                "report_date": str(current["report_date"]),
                "period_label": str(current.get("period_label") or current["report_date"]),
                "ni_growth": ni_growth,
                "ni_log_growth": ni_log_growth,
                "revenue_growth": revenue_growth,
                "gross_margin_delta": gross_margin_delta,
                "revenue_contribution": revenue_contribution,
                "gross_margin_contribution": gross_margin_contribution,
                "operating_conversion_contribution": operating_conversion_contribution,
                "net_conversion_contribution": net_conversion_contribution,
            }
        )
    return rows


def estimate_ni_fade_rho(
    decomposition_rows: list[dict[str, float | str]],
    terminal_growth: float,
) -> tuple[float, str, dict[str, float | int | str]]:
    revenue_growths = [
        float(row["revenue_growth"])
        for row in decomposition_rows
        if isinstance(row.get("revenue_growth"), (int, float))
    ]
    gross_margin_deltas = [
        float(row["gross_margin_delta"])
        for row in decomposition_rows
        if isinstance(row.get("gross_margin_delta"), (int, float))
    ]
    sales_growth_changes = [
        current - prior
        for prior, current in zip(revenue_growths, revenue_growths[1:])
    ]
    if len(sales_growth_changes) < 2 or len(gross_margin_deltas) < 3:
        details: dict[str, float | int | str] = {
            "observations": len(decomposition_rows),
            "sales_growth_change_observations": len(sales_growth_changes),
            "avg_abs_sales_growth_change": float("nan"),
            "avg_abs_gross_margin_change": float("nan"),
            "sales_growth_stability": float("nan"),
            "gross_margin_stability": float("nan"),
            "combined_stability": float("nan"),
        }
        return DEFAULT_NI_FADE_RHO, "可用历史观察不足，暂用默认 rho=0.75。", details

    avg_abs_sales_growth_change = sum(abs(value) for value in sales_growth_changes) / len(sales_growth_changes)
    avg_abs_gross_margin_change = sum(abs(value) for value in gross_margin_deltas) / len(gross_margin_deltas)
    sales_growth_stability = min(
        1.0,
        max(0.0, 1 - avg_abs_sales_growth_change / RHO_SALES_GROWTH_CHANGE_FULL_PENALTY),
    )
    gross_margin_stability = min(
        1.0,
        max(0.0, 1 - avg_abs_gross_margin_change / RHO_GROSS_MARGIN_CHANGE_FULL_PENALTY),
    )
    combined_stability = 0.65 * sales_growth_stability + 0.35 * gross_margin_stability
    rho = RHO_MIN + RHO_RANGE * combined_stability
    details = {
        "observations": len(revenue_growths),
        "sales_growth_change_observations": len(sales_growth_changes),
        "avg_abs_sales_growth_change": avg_abs_sales_growth_change,
        "avg_abs_gross_margin_change": avg_abs_gross_margin_change,
        "sales_growth_stability": sales_growth_stability,
        "gross_margin_stability": gross_margin_stability,
        "combined_stability": combined_stability,
    }
    note = (
        "用过去五年连续季度形成的滚动TTM序列估计："
        "收入增速变化越小、毛利率平均变动越小，成熟公司超额 NI 增长衰减越慢。"
    )
    return rho, note, details


def build_implied_growth_rows(
    company_facts: dict[str, Any],
    filing: Any,
    monthly_pe_rows: list[dict[str, Any]],
    comparison_filings: list[Any],
) -> list[dict[str, str]]:
    market_pe = latest_market_pe(monthly_pe_rows)
    revenue_ttm, revenue_concept = extract_ttm_value(
        company_facts,
        filing,
        ["RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "Revenues"],
    )
    gross_profit_ttm, gross_profit_concept = extract_ttm_value(company_facts, filing, ["GrossProfit"])
    operating_income_ttm, operating_income_concept = extract_ttm_value(company_facts, filing, ["OperatingIncomeLoss"])
    net_income_ttm, net_income_concept = extract_ttm_value(company_facts, filing, ["NetIncomeLoss"])
    buyback_history = historical_ttm_capital_returns(
        company_facts,
        comparison_filings,
        ["PaymentsForRepurchaseOfCommonStock", "StockRepurchasedAndRetiredDuringPeriodValue"],
    )
    dividend_history = historical_ttm_capital_returns(
        company_facts,
        comparison_filings,
        ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock", "Dividends"],
    )
    equity_entry = extract_equity_entry(company_facts, filing)
    book_equity = equity_entry["raw_value"] if equity_entry else None

    market_value = float(market_pe) * float(net_income_ttm) if isinstance(market_pe, (int, float)) and market_pe > 0 and isinstance(net_income_ttm, (int, float)) else None
    required_values = [market_pe, net_income_ttm, book_equity, market_value]
    if not all(isinstance(value, (int, float)) and value > 0 for value in required_values):
        return [{"item": "模型状态", "value": "缺少动态 PE、TTM 净利润或期末股东权益，暂不能做收益基准 PE 隐含净利润路径模型。"}]

    buyback_base = sum(float(row["value"]) for row in buyback_history) / len(buyback_history) if buyback_history else 0.0
    dividend_growth = average_growth_rate(dividend_history)
    if dividend_growth is None:
        dividend_growth = CURRENT_INFLATION_RATE

    dividend_ttm = float(dividend_history[-1]["value"]) if dividend_history else 0.0
    gross_margin = float(gross_profit_ttm) / float(revenue_ttm) if isinstance(gross_profit_ttm, (int, float)) and isinstance(revenue_ttm, (int, float)) and revenue_ttm else None
    operating_margin = float(operating_income_ttm) / float(revenue_ttm) if isinstance(operating_income_ttm, (int, float)) and isinstance(revenue_ttm, (int, float)) and revenue_ttm else None
    net_income_conversion = float(net_income_ttm) / float(operating_income_ttm) if isinstance(operating_income_ttm, (int, float)) and operating_income_ttm else None
    ni_decomposition_rows = build_historical_ni_decomposition_rows(company_facts, comparison_filings)
    fade_rho, fade_rho_note, fade_rho_details = estimate_ni_fade_rho(
        ni_decomposition_rows,
        CURRENT_INFLATION_RATE,
    )
    solved_initial_spread, path, terminal = solve_pe_implied_earnings_benchmark_model(
        market_value=float(market_value),
        net_income_ttm=float(net_income_ttm),
        book_equity=float(book_equity),
        buyback_base=buyback_base,
        dividend_ttm=dividend_ttm,
        equity_cost=DEFAULT_EQUITY_COST,
        terminal_growth=CURRENT_INFLATION_RATE,
        buyback_growth=CURRENT_INFLATION_RATE,
        dividend_growth=dividend_growth,
        fade_rho=fade_rho,
        forecast_years=IMPLIED_NI_FORECAST_YEARS,
        extension_years=LINEAR_NI_GROWTH_EXTENSION_YEARS,
    )

    concise_rows = [
        {
            "item": "模型名称",
            "value": "基于收益基准的 PE 隐含净利润路径模型",
        },
        {
            "item": "PE 输入",
            "value": (
                f"PE = {float(market_pe):,.1f}x；NI₀ = {format_fact_value(net_income_ttm, 'USD')}；"
                f"MV_PE = PE × NI₀ = {format_fact_value(market_value, 'USD')}"
            ),
        },
        {
            "item": "收益基准",
            "value": (
                f"BVE₀ = {format_fact_value(book_equity, 'USD')}；"
                f"收益 NI₁ = 10% × BVE₀ = {format_fact_value(DEFAULT_EQUITY_COST * float(book_equity), 'USD')}"
            ),
        },
        {
            "item": "求解公式",
            "value": (
                "求 initial spread，使 MV_PE = BVE₀ + Σ[(spread_t × BVE_(t-1)) / (1 + re)^t] + PV(终值)；"
                "NI_t = (re + spread_t) × BVE_(t-1)。"
            ),
        },
        {
            "item": "rho",
            "value": (
                f"{fade_rho:.2f}；rho = {RHO_MIN:.2f} + {RHO_RANGE:.2f} × "
                "(65% × 收入增速稳定分 + 35% × 毛利率稳定分)；spread_t = initial spread × rho^(t-1)"
            ),
        },
        {"item": "terminal growth", "value": CURRENT_INFLATION_LABEL},
    ]
    if solved_initial_spread is None or not path or terminal is None:
        concise_rows.append({"item": "模型状态", "value": "收益基准 PE 隐含净利润路径求解失败。"})
        return concise_rows

    first_year = path[0]
    ni1 = float(first_year["net_income"])
    implied_ni_growth1 = float(first_year["net_income_growth"])
    concise_rows.extend(
        [
            {"item": "隐含 initial spread", "value": display_percent(float(solved_initial_spread)) or "—"},
            {"item": "Year 1 总 NI 增长", "value": f"g₁ = {display_percent(implied_ni_growth1) or '—'}"},
            {
                "item": "明年 NI 代数",
                "value": (
                    f"NI₁ = (10% + spread₁) × BVE₀ = "
                    f"(10% + {display_percent(float(solved_initial_spread)) or '—'}) × "
                    f"{format_fact_value(book_equity, 'USD')} = {format_fact_value(ni1, 'USD')}"
                ),
            },
            {
                "item": "资本回报滚动",
                "value": "BVE_t = BVE_(t-1) + NI_t - Buyback_t - Dividend_t；回购按 CPI 增长，分红按历史平均增长率。",
            },
        ]
    )
    return concise_rows

    rows = [
        {"item": "市场 PE", "value": f"{market_pe:,.1f}x（使用动态 PE 图中的最新月度点）"},
        {"item": "市场隐含市值", "value": format_fact_value(market_value, "USD")},
        {"item": "TTM 收入", "value": f"{format_fact_value(revenue_ttm, 'USD')}（{revenue_concept or '—'}）"},
        {"item": "TTM 毛利率", "value": f"{display_percent(gross_margin) or '—'}（{gross_profit_concept or '—'} / 收入）"},
        {"item": "TTM 营业利润率", "value": f"{display_percent(operating_margin) or '—'}（{operating_income_concept or '—'} / 收入）"},
        {"item": "NI / 营业利润转换率", "value": f"{display_percent(net_income_conversion) or '—'}（不单独预测 tax/interest）"},
        {"item": "TTM 净利润", "value": f"{format_fact_value(net_income_ttm, 'USD')}（{net_income_concept or '—'}）"},
        {"item": "期末股东权益", "value": format_fact_value(book_equity, "USD")},
        {"item": "历史 TTM 回购", "value": format_historical_amounts(buyback_history)},
        {"item": "回购预测基准", "value": f"5 个同期间 TTM 金额算术平均：{format_fact_value(buyback_base, 'USD')}"},
        {"item": "回购年增长", "value": CURRENT_INFLATION_LABEL},
        {"item": "历史 TTM 分红", "value": format_historical_amounts(dividend_history)},
        {"item": "分红年增长", "value": f"过去 4 个同比增长率算术平均：{dividend_growth * 100:,.2f}%"},
        {"item": "收益率 re", "value": f"{DEFAULT_EQUITY_COST * 100:.1f}%（按指定的 10%；用于收益 NI = re × 期初权益）"},
        {"item": "当前超额收益金额", "value": f"TTM NI - 10% × 当前权益 = {format_fact_value(float(net_income_ttm) - DEFAULT_EQUITY_COST * float(book_equity), 'USD')}"},
        {"item": "历史估计 NI 衰减 rho", "value": f"{fade_rho:.2f}；{fade_rho_note}"},
        {
            "item": "rho 计算公式",
            "value": (
                f"sales_stability = 1 - 平均|Δ收入增速| / {RHO_SALES_GROWTH_CHANGE_FULL_PENALTY * 100:.0f}pp；"
                f"gm_stability = 1 - 平均|Δ毛利率| / {RHO_GROSS_MARGIN_CHANGE_FULL_PENALTY * 100:.0f}pp；"
                f"rho = {RHO_MIN:.2f} + {RHO_RANGE:.2f} × (65% × sales_stability + 35% × gm_stability)。"
            ),
        },
        {
            "item": "rho 元素",
            "value": (
                f"样本 {int(fade_rho_details['observations'])} 个滚动TTM节点观察；"
                f"收入增速变化样本 {int(fade_rho_details['sales_growth_change_observations'])} 个；"
                f"平均|Δ收入增速| {format_abs_pp(float(fade_rho_details['avg_abs_sales_growth_change']))}，"
                f"稳定分 {format_score(float(fade_rho_details['sales_growth_stability']))}；"
                f"平均|Δ毛利率| {format_abs_pp(float(fade_rho_details['avg_abs_gross_margin_change']))}，"
                f"稳定分 {format_score(float(fade_rho_details['gross_margin_stability']))}；"
                f"综合稳定分 {format_score(float(fade_rho_details['combined_stability']))}"
            ),
        },
        {
            "item": "明确预测期",
            "value": (
                f"Year 1-{IMPLIED_NI_FORECAST_YEARS}：反推 Year 1 NI 增长率，之后用历史拆解估计的 rho 衰减超额增长；"
                f"Year {IMPLIED_NI_FORECAST_YEARS + 1}-{IMPLIED_NI_FORECAST_YEARS + LINEAR_NI_GROWTH_EXTENSION_YEARS}："
                f"把 NI 增长率线性延长并收敛到 {CURRENT_INFLATION_RATE * 100:.1f}%。"
            ),
        },
        {"item": "终值", "value": f"Year {IMPLIED_NI_FORECAST_YEARS + LINEAR_NI_GROWTH_EXTENSION_YEARS + 1} 的 NI 按 {CURRENT_INFLATION_RATE * 100:.1f}% 增长，并用对应超额收益金额在 Year {IMPLIED_NI_FORECAST_YEARS + LINEAR_NI_GROWTH_EXTENSION_YEARS} 末资本化"},
    ]

    for decomposition_row in ni_decomposition_rows:
        rows.append(
            {
                "item": f"滚动TTM NI拆解 {decomposition_row.get('period_label') or decomposition_row['report_date']}",
                "value": (
                    f"NI增长 {display_percent(float(decomposition_row['ni_growth'])) or '—'}；"
                    f"收入增长 {display_percent(float(decomposition_row['revenue_growth'])) or '—'}；"
                    f"毛利率变化 {format_pp(float(decomposition_row['gross_margin_delta']))}；"
                    f"收入贡献 {format_pp(float(decomposition_row['revenue_contribution']))}；"
                    f"毛利率贡献 {format_pp(float(decomposition_row['gross_margin_contribution']))}；"
                    f"营业转换贡献 {format_pp(float(decomposition_row['operating_conversion_contribution']))}；"
                    f"NI转换贡献 {format_pp(float(decomposition_row['net_conversion_contribution']))}"
                ),
            }
        )

    if solved_initial_growth is None or not path or terminal is None:
        rows.append({"item": "模型状态", "value": "在 -90% 到 300% 的 Year 1 NI 增长率范围内未找到可解释市场价格的解。"})
        return rows

    rows.append({"item": "市场隐含 Year 1 NI增长", "value": display_percent(solved_initial_growth) or "—"})
    rows.append({"item": "NI增长衰减", "value": f"Year 1 为 {display_percent(solved_initial_growth) or '—'}；rho={fade_rho:.2f}；Year {IMPLIED_NI_FORECAST_YEARS + LINEAR_NI_GROWTH_EXTENSION_YEARS} 线性收敛到 {CURRENT_INFLATION_RATE * 100:.1f}%；Year {IMPLIED_NI_FORECAST_YEARS + LINEAR_NI_GROWTH_EXTENSION_YEARS + 1} 进入终值。"})
    rho_stage_path = [
        item
        for item in path
        if int(item["year"]) <= IMPLIED_NI_FORECAST_YEARS
    ]
    rows.append(
        {
            "item": "前10年增长路径",
            "value": (
                f"公式：gₜ = {CURRENT_INFLATION_RATE * 100:.1f}% + "
                f"({display_percent(solved_initial_growth) or '—'} - {CURRENT_INFLATION_RATE * 100:.1f}%) × "
                f"{fade_rho:.2f}^(t-1)；"
                + "；".join(
                    f"Y{int(item['year'])} {display_percent(float(item['net_income_growth'])) or '—'}"
                    for item in rho_stage_path
                )
            ),
        }
    )
    for item in path:
        net_income_growth = float(item["net_income_growth"])
        rows.append(
            {
                "item": f"Year {int(item['year'])}",
                "value": (
                    f"推导 NI {format_fact_value(item['net_income'], 'USD')}；"
                    f"NI增长 {display_percent(net_income_growth) or '—'}；"
                    f"spread收益额 {format_fact_value(item['abnormal_earnings'], 'USD')}；"
                    f"ROE {item['roe'] * 100:,.1f}%；"
                    f"回购 {format_fact_value(item['buyback'], 'USD')}；"
                    f"分红 {format_fact_value(item['dividend'], 'USD')}；"
                    f"期末权益 {format_fact_value(item['ending_book_value'], 'USD')}"
                ),
            }
        )
    rows.append(
        {
            "item": f"Year {int(terminal['year'])} 终值入口",
            "value": (
                f"NI {format_fact_value(terminal['net_income'], 'USD')}；"
                f"NI增长 {display_percent(terminal['net_income_growth']) or '—'}；"
                f"ROE {terminal['roe'] * 100:,.1f}%；"
                f"spread收益额 {format_fact_value(terminal['abnormal_earnings'], 'USD')}；"
                f"Year {int(terminal['explicit_years'])} 末终值 {format_fact_value(terminal['terminal_value'], 'USD')}；"
                f"终值现值 {format_fact_value(terminal['pv_terminal'], 'USD')}"
            ),
        }
    )
    rows.append({"item": "模型公式", "value": f"MV_PE = PE × TTM NI；收益 NI_t = 10% × BVE_(t-1)；NI_t = (10% + spread_t) × BVE_(t-1)；spread_t 前 {IMPLIED_NI_FORECAST_YEARS} 年按 rho 衰减，之后 {LINEAR_NI_GROWTH_EXTENSION_YEARS} 年线性收敛到 0。"})
    rows.append({"item": "资本回报影响", "value": "回购与分红直接扣减期末权益，进而影响以后年度收益 NI、推导ROE和终值；回购按 CPI 增长，分红按历史平均增长率。"})
    rows.append({"item": "口径提醒", "value": f"历史收入、毛利率、营业转换和NI转换只用于拆解过去 NI 增长结构、估计衰减速度；未来显性预测直接使用 NI 增长路径。Year {IMPLIED_NI_FORECAST_YEARS + LINEAR_NI_GROWTH_EXTENSION_YEARS + 1} 是终值入口，不是额外普通预测年。"})
    rows.append(
        {
            "item": "季度PE复查口径",
            "value": (
                "取过去五年 10-Q/10-K 披露节点；每个节点使用当时 TTM NI、期末BVE和披露日前一交易日 PE，"
                "保持rho、回购/分红增长和折现率假设不变，重新反推 Year 1 总NI增长。"
            ),
        }
    )
    for review in reporting_period_pe_review_rows(
        company_facts=company_facts,
        monthly_pe_rows=monthly_pe_rows,
        daily_price_rows=[],
        target_filing=filing,
        current_market_pe=float(market_pe),
        current_market_value=market_value,
        buyback_base=buyback_base,
        dividend_ttm=dividend_ttm,
        equity_cost=DEFAULT_EQUITY_COST,
        terminal_growth=CURRENT_INFLATION_RATE,
        buyback_growth=CURRENT_INFLATION_RATE,
        dividend_growth=dividend_growth,
        fade_rho=fade_rho,
        forecast_years=IMPLIED_NI_FORECAST_YEARS,
        extension_years=LINEAR_NI_GROWTH_EXTENSION_YEARS,
    ):
        implied_growth = review["implied_growth"]
        rows.append(
            {
                "item": f"季度PE复查 {review['month']}",
                "value": (
                    f"{review.get('period_label') or review['month']}；"
                    f"PE {review['pe']:,.1f}x；"
                    f"相对当前PE {display_percent(review['pe_vs_current']) or '—'}；"
                    f"隐含市值 {format_fact_value(review['market_value'], 'USD')}；"
                    f"反推下一年NI增长 {display_percent(implied_growth) if isinstance(implied_growth, (int, float)) else '无解'}"
                ),
            }
        )
    return rows


def build_pe_growth_review_rows(
    company_facts: dict[str, Any],
    filing: Any,
    monthly_pe_rows: list[dict[str, Any]],
    comparison_filings: list[Any],
) -> list[dict[str, Any]]:
    market_pe = latest_market_pe(monthly_pe_rows)
    net_income_ttm, _ = extract_ttm_value(company_facts, filing, ["NetIncomeLoss"])
    buyback_history = historical_ttm_capital_returns(
        company_facts,
        comparison_filings,
        ["PaymentsForRepurchaseOfCommonStock", "StockRepurchasedAndRetiredDuringPeriodValue"],
    )
    dividend_history = historical_ttm_capital_returns(
        company_facts,
        comparison_filings,
        ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock", "Dividends"],
    )
    equity_entry = extract_equity_entry(company_facts, filing)
    book_equity = equity_entry["raw_value"] if equity_entry else None
    if not all(isinstance(value, (int, float)) and value > 0 for value in [market_pe, net_income_ttm, book_equity]):
        return []
    if len(buyback_history) < CAPITAL_RETURN_HISTORY_PERIODS or len(dividend_history) < CAPITAL_RETURN_HISTORY_PERIODS:
        return []

    dividend_growth = average_growth_rate(dividend_history)
    if dividend_growth is None:
        return []

    buyback_base = sum(float(row["value"]) for row in buyback_history) / len(buyback_history)
    dividend_ttm = float(dividend_history[-1]["value"])
    sorted_filings = sorted(comparison_filings, key=lambda item: item.filing_date)
    first_filing_date = parse_iso_date(sorted_filings[0].filing_date) if sorted_filings else parse_iso_date(filing.filing_date)
    last_filing_date = parse_iso_date(filing.filing_date)
    if not first_filing_date or not last_filing_date:
        return []
    daily_price_rows = fetch_yahoo_daily_prices(
        filing.ticker,
        first_filing_date - timedelta(days=10),
        last_filing_date,
    )
    ni_decomposition_rows = build_historical_ni_decomposition_rows(company_facts, comparison_filings)
    fade_rho, _, _ = estimate_ni_fade_rho(ni_decomposition_rows, CURRENT_INFLATION_RATE)
    review_rows = reporting_period_pe_review_rows(
        company_facts=company_facts,
        monthly_pe_rows=monthly_pe_rows,
        daily_price_rows=daily_price_rows,
        target_filing=filing,
        current_market_pe=float(market_pe),
        current_market_value=float(market_pe) * float(net_income_ttm),
        buyback_base=buyback_base,
        dividend_ttm=dividend_ttm,
        equity_cost=DEFAULT_EQUITY_COST,
        terminal_growth=CURRENT_INFLATION_RATE,
        buyback_growth=CURRENT_INFLATION_RATE,
        dividend_growth=dividend_growth,
        fade_rho=fade_rho,
        forecast_years=IMPLIED_NI_FORECAST_YEARS,
        extension_years=LINEAR_NI_GROWTH_EXTENSION_YEARS,
    )
    return pe_growth_review_chart_rows(company_facts, review_rows)


def eps_duration_days(entry: dict[str, Any]) -> int | None:
    return duration_days(entry)


def collect_diluted_eps_entries(company_facts: dict[str, Any]) -> list[dict[str, Any]]:
    facts = company_facts.get("facts", {}).get("us-gaap", {})
    payload = facts.get("EarningsPerShareDiluted")
    if not payload:
        return []
    entries = payload.get("units", {}).get("USD/shares") or []
    rows: list[dict[str, Any]] = []
    for entry in entries:
        value = entry.get("val")
        filed = parse_iso_date(str(entry.get("filed", "")))
        end = parse_iso_date(str(entry.get("end", "")))
        days = eps_duration_days(entry)
        if not isinstance(value, (int, float)) or not filed or not end or days is None:
            continue
        form = str(entry.get("form", "")).upper()
        rows.append(
            {
                "value": float(value),
                "filed": filed,
                "end": end,
                "days": days,
                "form": form,
                "fp": str(entry.get("fp", "")).upper(),
                "fy": entry.get("fy"),
            }
        )
    rows.sort(key=lambda item: (item["filed"], item["end"]))
    return rows


def latest_ttm_eps_as_of(eps_entries: list[dict[str, Any]], as_of: date) -> float | None:
    available = [entry for entry in eps_entries if entry["filed"] <= as_of and entry["end"] <= as_of]
    if not available:
        return None

    annual_entries = [entry for entry in available if 330 <= entry["days"] <= 380]
    quarterly_entries = [entry for entry in available if 70 <= entry["days"] <= 110]

    recent_quarters: list[dict[str, Any]] = []
    seen_ends: set[date] = set()
    for entry in sorted(quarterly_entries, key=lambda item: (item["end"], item["filed"]), reverse=True):
        if entry["end"] in seen_ends:
            continue
        recent_quarters.append(entry)
        seen_ends.add(entry["end"])
        if len(recent_quarters) == 4:
            break
    if len(recent_quarters) == 4:
        return sum(entry["value"] for entry in recent_quarters)

    if annual_entries:
        return sorted(annual_entries, key=lambda item: (item["end"], item["filed"]), reverse=True)[0]["value"]

    return None


def build_monthly_pe_rows(company_facts: dict[str, Any], ticker: str, filings: list[Any]) -> list[dict[str, Any]]:
    if not filings:
        return []
    sorted_filings = sorted(filings, key=lambda item: item.report_date)
    end = parse_iso_date(sorted_filings[-1].report_date)
    if not end:
        return []
    start = shift_year(end, -5)

    prices = fetch_yahoo_monthly_prices(ticker, start, end)
    eps_entries = collect_diluted_eps_entries(company_facts)
    rows: list[dict[str, Any]] = []
    for price_row in prices:
        month_date = price_row["date"]
        ttm_eps = latest_ttm_eps_as_of(eps_entries, month_date)
        pe = None
        if isinstance(ttm_eps, (int, float)) and ttm_eps > 0:
            pe = price_row["close"] / ttm_eps
        rows.append(
            {
                "month": price_row["month"],
                "close": price_row["close"],
                "ttm_eps": ttm_eps,
                "pe": pe,
            }
        )
    return rows


def align_monthly_pe_rows_to_review_window(
    monthly_pe_rows: list[dict[str, Any]],
    review_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    review_months = [
        str(row.get("month", ""))
        for row in review_rows
        if re.match(r"^\d{4}-\d{2}$", str(row.get("month", "")))
    ]
    if not review_months:
        return monthly_pe_rows
    start_month = min(review_months)
    end_month = max(review_months)
    aligned_rows = [
        row
        for row in monthly_pe_rows
        if start_month <= str(row.get("month", "")) <= end_month
    ]
    return aligned_rows or monthly_pe_rows


def save_or_reuse_filing(filing: Any, user_agent: str) -> dict[str, str]:
    target_dir = (
        DATA_DIR
        / safe_path_part(filing.ticker)
        / safe_path_part(filing.form)
        / f"{filing.filing_date}_{safe_path_part(filing.accession_number)}"
    )
    document_path = target_dir / filing.primary_document
    metadata_path = target_dir / "metadata.json"

    if document_path.exists() and metadata_path.exists():
        return {
            "form": filing.form,
            "filing_date": filing.filing_date,
            "report_date": filing.report_date,
            "document_path": str(document_path),
            "metadata_path": str(metadata_path),
            "source_url": filing.primary_document_url,
            "accession_number": filing.accession_number,
            "primary_document": filing.primary_document,
        }

    saved_item = write_filing(filing, DATA_DIR, user_agent)
    saved_item.update(
        {
            "accession_number": filing.accession_number,
            "primary_document": filing.primary_document,
        }
    )
    return saved_item


def find_same_type_filings_for_vertical_compare(
    submissions: dict[str, Any],
    company: Any,
    user_agent: str,
    form: str,
    year: int,
    quarter: str | None,
    lookback_years: int = 4,
) -> tuple[list[Any], list[dict[str, Any]]]:
    normalized_form = form.upper()
    normalized_quarter = quarter.upper() if quarter else None
    target_years = [year - offset for offset in range(lookback_years + 1)]
    blocks = load_all_filing_blocks(submissions, user_agent)
    filings_by_year: dict[int, list[Any]] = {target_year: [] for target_year in target_years}

    for block in blocks:
        for index, block_form in enumerate(block["form"]):
            if str(block_form).upper() != normalized_form:
                continue

            report_date = str(block["reportDate"][index])
            matched_year = next((target_year for target_year in target_years if report_date.startswith(f"{target_year}-")), None)
            if matched_year is None:
                continue

            if normalized_form == "10-Q" and normalized_quarter:
                filing_date = str(block["filingDate"][index])
                if quarter_from_date(filing_date) != normalized_quarter:
                    continue

            filings_by_year[matched_year].append(filing_from_block(block, company, index))

    selected_filings: list[Any] = []
    missing_periods: list[dict[str, Any]] = []
    for target_year in target_years:
        matches = filings_by_year[target_year]
        if not matches:
            missing_periods.append({"year": target_year, "form": normalized_form, "quarter": normalized_quarter})
            continue
        matches.sort(key=lambda item: (item.report_date, item.filing_date), reverse=True)
        selected_filings.append(matches[0])

    return selected_filings, missing_periods


def find_continuous_quarter_filings_for_vertical_compare(
    submissions: dict[str, Any],
    company: Any,
    user_agent: str,
    target_filing: Any,
    max_periods: int = 20,
) -> tuple[list[Any], list[dict[str, Any]]]:
    target_report_date = parse_iso_date(target_filing.report_date)
    if target_report_date is None:
        return [target_filing], []

    blocks = load_all_filing_blocks(submissions, user_agent)
    candidates: list[Any] = []
    for block in blocks:
        for index, block_form in enumerate(block["form"]):
            normalized_form = str(block_form).upper()
            if normalized_form not in {"10-Q", "10-K"}:
                continue
            report_date = parse_iso_date(str(block["reportDate"][index]))
            if report_date is None or report_date > target_report_date:
                continue
            candidate = filing_from_block(block, company, index)
            if normalized_form == "10-Q":
                filing_quarter = quarter_from_date(candidate.filing_date)
                if filing_quarter not in {"Q1", "Q2", "Q3"}:
                    continue
            candidates.append(candidate)

    deduped: dict[tuple[str, str], Any] = {}
    for candidate in sorted(candidates, key=lambda item: (item.report_date, item.filing_date)):
        deduped[(candidate.report_date, candidate.form)] = candidate

    selected = list(deduped.values())[-max_periods:]
    if target_filing.accession_number not in {item.accession_number for item in selected}:
        selected.append(target_filing)
        selected = sorted(selected, key=lambda item: (item.report_date, item.filing_date))[-max_periods:]
    return selected, []


def metric_value(financial_rows: list[dict[str, Any]], metric: str) -> float | None:
    for row in financial_rows:
        if row.get("metric") == metric and isinstance(row.get("raw_value"), (int, float)):
            return float(row["raw_value"])
    return None


def percent(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:,.2f}%"


def multiple(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f}x"


def safe_divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    return numerator / denominator


def build_ratio_rows(financial_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    revenue = metric_value(financial_rows, "收入")
    gross_profit = metric_value(financial_rows, "毛利润")
    operating_income = metric_value(financial_rows, "营业利润")
    net_income = metric_value(financial_rows, "净利润")
    cash = metric_value(financial_rows, "现金及等价物")
    assets = metric_value(financial_rows, "总资产")
    liabilities = metric_value(financial_rows, "总负债")
    equity = metric_value(financial_rows, "股东权益")
    current_assets = metric_value(financial_rows, "流动资产")
    current_liabilities = metric_value(financial_rows, "流动负债")
    operating_cash_flow = metric_value(financial_rows, "经营现金流")
    capex = metric_value(financial_rows, "资本开支")
    free_cash_flow = None
    if operating_cash_flow is not None and capex is not None:
        free_cash_flow = operating_cash_flow - abs(capex)

    ratio_specs = [
        ("盈利能力", "毛利率", percent(safe_divide(gross_profit, revenue)), "毛利润 / 收入"),
        ("盈利能力", "营业利润率", percent(safe_divide(operating_income, revenue)), "营业利润 / 收入"),
        ("盈利能力", "净利率", percent(safe_divide(net_income, revenue)), "净利润 / 收入"),
        ("现金流质量", "经营现金流 / 净利润", multiple(safe_divide(operating_cash_flow, net_income)), "经营现金流 / 净利润"),
        ("现金流质量", "自由现金流", format_fact_value(free_cash_flow, "USD"), "经营现金流 - 资本开支"),
        ("现金流质量", "自由现金流率", percent(safe_divide(free_cash_flow, revenue)), "自由现金流 / 收入"),
        ("流动性", "流动比率", multiple(safe_divide(current_assets, current_liabilities)), "流动资产 / 流动负债"),
        ("流动性", "现金比率", multiple(safe_divide(cash, current_liabilities)), "现金 / 流动负债"),
        ("偿债能力", "负债 / 资产", percent(safe_divide(liabilities, assets)), "总负债 / 总资产"),
        ("偿债能力", "负债 / 权益", multiple(safe_divide(liabilities, equity)), "总负债 / 股东权益"),
    ]
    return [
        {"category": category, "metric": metric, "value": value, "formula": formula}
        for category, metric, value, formula in ratio_specs
    ]


def table_text(table: list[list[str]]) -> str:
    return " ".join(" ".join(row) for row in table).lower()


def looks_like_business_table(table: list[list[str]]) -> bool:
    text = table_text(table)
    business_keywords = [
        "segment",
        "reportable segment",
        "net sales by category",
        "product",
        "services",
        "iphone",
        "ipad",
        "mac",
        "wearables",
        "operating segment",
    ]
    financial_keywords = ["revenue", "sales", "net sales", "operating income", "income", "profit", "assets", "cash flow"]
    return any(keyword in text for keyword in business_keywords) and any(keyword in text for keyword in financial_keywords)


def extract_business_rows(tables: list[list[list[str]]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for table_index, table in enumerate(tables):
        if len(rows) >= 24:
            break
        if len(table) < 2 or not looks_like_business_table(table):
            continue

        header = table[0]
        for row in table[1:12]:
            if len(rows) >= 24:
                break
            if not row or len(row) < 2:
                continue
            item = row[0]
            if not item or item.lower() in {"total", "net sales"}:
                continue
            values = []
            for index, value in enumerate(row[1:], start=1):
                column_name = header[index] if index < len(header) else f"Column {index + 1}"
                if value:
                    values.append(f"{column_name}: {value}")
            if not values:
                continue
            rows.append(
                {
                    "segment": item,
                    "metric_snapshot": " | ".join(values[:4]),
                    "source": f"HTML 表格 #{table_index + 1}",
                    "confidence": "中",
                    "note": "摘自疑似业务/产品线表；如未披露分部现金流，不做强行拆分。",
                }
            )
    if not rows:
        rows.append(
            {
                "segment": "未识别",
                "metric_snapshot": "—",
                "source": "HTML 财报",
                "confidence": "低",
                "note": "本版本没有识别到明确业务分部表；可在原文中核对 Segment / Net sales by category。",
            }
        )
    return rows


def split_sentences(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    return [normalize_space(chunk) for chunk in chunks if len(normalize_space(chunk)) > 40]


def find_sentences(text: str, include: list[str], limit: int) -> list[str]:
    sentences = split_sentences(text)
    results = []
    for sentence in sentences:
        lowered = sentence.lower()
        if any(keyword in lowered for keyword in include):
            results.append(sentence)
        if len(results) >= limit:
            break
    return results


def build_guidance_rows(text: str) -> list[dict[str, str]]:
    keywords = ["guidance", "outlook", "forecast", "expects revenue", "expect revenue", "expects net sales", "expect net sales", "next fiscal year", "next year revenue"]
    explicit_period_keywords = ["next year", "next fiscal", "fiscal year", "full year", "annual", "quarter", "q1", "q2", "q3", "q4"]
    metric_keywords = ["revenue", "net sales", "sales", "gross margin", "operating margin", "eps", "capital expenditures", "tax rate"]
    rows = [
        {
            "metric": infer_text_metric(sentence),
            "guidance": sentence[:600],
            "source": "财报文本启发式抽取",
            "confidence": "低" if "expect" not in sentence.lower() and "guidance" not in sentence.lower() else "中",
        }
        for sentence in find_sentences(text, keywords, 12)
        if any(metric_keyword in sentence.lower() for metric_keyword in metric_keywords)
        and any(period_keyword in sentence.lower() for period_keyword in explicit_period_keywords)
        and "deferred revenue" not in sentence.lower()
        and "hedges" not in sentence.lower()
    ]
    if not rows:
        rows.append(
            {
                "metric": "收入 / 展望",
                "guidance": "这份 10-K/10-Q 中没有识别到明确的收入指引。若要研究下一年收入预期，建议接入 8-K、业绩新闻稿、电话会纪要或投资者演示材料。",
                "source": "财报文本启发式抽取",
                "confidence": "低",
            }
        )
    return rows


def infer_text_metric(sentence: str) -> str:
    lowered = sentence.lower()
    if "revenue" in lowered or "net sales" in lowered:
        return "收入"
    if "margin" in lowered:
        return "利润率"
    if "capital expenditure" in lowered or "capex" in lowered:
        return "资本开支"
    if "tax" in lowered:
        return "税率"
    if "cash flow" in lowered:
        return "现金流"
    return "展望"


def build_mdna_rows(text: str) -> list[dict[str, str]]:
    keywords = ["increased", "decreased", "declined", "growth", "due to", "primarily", "driven by", "offset by", "higher", "lower"]
    rows = [
        {
            "driver": infer_driver(sentence),
            "evidence": sentence[:600],
            "source": "MD&A / 财报文本启发式抽取",
            "confidence": "中" if "due to" in sentence.lower() or "driven by" in sentence.lower() else "低",
        }
        for sentence in find_sentences(text, keywords, 10)
    ]
    return rows[:10] or [{"driver": "未识别", "evidence": "没有识别到清晰的 MD&A 经营驱动句子。", "source": "财报文本启发式抽取", "confidence": "低"}]


def infer_driver(sentence: str) -> str:
    lowered = sentence.lower()
    if "foreign exchange" in lowered or "currency" in lowered:
        return "汇率"
    if "price" in lowered:
        return "价格"
    if "volume" in lowered or "unit" in lowered:
        return "销量 / 数量"
    if "mix" in lowered:
        return "结构 / Mix"
    if "cost" in lowered or "expense" in lowered:
        return "成本 / 费用"
    if "service" in lowered:
        return "服务业务"
    return "经营驱动"


def build_risk_rows(text: str) -> list[dict[str, str]]:
    keywords = ["risk", "uncertain", "competition", "supply", "regulation", "litigation", "customer", "macroeconomic", "cybersecurity", "privacy"]
    rows = [
        {
            "risk_category": infer_risk(sentence),
            "risk_evidence": sentence[:700],
            "source": "风险因素 / 财报文本启发式抽取",
            "confidence": "低",
        }
        for sentence in find_sentences(text, keywords, 10)
    ]
    return rows[:10] or [{"risk_category": "未识别", "risk_evidence": "没有通过启发式规则识别到风险句子。", "source": "财报文本启发式抽取", "confidence": "低"}]


def infer_risk(sentence: str) -> str:
    lowered = sentence.lower()
    if "competition" in lowered:
        return "竞争"
    if "supply" in lowered:
        return "供应链"
    if "regulation" in lowered or "privacy" in lowered:
        return "监管"
    if "litigation" in lowered or "legal" in lowered:
        return "法律 / 诉讼"
    if "customer" in lowered:
        return "客户集中度 / 需求"
    if "cyber" in lowered:
        return "网络安全"
    return "业务风险"


def build_accounting_flag_rows(financial_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    net_income = metric_value(financial_rows, "净利润")
    operating_cash_flow = metric_value(financial_rows, "经营现金流")
    current_assets = metric_value(financial_rows, "流动资产")
    current_liabilities = metric_value(financial_rows, "流动负债")
    liabilities = metric_value(financial_rows, "总负债")
    assets = metric_value(financial_rows, "总资产")

    ocf_ratio = safe_divide(operating_cash_flow, net_income)
    current_ratio = safe_divide(current_assets, current_liabilities)
    liability_ratio = safe_divide(liabilities, assets)

    checks = [
        ("盈利质量", ocf_ratio is not None and ocf_ratio < 0.8, f"经营现金流 / 净利润 = {multiple(ocf_ratio)}", "经营现金流明显低于净利润。"),
        ("流动性", current_ratio is not None and current_ratio < 1.0, f"流动比率 = {multiple(current_ratio)}", "流动负债超过流动资产。"),
        ("杠杆", liability_ratio is not None and liability_ratio > 0.75, f"负债 / 资产 = {percent(liability_ratio)}", "资产负债率较高。"),
    ]
    for flag_type, triggered, evidence, note in checks:
        rows.append(
            {
                "flag_type": flag_type,
                "severity": "中" if triggered else "低",
                "evidence": evidence,
                "note": note if triggered else "该检查未触发自动红旗。",
            }
        )
    return rows


def build_valuation_assumption_rows(financial_rows: list[dict[str, Any]], guidance_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    revenue = metric_value(financial_rows, "收入")
    operating_income = metric_value(financial_rows, "营业利润")
    operating_cash_flow = metric_value(financial_rows, "经营现金流")
    capex = metric_value(financial_rows, "资本开支")
    fcf = operating_cash_flow - abs(capex) if operating_cash_flow is not None and capex is not None else None
    guidance_text = guidance_rows[0]["guidance"] if guidance_rows else "No explicit guidance found."
    return [
        {"assumption": "基准收入", "suggested_input": format_fact_value(revenue, "USD"), "source": "当前财报 XBRL", "confidence": "高" if revenue is not None else "低"},
        {"assumption": "营业利润率", "suggested_input": percent(safe_divide(operating_income, revenue)), "source": "当前财报 XBRL", "confidence": "高" if operating_income is not None and revenue else "低"},
        {"assumption": "自由现金流", "suggested_input": format_fact_value(fcf, "USD"), "source": "经营现金流 - 资本开支", "confidence": "中" if fcf is not None else "低"},
        {"assumption": "下一年收入增长", "suggested_input": "需要外部来源或明确管理层指引", "source": guidance_text[:240], "confidence": "低"},
        {"assumption": "分部增长", "suggested_input": "验证业务分部表后使用", "source": "HTML 分部表启发式抽取", "confidence": "低"},
    ]


def handle_fetch_filing(payload: dict[str, Any]) -> dict[str, Any]:
    company_query = str(payload.get("company", "")).strip()
    year = int(payload.get("year"))
    form = str(payload.get("form", "")).upper()
    quarter = payload.get("quarter")
    quarter = str(quarter).upper() if quarter else None
    continuous_quarter_view = bool(payload.get("continuous_quarter_view"))
    user_agent = str(payload.get("user_agent") or os.environ.get("SEC_USER_AGENT") or DEFAULT_SEC_USER_AGENT).strip()

    if not company_query:
        raise SecFetchError("请输入公司名称或股票代码。")
    if form not in {"10-K", "10-Q"}:
        raise SecFetchError("请选择 10-K 年报或 10-Q 季报。")
    if form == "10-Q" and quarter not in {"Q1", "Q2", "Q3", "Q4"}:
        raise SecFetchError("选择 10-Q 时必须选择季度。")
    if form == "10-Q" and quarter == "Q4":
        raise SecFetchError("多数公司没有单独的 Q4 10-Q。请改选“全年年报 / 10-K”。")
    companies = load_companies(user_agent)
    company = find_company(company_query, companies)
    submissions = load_company_submissions(company.cik, user_agent)
    target_filings, target_missing_periods = find_same_type_filings_for_vertical_compare(
        submissions=submissions,
        company=company,
        user_agent=user_agent,
        form=form,
        year=year,
        quarter=quarter,
        lookback_years=0,
    )
    filing = next((candidate for candidate in target_filings if candidate.report_date.startswith(f"{year}-")), None)

    if not filing:
        period = f"{year} {quarter}" if quarter else str(year)
        if target_filings:
            latest_available = target_filings[0]
            raise SecFetchError(
                f"没有找到 {company.title} 的 {period} {form}。"
                f"当前最接近的可用 {form} 是 {latest_available.report_date[:4]} 年，"
                f"报告期 {latest_available.report_date}，提交日期 {latest_available.filing_date}。"
            )
        raise SecFetchError(f"没有找到 {company.title} 的 {period} {form}。可以换一个年份/季度。")

    if continuous_quarter_view:
        comparison_filings, missing_comparison_periods = find_continuous_quarter_filings_for_vertical_compare(
            submissions=submissions,
            company=company,
            user_agent=user_agent,
            target_filing=filing,
        )
    else:
        comparison_filings, missing_comparison_periods = find_same_type_filings_for_vertical_compare(
            submissions=submissions,
            company=company,
            user_agent=user_agent,
            form=form,
            year=year,
            quarter=quarter,
        )

    saved_filings = []
    for candidate in comparison_filings:
        saved_filings.append(save_or_reuse_filing(candidate, user_agent))
    write_index(DATA_DIR, company, saved_filings)
    saved = next(item for item in saved_filings if item["accession_number"] == filing.accession_number)

    document_path = Path(saved["document_path"]).resolve()
    relative_document_path = relative_to_data_dir(document_path)
    _, filing_text = parse_filing_html(document_path)
    company_profile_rows = build_company_profile_rows(filing, filing_text)
    company_facts = load_company_facts(company.cik, user_agent)
    net_income_comparison_rows = build_net_income_comparison_rows(company_facts, comparison_filings, quarter, continuous_quarter_view)
    roe_comparison_rows = build_roe_comparison_rows(company_facts, comparison_filings, quarter, continuous_quarter_view)
    leverage_rows = build_leverage_rows(company_facts, comparison_filings)
    monthly_pe_rows = build_monthly_pe_rows(company_facts, filing.ticker, comparison_filings)
    altman_rows = build_altman_rows(company_facts, comparison_filings, monthly_pe_rows)
    implied_growth_rows = build_implied_growth_rows(
        company_facts,
        filing,
        monthly_pe_rows,
        comparison_filings,
    )
    pe_growth_review_rows = build_pe_growth_review_rows(
        company_facts,
        filing,
        monthly_pe_rows,
        comparison_filings,
    )

    return {
        "company_name": filing.company_name,
        "ticker": filing.ticker,
        "cik": filing.cik,
        "form": filing.form,
        "filing_date": filing.filing_date,
        "report_date": filing.report_date,
        "accession_number": filing.accession_number,
        "primary_document": filing.primary_document,
        "primary_document_url": filing.primary_document_url,
        "local_document_path": str(document_path),
        "preview_url": f"/filing?path={urllib.parse.quote(relative_document_path)}",
        "comparison_filings": saved_filings,
        "missing_comparison_periods": missing_comparison_periods,
        "comparison_mode": "continuous_quarters" if continuous_quarter_view else "same_period",
        "tables": {
            "company_profile_rows": company_profile_rows,
            "net_income_comparison_rows": net_income_comparison_rows,
            "roe_comparison_rows": roe_comparison_rows,
            "leverage_rows": leverage_rows,
            "altman_rows": altman_rows,
            "monthly_pe_rows": monthly_pe_rows,
            "pe_growth_review_rows": pe_growth_review_rows,
            "implied_growth_rows": implied_growth_rows,
        },
    }



def latest_fact_entry(
    facts: dict[str, Any],
    concepts: list[str],
    unit: str,
    require_duration: bool | None = None,
) -> tuple[float | None, str | None, str | None]:
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    candidates: list[tuple[str, dict[str, Any]]] = []
    for concept in concepts:
        payload = us_gaap.get(concept)
        if not payload:
            continue
        units = payload.get("units", {})
        entries = units.get(unit)
        if not entries and units:
            _, entries = next(iter(units.items()))
        for entry in entries or []:
            if require_duration is True and not entry.get("start"):
                continue
            if require_duration is False and entry.get("start"):
                continue
            if isinstance(entry.get("val"), (int, float)):
                candidates.append((concept, entry))
    if not candidates:
        return None, None, None
    candidates.sort(key=lambda item: (str(item[1].get("end", "")), str(item[1].get("filed", ""))), reverse=True)
    concept, entry = candidates[0]
    return float(entry["val"]), concept, str(entry.get("end") or "—")


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def score_ratio(value: float | None, target: float, higher_is_better: bool = True) -> float:
    if value is None:
        return 0.0
    if higher_is_better:
        return clamp((value / target) * 100)
    return clamp((target / value) * 100) if value > 0 else 0.0


def display_percent(value: float | None) -> str | None:
    return None if value is None else f"{value * 100:,.1f}%"


def display_multiple(value: float | None) -> str | None:
    return None if value is None else f"{value:,.2f}x"



class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            html_response(self, HTML)
            return



        if parsed.path == "/filing":
            params = urllib.parse.parse_qs(parsed.query)
            requested = params.get("path", [""])[0]
            try:
                candidate = (DATA_DIR / requested).resolve()
                candidate.relative_to(DATA_DIR.resolve())
            except ValueError:
                self.send_error(403, "Invalid filing path")
                return

            if not candidate.exists() or not candidate.is_file():
                self.send_error(404, "Filing not found")
                return

            data = candidate.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_error(404, "Not found")

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/fetch-filing":
            self.send_error(404, "Not found")
            return

        try:
            payload = read_json_body(self)
            result = handle_fetch_filing(payload)
            json_response(self, 200, result)
        except (SecFetchError, ValueError, KeyError, json.JSONDecodeError) as exc:
            json_response(self, 400, {"error": str(exc)})
        except Exception as exc:
            traceback.print_exc()
            json_response(self, 500, {"error": f"Unexpected server error: {exc}"})


def main() -> int:
    host = os.environ.get("VALUATION_DASHBOARD_HOST", "127.0.0.1")
    port = int(os.environ.get("VALUATION_DASHBOARD_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"Financial report dashboard running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
