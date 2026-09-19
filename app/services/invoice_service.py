import io
import json
from datetime import datetime, timezone
from typing import List, Dict, Any
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    KeepTogether,
)

from app.models.payment import Payment


class InvoiceService:
    @staticmethod
    def generate_invoice_pdf(payment: Payment) -> bytes:
        """
        Generates a professional PDF invoice for a completed Payment.
        Returns the raw PDF bytes.
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36,
        )

        styles = getSampleStyleSheet()

        # Custom Palette
        PRIMARY_COLOR = colors.HexColor("#1A365D")   # Deep Navy
        SECONDARY_COLOR = colors.HexColor("#2B6CB0") # Steel Blue
        GOLD_ACCENT = colors.HexColor("#D69E2E")     # Elegant Gold
        TEXT_DARK = colors.HexColor("#2D3748")       # Dark Charcoal
        TEXT_MUTED = colors.HexColor("#718096")      # Slate Gray
        BG_LIGHT = colors.HexColor("#F7FAFC")        # Soft Ice
        BORDER_LIGHT = colors.HexColor("#E2E8F0")    # Soft border

        # Custom Typography
        title_style = ParagraphStyle(
            "DocTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            textColor=PRIMARY_COLOR,
        )

        subtitle_style = ParagraphStyle(
            "DocSubTitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=TEXT_MUTED,
        )

        badge_style = ParagraphStyle(
            "PaidBadge",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#22543D"),
            alignment=2,  # Right aligned
        )

        label_style = ParagraphStyle(
            "FieldLabel",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=11,
            textColor=SECONDARY_COLOR,
        )

        value_style = ParagraphStyle(
            "FieldValue",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=TEXT_DARK,
        )

        table_header_style = ParagraphStyle(
            "TableHeader",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=11,
            textColor=colors.white,
            alignment=1,  # Centered
        )

        cell_style = ParagraphStyle(
            "TableCell",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=TEXT_DARK,
        )

        cell_right = ParagraphStyle(
            "TableCellRight",
            parent=cell_style,
            alignment=2,  # Right
        )

        cell_center = ParagraphStyle(
            "TableCellCenter",
            parent=cell_style,
            alignment=1,  # Center
        )

        story = []

        # --- HEADER SECTION ---
        branch_name = payment.branch.name if payment.branch else "Sucursal Principal"
        branch_city = payment.branch.city if payment.branch else "Tienda Oficial"
        branch_address = payment.branch.address if payment.branch else "Venta en Mostrador"
        created_dt = payment.paid_at or payment.created_at or datetime.now(timezone.utc)
        date_str = created_dt.strftime("%d/%m/%Y %H:%M UTC")

        header_data = [
            [
                Paragraph("<b>FASHION STORE</b><br/><font size=9 color='#718096'>Sistema de Punto de Venta & Colección Textil</font>", title_style),
                Paragraph(f"<font color='#38A169'><b>✓ PAGO COMPLETADO</b></font><br/><font size=12 color='#1A365D'><b>FACTURA DE VENTA</b></font><br/><font size=9 color='#718096'>N° FAC-{payment.payment_code}</font>", badge_style),
            ]
        ]
        header_table = Table(header_data, colWidths=[3.8 * inch, 3.8 * inch])
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(header_table)

        story.append(HRFlowable(width="100%", thickness=2, color=PRIMARY_COLOR, spaceBefore=4, spaceAfter=12))

        # --- INFO META SECTION (2 Columns: Sucursal / Factura & Cliente) ---
        cashier_name = payment.cashier.full_name if payment.cashier else (payment.cashier.email if payment.cashier else "Caja de Sucursal")
        pay_method_label = "PayPal Sandbox (Online)" if payment.payment_type == "PAYPAL" else "Efectivo (Caja Física)"

        info_data = [
            [
                Paragraph("DATOS DE LA SUCURSAL", label_style),
                Paragraph("DATOS DEL CLIENTE", label_style),
            ],
            [
                Paragraph(f"<b>Sucursal:</b> {branch_name} ({branch_city})<br/><b>Ubicación:</b> {branch_address}<br/><b>Cajero/a:</b> {cashier_name}", value_style),
                Paragraph(f"<b>Cliente:</b> {payment.customer_name}<br/><b>Email:</b> {payment.customer_email or 'No registrado'}<br/><b>Código Cobro:</b> {payment.payment_code}", value_style),
            ],
            [
                Spacer(1, 4),
                Spacer(1, 4),
            ],
            [
                Paragraph("DETALLES DEL COBRO", label_style),
                Paragraph("MÉTODO Y TRANSACCIÓN", label_style),
            ],
            [
                Paragraph(f"<b>Fecha de Emisión:</b> {date_str}<br/><b>Concepto:</b> {payment.concept}", value_style),
                Paragraph(f"<b>Método de Pago:</b> {pay_method_label}<br/><b>Referencia:</b> {payment.reference or payment.paypal_order_id or 'Caja Local'}<br/><b>Estado:</b> <font color='#276749'><b>{payment.status}</b></font>", value_style),
            ],
        ]

        info_table = Table(info_data, colWidths=[3.8 * inch, 3.8 * inch])
        info_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 14))

        # --- ITEMS TABLE ---
        items_rows = [
            [
                Paragraph("ITEM", table_header_style),
                Paragraph("DESCRIPCIÓN / PRODUCTO", table_header_style),
                Paragraph("CANT.", table_header_style),
                Paragraph("PRECIO UNIT.", table_header_style),
                Paragraph("SUBTOTAL", table_header_style),
            ]
        ]

        # 1) Try items_detail (direct POS sale)
        has_items = False
        if payment.items_detail:
            try:
                parsed = json.loads(payment.items_detail)
                if isinstance(parsed, list) and len(parsed) > 0:
                    has_items = True
                    for idx, itm in enumerate(parsed, 1):
                        p_name = itm.get("product_name", "Prenda")
                        variant_str = f"SKU: {itm.get('sku', 'N/A')}"
                        if itm.get("size") or itm.get("color"):
                            variant_str += f" | {itm.get('color', '')} / {itm.get('size', '')}".strip(" /")
                        qty = itm.get("quantity", 1)
                        unit_p = float(itm.get("unit_price", 0.0))
                        subtot = float(itm.get("subtotal", qty * unit_p))

                        items_rows.append([
                            Paragraph(str(idx), cell_center),
                            Paragraph(f"<b>{p_name}</b><br/><font size=7 color='#718096'>{variant_str}</font>", cell_style),
                            Paragraph(str(qty), cell_center),
                            Paragraph(f"${unit_p:.2f} {payment.currency}", cell_right),
                            Paragraph(f"${subtot:.2f} {payment.currency}", cell_right),
                        ])
            except Exception:
                has_items = False

        # 2) If linked to reservation and no items_detail, use reservation items
        if not has_items and payment.reservation and payment.reservation.items:
            has_items = True
            for idx, r_item in enumerate(payment.reservation.items, 1):
                v = r_item.variant
                p_name = v.product.name if (v and v.product) else "Prenda Reservada"
                variant_str = f"SKU: {v.sku if v else 'N/A'}"
                if v and (v.color or v.size):
                    c_name = v.color.name if v.color else ""
                    s_name = v.size.name if v.size else ""
                    variant_str += f" | {c_name} / {s_name}".strip(" /")
                unit_p = float(v.product.price) if (v and v.product and v.product.price) else 0.0
                subtot = round(unit_p * r_item.quantity, 2)

                items_rows.append([
                    Paragraph(str(idx), cell_center),
                    Paragraph(f"<b>{p_name}</b><br/><font size=7 color='#718096'>{variant_str}</font>", cell_style),
                    Paragraph(str(r_item.quantity), cell_center),
                    Paragraph(f"${unit_p:.2f} {payment.currency}", cell_right),
                    Paragraph(f"${subtot:.2f} {payment.currency}", cell_right),
                ])

        # 3) Fallback to single concept line
        if not has_items:
            items_rows.append([
                Paragraph("1", cell_center),
                Paragraph(f"<b>{payment.concept}</b><br/><font size=7 color='#718096'>Venta registrada en mostrador de caja</font>", cell_style),
                Paragraph("1", cell_center),
                Paragraph(f"${float(payment.amount):.2f} {payment.currency}", cell_right),
                Paragraph(f"${float(payment.amount):.2f} {payment.currency}", cell_right),
            ])

        items_table = Table(items_rows, colWidths=[0.5 * inch, 4.1 * inch, 0.7 * inch, 1.1 * inch, 1.2 * inch])
        items_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), PRIMARY_COLOR),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("TOPPADDING", (0, 0), (-1, 0), 6),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
            ("TOPPADDING", (0, 1), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ]))
        story.append(items_table)
        story.append(Spacer(1, 10))

        # --- TOTALS SUMMARY TABLE ---
        total_float = float(payment.amount)
        subtotal_float = total_float
        iva_float = 0.00  # Tax included / 0%

        totals_data = [
            [Paragraph("<b>Subtotal:</b>", cell_right), Paragraph(f"${subtotal_float:.2f} {payment.currency}", cell_right)],
            [Paragraph("<b>IVA / Impuestos (0%):</b>", cell_right), Paragraph(f"${iva_float:.2f} {payment.currency}", cell_right)],
            [
                Paragraph("<font size=11 color='#1A365D'><b>TOTAL PAGADO:</b></font>", cell_right),
                Paragraph(f"<font size=12 color='#1A365D'><b>${total_float:.2f} {payment.currency}</b></font>", cell_right),
            ],
        ]
        totals_table = Table(totals_data, colWidths=[6.0 * inch, 1.6 * inch])
        totals_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LINEABOVE", (0, 2), (-1, 2), 1.5, PRIMARY_COLOR),
        ]))
        story.append(totals_table)

        # --- NOTES / LEGAL FOOTER ---
        story.append(Spacer(1, 20))
        if payment.notes:
            notes_p = Paragraph(f"<b>Notas de la transacción:</b> {payment.notes}", value_style)
            story.append(notes_p)
            story.append(Spacer(1, 8))

        footer_box = [
            [
                Paragraph(
                    "<b>TÉRMINOS Y CONDICIONES:</b> Este comprobante oficial certifica que los fondos han sido recibidos y liquidados a través de la caja del establecimiento comercial o pasarela autorizada PayPal Sandbox. Conserve esta factura para cualquier cambio, devolución o garantía dentro de los 30 días posteriores a la emisión según las políticas de tienda.",
                    subtitle_style,
                )
            ]
        ]
        footer_table = Table(footer_box, colWidths=[7.6 * inch])
        footer_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(KeepTogether(footer_table))

        # Build document
        doc.build(story)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes
