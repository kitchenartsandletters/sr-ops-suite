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
pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans-Bold.ttf")))


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
    return Paragraph(f"<para align='left'><b><font size='12'>{text.upper()}</font></b></para>", styles["Heading4"])


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
                ("FONTSIZE", (0, 0), (-1, -1), 7),
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
        "incoming": int,
        "vendor": str,
    }
    """
    if not rows:
        return

    story.append(generate_section_header(title, styles))
    story.append(Spacer(1, 0.15 * inch))

    headers = ["Title", "Author", "On Hand", "Incoming", "Attributes"]
    data = [
        [
            Paragraph(headers[0], styles["HeaderCell"]),
            Paragraph(headers[1], styles["HeaderCell"]),
            Paragraph(headers[2], styles["HeaderCell"]),
            Paragraph(headers[3], styles["HeaderCell"]),
            Paragraph(headers[4], styles["HeaderCell"]),
        ]
    ]

    combined_row_indices = []

    for r in sort_rows(rows):
        title_val = Paragraph(normalize_unicode(r.get("title", "")), styles["MainRow"])
        author_val = Paragraph(normalize_unicode(r.get("author", "")), styles["MainRow"])
        vendor_val = normalize_unicode(r.get("vendor", ""))

        on_hand = r.get("available", "")
        incoming = r.get("incoming", "")
        attrs = normalize_unicode(r.get("attributes", ""))

        isbn_val = r.get("isbn", "") or ""
        raw_price = r.get("price")
        price_display = ""
        if isinstance(raw_price, (int, float)):
            price_display = f"{raw_price:.2f}"
        elif isinstance(raw_price, str) and raw_price.strip() != "":
            try:
                price_display = f"{float(raw_price):.2f}"
            except (ValueError, TypeError):
                price_display = ""

        raw_collections = r.get("collections", [])
        # collections_text = ", ".join(raw_collections) if raw_collections else "None"
        # collections_display = f"Collections: {normalize_unicode(collections_text)}"
        # collections_para = Paragraph(collections_display, styles["CollectionsRow"])

        isbn_text = f"ISBN: {normalize_unicode(isbn_val)}" if isbn_val else "ISBN: —"
        isbn_para = Paragraph(isbn_text, styles["CollectionsRow"])

        price_text = f"Price: {price_display}" if price_display else "Price: —"
        price_para = Paragraph(price_text, styles["CollectionsRow"])

        # Main product row
        data.append(
            [
                title_val,
                author_val,
                str(on_hand),
                str(incoming),
                attrs,
            ]
        )

        combined_row = [
            "",                       # column 0 (empty string instead of collections)
            isbn_para,               # column 1 (no span)
            price_para,              # column 2 (will span to col 3)
            "",                      # placeholder col 3 for span
            Paragraph(
                f"Vendor: {vendor_val}" if vendor_val else "Vendor: —",
                styles["CollectionsRow"]
            ),                       # column 4
        ]
        data.append(combined_row)
        combined_row_indices.append(len(data) - 1)

    # Column widths for the main table
    col_widths = [
        2.4 * inch,  # Title
        1.6 * inch,  # Author
        0.8 * inch,  # On Hand
        0.8 * inch,  # Incoming
        2.0 * inch,  # Attributes
    ]

    table = Table(data, colWidths=col_widths, repeatRows=1)

    # Base table style (very similar to make_table, but extended for collections rows)
    base_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#A0A0A0")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("FONTNAME", (0, 0), (-1, 0), "DejaVuSans"),
        ("FONTNAME", (0, 1), (-1, -1), "DejaVuSans"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#ECECED")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]

    for row_idx in combined_row_indices:
        # Remove: base_style.append(("SPAN", (0, row_idx), (1, row_idx)))
        base_style.append(("SPAN", (2, row_idx), (3, row_idx)))
        base_style.append(("LEFTPADDING", (0, row_idx), (0, row_idx), 12))
        base_style.append(("LEFTPADDING", (1, row_idx), (1, row_idx), 12))
        base_style.append(("LEFTPADDING", (2, row_idx), (3, row_idx), 12))
        base_style.append(("LEFTPADDING", (4, row_idx), (4, row_idx), 12))
        base_style.append(("BACKGROUND", (0, row_idx), (4, row_idx), colors.HexColor("#F0F0F0")))

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
    styles["Heading4"].fontName = "DejaVuSans-Bold"
    styles["Heading4"].fontSize = 11

    from reportlab.lib.styles import ParagraphStyle

    styles.add(ParagraphStyle(
        name="HeaderCell",
        parent=styles["BodyText"],
        fontName="DejaVuSans",
        fontSize=8,
        leading=9
    ))

    styles.add(ParagraphStyle(
        name="MainRow",
        parent=styles["BodyText"],
        fontName="DejaVuSans",
        fontSize=8,
        leading=9
    ))

    styles.add(ParagraphStyle(
        name="CollectionsRow",
        parent=styles["BodyText"],
        fontName="DejaVuSans",
        fontSize=7,
        leading=8,
        maxLines=1,
        ellipsis=True
    ))

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