from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.units import inch

import unicodedata


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
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D9D9DB")),
            ]
        )
    )
    return table


def build_section(title, rows, story, styles):
    if not rows:
        return
    story.append(generate_section_header(title, styles))
    story.append(Spacer(1, 0.15 * inch))

    headers = ["Title", "Author", "Qty", "POS", "OnHand", "Attributes"]
    data = [headers]

    for r in sort_rows(rows):
        data.append(
            [
                normalize_unicode(r.get("title", "")),
                normalize_unicode(r.get("author", "")),
                str(r.get("qty", "")),
                str(r.get("pos", "")),
                str(r.get("on_hand", "")),
                ", ".join(r.get("attributes", [])),
            ]
        )

    col_widths = [2.4 * inch, 1.6 * inch, 0.6 * inch, 0.6 * inch, 0.7 * inch, 1.8 * inch]

    story.append(make_table(data, col_widths))
    story.append(Spacer(1, 0.3 * inch))


def generate_daily_sales_pdf(sections, output_path):
    """
    sections = {
        "main": [...],
        "backorders": [...],
        "out_of_stock": [...],
        "preorders": [...],
    }

    Each row is a dict:
    {
        "title": "...",
        "author": "...",
        "qty": int,
        "pos": int,
        "on_hand": int,
        "attributes": [...],
    }
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    story = []

    build_section("Main Sales", sections.get("main", []), story, styles)
    build_section("Backorders", sections.get("backorders", []), story, styles)
    build_section("Out of Stock", sections.get("out_of_stock", []), story, styles)
    build_section("Preorders", sections.get("preorders", []), story, styles)

    doc.build(story)
