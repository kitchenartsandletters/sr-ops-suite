from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Preformatted
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import unicodedata

import os

# Register Unicode font
FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans.ttf")
pdfmetrics.registerFont(TTFont("DejaVuSans", FONT_PATH))


def add_page_header(canvas, doc, report_title, window_text):
    canvas.saveState()

    # Draw headers ABOVE the story frame (safe area)
    header_y = doc.pagesize[1] - 0.6 * inch

    canvas.setFont("DejaVuSans", 12)
    canvas.drawString(doc.leftMargin, header_y, report_title)

    canvas.setFont("DejaVuSans", 9)
    canvas.drawString(doc.leftMargin, header_y - 14, window_text)

    canvas.restoreState()


def strip_leading_articles(title):
    if not title:
        return title
    lowered = title.lstrip()
    articles = ["the ", "a ", "an "]
    for art in articles:
        if lowered.lower().startswith(art):
            return lowered[len(art):]
    return lowered


def normalize_unicode(value):
    if not value:
        return value
    return unicodedata.normalize("NFKD", value)


def sort_rows(rows):
    return sorted(
        rows,
        key=lambda r: strip_leading_articles(normalize_unicode(r.get("title", "")))
    )


def generate_section_header(text, styles):
    return Paragraph(f"<para align='left'><b>{text}</b></para>", styles["Heading4"])


def make_table(data, col_widths):
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F6F6F7")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, 0), "DejaVuSans"),
                ("FONTNAME", (0, 1), (-1, -1), "DejaVuSans"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D9D9DB")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return table


def build_section(title, rows, story, styles):
    """
    rows is a list of dicts coming from daily_sales_report.py buckets, e.g.:

    {
        "title": str,
        "author": str,
        "collections": [...],
        "isbn": str,
        "available": int | None,
        "ol_sold": int,
        "pos_sold": int,
        "attributes": str,
    }
    """
    if not rows:
        return

    story.append(generate_section_header(title, styles))
    story.append(Spacer(1, 0.15 * inch))

    headers = ["Title", "Author", "OL", "POS", "On Hand", "Attributes"]
    data = [
        [
            Paragraph(headers[0], styles["BodyText"]),
            Paragraph(headers[1], styles["BodyText"]),
            Paragraph(headers[2], styles["BodyText"]),
            headers[3],
            headers[4],
            headers[5],
        ]
    ]

    # Track which rows are "Collections:" rows so we can span + style them
    collection_row_indices = []

    for r in sort_rows(rows):
        title_val = Paragraph(normalize_unicode(r.get("title", "")), styles["BodyText"])
        author_val = Paragraph(normalize_unicode(r.get("author", "")), styles["BodyText"])

        ol = r.get("ol_sold", 0) or 0
        pos = r.get("pos_sold", 0) or 0
        on_hand = r.get("available", "")
        attrs = normalize_unicode(r.get("attributes", ""))

        raw_collections = r.get("collections", [])
        collections_text = ", ".join(raw_collections) if raw_collections else "None"
        collections_display = f"Collections: {normalize_unicode(collections_text)}"

        collections_para = Paragraph(collections_display, styles["CollectionsStyle"])

        # Main product row
        data.append(
            [
                title_val,
                author_val,
                Paragraph(str(ol), styles["BodyText"]),
                str(pos),
                str(on_hand),
                attrs,
            ]
        )

        # Collections row (initially in first column; we will span it via TableStyle)
        data.append(
            [
                collections_para,
                "",
                "",
                "",
                "",
                "",
            ]
        )
        collection_row_indices.append(len(data) - 1)

    # Column widths for the main table
    col_widths = [
        2.5 * inch,  # Title
        1.6 * inch,  # Author
        0.5 * inch,  # OL
        0.6 * inch,  # POS
        0.8 * inch,  # On Hand
        1.8 * inch,  # Attributes
    ]

    table = Table(data, colWidths=col_widths, repeatRows=1)

    # Base table style (very similar to make_table, but extended for collections rows)
    base_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F6F6F7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("FONTNAME", (0, 0), (-1, 0), "DejaVuSans"),
        ("FONTNAME", (0, 1), (-1, -1), "DejaVuSans"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D9D9DB")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]

    # Apply spans + smaller font + indent for each collections row
    for row_idx in collection_row_indices:
        base_style.append(("SPAN", (0, row_idx), (-1, row_idx)))
        base_style.append(("FONTSIZE", (0, row_idx), (-1, row_idx), 7))
        base_style.append(("LEFTPADDING", (0, row_idx), (-1, row_idx), 12))

    table.setStyle(TableStyle(base_style))

    story.append(table)
    story.append(Spacer(1, 0.3 * inch))


def generate_daily_sales_pdf(sections, output_path, report_title, window_text):
    """
    sections is a dict:

        {
            "main":        [bucket_dict, ...],
            "backorders":  [bucket_dict, ...],
            "out_of_stock":[bucket_dict, ...],
            "preorders":   [bucket_dict, ...],
        }

    Each bucket_dict has the shape documented in build_section().
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=0.8 * inch,
        rightMargin=0.8 * inch,
        topMargin=1.1 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    styles["BodyText"].fontName = "DejaVuSans"
    styles["Heading4"].fontName = "DejaVuSans"

    # --- New: Style for single-line, truncated collections row ---
    from reportlab.lib.styles import ParagraphStyle
    styles.add(
        ParagraphStyle(
            name="CollectionsStyle",
            parent=styles["BodyText"],
            fontName="DejaVuSans",
            fontSize=7,
            leading=8,
            wordWrap="CJK",   # required by ReportLab, but overridden by maxLines=1
            maxLines=1,
            ellipsis=True,
        )
    )

    story = []

    section_specs = [
        ("Main Sales", sections.get("main", [])),
        ("Backorders", sections.get("backorders", [])),
        ("Out of Stock", sections.get("out_of_stock", [])),
        ("Preorders", sections.get("preorders", [])),
    ]

    for title, rows in section_specs:
        build_section(title, rows, story, styles)

    doc.build(
        story,
        onFirstPage=lambda canvas, doc: add_page_header(canvas, doc, report_title, window_text),
        onLaterPages=lambda canvas, doc: add_page_header(canvas, doc, report_title, window_text)
    )
