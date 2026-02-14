# 订单比对与利润核算系统

基于 Flask + Pandas 的网页版财务对账工具，支持：

- 官方订单表与客服统计表比对
- 自动识别/手工映射列名
- 重复单、漏记单、多记单识别
- 利润计算与亏损高亮
- 表格分页、排序
- 导出 Excel 对账结果

## 启动

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

访问 `http://127.0.0.1:8000`。

## 支持格式

- `.xlsx`
- `.xls`
- WPS 导出的 xlsx/xls
- `.et` 需先转为 xlsx/xls
