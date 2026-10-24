from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime


# --- Biometric Profile Schemas ---
class PerfilBiometricoBase(BaseModel):
    gender: str = Field(..., description="HOMBRE o MUJER")
    height_cm: float = Field(..., ge=80, le=250, description="Altura en cm")
    weight_kg: float = Field(..., ge=20, le=300, description="Peso en kg")
    chest_cm: float = Field(..., ge=40, le=200, description="Pecho o Busto en cm")
    waist_cm: float = Field(..., ge=30, le=200, description="Cintura en cm")
    hip_cm: float = Field(..., ge=40, le=200, description="Cadera en cm")
    photo_url: Optional[str] = Field(None, description="Foto de cuerpo entero (opcional)")


class PerfilBiometricoCreate(PerfilBiometricoBase):
    pass


class PerfilBiometricoResponse(PerfilBiometricoBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Talla Recommendation Schemas ---
class DetalleAjusteItem(BaseModel):
    zone: str              # Pecho, Cintura, Cadera, Largo
    fit_status: str        # AJUSTADO, IDEAL, HOLGADO
    difference_cm: float   # Diferencia en cm respecto a la media del molde
    message: str           # Ej: "Ajustado en el pecho (+2 cm)"


class RecomendacionTallaRequest(BaseModel):
    product_id: Optional[str] = None
    category_id: Optional[str] = None
    # Si el usuario quiere probar medidas sin tener perfil guardado todavía:
    gender: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    chest_cm: Optional[float] = None
    waist_cm: Optional[float] = None
    hip_cm: Optional[float] = None


class PuntuacionOpcionTalla(BaseModel):
    size_code: str
    confidence_score: float
    fit_summary: str


class RecomendacionTallaResponse(BaseModel):
    recommended_size: str
    confidence_score: float = Field(..., description="Porcentaje de confianza, ej. 95.0")
    fit_overall: str        # "Ajuste Excelente", "Ligeramente Ceñido", etc.
    fit_details: List[DetalleAjusteItem] = []
    other_sizes_evaluated: List[PuntuacionOpcionTalla] = []
    suggested_variant_id: Optional[str] = None


# --- Virtual Try-On (VTON) Schemas ---
class PruebaVestuarioRequest(BaseModel):
    product_id: str
    variant_id: Optional[str] = None
    user_image_base64: Optional[str] = None  # Si sube una foto en base64
    user_image_url: Optional[str] = None     # O pasa una URL de foto previa


class PruebaVestuarioResponse(BaseModel):
    session_id: str
    result_image_url: str
    user_image_url: Optional[str] = None
    garment_image_url: Optional[str] = None
    recommended_size: str
    confidence_score: float
    fit_feedback: str
    fit_details: List[DetalleAjusteItem] = []
    product_id: str
    variant_id: Optional[str] = None
    created_at: datetime
