"""
LOP Unfulfilled Orders PDF Builder

Presentation-only layer.
This module MUST NOT perform business logic, inference, or reclassification.

All emphasis and section membership must be derived from the input data.
"""

from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    PageBreak,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER
from pathlib import Path

# ---------------------------------------------------------------------
# Styling Constants
# ---------------------------------------------------------------------

HEADER_BG = colors.HexColor("#E0E0E0")
EMPHASIS_BG = colors.HexColor("#F2F2F2")

FONT_NORMAL = "Helvetica"
FONT_BOLD = "Helvetica-Bold"

PAGE_MARGIN = 0.5 * inch

# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------

def generate_lop_unfulfilled_pdf(
    order_view_rows,
    tqv_rows,
    op_rows,
    incomplete_orders_rows,
    output_path,
    report_title,
    subtitle,
):
    """
    Generate the LOP Unfulfilled Orders PDF.

    Parameters
    ----------
    order_view_rows : list[dict]
        Fully prepared ORDER VIEW rows.
    tqv_rows : list[dict]
        Fully prepared TOTAL QUANTITY VIEW rows.
    op_rows : list[dict]
        Fully prepared OUT-OF-PRINT ORDERS rows.
    incomplete_orders_rows : list[dict]
        Fully prepared INCOMPLETE ORDERS rows.
    output_path : str | Path
        Destination PDF path.
    report_title : str
        Main title shown at top of report.
    subtitle : str | None
        Optional subtitle (e.g., timestamp or run context).
    """

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=landscape(LETTER),
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN,
    )

    styles = _build_styles()
    elements = []

    # -----------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------

    elements.append(Paragraph(report_title, styles["lop_title"]))
    if subtitle:
        elements.append(Paragraph(subtitle, styles["subtitle"]))
    elements.append(Spacer(1, 0.25 * inch))

    # -----------------------------------------------------------------
    # ORDER VIEW
    # -----------------------------------------------------------------

    elements.append(Paragraph("ORDER VIEW", styles["section_header"]))
    elements.append(Spacer(1, 0.15 * inch))
    elements.append(_build_order_view_table(order_view_rows, styles))
    elements.append(Spacer(1, 0.35 * inch))

    # -----------------------------------------------------------------
    # TOTAL QUANTITY VIEW (TQV)
    # -----------------------------------------------------------------

    if tqv_rows:
        elements.append(Paragraph("TOTAL QUANTITY VIEW", styles["section_header"]))
        elements.append(Spacer(1, 0.15 * inch))
        elements.append(_build_tqv_table(tqv_rows, styles))
        elements.append(Spacer(1, 0.35 * inch))

    # -----------------------------------------------------------------
    # OUT-OF-PRINT (OP) ORDERS
    # -----------------------------------------------------------------

    if op_rows:
        elements.append(Paragraph("OUT-OF-PRINT (OP) ORDERS", styles["section_header"]))
        elements.append(Spacer(1, 0.15 * inch))
        elements.append(_build_op_orders_table(op_rows, styles))
        elements.append(Spacer(1, 0.35 * inch))

    # -----------------------------------------------------------------
    # INCOMPLETE ORDERS
    # -----------------------------------------------------------------

    if incomplete_orders_rows:
        elements.append(Paragraph("INCOMPLETE ORDERS", styles["section_header"]))
        elements.append(Spacer(1, 0.15 * inch))
        elements.append(_build_incomplete_orders_table(incomplete_orders_rows, styles))

    doc.build(elements)

# ---------------------------------------------------------------------
# Table Builders
# ---------------------------------------------------------------------

def _build_order_view_table(rows: list[dict], styles):
    """
    Build ORDER VIEW table.

    Expected row keys (example):
    - order_number
    - product
    - author
    - qty
    - notes
    - attributes
    - emphasis_flags (set[str])
    """

    header = [
        "Order",
        "Product",
        "Author",
        "QTY",
        "Notes",
        "Attributes",
    ]

    data = [header]
    row_styles = []

    for idx, row in enumerate(rows, start=1):
        notes = row.get("notes", "") or ""
        if len(notes) > 20:
            notes = notes[:20].rstrip() + "…"

        data.append([
            Paragraph(str(row["order_number"]), styles["cell_center"]),
            Paragraph(row["product"], styles["cell"]),
            Paragraph(row["author"], styles["cell"]),
            Paragraph(str(row["qty"]), styles["cell_center"]),
            Paragraph(notes, styles["cell"]),
            Paragraph(row.get("attributes", ""), styles["cell"]),
        ])

        if row.get("emphasis_flags"):
            row_styles.append(idx)

    table = Table(
        data,
        repeatRows=1,
        hAlign="LEFT",
        colWidths=[
            0.6 * inch,   # Order
            3.8 * inch,   # Product
            2.0 * inch,   # Author
            0.5 * inch,   # QTY
            1.4 * inch,   # Notes
            1.4 * inch,   # Attributes
        ],
    )
    table.setStyle(_base_table_style())

    for r in row_styles:
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, r), (-1, r), EMPHASIS_BG),
            ("FONTNAME", (0, r), (-1, r), FONT_BOLD),
        ]))

    return table


def _build_tqv_table(rows: list[dict], styles):
    """
    Build TOTAL QUANTITY VIEW (TQV) table.

    Expected row keys:
    - product
    - author
    - qty
    """

    header = [
        "Product",
        "Author",
        "QTY",
    ]

    data = [header]

    for row in rows:
        data.append([
            Paragraph(row["product"], styles["cell"]),
            Paragraph(row["author"], styles["cell"]),
            Paragraph(str(row["qty"]), styles["cell_center"]),
        ])

    table = Table(
        data,
        repeatRows=1,
        hAlign="LEFT",
        colWidths=[
            5.0 * inch,   # Product
            2.5 * inch,   # Author
            0.7 * inch,   # QTY
        ],
    )
    table.setStyle(_base_table_style())

    return table


def _build_op_orders_table(rows: list[dict], styles):
    """
    Build OUT-OF-PRINT (OP) ORDERS table.

    Expected row keys:
    - order_number
    - product
    - author
    - qty
    """

    header = [
        "Order",
        "Product",
        "Author",
        "QTY",
    ]

    data = [header]

    for row in rows:
        data.append([
            Paragraph(str(row["order_number"]), styles["cell_center"]),
            Paragraph(row["product"], styles["cell"]),
            Paragraph(row["author"], styles["cell"]),
            Paragraph(str(row["qty"]), styles["cell_center"]),
        ])

    table = Table(
        data,
        repeatRows=1,
        hAlign="LEFT",
        colWidths=[
            0.8 * inch,   # Order
            4.5 * inch,   # Product
            2.0 * inch,   # Author
            0.7 * inch,   # QTY
        ],
    )
    table.setStyle(_base_table_style())

    return table


def _build_incomplete_orders_table(rows: list[dict], styles):
    """
    Build INCOMPLETE ORDERS table.

    Expected row keys:
    - order_number
    - product
    - author
    - qty
    - reason   ("Preorder" or "Backorder")
    """

    header = [
        "Order",
        "Product",
        "Author",
        "QTY",
        "Reason",
    ]

    data = [header]

    for row in rows:
        data.append([
            Paragraph(str(row["order_number"]), styles["cell_center"]),
            Paragraph(row["product"], styles["cell"]),
            Paragraph(row["author"], styles["cell"]),
            Paragraph(str(row["qty"]), styles["cell_center"]),
            Paragraph(row["reason"], styles["cell"]),
        ])

    table = Table(
        data,
        repeatRows=1,
        hAlign="LEFT",
        colWidths=[
            0.6 * inch,   # Order
            3.8 * inch,   # Product
            2.0 * inch,   # Author
            0.5 * inch,   # QTY
            1.0 * inch,   # Reason
        ],
    )
    table.setStyle(_base_table_style())

    # Entire section is emphasized
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 1), (-1, -1), EMPHASIS_BG),
        ("FONTNAME", (0, 1), (-1, -1), FONT_BOLD),
    ]))

    return table

# ---------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------

def _build_styles():
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="lop_title",
        fontName=FONT_BOLD,
        fontSize=16,
        spaceAfter=6,
    ))

    styles.add(ParagraphStyle(
        name="subtitle",
        fontName=FONT_NORMAL,
        fontSize=10,
        textColor=colors.grey,
        spaceAfter=12,
    ))

    styles.add(ParagraphStyle(
        name="section_header",
        fontName=FONT_BOLD,
        fontSize=12,
        spaceBefore=6,
        spaceAfter=6,
    ))

    styles.add(ParagraphStyle(
        name="cell",
        fontName=FONT_NORMAL,
        fontSize=9,
        leading=11,
        wordWrap="LTR",
    ))

    styles.add(ParagraphStyle(
        name="cell_bold",
        fontName=FONT_BOLD,
        fontSize=9,
        leading=11,
        wordWrap="LTR",
    ))

    styles.add(ParagraphStyle(
    name="cell_center",
    fontName=FONT_NORMAL,
    fontSize=9,
    leading=11,
    alignment=TA_CENTER,
    ))

    return styles


def _base_table_style():
    return TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (3, 0), (3, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.grey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])