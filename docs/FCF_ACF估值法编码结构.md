# FCF 与 ACF 估值法编码结构

本项目已将 FMI 课程 PDF 中的估值框架整理成 Python 代码结构。

## 1. 学习来源

工作区文档：

- `FMI/Lecture Week9 SM1 2026-1.pdf`
- `FMI/Lecture Week10 SM1 2026.pdf`

关键内容：

- Week 9 第 29 页：基本估值模型包括股利折现、自由现金流折现、异常收益/剩余收益模型。
- Week 9 第 31-33 页：DCF/FCF 模型，区分 levered FCFE 和 unlevered FCFF。
- Week 10 第 3-10 页：异常收益估值，Equity Value = Book Value of Equity + PV(Future Abnormal Earnings)。
- Week 10 第 14 页：估 equity 用 cost of equity；估 assets / NOA 用 WACC。
- Week 10 第 17-18 页：两种异常收益模型：Abnormal Earnings 和 Abnormal NOPAT；terminal value 可用增长率法。
- Week 10 第 42 页：总结了 Dividend、Free Cash Flow、Residual Income 等模型的对应关系。

注意：课程 PDF 里主要使用的是 `Abnormal Earnings`、`Residual Income`、`Abnormal NOPAT`。用户口中的 ACF 在代码中作为 `ACF / AE` 兼容命名处理。

## 2. 代码目录

```text
valuation_methods/
├─ __init__.py
├─ common.py      # 折现、终值、通用 forecast row
├─ fcf.py         # FCFE / FCFF 估值
└─ acf.py         # Abnormal Earnings / Abnormal NOPAT 估值

examples/
└─ valuation_methods_example.py
```

## 3. FCF / DCF 模型

### 3.1 FCFE：直接估股权价值

适用：

- 直接预测归属于股东的自由现金流。
- 现金流已经扣除利息、债务偿还/新增融资等 financing effects。

公式结构：

```text
Equity Value = PV(FCFE_1 ... FCFE_n) + PV(Terminal Value)
Terminal Value_n = FCFE_n * (1 + g) / (re - g)
```

折现率：

```text
cost of equity
```

代码：

```python
from valuation_methods import CashFlowForecast, ForecastRow, TerminalGrowth, fcfe_valuation

forecast = CashFlowForecast(
    cash_flows=[
        ForecastRow(1, 110),
        ForecastRow(2, 125),
        ForecastRow(3, 140),
    ],
    terminal_growth=TerminalGrowth(growth_rate=0.03),
)

result = fcfe_valuation(
    forecast,
    cost_of_equity=0.10,
    shares_outstanding=100,
)
```

### 3.2 FCFF：先估企业价值，再桥接到股权价值

适用：

- 预测不含融资影响的自由现金流。
- 即 free cash flow before interest and debt transactions。

公式结构：

```text
Enterprise Value = PV(FCFF_1 ... FCFF_n) + PV(Terminal Value)
Equity Value = Enterprise Value - Net Debt + Non-operating Assets
Terminal Value_n = FCFF_n * (1 + g) / (WACC - g)
```

折现率：

```text
WACC
```

代码：

```python
from valuation_methods import CashFlowForecast, ForecastRow, TerminalGrowth, fcff_valuation

forecast = CashFlowForecast(
    cash_flows=[
        ForecastRow(1, 150),
        ForecastRow(2, 165),
        ForecastRow(3, 180),
    ],
    terminal_growth=TerminalGrowth(growth_rate=0.03),
)

result = fcff_valuation(
    forecast,
    wacc=0.085,
    net_debt=300,
    shares_outstanding=100,
)
```

## 4. ACF / AE 模型

### 4.1 Abnormal Earnings：估股权价值

课程口径：

```text
Fundamental value of equity = Book value of equity + PV(future abnormal earnings)
Abnormal Earnings = Net Income - cost of equity * opening book value of equity
```

公式结构：

```text
AE_t = NI_t - re * BVE_(t-1)
Equity Value = BVE_0 + PV(AE_1 ... AE_n) + PV(Terminal AE)
Terminal AE_n = AE_n * (1 + g) / (re - g)
```

代码：

```python
from valuation_methods import AbnormalEarningsForecast, ForecastRow, TerminalGrowth, abnormal_earnings_valuation

forecast = AbnormalEarningsForecast(
    opening_book_value_equity=900,
    net_income_forecasts=[
        ForecastRow(1, 120),
        ForecastRow(2, 135),
        ForecastRow(3, 150),
    ],
    opening_bve_by_period=[
        ForecastRow(1, 900),
        ForecastRow(2, 980),
        ForecastRow(3, 1070),
    ],
    terminal_growth=TerminalGrowth(growth_rate=0.02),
)

result = abnormal_earnings_valuation(
    forecast,
    cost_of_equity=0.10,
    shares_outstanding=100,
)
```

### 4.2 Abnormal NOPAT：估经营资产，再桥接到股权

课程口径：

- 估 equity：discount abnormal earnings available to equity holders，使用 cost of equity。
- 估 assets / NOA：discount abnormal earnings / NOPAT available to equity and debt holders，使用 WACC。

公式结构：

```text
Abnormal NOPAT_t = NOPAT_t - WACC * BVNOA_(t-1)
Asset / NOA Value = BVNOA_0 + PV(Abnormal NOPAT_1 ... n) + PV(Terminal Abnormal NOPAT)
Equity Value = Asset Value - Net Debt + Non-operating Assets
```

代码：

```python
from valuation_methods import AbnormalNopatForecast, ForecastRow, TerminalGrowth, abnormal_nopat_valuation

forecast = AbnormalNopatForecast(
    opening_book_value_noa=1300,
    nopat_forecasts=[
        ForecastRow(1, 160),
        ForecastRow(2, 180),
        ForecastRow(3, 200),
    ],
    opening_bvnoa_by_period=[
        ForecastRow(1, 1300),
        ForecastRow(2, 1390),
        ForecastRow(3, 1480),
    ],
    terminal_growth=TerminalGrowth(growth_rate=0.02),
)

result = abnormal_nopat_valuation(
    forecast,
    wacc=0.085,
    net_debt=300,
    shares_outstanding=100,
)
```

## 5. 和财报读取系统的衔接

当前网页已经能提取：

- 收入
- 毛利润
- 营业利润
- 净利润
- 经营现金流
- 资本开支
- 总资产
- 总负债
- 股东权益
- 普通股股数

下一步可以把这些字段映射到估值模型输入：

| 表格系统字段 | FCF / ACF 输入 |
|---|---|
| 经营现金流 | FCF 起点 |
| 资本开支 | FCF 扣减项 |
| 净利润 | Abnormal Earnings 的 NI |
| 营业利润 / 税率 | Abnormal NOPAT 的 NOPAT |
| 股东权益 | BVE |
| 净债务 | FCFF / Abnormal NOPAT 到 equity bridge |
| 普通股股数 | 每股价值 |

## 6. 建议后续实现

1. 在网页新增“估值假设”面板：
   - forecast horizon
   - revenue growth
   - margin
   - tax rate
   - capex ratio
   - WACC
   - cost of equity
   - terminal growth

2. 从当前财报自动生成 base year：
   - revenue
   - operating margin
   - OCF margin
   - capex / revenue
   - BVE
   - net debt

3. 生成四种估值输出：
   - FCFE equity value
   - FCFF equity value
   - abnormal earnings equity value
   - abnormal NOPAT equity value

4. 做 sensitivity table：
   - terminal growth vs discount rate
   - operating margin vs revenue growth

