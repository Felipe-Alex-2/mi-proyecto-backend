from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
import logging

logger = logging.getLogger("api")


FIELD_LABELS_ES = {
    "name": "Nombre",
    "description": "Descripción",
    "base_price": "Precio base",
    "price": "Precio",
    "cost_price": "Precio de costo",
    "category_id": "Categoría",
    "season_id": "Temporada",
    "collection_id": "Colección",
    "brand_id": "Marca",
    "supplier_id": "Proveedor",
    "promotion_id": "Promoción",
    "discount_percent": "Porcentaje de descuento",
    "start_date": "Fecha de inicio",
    "end_date": "Fecha de fin",
    "email": "Correo electrónico",
    "password": "Contraseña",
    "phone": "Teléfono",
    "quantity": "Cantidad",
    "stock": "Stock",
    "branch_id": "Sucursal",
    "size_id": "Talla",
    "color_id": "Color",
    "gender": "Género",
    "sku": "Código SKU",
    "barcode": "Código de barras",
    "full_name": "Nombre completo",
    "address": "Dirección",
    "city": "Ciudad",
    "country": "País",
    "variants": "Variantes de la prenda",
    "initial_stock": "Stock inicial",
}


def _translate_field_name(raw_field: str) -> str:
    parts = [p for p in raw_field.replace("body -> ", "").split(" -> ") if p]
    if not parts:
        return "Campo"
    translated_parts = []
    for part in parts:
        if part.isdigit():
            translated_parts.append(f"item #{int(part) + 1}")
        else:
            translated_parts.append(FIELD_LABELS_ES.get(part, part.replace("_", " ").capitalize()))
    return " > ".join(translated_parts)


def _translate_error_msg(error_type: str, msg: str) -> str:
    cleaned = msg.replace("Value error, ", "").strip()
    if "missing" in error_type or "field required" in cleaned.lower():
        return "Este campo es obligatorio y no puede estar vacío."
    if "string_too_short" in error_type:
        return "El texto ingresado es demasiado corto."
    if "greater_than_equal" in error_type or "greater_than" in error_type:
        return "Debe ser un valor numérico positivo mayor a 0."
    if "less_than_equal" in error_type or "less_than" in error_type:
        return "El valor numérico excede el límite máximo permitido."
    if "decimal" in error_type or "float" in error_type or "int" in error_type:
        return "Debe ingresar un valor numérico válido."
    if "json_invalid" in error_type:
        return "Formato JSON inválido."
    return cleaned


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Formats validation errors into highly explicit, prominent Spanish JSON format."""
    errors = []
    summary_lines = []

    for error in exc.errors():
        field_raw = " -> ".join([str(loc) for loc in error.get("loc", []) if loc != "body"])
        field_label = _translate_field_name(field_raw)
        readable_msg = _translate_error_msg(error.get("type", ""), error.get("msg", ""))

        errors.append({
            "field": field_raw,
            "field_label": field_label,
            "message": readable_msg,
            "type": error.get("type"),
        })
        summary_lines.append(f"• {field_label}: {readable_msg}")

    detail_message = (
        "Datos incompletos o inválidos en la solicitud:\n" + "\n".join(summary_lines)
        if summary_lines
        else "Error de validación en los datos enviados."
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": detail_message,
            "errors": errors,
        },
    )


async def general_exception_handler(request: Request, exc: Exception):
    """Global fallback exception handler."""
    logger.error(f"Unhandled error processing {request.method} {request.url}: {exc}", exc_info=True)

    if isinstance(exc, SQLAlchemyError):
        err_str = str(exc)
        if "duplicate key" in err_str.lower() or "unique constraint" in err_str.lower():
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"detail": "Ya existe un registro con esos datos en la base de datos (clave duplicada)."},
            )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": f"Error en la base de datos: {err_str}"},
        )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": f"Error interno en el servidor: {str(exc)}"},
    )

