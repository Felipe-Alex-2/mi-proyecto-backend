import io
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any
from xml.sax.saxutils import escape as xml_escape

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

from app.modelos.pago import Pago

logger = logging.getLogger("invoice")


def esc(val: Any) -> str:
    """Escapes XML entities so ReportLab Paragraphs don't crash."""
    if val is None:
        return ""
    return xml_escape(str(val))


class FacturaService:
    @staticmethod
    def generate_invoice_pdf(payment: Pago) -> bytes:
        """
        Generates a professional PDF invoice for a completed Pago.
        Returns the raw PDF bytes.
        """
        try:
            return FacturaService._build_pdf(payment)
        except Exception as exc:
            logger.error(f"Error generando PDF estilizado para pago {payment.payment_code}: {exc}. Usando fallback seguro.", exc_info=True)
            return FacturaService._build_fallback_pdf(payment)

    @staticmethod
    def _build_pdf(payment: Pago) -> bytes:
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
        branch_name = esc(payment.branch.name if payment.branch else "Sucursal Principal")
        branch_city = esc(payment.branch.city if payment.branch else "Tienda Oficial")
        branch_address = esc(payment.branch.address if payment.branch else "Venta en Mostrador")
        created_dt = payment.paid_at or payment.created_at or datetime.now(timezone.utc)
        date_str = esc(created_dt.strftime("%d/%m/%Y %H:%M UTC"))

        header_data = [
            [
                Paragraph(f"<b>{esc(payment.company.name if payment.company else 'VESTA')}</b><br/><font size=9 color='#718096'>Sistema de Punto de Venta &amp; Colección Textil</font>", title_style),
                Paragraph(f"<font color='#38A169'><b>✓ PAGO COMPLETADO</b></font><br/><font size=12 color='#1A365D'><b>FACTURA DE VENTA</b></font><br/><font size=9 color='#718096'>N° FAC-{esc(payment.payment_code)}</font>", badge_style),
            ]
        ]
        header_table = Table(header_data, colWidths=[3.8 * inch, 3.8 * inch])
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(header_table)

        story.append(HRFlowable(width="100%", thickness=2, color=PRIMARY_COLOR, spaceBefore=4, spaceAfter=12))

        # --- INFO META SECTION ---
        cashier_name = esc(payment.cashier.full_name if (payment.cashier and getattr(payment.cashier, 'full_name', None)) else (payment.cashier.email if payment.cashier else "Caja de Sucursal"))
        pay_method_label = "PayPal Sandbox (Online)" if payment.payment_type == "PAYPAL" else "Efectivo (Caja Física)"

        info_data = [
            [
                Paragraph("DATOS DE LA SUCURSAL", label_style),
                Paragraph("DATOS DEL CLIENTE", label_style),
            ],
            [
                Paragraph(f"<b>Sucursal:</b> {branch_name} ({branch_city})<br/><b>Ubicación:</b> {branch_address}<br/><b>Cajero/a:</b> {cashier_name}", value_style),
                Paragraph(f"<b>Cliente:</b> {esc(payment.customer_name)}<br/><b>Email:</b> {esc(payment.customer_email or 'No registrado')}<br/><b>Código Cobro:</b> {esc(payment.payment_code)}", value_style),
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
                Paragraph(f"<b>Fecha de Emisión:</b> {date_str}<br/><b>Concepto:</b> {esc(payment.concept)}", value_style),
                Paragraph(f"<b>Método de Pago:</b> {pay_method_label}<br/><b>Referencia:</b> {esc(payment.reference or payment.paypal_order_id or 'Caja Local')}<br/><b>Estado:</b> <font color='#276749'><b>{esc(payment.status)}</b></font>", value_style),
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

        currency = esc(payment.currency or "USD")

        # 1) Try items_detail (direct POS sale)
        has_items = False
        if payment.items_detail:
            try:
                parsed = json.loads(payment.items_detail)
                if isinstance(parsed, list) and len(parsed) > 0:
                    has_items = True
                    for idx, itm in enumerate(parsed, 1):
                        p_name = esc(itm.get("product_name", "Prenda"))
                        variant_str = f"SKU: {esc(itm.get('sku', 'N/A'))}"
                        if itm.get("size") or itm.get("color"):
                            variant_str += f" | {esc(itm.get('color', ''))} / {esc(itm.get('size', ''))}".strip(" /")
                        qty = itm.get("quantity", 1)
                        unit_p = float(itm.get("unit_price", 0.0))
                        subtot = float(itm.get("subtotal", qty * unit_p))

                        items_rows.append([
                            Paragraph(str(idx), cell_center),
                            Paragraph(f"<b>{p_name}</b><br/><font size=7 color='#718096'>{variant_str}</font>", cell_style),
                            Paragraph(str(qty), cell_center),
                            Paragraph(f"${unit_p:.2f} {currency}", cell_right),
                            Paragraph(f"${subtot:.2f} {currency}", cell_right),
                        ])
            except Exception as e:
                logger.warning(f"No se pudo parsear items_detail en pago {payment.id}: {e}")
                has_items = False

        # 2) If linked to reservation and no items_detail, use reservation items
        if not has_items and payment.reservation and getattr(payment.reservation, 'items', None):
            has_items = True
            for idx, r_item in enumerate(payment.reservation.items, 1):
                v = r_item.variant
                p_name = esc(v.product.name if (v and v.product) else "Prenda Reservada")
                variant_str = f"SKU: {esc(v.sku if v else 'N/A')}"
                if v and (v.color or v.size):
                    c_name = esc(v.color.name if v.color else "")
                    s_name = esc(v.size.name if v.size else "")
                    variant_str += f" | {c_name} / {s_name}".strip(" /")
                unit_p = float(v.product.price) if (v and v.product and v.product.price) else 0.0
                subtot = round(unit_p * r_item.quantity, 2)

                items_rows.append([
                    Paragraph(str(idx), cell_center),
                    Paragraph(f"<b>{p_name}</b><br/><font size=7 color='#718096'>{variant_str}</font>", cell_style),
                    Paragraph(str(r_item.quantity), cell_center),
                    Paragraph(f"${unit_p:.2f} {currency}", cell_right),
                    Paragraph(f"${subtot:.2f} {currency}", cell_right),
                ])

        # 3) Fallback to single concept line
        if not has_items:
            items_rows.append([
                Paragraph("1", cell_center),
                Paragraph(f"<b>{esc(payment.concept)}</b><br/><font size=7 color='#718096'>Venta registrada en mostrador de caja</font>", cell_style),
                Paragraph("1", cell_center),
                Paragraph(f"${float(payment.amount):.2f} {currency}", cell_right),
                Paragraph(f"${float(payment.amount):.2f} {currency}", cell_right),
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
        iva_float = 0.00

        totals_data = [
            [Paragraph("<b>Subtotal:</b>", cell_right), Paragraph(f"${subtotal_float:.2f} {currency}", cell_right)],
            [Paragraph("<b>IVA / Impuestos (0%):</b>", cell_right), Paragraph(f"${iva_float:.2f} {currency}", cell_right)],
            [
                Paragraph("<font size=11 color='#1A365D'><b>TOTAL PAGADO:</b></font>", cell_right),
                Paragraph(f"<font size=12 color='#1A365D'><b>${total_float:.2f} {currency}</b></font>", cell_right),
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
            notes_p = Paragraph(f"<b>Notas de la transacción:</b> {esc(payment.notes)}", value_style)
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

    @staticmethod
    def _build_fallback_pdf(payment: Pago) -> bytes:
        """Safe fallback PDF generator in case stylized generation encountered an unexpected layout issue."""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40)
        styles = getSampleStyleSheet()
        story = [
            Paragraph(f"<b>{esc(payment.company.name if payment.company else 'VESTA')} - FACTURA N° FAC-{esc(payment.payment_code)}</b>", styles["Heading1"]),
            Spacer(1, 10),
            Paragraph(f"<b>Cliente:</b> {esc(payment.customer_name)}", styles["Normal"]),
            Paragraph(f"<b>Email:</b> {esc(payment.customer_email or 'N/A')}", styles["Normal"]),
            Paragraph(f"<b>Concepto:</b> {esc(payment.concept)}", styles["Normal"]),
            Paragraph(f"<b>Total:</b> ${float(payment.amount):.2f} {esc(payment.currency or 'USD')}", styles["Normal"]),
            Paragraph(f"<b>Estado:</b> {esc(payment.status)}", styles["Normal"]),
            Paragraph(f"<b>Método:</b> {esc(payment.payment_type)}", styles["Normal"]),
            Spacer(1, 20),
            Paragraph("Comprobante oficial generado automáticamente.", styles["Italic"]),
        ]
        doc.build(story)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes

    @staticmethod
    def generate_subscription_invoice_pdf(payment: Any, tenant: Any, user: Any) -> bytes:
        """
        Generates a professional PDF receipt for a SaaS subscription payment.
        """
        try:
            return FacturaService._build_subscription_pdf(payment, tenant, user)
        except Exception as exc:
            logger.error(f"Error generando PDF de suscripción {payment.id}: {exc}", exc_info=True)
            return FacturaService._build_fallback_subscription_pdf(payment, tenant, user)

    @staticmethod
    def _build_subscription_pdf(payment: Any, tenant: Any, user: Any) -> bytes:
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
        PRIMARY_COLOR = colors.HexColor("#A64F3D")   # Vesta Terracotta
        SECONDARY_COLOR = colors.HexColor("#2B6CB0")
        TEXT_DARK = colors.HexColor("#2D3748")
        TEXT_MUTED = colors.HexColor("#718096")
        BG_LIGHT = colors.HexColor("#FAF7F2")
        BORDER_LIGHT = colors.HexColor("#E9DFD5")

        title_style = ParagraphStyle(
            "SubDocTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=PRIMARY_COLOR,
        )
        subtitle_style = ParagraphStyle(
            "SubDocSubTitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=TEXT_MUTED,
        )
        badge_style = ParagraphStyle(
            "SubPaidBadge",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            textColor=colors.HexColor("#22543D"),
            alignment=2,
        )
        label_style = ParagraphStyle(
            "SubFieldLabel",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=11,
            textColor=PRIMARY_COLOR,
        )
        value_style = ParagraphStyle(
            "SubFieldValue",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=TEXT_DARK,
        )
        table_header_style = ParagraphStyle(
            "SubTableHeader",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=TEXT_DARK,
        )
        table_cell_style = ParagraphStyle(
            "SubTableCell",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=TEXT_DARK,
        )

        story = []

        # Header Block
        header_table_data = [
            [
                Paragraph("<b>VESTA · PLATAFORMA SAAS</b><br/>Recibo Oficial de Suscripción", title_style),
                Paragraph(f"<b>PAGO CONFIRMADO</b><br/><font color='#718096' size='8'>PayPal Sandbox</font>", badge_style),
            ]
        ]
        header_table = Table(header_table_data, colWidths=[5.2 * inch, 2.4 * inch])
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(header_table)
        story.append(HRFlowable(width="100%", thickness=1.5, color=PRIMARY_COLOR, spaceAfter=14))

        # Information Cards
        created_str = (payment.paid_at or payment.created_at).strftime("%d/%m/%Y %H:%M") if hasattr(payment.created_at, "strftime") else str(payment.created_at or "")
        days_count = getattr(payment, 'duration_days', None) or 30
        duration_label = f"{days_count} días"
        plan_name = esc(getattr(payment, 'plan_name', None) or 'Profesional')
        expires_str = payment.expires_at.strftime("%d/%m/%Y") if payment.expires_at and hasattr(payment.expires_at, "strftime") else f"{days_count} días de cobertura"

        tenant_name = esc(tenant.name if tenant else "Empresa VESTA")
        admin_name = esc(user.full_name if user else "Administrador")
        admin_email = esc(user.email if user else "N/A")

        info_box = [
            [
                Paragraph("<b>DATOS DE LA EMPRESA</b>", label_style),
                Paragraph("<b>DETALLE DEL COMPROBANTE</b>", label_style),
            ],
            [
                Paragraph(f"<b>Empresa:</b> {tenant_name}<br/><b>Admin:</b> {admin_name}<br/><b>Email:</b> {admin_email}", value_style),
                Paragraph(f"<b>Recibo N°:</b> SUB-{esc(payment.id[:8].upper())}<br/><b>Fecha de pago:</b> {created_str}<br/><b>Vigencia hasta:</b> {expires_str}", value_style),
            ]
        ]
        info_table = Table(info_box, colWidths=[3.8 * inch, 3.8 * inch])
        info_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 16))

        # Items Table
        items_data = [
            [
                Paragraph("<b>Concepto y Beneficios Adquiridos</b>", table_header_style),
                Paragraph("<b>Duración</b>", table_header_style),
                Paragraph("<b>Precio</b>", table_header_style),
                Paragraph("<b>Importe</b>", table_header_style),
            ],
            [
                Paragraph(
                    f"<b>Plan {plan_name} VESTA</b><br/>"
                    "<font size='8' color='#718096'>"
                    "• Suscripción por período fijo, sin renovación automática"
                    "</font>",
                    table_cell_style
                ),
                Paragraph(duration_label, table_cell_style),
                Paragraph(f"${float(payment.amount):.2f} USD", table_cell_style),
                Paragraph(f"<b>${float(payment.amount):.2f} USD</b>", table_cell_style),
            ]
        ]
        items_table = Table(items_data, colWidths=[4.2 * inch, 1.1 * inch, 1.1 * inch, 1.2 * inch])
        items_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F0EAE1")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(items_table)
        story.append(Spacer(1, 14))

        # Totals and PayPal metadata
        totals_data = [
            [
                Paragraph(f"<b>Referencia PayPal Orden:</b> {esc(payment.paypal_order_id or 'Sin orden')}<br/><b>Referencia Captura:</b> {esc(payment.capture_id or 'Sin captura')}<br/><b>Pasarela:</b> PayPal Sandbox (Cobro verificado)", subtitle_style),
                Paragraph(f"<b>Total Pagado:</b> <font color='#A64F3D' size='13'>${float(payment.amount):.2f} USD</font>", title_style),
            ]
        ]
        totals_table = Table(totals_data, colWidths=[4.5 * inch, 3.1 * inch])
        totals_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(totals_table)
        story.append(Spacer(1, 20))

        # Footer terms
        footer_box = [
            [
                Paragraph(
                    f"<b>INFORMACIÓN DE SUSCRIPCIÓN:</b> Este comprobante acredita la contratación del plan {plan_name} por {days_count} días. La fecha de vigencia indicada incluye los días acumulados de pagos anteriores cuando corresponde. No se realizan cobros automáticos recurrentes.",
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

        doc.build(story)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes

    @staticmethod
    def _build_fallback_subscription_pdf(payment: Any, tenant: Any, user: Any) -> bytes:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40)
        styles = getSampleStyleSheet()
        story = [
            Paragraph(f"<b>VESTA - RECIBO DE SUSCRIPCIÓN N° SUB-{esc(payment.id[:8].upper())}</b>", styles["Heading1"]),
            Spacer(1, 10),
            Paragraph(f"<b>Empresa:</b> {esc(tenant.name if tenant else 'VESTA')}", styles["Normal"]),
            Paragraph(f"<b>Administrador:</b> {esc(user.full_name if user else 'Admin')} ({esc(user.email if user else '')})", styles["Normal"]),
            Paragraph(f"<b>Concepto:</b> Plan {esc(getattr(payment, 'plan_name', None) or 'Profesional')} ({payment.duration_days} días)", styles["Normal"]),
            Paragraph(f"<b>Total Pagado:</b> ${float(payment.amount):.2f} USD", styles["Normal"]),
            Paragraph(f"<b>Estado:</b> {esc(payment.status)}", styles["Normal"]),
            Paragraph(f"<b>Orden PayPal:</b> {esc(payment.paypal_order_id or 'N/A')}", styles["Normal"]),
            Paragraph(f"<b>Captura PayPal:</b> {esc(payment.capture_id or 'N/A')}", styles["Normal"]),
            Spacer(1, 20),
            Paragraph("Comprobante oficial de suscripción generado automáticamente por VESTA.", styles["Italic"]),
        ]
        doc.build(story)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes
