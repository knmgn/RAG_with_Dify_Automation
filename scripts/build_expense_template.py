"""
Build script for expense_template_v3.xlsx (expense report template v3).

Generates a dummy Excel expense report template that complies with Demo Logistics
Inc.'s Travel, Expense Reimbursement and HR Procedures Policy (DL-HR-RG-2024-007).
This is the file the bot hands out when an employee asks for the template.

Usage:
    python3 scripts/build_expense_template.py

Output:
    ./expense_template_v3.xlsx

For the §4-7 fully-local Docker setup (recommended for SME deployments),
copy the generated file into the n8n bind-mount directory:

    cp expense_template_v3.xlsx docker/n8n/templates/expense_template_v3.xlsx
    xattr -c docker/n8n/templates/expense_template_v3.xlsx    # macOS only

The xattr -c step is mandatory on macOS to clear Google Drive (drivefs)
extended attributes that otherwise cause EPERM in n8n's Read/Write Files
node. See §4-8 ③ in the design doc.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import (
    Alignment,
    Border,
    Font,
    PatternFill,
    Side,
)
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.dimensions import ColumnDimension


OUTPUT_FILENAME = "expense_template_v3.xlsx"

# Excel number format for U.S. dollar amounts.
USD = '"$"#,##0.00'


NAVY = "1F3864"
LIGHT_NAVY = "2E5A9E"
GREY_BG = "F2F2F2"
ALT_ROW = "FAFAFA"
WARN_BG = "FFF2CC"
ACCENT = "C00000"

THIN = Side(style="thin", color="999999")
BORDER_ALL = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _title_font(size: int = 14, color: str = "FFFFFF") -> Font:
    return Font(name="Calibri", size=size, bold=True, color=color)


def _body_font(size: int = 10, bold: bool = False, color: str = "000000") -> Font:
    return Font(name="Calibri", size=size, bold=bold, color=color)


def _set_col_widths(ws, widths: dict[str, float]) -> None:
    for col, width in widths.items():
        ws.column_dimensions[col].width = width


def build_main_sheet(wb: Workbook) -> None:
    ws = wb.active
    ws.title = "Expense Report"
    ws.sheet_view.showGridLines = False

    _set_col_widths(
        ws,
        {
            "A": 4,
            "B": 12,
            "C": 14,
            "D": 28,
            "E": 26,
            "F": 18,
            "G": 14,
            "H": 10,
            "I": 24,
        },
    )

    ws.merge_cells("A1:I1")
    ws["A1"] = "Expense Reimbursement Form"
    ws["A1"].font = _title_font(16)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws["A1"].fill = PatternFill("solid", fgColor=NAVY)
    ws.row_dimensions[1].height = 32

    ws.merge_cells("A2:I2")
    ws["A2"] = "Form No. F-001-v3 / Governing policy: DL-HR-RG-2024-007 (Revision 3, revised October 1, 2024)"
    ws["A2"].font = _body_font(9, color="595959")
    ws["A2"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 18

    header_rows = [
        ("A4", "Date",       "B4", "",                    "D4", "Report No.",    "E4", ""),
        ("A5", "Name",       "B5", "",                    "D5", "Employee ID",   "E5", ""),
        ("A6", "Department", "B6", "",                    "D6", "Title",         "E6", ""),
        ("A7", "Period",     "B7", "",                    "D7", "Payment date",  "E7", ""),
    ]
    for label_cell, label, value_cell, _, label2_cell, label2, value2_cell, _ in header_rows:
        ws[label_cell] = label
        ws[label_cell].font = _body_font(10, bold=True)
        ws[label_cell].fill = PatternFill("solid", fgColor=GREY_BG)
        ws[label_cell].alignment = Alignment(horizontal="center", vertical="center")
        ws[label_cell].border = BORDER_ALL

        ws.merge_cells(f"{value_cell}:C{value_cell[1:]}")
        ws[value_cell].border = BORDER_ALL
        ws[value_cell].alignment = Alignment(horizontal="left", vertical="center", indent=1)

        ws[label2_cell] = label2
        ws[label2_cell].font = _body_font(10, bold=True)
        ws[label2_cell].fill = PatternFill("solid", fgColor=GREY_BG)
        ws[label2_cell].alignment = Alignment(horizontal="center", vertical="center")
        ws[label2_cell].border = BORDER_ALL

        ws.merge_cells(f"{value2_cell}:I{value2_cell[1:]}")
        ws[value2_cell].border = BORDER_ALL
        ws[value2_cell].alignment = Alignment(horizontal="left", vertical="center", indent=1)

    ws["B4"] = "05/26/2026"
    ws["E4"] = "EX-2026-05-0123"
    ws["B5"] = "Jordan Smith"
    ws["E5"] = "DL-04321"
    ws["B6"] = "Sales, Enterprise Accounts"
    ws["E6"] = "Account Manager"
    ws["B7"] = "05/01/2026 – 05/25/2026"
    ws["E7"] = "06/25/2026 (payroll date)"

    detail_header_row = 9
    detail_headers = [
        ("A", "No."),
        ("B", "Date"),
        ("C", "Category"),
        ("D", "Description / purpose"),
        ("E", "Route / location"),
        ("F", "Attendees / co-riders"),
        ("G", "Amount (USD)"),
        ("H", "Receipt"),
        ("I", "Notes (F-021, etc.)"),
    ]
    for col, label in detail_headers:
        cell = ws[f"{col}{detail_header_row}"]
        cell.value = label
        cell.font = _title_font(10)
        cell.fill = PatternFill("solid", fgColor=LIGHT_NAVY)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER_ALL
    ws.row_dimensions[detail_header_row].height = 28

    sample_rows = [
        (1, "05/08/2026", "Rail",                 "Client visit, Acme Corp",                "Philadelphia ↔ New York (round trip)", "—",                                   186.00, "Yes", ""),
        (2, "05/10/2026", "Rideshare (late night)", "Ride home after work ended late",       "Office (Midtown) → Home (Queens)",     "—",                                    48.20, "Yes", "Work ended 11:45 PM / after last train"),
        (3, "05/14/2026", "Rideshare (daytime)",  "Carrying original contracts with client", "HQ → Beta Inc. (Financial District)", "Ms. Lee (Beta Inc.) rode along",        31.80, "Yes", "Pre-approved 05/12/2026"),
        (4, "05/16/2026", "Air",                  "Joint meeting with Chicago branch",       "LGA → ORD (economy)",                 "—",                                   247.30, "Yes", ""),
        (5, "05/16/2026", "Lodging",              "Business trip lodging (Chicago)",         "Hotel ABC, Chicago",                  "—",                                   205.00, "Yes", "Within USD 220 cap"),
        (6, "05/18/2026", "Rideshare (late night)", "Ride home (work ended 12:30 AM)",       "HQ → Home (Westchester)",             "—",                                   132.40, "Yes", "Over cap: F-021 submitted (dept head + People Ops approval)"),
        (7, "05/20/2026", "Client entertainment", "Dinner with Gamma Co. executives",        "Restaurant XYZ, Manhattan",           "Mr. Tanaka, Ms. Park (Gamma Co.); J. Smith", 286.00, "Yes", "F-009 pre-approved / USD 95.33 per person"),
        (8, "05/22/2026", "Supplies",             "Printer toner",                           "Amazon",                              "—",                                    41.80, "Yes", "Online order screenshot attached"),
        (9, "05/24/2026", "Public transit",       "People Operations meeting",               "Subway (round trip)",                 "—",                                     5.80, "—",   "Under USD 25: statement screenshot"),
    ]

    detail_start = detail_header_row + 1
    for offset, row in enumerate(sample_rows):
        r = detail_start + offset
        for col_idx, value in enumerate(row, start=1):
            cell = ws.cell(row=r, column=col_idx, value=value)
            cell.border = BORDER_ALL
            cell.font = _body_font(10)
            if col_idx == 1:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx == 7:
                cell.alignment = Alignment(horizontal="right", vertical="center", indent=1)
                cell.number_format = USD
            elif col_idx == 8:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center", indent=1, wrap_text=True)
            if offset % 2 == 1:
                cell.fill = PatternFill("solid", fgColor=ALT_ROW)
        ws.row_dimensions[r].height = 22

    blank_rows = 12
    for offset in range(len(sample_rows), len(sample_rows) + blank_rows):
        r = detail_start + offset
        for col_idx in range(1, 10):
            cell = ws.cell(row=r, column=col_idx)
            cell.border = BORDER_ALL
            cell.font = _body_font(10)
            if col_idx == 1:
                cell.value = offset + 1
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx == 7:
                cell.alignment = Alignment(horizontal="right", vertical="center", indent=1)
                cell.number_format = USD
            elif col_idx == 8:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center", indent=1, wrap_text=True)
        ws.row_dimensions[r].height = 22

    total_row = detail_start + len(sample_rows) + blank_rows + 1
    ws.merge_cells(f"A{total_row}:F{total_row}")
    ws[f"A{total_row}"] = "Total"
    ws[f"A{total_row}"].font = _body_font(11, bold=True)
    ws[f"A{total_row}"].fill = PatternFill("solid", fgColor=GREY_BG)
    ws[f"A{total_row}"].alignment = Alignment(horizontal="right", vertical="center", indent=1)
    ws[f"A{total_row}"].border = BORDER_ALL

    last_detail_row = detail_start + len(sample_rows) + blank_rows - 1
    total_cell = ws.cell(row=total_row, column=7)
    total_cell.value = f"=SUM(G{detail_start}:G{last_detail_row})"
    total_cell.number_format = USD
    total_cell.font = _body_font(12, bold=True, color=ACCENT)
    total_cell.alignment = Alignment(horizontal="right", vertical="center", indent=1)
    total_cell.fill = PatternFill("solid", fgColor=GREY_BG)
    total_cell.border = BORDER_ALL

    ws.merge_cells(f"H{total_row}:I{total_row}")
    ws[f"H{total_row}"].border = BORDER_ALL
    ws[f"H{total_row}"].fill = PatternFill("solid", fgColor=GREY_BG)

    advance_row = total_row + 1
    ws.merge_cells(f"A{advance_row}:F{advance_row}")
    ws[f"A{advance_row}"] = "Cash advance received"
    ws[f"A{advance_row}"].font = _body_font(10)
    ws[f"A{advance_row}"].alignment = Alignment(horizontal="right", vertical="center", indent=1)
    ws[f"A{advance_row}"].border = BORDER_ALL
    ws.cell(row=advance_row, column=7, value=0).number_format = USD
    ws.cell(row=advance_row, column=7).alignment = Alignment(horizontal="right", vertical="center", indent=1)
    ws.cell(row=advance_row, column=7).border = BORDER_ALL
    ws.merge_cells(f"H{advance_row}:I{advance_row}")
    ws[f"H{advance_row}"].border = BORDER_ALL

    net_row = advance_row + 1
    ws.merge_cells(f"A{net_row}:F{net_row}")
    ws[f"A{net_row}"] = "Net reimbursement"
    ws[f"A{net_row}"].font = _body_font(11, bold=True)
    ws[f"A{net_row}"].fill = PatternFill("solid", fgColor=WARN_BG)
    ws[f"A{net_row}"].alignment = Alignment(horizontal="right", vertical="center", indent=1)
    ws[f"A{net_row}"].border = BORDER_ALL
    net_cell = ws.cell(row=net_row, column=7, value=f"=G{total_row}-G{advance_row}")
    net_cell.number_format = USD
    net_cell.font = _body_font(12, bold=True, color=ACCENT)
    net_cell.alignment = Alignment(horizontal="right", vertical="center", indent=1)
    net_cell.fill = PatternFill("solid", fgColor=WARN_BG)
    net_cell.border = BORDER_ALL
    ws.merge_cells(f"H{net_row}:I{net_row}")
    ws[f"H{net_row}"].border = BORDER_ALL
    ws[f"H{net_row}"].fill = PatternFill("solid", fgColor=WARN_BG)

    sig_header_row = net_row + 2
    sig_labels = ["Employee", "Manager", "Department head", "Accounts Payable", "People Operations"]
    sig_cols = ["A", "C", "E", "G", "H"]
    sig_widths = [("A", "B"), ("C", "D"), ("E", "F"), ("G", "G"), ("H", "I")]
    for label, (start_col, end_col) in zip(sig_labels, sig_widths):
        ws.merge_cells(f"{start_col}{sig_header_row}:{end_col}{sig_header_row}")
        cell = ws[f"{start_col}{sig_header_row}"]
        cell.value = label
        cell.font = _body_font(10, bold=True)
        cell.fill = PatternFill("solid", fgColor=LIGHT_NAVY)
        cell.font = _title_font(10)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = BORDER_ALL

        ws.merge_cells(f"{start_col}{sig_header_row + 1}:{end_col}{sig_header_row + 1}")
        cell2 = ws[f"{start_col}{sig_header_row + 1}"]
        cell2.border = BORDER_ALL
        cell2.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[sig_header_row + 1].height = 60

        ws.merge_cells(f"{start_col}{sig_header_row + 2}:{end_col}{sig_header_row + 2}")
        cell3 = ws[f"{start_col}{sig_header_row + 2}"]
        cell3.value = "(date)"
        cell3.font = _body_font(8, color="808080")
        cell3.alignment = Alignment(horizontal="center", vertical="center")
        cell3.border = BORDER_ALL

    note_row = sig_header_row + 4
    ws.merge_cells(f"A{note_row}:I{note_row}")
    note_cell = ws[f"A{note_row}"]
    note_cell.value = (
        "* Reports must be received by 5:00 PM on the 25th of each month (Article 8). "
        "Late reports are reimbursed in the month after next and require a Late Submission Explanation (F-007). "
        "For rideshare/taxi fares above the USD 100 per-ride cap, attach the Excess Justification Form F-021 (Article 5, Clause 4)."
    )
    note_cell.font = _body_font(9, color="595959")
    note_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1, wrap_text=True)
    note_cell.fill = PatternFill("solid", fgColor=WARN_BG)
    note_cell.border = BORDER_ALL
    ws.row_dimensions[note_row].height = 36

    category_dv = DataValidation(
        type="list",
        formula1='"Public transit,Rail,Air,Bus,Rideshare (daytime),Rideshare (late night),Personal vehicle,Lodging,Client entertainment,Meetings,Supplies,Phone & internet,Other"',
        allow_blank=True,
    )
    category_dv.error = "Choose a category from the Categories sheet"
    category_dv.errorTitle = "Invalid category"
    ws.add_data_validation(category_dv)
    category_dv.add(f"C{detail_start}:C{last_detail_row}")

    receipt_dv = DataValidation(
        type="list",
        formula1='"Yes,—,E-statement,To follow"',
        allow_blank=True,
    )
    ws.add_data_validation(receipt_dv)
    receipt_dv.add(f"H{detail_start}:H{last_detail_row}")

    ws.print_options.horizontalCentered = True
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins.left = 0.5
    ws.page_margins.right = 0.5
    ws.page_margins.top = 0.6
    ws.page_margins.bottom = 0.6
    ws.print_title_rows = "1:9"


def build_taxi_sheet(wb: Workbook) -> None:
    ws = wb.create_sheet("Rideshare Log")
    ws.sheet_view.showGridLines = False

    _set_col_widths(
        ws,
        {
            "A": 4,
            "B": 12,
            "C": 10,
            "D": 10,
            "E": 22,
            "F": 22,
            "G": 22,
            "H": 14,
            "I": 14,
            "J": 28,
        },
    )

    ws.merge_cells("A1:J1")
    ws["A1"] = "Rideshare and Taxi Log (Article 5 detail)"
    ws["A1"].font = _title_font(14)
    ws["A1"].fill = PatternFill("solid", fgColor=NAVY)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:J2")
    ws["A2"] = (
        "Reimbursed only for late-night rides (after 11:00 PM or after the last train), rides with a client present (pre-approval required) "
        "or unavoidable circumstances. Cap: USD 100 per ride. Submit F-021 for any amount above the cap."
    )
    ws["A2"].font = _body_font(9, color="595959")
    ws["A2"].alignment = Alignment(horizontal="left", vertical="center", indent=1, wrap_text=True)
    ws["A2"].fill = PatternFill("solid", fgColor=WARN_BG)
    ws.row_dimensions[2].height = 32

    headers = [
        "No.",
        "Date",
        "Pickup time",
        "Drop-off time",
        "Pickup location",
        "Drop-off location",
        "Purpose",
        "Amount (USD)",
        "Over cap",
        "F-021 / pre-approval status",
    ]
    for col_idx, label in enumerate(headers, start=1):
        cell = ws.cell(row=4, column=col_idx, value=label)
        cell.font = _title_font(10)
        cell.fill = PatternFill("solid", fgColor=LIGHT_NAVY)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER_ALL
    ws.row_dimensions[4].height = 32

    rows = [
        (1, "05/10/2026", "11:50 PM", "12:18 AM", "Office (Midtown Manhattan)", "Home (Astoria, Queens)", "Ride home after last train (work ended 11:45 PM)", 48.20, "No", "—"),
        (2, "05/14/2026", "1:20 PM", "1:45 PM", "HQ (Midtown Manhattan)", "Beta Inc. (Financial District)", "Client present, carrying original contracts", 31.80, "No", "Pre-approved 05/12/2026 (approver: R. Taylor)"),
        (3, "05/18/2026", "12:35 AM", "1:20 AM", "HQ (Midtown Manhattan)", "Home (White Plains, Westchester)", "Ride home (work ended 12:30 AM)", 132.40, "Yes", "F-021 submitted / dept head approved 5/19 / People Ops approved 5/20"),
    ]

    for offset, row in enumerate(rows):
        r = 5 + offset
        for col_idx, value in enumerate(row, start=1):
            cell = ws.cell(row=r, column=col_idx, value=value)
            cell.border = BORDER_ALL
            cell.font = _body_font(10)
            if col_idx in (1, 3, 4, 9):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx == 8:
                cell.alignment = Alignment(horizontal="right", vertical="center", indent=1)
                cell.number_format = USD
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center", indent=1, wrap_text=True)
            if offset % 2 == 1:
                cell.fill = PatternFill("solid", fgColor=ALT_ROW)
        ws.row_dimensions[r].height = 24

    for offset in range(len(rows), len(rows) + 8):
        r = 5 + offset
        for col_idx in range(1, 11):
            cell = ws.cell(row=r, column=col_idx)
            cell.border = BORDER_ALL
            cell.font = _body_font(10)
            if col_idx == 1:
                cell.value = offset + 1
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx == 8:
                cell.alignment = Alignment(horizontal="right", vertical="center", indent=1)
                cell.number_format = USD
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center", indent=1, wrap_text=True)
        ws.row_dimensions[r].height = 22

    excess_dv = DataValidation(type="list", formula1='"No,Yes"', allow_blank=True)
    ws.add_data_validation(excess_dv)
    excess_dv.add("I5:I20")


def build_advance_sheet(wb: Workbook) -> None:
    ws = wb.create_sheet("Cash Advance")
    ws.sheet_view.showGridLines = False

    _set_col_widths(ws, {"A": 4, "B": 14, "C": 24, "D": 14, "E": 14, "F": 14, "G": 30})

    ws.merge_cells("A1:G1")
    ws["A1"] = "Cash Advance Settlement (Article 12)"
    ws["A1"].font = _title_font(14)
    ws["A1"].fill = PatternFill("solid", fgColor=NAVY)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:G2")
    ws["A2"] = "If you received a cash advance before a trip, settle it on this sheet within 5 business days after return."
    ws["A2"].font = _body_font(9, color="595959")
    ws["A2"].alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[2].height = 22

    headers = ["No.", "Request date", "Purpose", "Advance", "Actual total", "Difference", "Notes"]
    for col_idx, label in enumerate(headers, start=1):
        cell = ws.cell(row=4, column=col_idx, value=label)
        cell.font = _title_font(10)
        cell.fill = PatternFill("solid", fgColor=LIGHT_NAVY)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER_ALL
    ws.row_dimensions[4].height = 24

    for r in range(5, 13):
        for col_idx in range(1, 8):
            cell = ws.cell(row=r, column=col_idx)
            cell.border = BORDER_ALL
            cell.font = _body_font(10)
            if col_idx == 1:
                cell.value = r - 4
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx in (4, 5, 6):
                cell.alignment = Alignment(horizontal="right", vertical="center", indent=1)
                cell.number_format = USD
                if col_idx == 6:
                    cell.value = f"=D{r}-E{r}"
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center", indent=1, wrap_text=True)


def build_category_master(wb: Workbook) -> None:
    ws = wb.create_sheet("Categories")
    ws.sheet_view.showGridLines = False

    _set_col_widths(ws, {"A": 22, "B": 16, "C": 50})

    ws["A1"] = "Category"
    ws["B1"] = "GL account"
    ws["C1"] = "Notes / policy reference"
    for col in ("A1", "B1", "C1"):
        ws[col].font = _title_font(10)
        ws[col].fill = PatternFill("solid", fgColor=LIGHT_NAVY)
        ws[col].alignment = Alignment(horizontal="center", vertical="center")
        ws[col].border = BORDER_ALL
    ws.row_dimensions[1].height = 24

    rows = [
        ("Public transit",          "Travel",        "Article 4 / most economical and fastest route"),
        ("Rail",                    "Travel",        "Article 4, Para. 2 / coach for trips of 100+ miles"),
        ("Air",                     "Travel",        "Article 4, Para. 3 / 300+ miles or saves 2+ hours"),
        ("Bus",                     "Travel",        "Article 4"),
        ("Rideshare (daytime)",     "Travel",        "Article 5, Clause 2 / exceptions only, e.g. client present"),
        ("Rideshare (late night)",  "Travel",        "Article 5, Clause 1 / after 11:00 PM or after the last train"),
        ("Personal vehicle",        "Travel",        "Article 6 / USD 0.67 per mile / F-015 required"),
        ("Lodging",                 "Travel",        "Article 7 / caps by location"),
        ("Client entertainment",    "Entertainment", "Article 10 / F-009 above USD 75 per person"),
        ("Meetings",                "Meetings",      "Meals for internal meetings, etc."),
        ("Supplies",                "Supplies",      "—"),
        ("Phone & internet",        "Communications", "—"),
        ("Other",                   "Miscellaneous", "Manager approval required"),
    ]
    for offset, row in enumerate(rows):
        r = 2 + offset
        for col_idx, value in enumerate(row, start=1):
            cell = ws.cell(row=r, column=col_idx, value=value)
            cell.border = BORDER_ALL
            cell.font = _body_font(10)
            if col_idx == 1:
                cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center", indent=1, wrap_text=True)


def build_instructions_sheet(wb: Workbook) -> None:
    ws = wb.create_sheet("Instructions")
    ws.sheet_view.showGridLines = False

    _set_col_widths(ws, {"A": 4, "B": 100})

    ws.merge_cells("A1:B1")
    ws["A1"] = "expense_template_v3.xlsx — How to fill in"
    ws["A1"].font = _title_font(14)
    ws["A1"].fill = PatternFill("solid", fgColor=NAVY)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    ws.merge_cells("A2:B2")
    ws["A2"] = "Governing policy: Demo Logistics Inc. Travel, Expense Reimbursement and HR Procedures Policy (DL-HR-RG-2024-007, Revision 3)"
    ws["A2"].font = _body_font(9, color="595959")
    ws["A2"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 18

    sections = [
        ("Submission deadline", [
            "Reports must be received by 5:00 PM on the 25th of each month (Article 8).",
            "If the 25th falls on a weekend or holiday, the deadline moves to the preceding business day.",
            "Late reports are reimbursed in the month after next and require a Late Submission Explanation (F-007).",
            "Three or more late submissions in a fiscal year lead to a deduction in the performance review.",
        ]),
        ("How to fill in", [
            "1. Complete the header of the Expense Report sheet (name, employee ID, department, period, etc.).",
            "2. Enter one expense per row. Choose the Category from the drop-down.",
            "3. In the Receipt column choose Yes (receipt attached), — (none), E-statement or To follow.",
            "4. Also record rideshare and taxi rides on the Rideshare Log sheet (Article 5 detail).",
            "5. If you received a cash advance, complete the Cash Advance sheet.",
            "6. Totals and net reimbursement are calculated automatically (avoid inserting rows mid-table so the formulas stay intact).",
            "7. Obtain approvals in this order: manager → department head → Accounts Payable → People Operations.",
        ]),
        ("Receipts", [
            "USD 25 or more: an itemized receipt is required (PDF or JPEG e-receipts are accepted).",
            "Under USD 25: a screenshot of the electronic statement showing date, merchant, amount and purpose is accepted.",
            "Meals: list the names and affiliations of all attendees. Client entertainment above USD 75 per person requires F-009 pre-approval.",
        ]),
        ("Rideshare and taxi rules (Article 5)", [
            "Ride home after work ends after 11:00 PM, or after the last train → reimbursable.",
            "Daytime rides → not reimbursable as a rule. Exceptions: (1) client present + pre-approval, (2) heavy or confidential items, (3) unavoidable circumstances.",
            "Cap: USD 100 per ride (tax and tip included). For any excess, submit the Excess Justification Form F-021 (department head + Director of People Operations).",
            "F-021 is due by 5:00 PM two business days after the ride. After that, the full fare is paid by the employee.",
            "Rides home after private social events, rides to the nearest station, and trips mixed with sightseeing are not reimbursable.",
        ]),
        ("Using this template", [
            "This is template v3. Reports on v2 or older templates are not accepted (Article 9, Paragraph 3).",
            "Macros must be enabled (Article 9, Paragraph 4). Do not change the cell structure or formulas.",
            "Download the file, fill it in locally, and upload it to the FlowDesk workflow system.",
            "Recommended file name: Expenses_YYYY-MM_FirstLast.xlsx",
        ]),
        ("Contacts", [
            "Expenses and payments: Accounts Payable (ext. 1456 / accounts-payable@demo-logistics.example.com)",
            "Policy and HR: People Operations (ext. 1234 / people-ops@demo-logistics.example.com)",
            "Shifts and night work: Logistics Operations (ext. 2210)",
        ]),
    ]

    row = 4
    for title, lines in sections:
        ws.merge_cells(f"A{row}:B{row}")
        cell = ws[f"A{row}"]
        cell.value = title
        cell.font = _body_font(11, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=LIGHT_NAVY)
        cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        cell.border = BORDER_ALL
        ws.row_dimensions[row].height = 22
        row += 1

        for line in lines:
            ws.merge_cells(f"A{row}:B{row}")
            line_cell = ws[f"A{row}"]
            line_cell.value = line
            line_cell.font = _body_font(10)
            line_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1, wrap_text=True)
            line_cell.border = BORDER_ALL
            ws.row_dimensions[row].height = 22
            row += 1

        row += 1


def build() -> Path:
    wb = Workbook()
    build_main_sheet(wb)
    build_taxi_sheet(wb)
    build_advance_sheet(wb)
    build_category_master(wb)
    build_instructions_sheet(wb)

    wb.properties.title = "Expense Report Template v3"
    wb.properties.creator = "Demo Logistics Inc. People Operations"
    wb.properties.lastModifiedBy = "Demo-Logi-Bot"
    wb.properties.subject = "Expense Reimbursement Template (Dummy)"
    wb.properties.description = (
        "Complies with policy DL-HR-RG-2024-007 / dummy file for the Dify x n8n portfolio demo"
    )
    wb.properties.keywords = "expense report, travel, rideshare, policy, demo"

    output_path = Path(__file__).resolve().parent.parent / OUTPUT_FILENAME
    wb.save(output_path)
    return output_path


if __name__ == "__main__":
    path = build()
    print(f"Generated: {path}")
