"""Train/evaluate real estimators; artifacts are created only by this server."""
from datetime import date, timedelta
import hashlib

import numpy as np
import sklearn
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest, RandomForestRegressor
from sklearn.metrics import (f1_score, mean_absolute_error, mean_squared_error,
                             precision_score, r2_score, recall_score, silhouette_score)
from threadpoolctl import threadpool_limits

from app.servicios.datos_sinteticos_service import decode, demand_features, encode

def finite(value):
    return round(float(value), 5) if np.isfinite(value) else None


def silhouette(matrix, labels, seed):
    if not 1 < len(set(labels)) < len(labels):
        return None
    return finite(silhouette_score(matrix, labels, sample_size=min(1000, len(labels)), random_state=seed))


def train_models(dataset, clusters):
    if dataset.summary.get('sklearn_version') != sklearn.__version__:
        raise ValueError('Regenera los datos con la versión actual de scikit-learn.')
    prepared = dataset.payload['prepared']
    seed = dataset.parameters['seed']
    transformers = decode(dataset.preprocessing)
    demand = prepared['demand']
    x = np.array(prepared['demand_matrix'])
    y = np.array([row['units'] for row in demand])
    train = np.array([row['split'] == 'train' for row in demand])
    # Single-thread estimators and BLAS keep the web worker's resources bounded.
    with threadpool_limits(limits=1):
        regressor = RandomForestRegressor(n_estimators=80, max_depth=12, min_samples_leaf=2, random_state=seed, n_jobs=1)
        regressor.fit(x[train], y[train])
        prediction = regressor.predict(x[~train])
        demand_metrics = {'mae': finite(mean_absolute_error(y[~train], prediction)),
                          'rmse': finite(np.sqrt(mean_squared_error(y[~train], prediction))),
                          'r2': finite(r2_score(y[~train], prediction)),
                          'baseline_mae': finite(mean_absolute_error(y[~train], np.full(len(prediction), y[train].mean()))),
                          'train_rows': int(train.sum()), 'test_rows': int((~train).sum()),
                          'split': 'Cronológico por semanas completas: 80% anteriores / 20% posteriores',
                          'train_until': dataset.summary['train_until'], 'test_from': dataset.summary['test_from']}
        rfm = prepared['rfm']
        rfm_x = np.array(prepared['rfm_matrix'])
        rfm_train = np.array([row['split'] == 'train' for row in rfm])
        if len(rfm_x[rfm_train]) <= clusters:
            raise ValueError('No hay suficientes clientes con compras para el número de grupos seleccionado.')
        kmeans = KMeans(n_clusters=clusters, n_init=10, random_state=seed)
        kmeans.fit(rfm_x[rfm_train])
        cluster_labels = kmeans.predict(rfm_x)
        cluster_metrics = {'silhouette': silhouette(rfm_x[~rfm_train], cluster_labels[~rfm_train], seed),
                           'train_silhouette': silhouette(rfm_x[rfm_train], cluster_labels[rfm_train], seed),
                           'clusters': clusters, 'train_rows': int(rfm_train.sum()), 'test_rows': int((~rfm_train).sum()),
                           'features': ['recency_days', 'frequency_purchases', 'monetary_BOB'],
                           'split': '80% de clientes para ajuste y 20% para evaluación; partición reproducible',
                           'note': 'Silueta no disponible cuando la muestra no contiene al menos dos grupos válidos.'}
        anomaly = prepared['anomaly']
        anomaly_x = np.array(prepared['anomaly_matrix'])
        anomaly_train = np.array([row['split'] == 'train' for row in anomaly])
        isolation = IsolationForest(n_estimators=100, contamination=.04, random_state=seed, n_jobs=1)
        isolation.fit(anomaly_x[anomaly_train])
        abnormal = isolation.predict(anomaly_x) == -1
        scores = isolation.decision_function(anomaly_x)
        truth = np.array([row['injected_anomaly'] for row in anomaly])
        anomaly_metrics = {'precision': finite(precision_score(truth[~anomaly_train], abnormal[~anomaly_train], zero_division=0)),
                           'recall': finite(recall_score(truth[~anomaly_train], abnormal[~anomaly_train], zero_division=0)),
                           'f1': finite(f1_score(truth[~anomaly_train], abnormal[~anomaly_train], zero_division=0)),
                           'train_rows': int(anomaly_train.sum()), 'test_rows': int((~anomaly_train).sum()),
                           'test_detected': int(abnormal[~anomaly_train].sum()), 'detected': int(abnormal.sum()),
                           'test_injected': int(truth[~anomaly_train].sum()),
                           'features': transformers['anomaly_features'],
                           'note': 'Evaluación retrospectiva frente a anomalías sintéticas conocidas. La etiqueta no se usa para ajustar el modelo.'}
    groups = []
    for group in range(clusters):
        members = [row for row, label in zip(rfm, cluster_labels) if label == group]
        groups.append({'cluster': group, 'name': f'Grupo {group + 1}', 'customers': len(members),
                       'recency_days': finite(np.mean([r['recency'] for r in members])) if members else None,
                       'frequency': finite(np.mean([r['frequency'] for r in members])) if members else None,
                       'monetary': finite(np.mean([r['monetary'] for r in members])) if members else None})
    flagged = sorted((dict(row, score=finite(score)) for row, flag, score in zip(anomaly, abnormal, scores) if flag), key=lambda row: row['score'])
    test_rows = [row for row in demand if row['split'] == 'test']
    comparisons = [dict(week=row['week'], category=row['category'], branch=row['branch'],
                        actual=row['units'], predicted=finite(estimate)) for row, estimate in zip(test_rows, prediction)]
    bundle = {'version': 1, 'sklearn_version': sklearn.__version__, 'tenant_id': dataset.tenant_id,
              'dataset_id': dataset.id, 'transformers': transformers, 'demand': regressor,
              'clustering': kmeans, 'anomalies': isolation,
              'categories': dataset.summary['categories'], 'branches': dataset.summary['branches']}
    # Example inference is generated from the fitted estimator, not invented UI data.
    last = date.fromisoformat(dataset.parameters['date_to'])
    next_week = last + timedelta(days=7 - last.weekday())
    forecasts = []
    for category in bundle['categories']:
        for branch in bundle['branches']:
            forecasts.append({'week': next_week.isoformat(), 'category': category, 'branch': branch,
                              'predicted_units': infer(bundle, next_week, category, branch)})
    results = {'groups': groups, 'anomalies': flagged[:50], 'comparisons': comparisons[:100],
               'forecasts': forecasts, 'anomalies_total': len(flagged),
               'customer_segments': [{'customer_id': row['customer_id'], 'cluster': int(label)} for row, label in zip(rfm, cluster_labels)]}
    metrics = {'demand': demand_metrics, 'clustering': cluster_metrics, 'anomalies': anomaly_metrics,
               'sklearn_version': sklearn.__version__, 'numpy_version': np.__version__,
               'source': 'synthetic', 'seed': seed, 'currency': 'BOB',
               'limitation': 'Resultados de simulación; no demuestran precisión en ventas reales.'}
    artifact = encode(bundle)
    return metrics, results, artifact, hashlib.sha256(artifact).hexdigest()


def infer(bundle, week, category, branch):
    transformed = bundle['transformers']
    x = transformed['encoder'].transform([demand_features(week, category, branch)])
    x = transformed['demand_scaler'].transform(x)
    return max(0, finite(bundle['demand'].predict(x)[0]))
