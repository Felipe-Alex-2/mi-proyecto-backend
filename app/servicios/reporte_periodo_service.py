"""Calendar periods shared by local interpretation and the AI report planner."""
import calendar
import re
from datetime import date, datetime, time, timedelta, timezone


NUMBERS = {'un': 1, 'uno': 1, 'una': 1, 'dos': 2, 'tres': 3, 'cuatro': 4,
           'cinco': 5, 'seis': 6, 'siete': 7, 'ocho': 8, 'nueve': 9,
           'diez': 10, 'once': 11, 'doce': 12}


def months_before(day: date, months: int) -> date:
    year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
    if year < 1:
        raise ValueError('El periodo solicitado es demasiado amplio.')
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def resolve_period(phrase: str, today: date) -> tuple[dict, str | None]:
    dates = re.findall(r'\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{4}\b', phrase)
    if dates:
        parsed = [date.fromisoformat(v) if '-' in v else date(*map(int, v.split('/')[::-1])) for v in dates]
        if len(parsed) > 2:
            raise ValueError('Indica una fecha inicial y una fecha final.')
        if len(parsed) == 2:
            return {'date_from': parsed[0], 'date_to': parsed[1]}, None
        if 'desde' in phrase:
            return {'date_from': parsed[0], 'date_to': today}, None
        if 'hasta' in phrase:
            return {'date_to': parsed[0]}, None
        return {'date_from': parsed[0], 'date_to': parsed[0]}, None
    if re.search(r'hasta(?:\s+a)?\s+ahora|a\s+la\s+fecha|hasta\s+hoy', phrase):
        return {'date_to': today}, 'Hasta ahora'
    numbers = r'(\d+|' + '|'.join(NUMBERS) + r')'
    rolling = re.search(r'\b' + numbers + r'\s+(dias?|semanas?|mes(?:es)?|anos?)\b', phrase)
    if rolling:
        count = int(rolling[1]) if rolling[1].isdigit() else NUMBERS[rolling[1]]
        if count < 1 or count > 1200:
            raise ValueError('El periodo debe ser de entre 1 y 1200 unidades.')
        unit = rolling[2]
        if re.search(r'\bhace\s*$', phrase[:rolling.start()]):
            if unit.startswith('mes'):
                target = months_before(today, count)
                start, end = target.replace(day=1), target.replace(day=calendar.monthrange(target.year, target.month)[1])
            elif unit.startswith('ano'):
                start, end = date(today.year-count, 1, 1), date(today.year-count, 12, 31)
            elif unit.startswith('semana'):
                start = today - timedelta(days=today.weekday()+count*7)
                end = start + timedelta(days=6)
            else:
                start = end = today - timedelta(days=count)
            return {'date_from':start,'date_to':end}, f'Hace {count} {unit}'
        if unit.startswith('mes'):
            start, label = months_before(today, count), f'Últimos {count} meses'
        elif unit.startswith('ano'):
            start, label = months_before(today, count * 12), f'Últimos {count} años'
        else:
            start = today - timedelta(days=count * (7 if unit.startswith('semana') else 1) - 1)
            label = f'Últimos {count} ' + ('semanas' if unit.startswith('semana') else 'días')
        return {'date_from': start, 'date_to': today}, label
    if 'mes pasado' in phrase:
        end = today.replace(day=1) - timedelta(days=1)
        return {'date_from': end.replace(day=1), 'date_to': end}, 'Mes pasado'
    if 'semana pasada' in phrase:
        end = today - timedelta(days=today.weekday() + 1)
        return {'date_from': end - timedelta(days=6), 'date_to': end}, 'Semana pasada'
    if 'ano pasado' in phrase:
        return {'date_from': date(today.year - 1, 1, 1), 'date_to': date(today.year - 1, 12, 31)}, 'Año pasado'
    if 'ayer' in phrase:
        return {'date_from': today - timedelta(days=1), 'date_to': today - timedelta(days=1)}, 'Ayer'
    if 'hoy' in phrase:
        return {'date_from': today, 'date_to': today}, 'Hoy'
    if 'esta semana' in phrase:
        return {'date_from': today - timedelta(days=today.weekday()), 'date_to': today}, 'Esta semana'
    if 'este mes' in phrase:
        return {'date_from': today.replace(day=1), 'date_to': today}, 'Este mes'
    if 'este ano' in phrase:
        return {'date_from': today.replace(month=1, day=1), 'date_to': today}, 'Este año'
    return {}, None


def describe_period(request) -> str:
    start, end = request.date_from, request.date_to
    if not start and not end:
        return 'Todo el historial'
    text = (f'{start:%d/%m/%Y} al {end:%d/%m/%Y}' if start and end else
            f'Desde {start:%d/%m/%Y}' if start else f'Hasta {end:%d/%m/%Y}')
    return f'{request._period_label} · {text}' if request._period_label else text


def utc_bounds(request):
    tz = timezone(timedelta(hours=-4))
    return (
        datetime.combine(request.date_from, time.min, tz).astimezone(timezone.utc) if request.date_from else None,
        datetime.combine(request.date_to + timedelta(days=1), time.min, tz).astimezone(timezone.utc) if request.date_to else None,
    )


def report_metadata(request, summary, rows, title):
    if request.report_type in {'sales_by_branch', 'sales_by_company', 'payments_detail', 'wallet_topups',
                                'registered_customers', 'reservations_by_branch', 'reservations_status'}:
        summary['period'] = describe_period(request)
    if request.report_type in {'sales_by_branch', 'sales_by_company'}:
        metric = request.sort_by if request.sort_by in {'sales', 'units', 'amount'} else 'amount'
        ascending = bool(request.sort_by) and not request.descending
        if ascending:
            for key in list(summary):
                if key.startswith('leader_'):
                    del summary[key]
            title = 'Menores ventas por ' + ('empresa' if request.report_type == 'sales_by_company' else 'sucursal')
        summary['ranking_criterion'] = {'amount': 'Importe cobrado', 'units': 'Unidades vendidas', 'sales': 'Cantidad de cobros'}[metric]
        if request.only_without_sales:
            for key in list(summary):
                if key.startswith('leader_'):
                    del summary[key]
            summary['ranking_criterion'] = 'Sin cobros en el periodo'
            return 'Empresas sin ventas' if request.report_type == 'sales_by_company' else 'Sucursales sin ventas'
        # Do not fabricate winners for custom aggregation plans lacking these fields.
        for currency in sorted({r['currency'] for r in rows if 'currency' in r and metric in r}):
            candidates = [r for r in rows if r.get('currency') == currency and metric in r]
            best = sorted(candidates, key=lambda r: ((r[metric] if ascending else -r[metric]), r.get('company', ''), r.get('branch', '')))[0]
            summary[('lowest_' if ascending else 'leader_') + currency] = ' · '.join(str(best[k]) for k in ('company', 'branch') if best.get(k))
    elif request.report_type == 'inventory_by_branch' and request.sort_by == 'units' and not request.descending:
        summary.pop('most_stock_branch', None)
        summary['least_stock_branch'] = rows[0]['branch'] if rows else 'Sin sucursales'
        title = 'Menor stock por sucursal'
    return title
