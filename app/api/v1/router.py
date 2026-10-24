from fastapi import APIRouter, Depends
from app.api.auditoria_negocio import audit_business_mutation
from app.api.v1.autenticacion import router as auth_router
from app.api.v1.usuarios import router as users_router
from app.api.v1.sucursales import router as branches_router
from app.api.v1.atributos import router as attributes_router
from app.api.v1.temporadas import router as seasons_router
from app.api.v1.promociones import router as promotions_router
from app.api.v1.proveedores import router as suppliers_router
from app.api.v1.productos import router as products_router
from app.api.v1.stocks import router as stocks_router
from app.api.v1.inventario import router as inventory_router
from app.api.v1.carrito import router as cart_router
from app.api.v1.reservas import router as reservations_router
from app.api.v1.catalogo import router as catalog_router
from app.api.v1.reportes import router as reports_router
from app.api.v1.recomendaciones import router as recommendations_router
from app.api.v1.bitacoras import router as activity_logs_router
from app.api.v1.pagos import router as payments_router
from app.api.v1.notificaciones import router as notifications_router
from app.api.v1.vestidor_virtual import router as virtual_fitting_router

api_v1_router = APIRouter(prefix="/v1")

api_v1_router.include_router(auth_router)
api_v1_router.include_router(users_router)
api_v1_router.include_router(branches_router, dependencies=[Depends(audit_business_mutation)])
api_v1_router.include_router(attributes_router, dependencies=[Depends(audit_business_mutation)])
api_v1_router.include_router(seasons_router, dependencies=[Depends(audit_business_mutation)])
api_v1_router.include_router(promotions_router, dependencies=[Depends(audit_business_mutation)])
api_v1_router.include_router(suppliers_router, dependencies=[Depends(audit_business_mutation)])
api_v1_router.include_router(products_router)
api_v1_router.include_router(stocks_router, dependencies=[Depends(audit_business_mutation)])
api_v1_router.include_router(inventory_router, dependencies=[Depends(audit_business_mutation)])
api_v1_router.include_router(cart_router)
api_v1_router.include_router(reservations_router)
api_v1_router.include_router(catalog_router)
api_v1_router.include_router(reports_router)
api_v1_router.include_router(recommendations_router)
api_v1_router.include_router(activity_logs_router)
api_v1_router.include_router(payments_router)
api_v1_router.include_router(notifications_router)
api_v1_router.include_router(virtual_fitting_router)



from app.api.v1.sincronizacion import router as sync_router
api_v1_router.include_router(sync_router)

from app.api.v1.saas import router as saas_router
api_v1_router.include_router(saas_router)

from app.api.v1.respaldos import router as backups_router
api_v1_router.include_router(backups_router)
