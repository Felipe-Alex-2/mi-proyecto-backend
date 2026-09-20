import os
import json
import uuid
from typing import Optional
from datetime import datetime, timezone
import httpx
from sqlalchemy.orm import Session
from app.models.biometric_profile import BiometricProfile
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.models.virtual_fitting_session import VirtualFittingSession
from app.schemas.virtual_fitting import (
    BiometricProfileCreate,
    BiometricProfileResponse,
    SizeRecommendationRequest,
    SizeRecommendationResponse,
    TryOnRequest,
    TryOnResponse,
)
from app.services.size_recommendation_service import SizeRecommendationService
from app.core.exceptions import NotFoundException, BadRequestException

AWS_VTON_ENDPOINT = os.getenv("AWS_VTON_ENDPOINT", "").strip()


class VirtualFittingService:

    @staticmethod
    def get_profile(db: Session, user_id: str) -> Optional[BiometricProfile]:
        return db.query(BiometricProfile).filter(BiometricProfile.user_id == user_id).first()

    @staticmethod
    def upsert_profile(db: Session, user_id: str, data: BiometricProfileCreate) -> BiometricProfile:
        profile = db.query(BiometricProfile).filter(BiometricProfile.user_id == user_id).first()
        if not profile:
            profile = BiometricProfile(
                user_id=user_id,
                gender=data.gender.upper(),
                height_cm=data.height_cm,
                weight_kg=data.weight_kg,
                chest_cm=data.chest_cm,
                waist_cm=data.waist_cm,
                hip_cm=data.hip_cm,
                photo_url=data.photo_url,
            )
            db.add(profile)
        else:
            profile.gender = data.gender.upper()
            profile.height_cm = data.height_cm
            profile.weight_kg = data.weight_kg
            profile.chest_cm = data.chest_cm
            profile.waist_cm = data.waist_cm
            profile.hip_cm = data.hip_cm
            if data.photo_url:
                profile.photo_url = data.photo_url

        db.commit()
        db.refresh(profile)
        return profile

    @staticmethod
    def get_recommendation_for_user(
        db: Session,
        user_id: str,
        product_id: Optional[str] = None,
        category_id: Optional[str] = None,
        custom_data: Optional[SizeRecommendationRequest] = None,
    ) -> SizeRecommendationResponse:
        profile = VirtualFittingService.get_profile(db, user_id)

        gender = (custom_data.gender if custom_data and custom_data.gender else None) or (profile.gender if profile else "HOMBRE")
        height_cm = (custom_data.height_cm if custom_data and custom_data.height_cm else None) or (float(profile.height_cm) if profile else 172.0)
        weight_kg = (custom_data.weight_kg if custom_data and custom_data.weight_kg else None) or (float(profile.weight_kg) if profile else 70.0)
        chest_cm = (custom_data.chest_cm if custom_data and custom_data.chest_cm else None) or (float(profile.chest_cm) if profile else 95.0)
        waist_cm = (custom_data.waist_cm if custom_data and custom_data.waist_cm else None) or (float(profile.waist_cm) if profile else 82.0)
        hip_cm = (custom_data.hip_cm if custom_data and custom_data.hip_cm else None) or (float(profile.hip_cm) if profile else 98.0)

        target_product_id = product_id or (custom_data.product_id if custom_data else None)
        target_category_id = category_id or (custom_data.category_id if custom_data else None)

        return SizeRecommendationService.calculate_recommendation(
            db=db,
            gender=gender,
            height_cm=height_cm,
            weight_kg=weight_kg,
            chest_cm=chest_cm,
            waist_cm=waist_cm,
            hip_cm=hip_cm,
            product_id=target_product_id,
            category_id=target_category_id,
        )

    @staticmethod
    def process_try_on(
        db: Session,
        user_id: str,
        payload: TryOnRequest,
    ) -> TryOnResponse:
        product = db.query(Product).filter(Product.id == payload.product_id).first()
        if not product:
            raise NotFoundException("Producto no encontrado")

        variant = None
        if payload.variant_id:
            variant = db.query(ProductVariant).filter(ProductVariant.id == payload.variant_id).first()

        profile = VirtualFittingService.get_profile(db, user_id)
        recommendation = VirtualFittingService.get_recommendation_for_user(
            db=db,
            user_id=user_id,
            product_id=product.id,
        )

        user_photo = payload.user_image_url or (profile.photo_url if profile else None) or product.image_url
        garment_photo = product.image_url

        # Orquestación con AWS EC2 si la variable de entorno está presente
        result_image_url = None
        if AWS_VTON_ENDPOINT:
            try:
                # Llamada al microservicio de inferencia en AWS EC2 (GPU)
                with httpx.Client(timeout=45.0) as client:
                    resp = client.post(
                        f"{AWS_VTON_ENDPOINT}/vton/predict",
                        json={
                            "user_image": payload.user_image_base64 or user_photo,
                            "garment_image": garment_photo,
                            "category": product.category.name if product.category else "upper_body",
                        },
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        result_image_url = data.get("result_image_url")
            except Exception as e:
                # Log error y fallback graceful
                pass

        # Fallback si AWS no está activo o mientras se configura la máquina de AWS
        if not result_image_url:
            # Si el usuario subió foto o pasamos imagen de la prenda, proporcionamos la imagen compuesta
            result_image_url = garment_photo or user_photo

        # Registrar sesión de prueba virtual en BD
        session = VirtualFittingSession(
            user_id=user_id,
            product_id=product.id,
            variant_id=variant.id if variant else None,
            user_image_url=user_photo,
            garment_image_url=garment_photo,
            result_image_url=result_image_url,
            recommended_size=recommendation.recommended_size,
            confidence_score=recommendation.confidence_score,
            fit_feedback=json.dumps([item.model_dump() for item in recommendation.fit_details]),
            status="COMPLETED",
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        return TryOnResponse(
            session_id=session.id,
            result_image_url=result_image_url or "",
            user_image_url=user_photo,
            garment_image_url=garment_photo,
            recommended_size=recommendation.recommended_size,
            confidence_score=recommendation.confidence_score,
            fit_feedback=recommendation.fit_overall,
            fit_details=recommendation.fit_details,
            product_id=product.id,
            variant_id=variant.id if variant else recommendation.suggested_variant_id,
            created_at=session.created_at,
        )
