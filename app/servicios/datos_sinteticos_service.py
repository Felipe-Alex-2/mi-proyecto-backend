"""Reproducible simulation; never inserts into operational business tables."""
from collections import defaultdict
from datetime import date, timedelta
from io import BytesIO
import math
import random

import joblib
import numpy as np
import sklearn
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import StandardScaler


def encode(value):
    output = BytesIO()
    joblib.dump(value, output, compress=3)
    return output.getvalue()


def decode(value):
    return joblib.load(BytesIO(value))


def special_day(day):
    # Christmas shopping and the last Friday in November (Black Friday).
    black_friday = day.month == 11 and day.weekday() == 4 and (day + timedelta(days=7)).month == 12
    return int(black_friday or (day.month == 12 and 15 <= day.day <= 24))


def demand_features(week, category, branch):
    return {'category': category, 'branch': branch,
            'month_sin': math.sin(2 * math.pi * week.month / 12),
            'month_cos': math.cos(2 * math.pi * week.month / 12),
            'week_of_year': week.isocalendar().week,
            'special_days': sum(special_day(week + timedelta(days=i)) for i in range(7))}


def generate(parameters, branches):
    rng = random.Random(parameters.seed)
    start, end = parameters.date_from, parameters.date_to
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    day_weights = [(1.7 if day.weekday() >= 5 else 1) * (3 if special_day(day) else 1) for day in days]
    categories = ['Abrigos', 'Poleras', 'Pantalones', 'Vestidos', 'Camisas']
    customers = [{'id': f'C{i:05}', 'name': f'Cliente sintético {i + 1}',
                  'profile': ('frecuente' if i % 5 == 0 else 'ocasional' if i % 5 < 4 else 'esporádico')}
                 for i in range(parameters.customers)]
    customer_weights = [8 if c['profile'] == 'frecuente' else 2 if c['profile'] == 'ocasional' else .4 for c in customers]
    products = [{'id': f'P{i:04}', 'name': f'{categories[i % 5]} sintético {i + 1}',
                 'category': categories[i % 5], 'price': round(rng.uniform(45, 400), 2)}
                for i in range(parameters.products)]
    anomalies = set(rng.sample(range(parameters.sales), max(2, round(parameters.sales * .03))))
    sales, returns = [], []
    for index, day in enumerate(rng.choices(days, weights=day_weights, k=parameters.sales)):
        winter = day.month in (5, 6, 7, 8)
        weights = [(3.5 if winter else .6) if p['category'] == 'Abrigos' else
                   (2.7 if not winter else .8) if p['category'] in ('Poleras', 'Vestidos') else 1.4 for p in products]
        product = rng.choices(products, weights=weights)[0]
        customer = rng.choices(customers, weights=customer_weights)[0]
        anomalous = index in anomalies
        quantity = rng.randint(15, 45) if anomalous else rng.choices([1, 2, 3, 4], [65, 25, 8, 2])[0]
        discount = rng.choice([0, 10, 15, 20]) if special_day(day) else rng.choice([0, 0, 0, 5, 10])
        amount = round(quantity * product['price'] * (1 - discount / 100), 2)
        sale = {'id': f'S{index:06}', 'date': day.isoformat(), 'customer_id': customer['id'],
                'product_id': product['id'], 'category': product['category'],
                'branch': rng.choice(branches), 'quantity': quantity, 'unit_price': product['price'],
                'discount_percent': discount, 'amount': amount, 'injected_anomaly': anomalous}
        sales.append(sale)
        if anomalous or rng.random() < .07:
            returned = max(1, quantity - 1) if anomalous else 1
            return_day = min(end, day + timedelta(days=rng.randint(1, 14)))
            returns.append({'sale_id': sale['id'], 'date': return_day.isoformat(), 'quantity': returned,
                            'amount': round(amount * returned / quantity, 2)})
    sales.sort(key=lambda row: (row['date'], row['id']))
    raw = {'customers': customers, 'products': products, 'sales': sales, 'returns': returns,
           'branches': branches, 'categories': categories}
    prepared, transformers, summary = preprocess(raw, start, end, parameters.seed)
    return {'raw': raw, 'prepared': prepared}, encode(transformers), summary


def preprocess(raw, start, end, seed):
    """Clean, select and encode; all fitted transforms see training rows only."""
    customer_ids = {row['id'] for row in raw['customers']}
    product_ids = {row['id'] for row in raw['products']}
    sales, seen, discarded = [], set(), 0
    for row in raw['sales']:
        valid = (row['id'] not in seen and row['customer_id'] in customer_ids and row['product_id'] in product_ids
                 and row['branch'] in raw['branches'] and row['category'] in raw['categories']
                 and start.isoformat() <= row['date'] <= end.isoformat() and row['quantity'] > 0
                 and math.isfinite(row['amount']) and row['amount'] >= 0)
        if not valid:
            discarded += 1
            continue
        seen.add(row['id']); sales.append(row)
    sales.sort(key=lambda row: (row['date'], row['id']))
    sale_map = {row['id']: row for row in sales}
    returned = defaultdict(int)
    valid_returns = []
    for row in raw['returns']:
        sale = sale_map.get(row['sale_id'])
        if (sale and row['quantity'] > 0 and returned[row['sale_id']] + row['quantity'] <= sale['quantity']
                and sale['date'] <= row['date'] <= end.isoformat() and math.isfinite(row['amount']) and row['amount'] >= 0):
            returned[row['sale_id']] += row['quantity']; valid_returns.append(row)
        else:
            discarded += 1
    raw['sales'], raw['returns'] = sales, valid_returns
    grouped, rfm = defaultdict(int), {}
    for row in sales:
        day = date.fromisoformat(row['date'])
        week = day - timedelta(days=day.weekday())
        grouped[(week.isoformat(), row['category'], row['branch'])] += row['quantity']
        client = rfm.setdefault(row['customer_id'], {'customer_id': row['customer_id'], 'recency': 0, 'frequency': 0, 'monetary': 0})
        client['recency'] = (end - day).days  # Sorted dates: last purchase wins.
        client['frequency'] += 1; client['monetary'] += row['amount']
    # Keep full weeks only and include zero-demand category/branch combinations.
    first = start + timedelta(days=(-start.weekday()) % 7)
    weeks = []
    while first + timedelta(days=6) <= end:
        weeks.append(first); first += timedelta(days=7)
    cutoff = max(1, int(len(weeks) * .8))
    demand = []
    for index, week in enumerate(weeks):
        for category in raw['categories']:
            for branch in raw['branches']:
                demand.append({'week': week.isoformat(), 'category': category, 'branch': branch,
                               'units': grouped[(week.isoformat(), category, branch)],
                               'split': 'train' if index < cutoff else 'test',
                               'features': demand_features(week, category, branch)})
    encoder = DictVectorizer(sparse=False)
    train_features = [row['features'] for row in demand if row['split'] == 'train']
    vector_train = encoder.fit_transform(train_features)
    demand_scaler = StandardScaler().fit(vector_train)
    demand_matrix = demand_scaler.transform(encoder.transform([row['features'] for row in demand]))
    rfm_rows = sorted(rfm.values(), key=lambda row: row['customer_id'])
    indices = np.random.default_rng(seed).permutation(len(rfm_rows))
    train_customers = set(int(i) for i in indices[:int(len(indices) * .8)])
    rfm_matrix = np.log1p([[row['recency'], row['frequency'], row['monetary']] for row in rfm_rows])
    rfm_scaler = StandardScaler().fit(rfm_matrix[sorted(train_customers)])
    rfm_matrix = rfm_scaler.transform(rfm_matrix)
    anomaly = []
    for i, row in enumerate(sales):
        anomaly.append({'sale_id': row['id'], 'date': row['date'], 'category': row['category'], 'branch': row['branch'],
                        'quantity': row['quantity'], 'amount': row['amount'], 'returned_quantity': returned[row['id']],
                        'return_ratio': returned[row['id']] / row['quantity'], 'discount_percent': row['discount_percent'],
                        'injected_anomaly': row['injected_anomaly'], 'split': 'train' if i < int(len(sales) * .8) else 'test'})
    anomaly_features = ['quantity', 'amount', 'returned_quantity', 'return_ratio', 'discount_percent']
    anomaly_matrix = np.array([[row[key] for key in anomaly_features] for row in anomaly], dtype=float)
    anomaly_train = [i for i, row in enumerate(anomaly) if row['split'] == 'train']
    anomaly_scaler = StandardScaler().fit(anomaly_matrix[anomaly_train])
    anomaly_matrix = anomaly_scaler.transform(anomaly_matrix)
    for i, row in enumerate(rfm_rows):
        row['monetary'] = round(row['monetary'], 2)
        row['split'] = 'train' if i in train_customers else 'test'
    transformers = {'encoder': encoder, 'demand_scaler': demand_scaler, 'rfm_scaler': rfm_scaler,
                    'anomaly_scaler': anomaly_scaler, 'anomaly_features': anomaly_features}
    prepared = {'demand': demand, 'rfm': rfm_rows, 'anomaly': anomaly,
                'demand_matrix': demand_matrix.tolist(), 'rfm_matrix': rfm_matrix.tolist(),
                'anomaly_matrix': anomaly_matrix.tolist()}
    summary = {'customers': len(raw['customers']), 'customers_with_purchases': len(rfm_rows),
               'products': len(raw['products']), 'sales': len(sales), 'returns': len(valid_returns),
               'injected_anomalies': sum(row['injected_anomaly'] for row in sales), 'discarded_rows': discarded,
               'weeks': len(weeks), 'demand_train': len(train_features), 'demand_test': len(demand) - len(train_features),
               'train_until': weeks[cutoff - 1].isoformat(), 'test_from': weeks[cutoff].isoformat(),
               'features': list(encoder.get_feature_names_out()), 'anomaly_features': anomaly_features,
               'preprocessing': 'Limpieza, selección, one-hot de categoría/sucursal y estandarización ajustada solo con entrenamiento; RFM con log1p.',
               'assumptions': ['Mayor frecuencia en fines de semana', 'Abrigos en mayo–agosto; prendas ligeras el resto del año',
                               'Picos por Black Friday y compras navideñas', 'Clientes frecuentes, ocasionales y esporádicos',
                               '3% de ventas con cantidades y devoluciones inusuales'],
               'currency': 'BOB', 'branches': raw['branches'], 'categories': raw['categories'],
               'sklearn_version': sklearn.__version__, 'preprocessing_version': 1}
    return prepared, transformers, summary
