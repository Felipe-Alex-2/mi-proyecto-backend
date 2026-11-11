"""Persist an authorized report snapshot, speak its actual figures and mail its PDF."""
import io,json,logging,smtplib,base64
import httpx
from datetime import datetime,timezone
from email.message import EmailMessage
from xml.sax.saxutils import escape
from fastapi import HTTPException
from app.configuracion import settings
from app.modelos.reporte_guardado import ReporteGuardado
from app.esquemas.reporte import ReporteResponse

LABELS={'interpretation_source':'Interpretación','unit_price':'Precio unitario neto','current_value':'Valor de venta del stock','day':'Día','week':'Semana','month':'Mes','year':'Año','movement_type':'Tipo de movimiento','previous_stock':'Stock anterior','new_stock':'Stock nuevo','reason':'Motivo','courier':'Repartidor','fee':'Envío cotizado (USD)','distance_km':'Distancia (km)','estimated_minutes':'Minutos estimados','points':'Puntos','description':'Descripción','role':'Rol','active':'Activo','estimated_amount':'Importe estimado','payment_status':'Estado de pago','reservation_code':'Código de reserva','created_at':'Fecha de registro','unitemized_sales':'Cobros sin detalle de prendas','unpriced_sales':'Ventas sin desglose histórico de importes','records_shown':'Filas mostradas','limit_scope':'Límite aplicado','company_name':'Empresa','branch_name':'Sucursal','payment_code':'Código de comprobante',
 'concept':'Concepto','paid_at':'Fecha de pago','payment_type':'Forma de pago','reference':'Referencia',
 'exchange_code':'Código para cambios','exchange_limit':'Plazo de cambio','price':'Precio unitario',
 'size':'Talla','color':'Color','address':'Dirección','matching_records':'Registros encontrados','groups':'Grupos',
 'period':'Periodo consultado','ranking_criterion':'Criterio de comparación',
 'comparison_sales':'Cobros de todo el ámbito','comparison_units':'Unidades de todo el ámbito','least_stock_branch':'Menor inventario',
 'company':'Empresa','companies':'Empresas','branch':'Sucursal','city':'Ciudad','units':'Unidades','sales':'Cobros realizados',
 'amount':'Importe cobrado','currency':'Moneda','scope':'Ámbito','total_units':'Unidades totales','branches':'Sucursales','records':'Registros',
 'product':'Prenda','products':'Prendas','category':'Categoría','categories':'Categorías','season':'Temporada','seasons':'Temporadas',
 'supplier':'Proveedor','suppliers':'Proveedores','customer':'Cliente','customers':'Clientes','email':'Correo','status':'Estado',
 'quantity':'Cantidad','threshold':'Umbral','alerts':'Alertas','sku':'SKU','registered_at':'Fecha de registro','reservations':'Reservas',
 'total':'Total','variants_in_stock':'Variantes con stock','most_stock_branch':'Mayor inventario','product_names':'Prendas'}


def label(key):
    for prefix,title in [('sum_','Total de '),('avg_','Promedio de '),('count_','Cantidad de '),('distinct_','Valores distintos de '),('min_','Mínimo de '),('max_','Máximo de ')]:
        if key.startswith(prefix):return title+label(key[len(prefix):])
    if key.startswith('leader_'): return 'Mayor venta en '+key[7:]
    if key.startswith('comparison_total_'): return 'Total de todo el ámbito en '+key[17:]
    if key.startswith('lowest_'): return 'Menor venta en '+key[7:]
    if key.startswith('total_') and key not in LABELS: return 'Total en '+key[6:]
    return LABELS.get(key,key.replace('_',' '))


def value(v):
    return ', '.join(map(str,v)) if isinstance(v,list) else str(v) if v is not None else '—'


def narration(report):
    parts=[report.title+'.']
    parts += [f'{label(k)}: {value(v)}.' for k,v in report.summary.items()]
    if not report.rows: parts.append('No hay registros para los filtros seleccionados.')
    for row in report.rows[:20]:
        parts.append('; '.join(f'{label(k)}: {value(row.get(k))}' for k in report.columns)+'.')
    if len(report.rows)>20: parts.append('La lectura incluye los primeros 20 registros. El PDF y CSV contienen el reporte completo.')
    return ' '.join(parts)


def pdf(report):
    from reportlab.lib.pagesizes import A4,landscape
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
    out=io.BytesIO();page=landscape(A4) if len(report.columns)>5 else A4
    doc=SimpleDocTemplate(out,pagesize=page,rightMargin=30,leftMargin=30,topMargin=32,bottomMargin=32)
    styles=getSampleStyleSheet();small=ParagraphStyle('Cell',parent=styles['BodyText'],fontSize=8,leading=11)
    paragraph=lambda text:Paragraph(escape(value(text)),small)
    story=[Paragraph('VESTA · '+escape(report.title),styles['Heading1']),
        paragraph('Generado: '+datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')),Spacer(1,12)]
    for key,val in report.summary.items(): story.append(paragraph(label(key)+': '+value(val)))
    story.append(Spacer(1,14))
    if report.columns:
        data=[[paragraph(label(k)) for k in report.columns]]
        data += [[paragraph(row.get(k)) for k in report.columns] for row in report.rows]
        if not report.rows:data.append([paragraph('Sin registros')]+[paragraph('') for _ in report.columns[1:]])
        table=Table(data,colWidths=[(page[0]-60)/len(report.columns)]*len(report.columns),repeatRows=1,hAlign='LEFT')
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#F0E5DA')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('GRID',(0,0),(-1,-1),.35,colors.HexColor('#D9C8BA')),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
        story.append(table)
    def footer(canvas,document):
        canvas.setFont('Helvetica',8);canvas.drawRightString(page[0]-30,18,f'VESTA · Página {document.page}')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()


def send_report_email(recipient,report):
    if settings.RESEND_API_KEY:
        if not settings.REPORT_EMAIL_FROM:return False
        attachment=pdf(report)
        try:
            result=httpx.post('https://api.resend.com/emails',
                headers={'Authorization':'Bearer '+settings.RESEND_API_KEY},
                json={'from':settings.REPORT_EMAIL_FROM,'to':[recipient],'subject':'VESTA · '+report.title,
                    'text':'Adjuntamos el reporte solicitado en PDF.\n\n'+report.title,
                    'attachments':[{'filename':'reporte-vesta.pdf','content':base64.b64encode(attachment).decode()}]},timeout=15)
            result.raise_for_status()
            return bool(result.json().get('id'))
        except (httpx.HTTPError,ValueError):
            logging.getLogger(__name__).warning('El proveedor HTTPS no aceptó el correo del reporte.')
            return False
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:return False
    msg=EmailMessage();msg['Subject']='VESTA · '+report.title;msg['From']=settings.SMTP_USER;msg['To']=recipient
    msg.set_content('Adjuntamos el reporte solicitado en PDF.\n\n'+report.title)
    msg.add_attachment(pdf(report),maintype='application',subtype='pdf',filename='reporte-vesta.pdf')
    try:
        with smtplib.SMTP(settings.SMTP_HOST,settings.SMTP_PORT,timeout=10) as server:
            server.ehlo();server.starttls();server.ehlo();server.login(settings.SMTP_USER,settings.SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception:
        logging.getLogger(__name__).warning('No se pudo enviar el PDF del reporte por SMTP.')
        return False


def deliver(db,row,recipient):
    report=ReporteResponse.model_validate_json(row.result_json)
    report.report_id=row.id
    if row.email_status=='SENT' and row.email_to==recipient:return response(row)
    row.email_to=recipient
    row.email_status='SENT' if send_report_email(recipient,report) else 'FAILED'
    db.commit()
    return response(row)


def response(row):
    report=ReporteResponse.model_validate_json(row.result_json)
    report.report_id=row.id;report.email_status=row.email_status
    report.email_message={'SENT':'PDF enviado a '+str(row.email_to),'FAILED':'No se pudo enviar el PDF. Reintenta o revisa la configuración de correo del backend (Resend por HTTPS en Railway Free/Trial/Hobby).' ,'NOT_REQUESTED':''}.get(row.email_status,'')
    return report


def finish(db,user,report,payload):
    report.narration=narration(report)
    row=ReporteGuardado(tenant_id=db.info['tenant_id'],user_id=user.id,result_json=report.model_dump_json(),email_status='NOT_REQUESTED')
    db.add(row);db.commit()
    recipient=user.email if payload.email_self else payload.email_to
    return deliver(db,row,str(recipient)) if recipient else response(row)


def owned(db,user,id):
    row=db.query(ReporteGuardado).execution_options(skip_tenant=True).filter(ReporteGuardado.id==id,ReporteGuardado.user_id==user.id).first()
    if not row:raise HTTPException(404,'Reporte no encontrado en esta cuenta y empresa.')
    return row
