from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.schemas.promotion import PromotionCreate, PromotionUpdate, PromotionResponse
from app.services.promotion_service import PromotionService
from app.api.deps import get_current_user, require_admin

router = APIRouter(prefix="/promotions", tags=["Promotions & Discounts"])


@router.get(
    "",
    response_model=List[PromotionResponse],
    status_code=status.HTTP_200_OK,
    summary="List all promotions and discounts",
)
def list_promotions(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, description="Search by promotion name"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    promotions = PromotionService.list_promotions(db, is_active=is_active, search=search)
    return [PromotionService.format_response(p) for p in promotions]


@router.post(
    "",
    response_model=PromotionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create promotion (Admin only)",
)
def create_promotion(
    request: PromotionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    promotion = PromotionService.create_promotion(db, request)
    return PromotionService.format_response(promotion)


@router.get(
    "/{promotion_id}",
    response_model=PromotionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get promotion by ID",
)
def get_promotion(
    promotion_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    promotion = PromotionService.get_promotion_by_id(db, promotion_id)
    return PromotionService.format_response(promotion)


@router.put(
    "/{promotion_id}",
    response_model=PromotionResponse,
    status_code=status.HTTP_200_OK,
    summary="Update promotion (Admin only)",
)
def update_promotion(
    promotion_id: str,
    request: PromotionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    promotion = PromotionService.update_promotion(db, promotion_id, request)
    return PromotionService.format_response(promotion)


@router.patch(
    "/{promotion_id}/toggle-status",
    response_model=PromotionResponse,
    status_code=status.HTTP_200_OK,
    summary="Toggle promotion active status (Admin only)",
)
def toggle_status(
    promotion_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    promotion = PromotionService.toggle_status(db, promotion_id)
    return PromotionService.format_response(promotion)
