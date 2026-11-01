from datetime import date
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class GenerarSinteticosRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    name: str = Field(default='Simulación comercial', min_length=2, max_length=120)
    date_from: date
    date_to: date
    customers: int = Field(default=200, ge=20, le=2000)
    products: int = Field(default=50, ge=10, le=200)
    sales: int = Field(default=5000, ge=500, le=20000)
    seed: int = Field(default=42, ge=0, le=2147483647)

    @model_validator(mode='after')
    def valid_dates(self):
        if not 89 <= (self.date_to - self.date_from).days <= 730:
            raise ValueError('El periodo debe tener entre 90 y 731 días, en orden cronológico.')
        self.name = self.name.strip()
        if len(self.name) < 2:
            raise ValueError('Escribe un nombre para el conjunto.')
        return self


class EntrenarRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    dataset_id: UUID
    clusters: int = Field(default=3, ge=2, le=6)


class PrediccionDemandaRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    category: str = Field(min_length=1, max_length=150)
    branch: str = Field(min_length=1, max_length=300)
    week: date
