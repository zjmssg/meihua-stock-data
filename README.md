# A股收盘价梅花易数｜GitHub Actions在线数据版

这个仓库把“行情抓取”和“网页起卦”分开：

1. GitHub Actions在收盘后运行Python；
2. TuShare按交易日一次获取全A股日线；
3. TuShare不可用时，当日更新可尝试AKShare全A快照；
4. 行情写入 `data/daily/YYYY-MM-DD.json` 并更新 `data/manifest.json`；
5. GitHub Pages上的 `index.html` 只读取同仓库静态数据，不再直接访问行情网站；
6. 页面完成收盘价起卦、384爻解释、次日验证和命中率统计。

## 第一次部署

1. 新建一个GitHub仓库，把本压缩包中的全部文件上传到仓库根目录。
2. 在TuShare注册并取得Token。
3. 打开仓库 `Settings → Secrets and variables → Actions → New repository secret`。
4. Secret名称填写 `TUSHARE_TOKEN`，值填写你的Token。
5. 打开 `Actions → 回填历史A股日行情 → Run workflow`：
   - 开始日期填 `2026-01-01`；
   - 结束日期填写最近一个交易日；
   - 首次运行不勾选覆盖。
6. 打开 `Settings → Pages`，Source选择 `Deploy from a branch`，分支选择默认分支，目录选择 `/ (root)`。
7. 等Pages生成网址后，通过该网址打开工具。不要直接双击本地HTML。

## 自动更新

`更新A股日行情` 工作流设置为上海时间每周一至周五18:35运行，也支持手动指定交易日。

## 数据口径

- 起卦使用未复权的实际收盘价；
- TuShare成交量由“手”转换为“股”；
- TuShare成交额由“千元”转换为“元”；
- 日文件至少需要1000条有效行情才允许写入，避免把接口异常的空数据提交进仓库；
- 停牌股票可能在某日没有行情，页面会显示“当日无行情”，不会伪造上一交易日价格。

## 文件说明

- `index.html`：梅花易数分析与回测页面；
- `scripts/update_market_data.py`：最近交易日更新；
- `scripts/backfill_market_data.py`：历史日期范围回填；
- `scripts/validate_data.py`：数据完整性检查；
- `.github/workflows/update-market-data.yml`：每日自动更新；
- `.github/workflows/backfill-market-data.yml`：手动历史回填；
- `data/manifest.json`：可用交易日清单；
- `data/daily/*.json`：每天全A股行情。

## 注意

GitHub公开仓库中的行情文件任何人都能查看；不要把TuShare Token写进代码或HTML，只放在Actions Secret中。历史回填必须使用TuShare Token；当日自动更新在TuShare失败时才会尝试AKShare。

梅花易数与股票走势映射不具备经验证的预测能力，仅用于传统文化研究与历史回测，不构成投资建议。
