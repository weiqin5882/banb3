const requiredFields = ["order_no", "product", "status", "sales", "cost"];
const fieldLabels = {
  order_no: "订单号",
  product: "商品名称",
  status: "订单状态",
  sales: "销售金额",
  cost: "成本金额",
};

let compareRows = [];
let compareSummary = {};
let sortKey = "index";
let sortDirection = "asc";
let currentPage = 1;

function getFiles() {
  const official = document.getElementById("officialFile").files[0];
  const service = document.getElementById("serviceFile").files[0];
  if (!official || !service) {
    alert("请先上传两个文件");
    return null;
  }
  return { official, service };
}

function buildMappingUI(type, columns, autoMapping) {
  const group = document.createElement("div");
  group.className = "map-group";
  group.innerHTML = `<h3>${type === "official" ? "官方订单表" : "客服统计表"}</h3>`;

  requiredFields.forEach((field) => {
    const row = document.createElement("div");
    row.className = "map-row";
    const select = document.createElement("select");
    select.id = `${type}_${field}`;
    select.appendChild(new Option("自动识别", ""));
    columns.forEach((col) => select.appendChild(new Option(col, col)));
    if (autoMapping[field]) select.value = autoMapping[field];
    row.innerHTML = `<span>${fieldLabels[field]}</span>`;
    row.appendChild(select);
    group.appendChild(row);
  });
  return group;
}

async function loadColumns() {
  const files = getFiles();
  if (!files) return;

  const formData = new FormData();
  formData.append("official", files.official);
  formData.append("service", files.service);

  const resp = await fetch("/api/columns", { method: "POST", body: formData });
  const data = await resp.json();
  if (!resp.ok) {
    alert(data.error || "加载字段失败");
    return;
  }

  const area = document.getElementById("mappingArea");
  area.innerHTML = "";
  area.appendChild(buildMappingUI("official", data.official_columns, data.official_auto_mapping));
  area.appendChild(buildMappingUI("service", data.service_columns, data.service_auto_mapping));
}

function applySortAndRender() {
  const rows = [...compareRows].sort((a, b) => {
    const av = a[sortKey];
    const bv = b[sortKey];
    if (typeof av === "number" && typeof bv === "number") {
      return sortDirection === "asc" ? av - bv : bv - av;
    }
    return sortDirection === "asc"
      ? String(av).localeCompare(String(bv), "zh-Hans-CN")
      : String(bv).localeCompare(String(av), "zh-Hans-CN");
  });

  const pageSize = Number(document.getElementById("pageSize").value);
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  if (currentPage > totalPages) currentPage = totalPages;

  const start = (currentPage - 1) * pageSize;
  const pageRows = rows.slice(start, start + pageSize);

  const tbody = document.querySelector("#resultTable tbody");
  tbody.innerHTML = "";
  pageRows.forEach((row) => {
    const tr = document.createElement("tr");
    if (row.loss) tr.classList.add("loss-row");
    tr.innerHTML = `
      <td>${row.index}</td>
      <td>${row.order_no}</td>
      <td>${row.product}</td>
      <td>${row.sales.toFixed(2)}</td>
      <td>${row.cost.toFixed(2)}</td>
      <td>${row.profit.toFixed(2)}</td>
      <td>${row.status_mark}</td>`;
    tbody.appendChild(tr);
  });

  document.getElementById("pager").textContent = `第 ${currentPage}/${totalPages} 页（共 ${rows.length} 条）`;
}

async function compare() {
  const files = getFiles();
  if (!files) return;

  const formData = new FormData();
  formData.append("official", files.official);
  formData.append("service", files.service);

  ["official", "service"].forEach((type) => {
    requiredFields.forEach((field) => {
      const el = document.getElementById(`${type}_${field}`);
      if (el) formData.append(`${type}_${field}`, el.value);
    });
  });

  const resp = await fetch("/api/compare", { method: "POST", body: formData });
  const data = await resp.json();
  if (!resp.ok) {
    alert(data.error || "比对失败");
    return;
  }

  compareRows = data.rows;
  compareSummary = data.summary;
  currentPage = 1;
  applySortAndRender();

  document.getElementById("summary").textContent = `总销售额：${compareSummary.total_sales} ｜ 总成本：${compareSummary.total_cost} ｜ 总利润：${compareSummary.total_profit} ｜ 订单总数：${compareSummary.order_count}`;
  document.getElementById("downloadBtn").disabled = false;
}

async function downloadExcel() {
  const resp = await fetch("/api/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rows: compareRows, summary: compareSummary }),
  });
  const blob = await resp.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "订单对账结果.xlsx";
  a.click();
  URL.revokeObjectURL(url);
}

document.getElementById("loadColumnsBtn").addEventListener("click", loadColumns);
document.getElementById("compareBtn").addEventListener("click", compare);
document.getElementById("downloadBtn").addEventListener("click", downloadExcel);
document.getElementById("pageSize").addEventListener("change", () => {
  currentPage = 1;
  applySortAndRender();
});

document.querySelectorAll("#resultTable th").forEach((th) => {
  th.addEventListener("click", () => {
    const key = th.dataset.key;
    if (sortKey === key) {
      sortDirection = sortDirection === "asc" ? "desc" : "asc";
    } else {
      sortKey = key;
      sortDirection = "asc";
    }
    applySortAndRender();
  });
});
