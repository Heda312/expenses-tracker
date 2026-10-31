"""Export transaksi ke file Excel (.xlsx)."""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, Reference

KIND_LABEL = {
    "expense": "Pengeluaran",
    "income": "Pemasukan",
    "transfer": "Transfer",
}

HEADER_FILL = PatternFill("solid", fgColor="1F2937")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
TITLE_FONT = Font(bold=True, size=14, color="111827")
THIN_BORDER = Border(bottom=Side(style="thin", color="E5E7EB"))
RIGHT = Alignment(horizontal="right")


def _style_header(sheet, columns: int) -> None:
    for column in range(1, columns + 1):
        cell = sheet.cell(row=1, column=column)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")


def build_workbook(rows: list[dict], summary: dict, by_category: list[dict]) -> BytesIO:
    workbook = Workbook()

    # --- Sheet 1: daftar transaksi -----------------------------------------
    sheet = workbook.active
    sheet.title = "Transaksi"
    headers = ["Tanggal", "Jenis", "Kategori", "Dompet", "Merchant", "Catatan", "Nominal", "Sumber"]
    sheet.append(headers)

    for row in rows:
        sheet.append(
            [
                row["date"],
                KIND_LABEL.get(row["kind"], row["kind"]),
                row["category"],
                row["account"],
                row["merchant"],
                row["note"],
                row["amount"],
                row["source"],
            ]
        )

    _style_header(sheet, len(headers))
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(sheet.max_row, 1)}"

    widths = [18, 14, 20, 16, 26, 34, 16, 12]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width

    for row_number in range(2, sheet.max_row + 1):
        sheet.cell(row=row_number, column=7).number_format = '#,##0'
        for column in range(1, len(headers) + 1):
            sheet.cell(row=row_number, column=column).border = THIN_BORDER

    # --- Sheet 2: ringkasan ------------------------------------------------
    recap = workbook.create_sheet("Ringkasan")
    recap["A1"] = f"Ringkasan {summary['label']}"
    recap["A1"].font = TITLE_FONT
    recap.column_dimensions["A"].width = 26
    recap.column_dimensions["B"].width = 20

    lines = [
        ("Total pemasukan", summary["income"]),
        ("Total pengeluaran", summary["expense"]),
        ("Selisih", summary["net"]),
        ("Jumlah transaksi", summary["count"]),
    ]
    for offset, (label, value) in enumerate(lines, start=3):
        recap.cell(row=offset, column=1, value=label)
        cell = recap.cell(row=offset, column=2, value=value)
        if label != "Jumlah transaksi":
            cell.number_format = '#,##0'
            cell.alignment = RIGHT

    recap.cell(row=8, column=1, value="Pengeluaran per kategori").font = Font(bold=True)
    recap.cell(row=9, column=1, value="Kategori")
    recap.cell(row=9, column=2, value="Total")
    for cell in (recap.cell(row=9, column=1), recap.cell(row=9, column=2)):
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL

    for offset, item in enumerate(by_category, start=10):
        recap.cell(row=offset, column=1, value=item["name"])
        cell = recap.cell(row=offset, column=2, value=item["total"])
        cell.number_format = '#,##0'
        cell.alignment = RIGHT

    chart = BarChart()
    chart.title = "Pengeluaran per kategori"
    chart.y_axis.title = "Rupiah"
    chart.x_axis.title = "Kategori"
    chart.add_data(Reference(recap, min_col=2, min_row=9, max_row=9 + len(by_category)), titles_from_data=True)
    chart.set_categories(Reference(recap, min_col=1, min_row=10, max_row=9 + len(by_category)))
    chart.height = 7
    chart.width = 14
    recap.add_chart(chart, "D3")

    # --- Sheet 3: budget (kalau ada) --------------------------------------
    if summary.get("budgets"):
        budget_sheet = workbook.create_sheet("Budget")
        budget_sheet.append(["Kategori", "Budget", "Terpakai", "Sisa", "Pemakaian (%)"])
        for item in summary["budgets"]:
            budget_sheet.append(
                [item["name"], item["amount"], item["spent"], item["remaining"], item["pct"]]
            )
        _style_header(budget_sheet, 5)
        budget_sheet.freeze_panes = "A2"
        for index, width in enumerate([22, 16, 16, 16, 16], start=1):
            budget_sheet.column_dimensions[get_column_letter(index)].width = width
        for row_number in range(2, budget_sheet.max_row + 1):
            for column in (2, 3, 4):
                budget_sheet.cell(row=row_number, column=column).number_format = '#,##0'

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer
