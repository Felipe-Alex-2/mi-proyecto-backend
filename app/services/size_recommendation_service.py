import math
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.models.product import Product
from app.models.category import Category
from app.models.size import Size
from app.models.size_guide import SizeGuide
from app.models.biometric_profile import BiometricProfile
from app.schemas.virtual_fitting import (
    SizeRecommendationResponse,
    FitDetailItem,
    SizeOptionScore,
)

# Tablas maestras biométricas internacionales por defecto (en cm)
DEFAULT_SIZE_CHARTS = {
    "HOMBRE": {
        "XS": {"chest": (82, 88), "waist": (70, 76), "hip": (84, 90), "height": (160, 170)},
        "S":  {"chest": (88, 94), "waist": (76, 82), "hip": (90, 96), "height": (165, 175)},
        "M":  {"chest": (94, 102), "waist": (82, 90), "hip": (96, 104), "height": (170, 182)},
        "L":  {"chest": (102, 110), "waist": (90, 98), "hip": (104, 112), "height": (175, 188)},
        "XL": {"chest": (110, 118), "waist": (98, 106), "hip": (112, 120), "height": (180, 192)},
        "XXL": {"chest": (118, 128), "waist": (106, 116), "hip": (120, 130), "height": (180, 195)},
    },
    "MUJER": {
        "XS": {"chest": (78, 84), "waist": (60, 66), "hip": (86, 92), "height": (155, 165)},
        "S":  {"chest": (84, 90), "waist": (66, 72), "hip": (92, 98), "height": (158, 168)},
        "M":  {"chest": (90, 98), "waist": (72, 80), "hip": (98, 106), "height": (162, 172)},
        "L":  {"chest": (98, 106), "waist": (80, 88), "hip": (106, 114), "height": (165, 176)},
        "XL": {"chest": (106, 114), "waist": (88, 98), "hip": (114, 122), "height": (168, 180)},
        "XXL": {"chest": (114, 124), "waist": (98, 108), "hip": (122, 132), "height": (168, 182)},
    }
}


class SizeRecommendationService:

    @staticmethod
    def calculate_recommendation(
        db: Session,
        gender: str,
        height_cm: float,
        weight_kg: float,
        chest_cm: float,
        waist_cm: float,
        hip_cm: float,
        product_id: Optional[str] = None,
        category_id: Optional[str] = None,
    ) -> SizeRecommendationResponse:
        """
        Algoritmo central de recomendación de talla con IA geométrica-estadística.
        Calcula la distancia multidimensional entre las medidas del cliente y las matrices de tallas,
        generando el score de confianza y el desglose de ajuste (Fit Analysis).
        """
        clean_gender = "MUJER" if "MUJER" in gender.upper() else "HOMBRE"
        charts = DEFAULT_SIZE_CHARTS.get(clean_gender, DEFAULT_SIZE_CHARTS["HOMBRE"])

        # Identificar si el producto tiene variantes de tallas específicas
        target_product = None
        available_product_sizes: List[str] = []
        if product_id:
            target_product = db.query(Product).filter(Product.id == product_id).first()
            if target_product:
                category_id = target_product.category_id
                for v in target_product.variants:
                    if v.is_active and v.size and v.size.name not in available_product_sizes:
                        available_product_sizes.append(v.size.name.upper())

        # Evaluar cada talla y su distancia
        evaluated_scores: List[Dict[str, Any]] = []

        # Pesos según zona anatómica (Pecho y Cintura suelen ser los más críticos)
        w_chest = 0.40
        w_waist = 0.35
        w_hip = 0.25

        for size_code, ranges in charts.items():
            chest_mid = (ranges["chest"][0] + ranges["chest"][1]) / 2.0
            waist_mid = (ranges["waist"][0] + ranges["waist"][1]) / 2.0
            hip_mid = (ranges["hip"][0] + ranges["hip"][1]) / 2.0

            # Desviación normalizada
            diff_chest = abs(chest_cm - chest_mid) / ((ranges["chest"][1] - ranges["chest"][0]) or 1.0)
            diff_waist = abs(waist_cm - waist_mid) / ((ranges["waist"][1] - ranges["waist"][0]) or 1.0)
            diff_hip = abs(hip_cm - hip_mid) / ((ranges["hip"][1] - ranges["hip"][0]) or 1.0)

            # Distancia euclidiana ponderada
            dist = math.sqrt(
                w_chest * (diff_chest ** 2) +
                w_waist * (diff_waist ** 2) +
                w_hip * (diff_hip ** 2)
            )

            # Convertir distancia en Porcentaje de Confianza (60% a 98%)
            confidence = max(60.0, min(98.5, round(100.0 - (dist * 22.0), 1)))

            # Resumen breve
            if dist < 0.35:
                fit_summary = "Ajuste Perfecto"
            elif chest_cm > ranges["chest"][1]:
                fit_summary = "Ajustado en pecho"
            elif waist_cm > ranges["waist"][1]:
                fit_summary = "Ceñido en cintura"
            else:
                fit_summary = "Holgado cómodo"

            evaluated_scores.append({
                "size": size_code,
                "distance": dist,
                "confidence": confidence,
                "fit_summary": fit_summary,
                "ranges": ranges
            })

        # Ordenar por menor distancia (mayor coincidencia)
        evaluated_scores.sort(key=lambda x: x["distance"])

        # Si el producto tiene tallas disponibles, priorizar la mejor que esté en stock
        best_match = evaluated_scores[0]
        if available_product_sizes:
            matching = [s for s in evaluated_scores if s["size"] in available_product_sizes]
            if matching:
                best_match = matching[0]

        chosen_size = best_match["size"]
        confidence_score = best_match["confidence"]
        ranges = best_match["ranges"]

        # Generar diagnóstico de Fit detallado (Fase 4 - Simulación de Ajuste)
        fit_details: List[FitDetailItem] = []

        # 1. Pecho / Busto
        chest_min, chest_max = ranges["chest"]
        chest_label = "Busto" if clean_gender == "MUJER" else "Pecho"
        if chest_cm > chest_max:
            diff = round(chest_cm - chest_max, 1)
            fit_details.append(FitDetailItem(
                zone=chest_label,
                fit_status="AJUSTADO",
                difference_cm=diff,
                message=f"Ajustado en el {chest_label.lower()} (+{diff} cm respecto a la horma)"
            ))
        elif chest_cm < chest_min:
            diff = round(chest_min - chest_cm, 1)
            fit_details.append(FitDetailItem(
                zone=chest_label,
                fit_status="HOLGADO",
                difference_cm=-diff,
                message=f"Suelto en el {chest_label.lower()} (-{diff} cm para mayor holgura)"
            ))
        else:
            fit_details.append(FitDetailItem(
                zone=chest_label,
                fit_status="IDEAL",
                difference_cm=0.0,
                message=f"Ajuste ideal en el {chest_label.lower()} (medida dentro del rango óptimo)"
            ))

        # 2. Cintura
        waist_min, waist_max = ranges["waist"]
        if waist_cm > waist_max:
            diff = round(waist_cm - waist_max, 1)
            fit_details.append(FitDetailItem(
                zone="Cintura",
                fit_status="AJUSTADO",
                difference_cm=diff,
                message=f"Ceñido en la cintura (+{diff} cm)"
            ))
        elif waist_cm < waist_min:
            diff = round(waist_min - waist_cm, 1)
            fit_details.append(FitDetailItem(
                zone="Cintura",
                fit_status="HOLGADO",
                difference_cm=-diff,
                message=f"Cintura con caída relajada (-{diff} cm)"
            ))
        else:
            fit_details.append(FitDetailItem(
                zone="Cintura",
                fit_status="IDEAL",
                difference_cm=0.0,
                message="Ajuste ergonómico exacto en la cintura"
            ))

        # 3. Cadera
        hip_min, hip_max = ranges["hip"]
        if hip_cm > hip_max:
            diff = round(hip_cm - hip_max, 1)
            fit_details.append(FitDetailItem(
                zone="Cadera",
                fit_status="AJUSTADO",
                difference_cm=diff,
                message=f"Ligeramente ceñido en cadera (+{diff} cm)"
            ))
        elif hip_cm < hip_min:
            diff = round(hip_min - hip_cm, 1)
            fit_details.append(FitDetailItem(
                zone="Cadera",
                fit_status="HOLGADO",
                difference_cm=-diff,
                message="Suelto en cadera para máxima movilidad"
            ))
        else:
            fit_details.append(FitDetailItem(
                zone="Cadera",
                fit_status="IDEAL",
                difference_cm=0.0,
                message="Ajuste perfecto y proporcionado en cadera"
            ))

        # Resumen global
        if confidence_score >= 90:
            fit_overall = f"Ajuste óptimo recomendado: Talla {chosen_size}"
        elif confidence_score >= 80:
            fit_overall = f"Buen ajuste: Talla {chosen_size} (con ligeros puntos de holgura/ceñido)"
        else:
            fit_overall = f"Talla aproximada: {chosen_size}"

        # Buscar variante sugerida en el producto si existe
        suggested_variant_id = None
        if target_product:
            for v in target_product.variants:
                if v.is_active and v.size and v.size.name.upper() == chosen_size.upper():
                    suggested_variant_id = v.id
                    break

        other_evaluated = [
            SizeOptionScore(
                size_code=s["size"],
                confidence_score=s["confidence"],
                fit_summary=s["fit_summary"]
            )
            for s in evaluated_scores if s["size"] != chosen_size
        ]

        return SizeRecommendationResponse(
            recommended_size=chosen_size,
            confidence_score=confidence_score,
            fit_overall=fit_overall,
            fit_details=fit_details,
            other_sizes_evaluated=other_evaluated,
            suggested_variant_id=suggested_variant_id
        )
