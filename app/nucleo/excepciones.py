from fastapi import HTTPException, status


class AutenticacionException(HTTPException):
    def __init__(self, detail: str = "No se pudieron validar las credenciales", headers: dict = None):
        if headers is None:
            headers = {"WWW-Authenticate": "Bearer"}
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers=headers,
        )


class AccesoDenegadoException(HTTPException):
    def __init__(self, detail: str = "No tienes permisos suficientes"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


class NoEncontradoException(HTTPException):
    def __init__(self, detail: str = "Recurso no encontrado"):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail,
        )


class SolicitudInvalidaException(HTTPException):
    def __init__(self, detail: str = "Solicitud no válida"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )


class ConflictoException(HTTPException):
    def __init__(self, detail: str = "El recurso ya existe"):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        )


def insufficient_stock(db, variant_id, product_name, available, requested):
    message = f"Stock insuficiente para {product_name}. Disponible: {available}, solicitado: {requested}."
    if db.info.get('sync_atomic'):
        raise HTTPException(409, {
            'code': 'STOCK_INSUFFICIENT', 'message': message,
            'variant_id': variant_id, 'product_name': product_name,
            'available': available, 'requested': requested,
        })
    raise SolicitudInvalidaException(message)
