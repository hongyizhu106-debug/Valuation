from __future__ import annotations

import json
import os
import re
import sys
import traceback
import urllib.parse
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
DATA_DIR = PROJECT_ROOT / "data" / "sec_filings"
DEFAULT_SEC_USER_AGENT = "Valuation Dashboard local-research@example.com"

sys.path.insert(0, str(SCRIPTS_DIR))

from fetch_sec_filings import (  # noqa: E402
    SecFetchError,
    fetch_json,
    find_company,
    find_filing_by_period,
    load_companies,
    load_company_submissions,
    safe_path_part,
    write_filing,
    write_index,
)


SEC_COMPANY_FACTS_BASE = "https://data.sec.gov/api/xbrl/companyfacts"

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
      display: grid;
      grid-template-columns: 340px minmax(0, 1fr);
      min-height: 560px;
    }

    .details {
      padding: 18px;
      border-right: 1px solid var(--border);
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
      padding: 18px;
      min-width: 0;
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
      max-height: 320px;
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

    iframe {
      width: 100%;
      height: 760px;
      border: 1px solid var(--border);
      border-radius: 18px;
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
      .details { border-right: 0; border-bottom: 1px solid var(--border); }
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

      <div id="empty-state" class="empty">
        <div>
          <strong>财报会显示在这里</strong>
          <p>提交表单后，左侧会显示元数据，右侧会嵌入本地保存的 SEC 原始 HTML 文件。</p>
        </div>
      </div>

      <div id="workspace" class="workspace" hidden>
        <aside class="details">
          <h2>下载结果</h2>
          <div class="kv">
            <div><span>Ticker / CIK</span><code id="ticker-cik">—</code></div>
            <div><span>Accession Number</span><code id="accession">—</code></div>
            <div><span>本地文件</span><code id="local-path">—</code></div>
            <div><span>SEC 来源</span><code id="source-url">—</code></div>
          </div>
        </aside>
        <section class="viewer">
          <div class="extract-panel">
            <div class="extract-card">
              <h3>自动摘录：关键财务数据</h3>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>分类</th>
                      <th>指标</th>
                      <th>数值</th>
                      <th>期间</th>
                      <th>XBRL Concept</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody id="financial-rows"></tbody>
                </table>
              </div>
            </div>
            <div class="extract-card">
              <h3>自动摘录：非财务与文件信息</h3>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>分类</th>
                      <th>字段</th>
                      <th>内容</th>
                      <th>来源</th>
                    </tr>
                  </thead>
                  <tbody id="nonfinancial-rows"></tbody>
                </table>
              </div>
            </div>
            <div class="extract-card">
              <h3>财务比率与健康检查</h3>
              <div class="table-wrap">
                <table>
                  <thead><tr><th>分类</th><th>指标</th><th>数值</th><th>公式</th></tr></thead>
                  <tbody id="ratio-rows"></tbody>
                </table>
              </div>
            </div>
            <div class="extract-card">
              <h3>业务 / 产品线分部</h3>
              <div class="table-wrap">
                <table>
                  <thead><tr><th>分部 / 项目</th><th>指标快照</th><th>来源</th><th>置信度</th><th>备注</th></tr></thead>
                  <tbody id="business-rows"></tbody>
                </table>
              </div>
            </div>
            <div class="extract-card">
              <h3>管理层指引 / 展望</h3>
              <div class="table-wrap">
                <table>
                  <thead><tr><th>指标</th><th>指引 / 证据</th><th>来源</th><th>置信度</th></tr></thead>
                  <tbody id="guidance-rows"></tbody>
                </table>
              </div>
            </div>
            <div class="extract-card">
              <h3>MD&A 经营驱动</h3>
              <div class="table-wrap">
                <table>
                  <thead><tr><th>驱动因素</th><th>证据</th><th>来源</th><th>置信度</th></tr></thead>
                  <tbody id="mdna-rows"></tbody>
                </table>
              </div>
            </div>
            <div class="extract-card">
              <h3>风险因素</h3>
              <div class="table-wrap">
                <table>
                  <thead><tr><th>风险分类</th><th>证据</th><th>来源</th><th>置信度</th></tr></thead>
                  <tbody id="risk-rows"></tbody>
                </table>
              </div>
            </div>
            <div class="extract-card">
              <h3>会计质量红旗</h3>
              <div class="table-wrap">
                <table>
                  <thead><tr><th>红旗类型</th><th>严重程度</th><th>证据</th><th>说明</th></tr></thead>
                  <tbody id="accounting-flag-rows"></tbody>
                </table>
              </div>
            </div>
            <div class="extract-card">
              <h3>估值假设输入</h3>
              <div class="table-wrap">
                <table>
                  <thead><tr><th>假设项</th><th>建议输入</th><th>来源</th><th>置信度</th></tr></thead>
                  <tbody id="valuation-assumption-rows"></tbody>
                </table>
              </div>
            </div>
          </div>
          <h2>财报预览</h2>
          <iframe id="filing-frame" title="SEC filing preview"></iframe>
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
      tickerCik: document.getElementById("ticker-cik"),
      accession: document.getElementById("accession"),
      localPath: document.getElementById("local-path"),
      sourceUrl: document.getElementById("source-url"),
      frame: document.getElementById("filing-frame"),
      financialRows: document.getElementById("financial-rows"),
      nonfinancialRows: document.getElementById("nonfinancial-rows"),
      ratioRows: document.getElementById("ratio-rows"),
      businessRows: document.getElementById("business-rows"),
      guidanceRows: document.getElementById("guidance-rows"),
      mdnaRows: document.getElementById("mdna-rows"),
      riskRows: document.getElementById("risk-rows"),
      accountingFlagRows: document.getElementById("accounting-flag-rows"),
      valuationAssumptionRows: document.getElementById("valuation-assumption-rows")
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

    function renderFinancialRows(rows) {
      fields.financialRows.innerHTML = rows.map((row) => {
        const statusClass = row.status === "缺失" ? "pill missing" : "pill";
        return `
          <tr>
            <td>${escapeHtml(row.category)}</td>
            <td>${escapeHtml(row.metric)}</td>
            <td>${escapeHtml(row.value)}</td>
            <td class="muted-cell">${escapeHtml(row.period)}</td>
            <td class="muted-cell">${escapeHtml(row.concept)}</td>
            <td><span class="${statusClass}">${escapeHtml(row.status)}</span></td>
          </tr>
        `;
      }).join("");
    }

    function renderNonfinancialRows(rows) {
      fields.nonfinancialRows.innerHTML = rows.map((row) => `
        <tr>
          <td>${escapeHtml(row.category)}</td>
          <td>${escapeHtml(row.field)}</td>
          <td class="muted-cell">${escapeHtml(row.value)}</td>
          <td>${escapeHtml(row.source)}</td>
        </tr>
      `).join("");
    }

    function renderGenericRows(target, rows, columns) {
      target.innerHTML = rows.map((row) => `
        <tr>
          ${columns.map((column) => `<td class="muted-cell">${escapeHtml(row[column])}</td>`).join("")}
        </tr>
      `).join("");
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(form);
      const [formType, quarter] = String(formData.get("period")).split(":");

      const payload = {
        company: formData.get("company"),
        year: Number(formData.get("year")),
        form: formType,
        quarter: quarter === "FY" ? null : quarter,
        user_agent: formData.get("user_agent")
      };

      button.disabled = true;
      button.textContent = "正在读取 SEC 财报…";
      setStatus("正在匹配公司、查找报告期并下载原始财报。第一次请求可能需要几秒钟。");

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
        fields.tickerCik.textContent = `${result.ticker} / ${result.cik}`;
        fields.accession.textContent = result.accession_number;
        fields.localPath.textContent = result.local_document_path;
        fields.sourceUrl.textContent = result.primary_document_url;
        fields.frame.src = result.preview_url;
        renderFinancialRows(result.tables.financial_rows || []);
        renderNonfinancialRows(result.tables.nonfinancial_rows || []);
        renderGenericRows(fields.ratioRows, result.tables.ratio_rows || [], ["category", "metric", "value", "formula"]);
        renderGenericRows(fields.businessRows, result.tables.business_rows || [], ["segment", "metric_snapshot", "source", "confidence", "note"]);
        renderGenericRows(fields.guidanceRows, result.tables.guidance_rows || [], ["metric", "guidance", "source", "confidence"]);
        renderGenericRows(fields.mdnaRows, result.tables.mdna_rows || [], ["driver", "evidence", "source", "confidence"]);
        renderGenericRows(fields.riskRows, result.tables.risk_rows || [], ["risk_category", "risk_evidence", "source", "confidence"]);
        renderGenericRows(fields.accountingFlagRows, result.tables.accounting_flag_rows || [], ["flag_type", "severity", "evidence", "note"]);
        renderGenericRows(fields.valuationAssumptionRows, result.tables.valuation_assumption_rows || [], ["assumption", "suggested_input", "source", "confidence"]);

        emptyState.hidden = true;
        workspace.hidden = false;
        setStatus("读取完成。上方表格已自动摘录关键数据，下面保留 SEC 原始财报预览用于核对。");
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


def build_nonfinancial_rows(company: Any, filing: Any, saved: dict[str, str], document_path: Path) -> list[dict[str, str]]:
    return [
        {"category": "文件身份", "field": "公司", "value": filing.company_name, "source": "SEC submissions"},
        {"category": "文件身份", "field": "股票代码", "value": filing.ticker, "source": "SEC company tickers"},
        {"category": "文件身份", "field": "CIK", "value": filing.cik, "source": "SEC submissions"},
        {"category": "文件身份", "field": "报表类型", "value": filing.form, "source": "SEC submissions"},
        {"category": "文件身份", "field": "提交日期", "value": filing.filing_date, "source": "SEC submissions"},
        {"category": "文件身份", "field": "报告期结束日", "value": filing.report_date, "source": "SEC submissions"},
        {"category": "文件身份", "field": "Accession 编号", "value": filing.accession_number, "source": "SEC submissions"},
        {"category": "文件位置", "field": "主文件", "value": filing.primary_document, "source": "SEC archives"},
        {"category": "文件位置", "field": "SEC 来源链接", "value": filing.primary_document_url, "source": "SEC archives"},
        {"category": "文件位置", "field": "本地保存路径", "value": str(document_path), "source": "本地文件"},
    ]


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
    user_agent = str(payload.get("user_agent") or os.environ.get("SEC_USER_AGENT") or DEFAULT_SEC_USER_AGENT).strip()

    if not company_query:
        raise SecFetchError("请输入公司名称或股票代码。")
    if form not in {"10-K", "10-Q"}:
        raise SecFetchError("请选择 10-K 年报或 10-Q 季报。")
    if form == "10-Q" and quarter not in {"Q1", "Q2", "Q3", "Q4"}:
        raise SecFetchError("选择 10-Q 时必须选择季度。")
    companies = load_companies(user_agent)
    company = find_company(company_query, companies)
    submissions = load_company_submissions(company.cik, user_agent)
    filing = find_filing_by_period(
        submissions=submissions,
        company=company,
        user_agent=user_agent,
        form=form,
        year=year,
        quarter=quarter,
    )

    if not filing:
        period = f"{year} {quarter}" if quarter else str(year)
        raise SecFetchError(f"没有找到 {company.title} 的 {period} {form}。可以换一个年份/季度，或选择 10-K 年报。")

    saved = write_filing(filing, DATA_DIR, user_agent)
    write_index(DATA_DIR, company, [saved])

    document_path = Path(saved["document_path"]).resolve()
    relative_document_path = relative_to_data_dir(document_path)
    company_facts = load_company_facts(company.cik, user_agent)
    financial_rows = extract_financial_rows(company_facts, filing)
    nonfinancial_rows = build_nonfinancial_rows(company, filing, saved, document_path)
    filing_tables, filing_text = parse_filing_html(document_path)
    ratio_rows = build_ratio_rows(financial_rows)
    business_rows = extract_business_rows(filing_tables)
    guidance_rows = build_guidance_rows(filing_text)
    mdna_rows = build_mdna_rows(filing_text)
    risk_rows = build_risk_rows(filing_text)
    accounting_flag_rows = build_accounting_flag_rows(financial_rows)
    valuation_assumption_rows = build_valuation_assumption_rows(financial_rows, guidance_rows)

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
        "tables": {
            "financial_rows": financial_rows,
            "nonfinancial_rows": nonfinancial_rows,
            "ratio_rows": ratio_rows,
            "business_rows": business_rows,
            "guidance_rows": guidance_rows,
            "mdna_rows": mdna_rows,
            "risk_rows": risk_rows,
            "accounting_flag_rows": accounting_flag_rows,
            "valuation_assumption_rows": valuation_assumption_rows,
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
