from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

import pandas as pd
from flask import Flask, jsonify, render_template, request, send_file

app = Flask(__name__)

KEYWORDS = {
    "order_no": ["订单编号", "订单号", "子订单号", "单号", "订单", "交易号"],
    "product": ["商品名称", "产品", "商品", "货品"],
    "status": ["订单状态", "状态", "交易状态", "发货状态"],
    "sales": ["实付金额", "销售金额", "实收", "金额", "销售额", "付款金额"],
    "cost": ["成本价", "进货价", "成本", "采购价"],
}

VALID_STATUSES = {"交易成功", "已发货"}


@dataclass
class CompareResult:
    rows: List[dict]
    summary: dict


def load_excel(file_storage) -> pd.DataFrame:
    filename = (file_storage.filename or "").lower()
    if filename.endswith(".et"):
        raise ValueError("当前环境不支持直接读取 .et 文件，请先转换为 .xlsx 或 .xls 后上传。")

    data = io.BytesIO(file_storage.read())
    try:
        return pd.read_excel(data, dtype=str)
    except Exception as exc:
        raise ValueError(f"读取文件失败: {exc}") from exc


def normalize_amount(value) -> float:
    if pd.isna(value):
        return 0.0
    text = str(value).strip().replace(",", "")
    text = text.replace("¥", "").replace("￥", "")
    text = re.sub(r"[^0-9.-]", "", text)
    if text in {"", "-", ".", "-."}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def normalize_order_no(value: str) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    text = re.sub(r"[\s\-_,./\\|]+", "", text)
    text = re.sub(r"[^0-9]", "", text)
    return text


def normalize_status(value: str) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def infer_mapping(columns: List[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for key, words in KEYWORDS.items():
        for col in columns:
            col_str = str(col).strip()
            if any(word in col_str for word in words):
                mapping[key] = col
                break
    return mapping


def apply_mapping(df: pd.DataFrame, mapping: Dict[str, str], prefix: str) -> pd.DataFrame:
    work = df.copy()
    cols = list(work.columns)
    inferred = infer_mapping(cols)

    final_mapping = {}
    for key in KEYWORDS:
        selected = mapping.get(key)
        if selected and selected in cols:
            final_mapping[key] = selected
        elif key in inferred:
            final_mapping[key] = inferred[key]

    for key in KEYWORDS:
        if key not in final_mapping:
            work[f"{prefix}_{key}"] = ""
        else:
            work[f"{prefix}_{key}"] = work[final_mapping[key]]

    work[f"{prefix}_order_no"] = work[f"{prefix}_order_no"].apply(normalize_order_no)
    work[f"{prefix}_status"] = work[f"{prefix}_status"].apply(normalize_status)
    work[f"{prefix}_sales"] = work[f"{prefix}_sales"].apply(normalize_amount)
    work[f"{prefix}_cost"] = work[f"{prefix}_cost"].apply(normalize_amount)
    work[f"{prefix}_product"] = work[f"{prefix}_product"].fillna("").astype(str).str.strip()

    work = work[(work[f"{prefix}_status"].isin(VALID_STATUSES)) & (work[f"{prefix}_order_no"] != "")]
    return work


def aggregate_by_order(df: pd.DataFrame, prefix: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    grouped = (
        df.groupby(f"{prefix}_order_no", as_index=False)
        .agg(
            {
                f"{prefix}_product": lambda x: " / ".join(sorted({i for i in x if i})),
                f"{prefix}_sales": "sum",
                f"{prefix}_cost": "sum",
            }
        )
        .rename(columns={f"{prefix}_order_no": "order_no"})
    )
    duplicate = (
        df.groupby(f"{prefix}_order_no", as_index=False)
        .size()
        .rename(columns={f"{prefix}_order_no": "order_no", "size": f"{prefix}_duplicate_count"})
    )
    return grouped, duplicate


def compare_orders(official_df: pd.DataFrame, service_df: pd.DataFrame) -> CompareResult:
    official_agg, official_dup = aggregate_by_order(official_df, "official")
    service_agg, service_dup = aggregate_by_order(service_df, "service")

    merged = official_agg.merge(service_agg, on="order_no", how="outer", indicator=True)
    merged = merged.merge(official_dup, on="order_no", how="left").merge(service_dup, on="order_no", how="left")
    merged[["official_duplicate_count", "service_duplicate_count"]] = merged[
        ["official_duplicate_count", "service_duplicate_count"]
    ].fillna(0)

    def get_status(row) -> str:
        if row["_merge"] == "both":
            return "正常匹配"
        if row["_merge"] == "left_only":
            return "客服漏记"
        return "客服多记"

    merged["status_mark"] = merged.apply(get_status, axis=1)

    merged["sales"] = merged["official_sales"].fillna(merged["service_sales"]).fillna(0)
    merged["cost"] = merged["official_cost"].fillna(merged["service_cost"]).fillna(0)
    merged["product"] = merged["official_product"].fillna(merged["service_product"]).fillna("")
    merged["profit"] = merged["sales"] - merged["cost"]
    merged.loc[merged["profit"] < 0, "status_mark"] = merged.loc[merged["profit"] < 0, "status_mark"] + " / 亏损订单"

    rows = []
    for idx, row in merged.sort_values("order_no").reset_index(drop=True).iterrows():
        rows.append(
            {
                "index": idx + 1,
                "order_no": row["order_no"],
                "product": row["product"],
                "sales": round(float(row["sales"]), 2),
                "cost": round(float(row["cost"]), 2),
                "profit": round(float(row["profit"]), 2),
                "status_mark": row["status_mark"],
                "loss": float(row["profit"]) < 0,
                "official_duplicate_count": int(row["official_duplicate_count"]),
                "service_duplicate_count": int(row["service_duplicate_count"]),
            }
        )

    summary = {
        "total_sales": round(float(merged["sales"].sum()), 2),
        "total_cost": round(float(merged["cost"].sum()), 2),
        "total_profit": round(float(merged["profit"].sum()), 2),
        "order_count": int(len(merged)),
    }

    return CompareResult(rows=rows, summary=summary)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/columns", methods=["POST"])
def columns():
    official = request.files.get("official")
    service = request.files.get("service")
    if not official or not service:
        return jsonify({"error": "请上传两个文件"}), 400

    official_df = load_excel(official)
    service_df = load_excel(service)

    return jsonify(
        {
            "official_columns": [str(c) for c in official_df.columns],
            "service_columns": [str(c) for c in service_df.columns],
            "official_auto_mapping": infer_mapping([str(c) for c in official_df.columns]),
            "service_auto_mapping": infer_mapping([str(c) for c in service_df.columns]),
        }
    )


@app.route("/api/compare", methods=["POST"])
def compare():
    official = request.files.get("official")
    service = request.files.get("service")
    if not official or not service:
        return jsonify({"error": "请上传两个文件"}), 400

    official_mapping = {
        "order_no": request.form.get("official_order_no", ""),
        "product": request.form.get("official_product", ""),
        "status": request.form.get("official_status", ""),
        "sales": request.form.get("official_sales", ""),
        "cost": request.form.get("official_cost", ""),
    }
    service_mapping = {
        "order_no": request.form.get("service_order_no", ""),
        "product": request.form.get("service_product", ""),
        "status": request.form.get("service_status", ""),
        "sales": request.form.get("service_sales", ""),
        "cost": request.form.get("service_cost", ""),
    }

    official_df = apply_mapping(load_excel(official), official_mapping, "official")
    service_df = apply_mapping(load_excel(service), service_mapping, "service")

    result = compare_orders(official_df, service_df)

    return jsonify({"rows": result.rows, "summary": result.summary})


@app.route("/api/export", methods=["POST"])
def export():
    payload = request.get_json(force=True, silent=True) or {}
    rows = payload.get("rows", [])
    summary = payload.get("summary", {})

    output_df = pd.DataFrame(rows)
    output_df = output_df[
        ["index", "order_no", "product", "sales", "cost", "profit", "status_mark"]
    ].rename(
        columns={
            "index": "序号",
            "order_no": "订单号",
            "product": "商品名称",
            "sales": "销售金额",
            "cost": "成本",
            "profit": "单笔利润",
            "status_mark": "状态标记",
        }
    )

    summary_df = pd.DataFrame(
        [
            {"统计项": "总销售额", "值": summary.get("total_sales", 0)},
            {"统计项": "总成本", "值": summary.get("total_cost", 0)},
            {"统计项": "总利润", "值": summary.get("total_profit", 0)},
            {"统计项": "订单总数", "值": summary.get("order_count", 0)},
        ]
    )

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        output_df.to_excel(writer, index=False, sheet_name="对账结果")
        summary_df.to_excel(writer, index=False, sheet_name="汇总")

    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name="订单对账结果.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
