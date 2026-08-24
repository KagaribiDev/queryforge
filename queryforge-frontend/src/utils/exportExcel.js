function displayWidth(value) {
  return Array.from(String(value ?? "")).reduce(
    (width, char) => width + (char.charCodeAt(0) > 255 ? 2 : 1),
    0,
  );
}

function normalizeCellValue(value) {
  if (value == null) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return value;
}

function buildColumnWidths(columns, rows) {
  return columns.map((column) => {
    const maxWidth = rows.reduce(
      (width, row) => Math.max(width, displayWidth(row[column])),
      displayWidth(column),
    );
    return { wch: Math.min(Math.max(maxWidth + 2, 10), 40) };
  });
}

function formatTimestamp(date = new Date()) {
  const pad = (value) => String(value).padStart(2, "0");
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
    "_",
    pad(date.getHours()),
    pad(date.getMinutes()),
    pad(date.getSeconds()),
  ].join("");
}

export function buildTableWorkbook(XLSX, { columns = [], rows = [] } = {}) {
  const workbook = XLSX.utils.book_new();

  const matrix = columns.length
    ? [
        columns,
        ...rows.map((row) => columns.map((column) => normalizeCellValue(row[column]))),
      ]
    : [];
  const worksheet = XLSX.utils.aoa_to_sheet(matrix);

  if (columns.length) {
    worksheet["!cols"] = buildColumnWidths(columns, rows);
    worksheet["!autofilter"] = {
      ref: XLSX.utils.encode_range({
        s: { r: 0, c: 0 },
        e: { r: Math.max(rows.length, 0), c: columns.length - 1 },
      }),
    };
  }

  XLSX.utils.book_append_sheet(workbook, worksheet, "查询结果");
  return workbook;
}

/**
 * 将最近一次回复中的表格数据导出为 Excel。
 * 数据源只允许使用 result SSE 事件保存的 columns/rows，图表配置不参与导出。
 */
export async function exportTableToExcel({ columns = [], rows = [] } = {}) {
  const XLSX = await import("xlsx");
  const workbook = buildTableWorkbook(XLSX, { columns, rows });

  XLSX.writeFileXLSX(
    workbook,
    `QueryForge_最近查询结果_${formatTimestamp()}.xlsx`,
    { compression: true },
  );
}
