# ETF 身份清单数据规范

本规范只定义“研究对象是谁、跟踪什么”的最小输入；不下载行情、不计算收益、不做筛选打分。

每行代表一个交易所挂牌代码，使用 UTF-8 CSV。导入前必须人工或以可追溯的公开来源核实，不能把名称推测当作跟踪标的。

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `exchange` | 是 | `SSE` 或 `SZSE` |
| `code` | 是 | 六位证券代码 |
| `name` | 是 | ETF 证券简称 |
| `tracking_target` | 是 | 实际跟踪的指数或客观资产 |
| `asset_type` | 是 | 如宽基、行业、主题、海外、商品；仅作归类，不是投资结论 |
| `passive_tracking` | 是 | `true`/`false` 或 `1`/`0`；是否具有明确被动跟踪规则 |
| `listing_date` | 否 | 上市日期，`YYYY-MM-DD` |
| `source_name` | 是 | 数据来源名称 |
| `source_url` | 否 | 可复核来源页面或文件地址 |
| `source_as_of` | 是 | 来源资料的截至日期，`YYYY-MM-DD` |
| `source_record_id` | 否 | 来源中的记录标识 |

示例命令（不会下载任何行情数据）：

```powershell
$env:PYTHONPATH = 'src'
python -m etf_investment identity-template data/local/etf_identity.csv
python -m etf_investment import-identities data/local/etf_identity.csv
python -m etf_investment list-identities
```

导入后，系统保留来源、截至日期和原始记录标识。后续筛选阶段必须通过 `decision_event` 追加证据，不能覆盖前一阶段结论。

## 日线输入

日线同样使用 UTF-8 CSV，必填列为：`exchange`、`code`、`date`、`open`、`high`、`low`、`close`、`adjustment`、`source_name`、`source_as_of`。可选列为 `volume`、`amount` 和 `source_url`。

`adjustment` 必须显式写为 `none`、`forward`、`backward` 或 `total_return`。导入器不会自行推测复权语义；指标输出会明确标记为 `price_return` 或 `total_return`。

```powershell
python -m etf_investment import-daily data/local/510300_daily.csv
python -m etf_investment metrics SSE 510300 --adjustment none
```

## 策略基准

固定定投基准要求调用方显式传入金额、频率、现金预留、交易成本和执行价格口径（后两项会在策略配置层加入）。系统不内置任何正式金额、阈值或网格参数。
