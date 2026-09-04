from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.users import router as users_router
from app.api.v1.branches import router as branches_router
from app.api.v1.attributes import router as attributes_router
from app.api.v1.seasons import router as seasons_router
from app.api.v1.suppliers import router as suppliers_router
from app.api.v1.products import router as products_router
from app.api.v1.stocks import router as stocks_router

api_v1_router = APIRouter(prefix="/v1")

api_v1_router.include_router(auth_router)
api_v1_router.include_router(users_router)
api_v1_router.include_router(branches_router)
api_v1_router.include_router(attributes_router)
api_v1_router.include_router(seasons_router)
api_v1_router.include_router(suppliers_router)
api_v1_router.include_router(products_router)
api_v1_router.include_router(stocks_router)
