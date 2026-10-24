# Empresas, planes y suscripciones de VESTA

## Uso en la web

- La cuenta existente **Admin SAS** (`adminsas@gmail.com`) conserva el acceso de
  plataforma. En Administración aparece **Empresas y planes** (`/companies`).
- Crear empresa registra su nombre, identificador, administrador, contraseña
  inicial. Siempre empieza en Básico gratuito y sin vencimiento. El administrador nuevo tiene rol ADMIN dentro de su
  empresa, sin la capacidad `is_saas_admin`.
- La empresa empieza sin sucursales ni productos. Su administrador inicia sesión
  y crea su propia estructura. Los datos existentes permanecen en VESTA.
- **Mi plan** (`/subscription`) muestra estado, vencimiento, uso de sucursales,
  comparación de planes y pagos de suscripción. Solo ADMIN de empresa puede pagar.
- VESTA es la empresa raíz interna: no vence, no compra suscripciones y no está
  sujeta al cupo de sucursales de los clientes. No puede suspenderse desde el panel.

| Plan | Precio | Sucursales activas | Reportes convencionales | Reportes con IA |
|---|---|---|---|---|
| Básico | Gratis, sin vencimiento | 2 | Sí | No |
| Profesional | USD 25 / 30 días | 10 | Sí | Sí |

Productos, inventario, ventas, reservas y las capacidades offline existentes
continúan disponibles en ambos planes. Los puntos de PWA y operación offline web están documentados en
`../web/PWA_Y_OFFLINE.md`.

Los límites de sucursales y la inclusión de IA se configuran desde VESTA.
El Básico es gratuito y no tiene fecha de vencimiento. El Profesional cuesta
siempre USD 25 por 30 días: su precio y duración no se editan desde la web ni API.
El creador de empresas no asigna Profesional ni una vigencia inicial. Cada
administrador de empresa decide y paga desde Mi plan para habilitar sus ventajas.
La plataforma puede suspender/reactivar una empresa; esto no regala ni renueva
el período Profesional. Los pagos y períodos ya confirmados se conservan.

## Cobro mediante PayPal

1. ADMIN de empresa pulsa **Pagar USD 25 con PayPal Sandbox** en Mi plan.
2. El servidor crea la orden por USD 25 fijos y 30 días, y la vincula a una
   empresa y a un registro de pago de suscripción. Las órdenes recientes pendientes
   se reutilizan ante clics repetidos.
3. El pago se abre en otra pestaña. El comprador inicia sesión con su cuenta personal Sandbox (compradora), autoriza
   el pago y vuelve temporalmente a `/subscription` para confirmar la captura.
   Una vez confirmado, se actualiza la pestaña original y la de pago va al inicio de Sandbox. El cobro llega a la cuenta del comercio
   vinculada a las credenciales de PayPal ya configuradas en el backend.
4. El backend captura y valida ID de orden, `custom_id`, estado COMPLETED, ID de
   captura, importe y moneda antes de habilitar Profesional.
5. Una captura aceptada y la extensión de vigencia se guardan en la misma
   transacción. Repetir la verificación devuelve el resultado sin extender otra vez.

Un retorno con `token` o una respuesta fallida no habilita funciones. Desde el
historial se puede volver a verificar una orden pendiente después de un corte de
conexión. Se conserva el período Profesional aún vigente al añadir otra renovación.
No hay cobros recurrentes automáticos, devolución automática ni cancelación de
contratos externos: cada pago compra un período. Los pagos de planes están separados
de las ventas de ropa y no alteran stock.

Se reutilizan `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_BASE_URL` y
`FRONTEND_URL`. El retorno usa el origen real de la petición web cuando pertenece a
`CORS_ORIGINS`; `FRONTEND_URL` es el valor de respaldo para clientes sin Origin. El servidor debe recibir ambas credenciales;
la contraseña secreta de PayPal nunca se entrega a Angular ni Flutter. La moneda
de suscripciones es USD aunque las ventas de ropa estén configuradas en otra moneda.
El entorno actual continúa en localhost y PayPal Sandbox. No se hicieron cobros reales.

Referencia del contrato de captura:
[PayPal Orders API](https://developer.paypal.com/api/orders-v2/save-with-purchase/paypal).

## Empresas y seguridad

- `Tenant` identifica una empresa; `Branch` identifica una de sus sucursales.
- Los recursos comerciales incorporan `tenant_id`. Los nombres, códigos de talla,
  proveedores y SKU pueden repetirse entre empresas, pero mantienen sus reglas de
  unicidad dentro de cada una.
- `tenant_scope.py` aplica criterios a consultas ORM, relaciones y operaciones
  masivas; las escrituras comprueban que las referencias pertenezcan a la misma empresa.
- El servidor obtiene la propiedad del personal desde su cuenta. Un ADMIN de
  empresa no puede convertirse en administrador SaaS ni elegir otra empresa mediante
  un encabezado o un ID en la solicitud.
- Crear/reactivar sucursales comprueba el cupo y bloquea la fila de empresa en
  PostgreSQL para serializar solicitudes concurrentes. La IA empresarial se valida
  también en el backend; ocultarla en la web no es el control de seguridad.
- Una suscripción Profesional vencida permite lectura y renovación, pero impide nuevas
  operaciones comerciales e IA. La suspensión de la empresa bloquea su operación.
  Una suscripción suspendida requiere intervención de VESTA antes de volver a pagar.
- Las acciones administrativas y los cobros de suscripción se registran en bitácora
  sin contraseñas, IP ni credenciales de PayPal.

## Cuenta global del cliente

El cliente mantiene una sola identidad VESTA. En el registro elige una empresa y
una sucursal mediante un acordeón. Desde Mi perfil puede cambiar ambas; la API
comprueba que la sucursal pertenezca a la empresa elegida. Solo se ofrecen empresas
y sucursales activas. Cambiar de tienda requiere conexión.

El catálogo y disponibilidad dependen de la empresa/sucursal actual. Los carritos
se separan por ese contexto. El historial de reservas y los comprobantes propios
se conservan entre empresas; las empresas no reciben el historial de las demás.
Personal administra cuentas de empleados de su empresa, no la cuenta global del cliente.

Los clientes pueden mantener contextos distintos en dos dispositivos. Los clientes
envían `X-Vesta-Tenant` y `X-Vesta-Branch`, que el servidor valida. Estos encabezados
no permiten cambiar la empresa del personal. Las respuestas de perfil reflejan el
contexto válido del dispositivo sin trasladar las operaciones existentes.

Flutter guarda caché y cola bajo `API|empresa|sucursal|usuario`. Procesa las colas
de ese usuario incluso si está mirando otra tienda y envía el contexto original
en cada comando. Los conflictos siguen visibles. Las operaciones anteriores al
cambio se conservan como pertenecientes a VESTA. Los UUID y comprobantes de
sincronización mantienen la prevención de duplicados. Las pantallas y servicios
de sesión se reconstruyen al cambiar de tienda para no mostrar el catálogo anterior.

## Actualización de base de datos

`core/saas_schema.py` actualiza la instalación existente y asigna sus datos a VESTA.
Se ejecuta con `AUTO_CREATE_TABLES=true`; también se entrega la revisión Alembic
`f5b61021f001`, posterior a `e4b61020f001`, y la corrección `f5b61021f002`, para instalaciones existentes que ya
administran migraciones. El historial inicial de Alembic del proyecto no representa
una instalación nueva completa: para instalaciones nuevas usar la inicialización
de tablas del proyecto, no asumir que la revisión base crea todo.

La corrección elimina cualquier vencimiento antiguo de Básico y fija el precio
y duración del catálogo de planes. No altera vencimientos ni recibos Profesionales
ya pagados.

La migración es repetible, conserva registros y cambia la unicidad global a
unicidad por empresa. No existe downgrade automático a una empresa, porque perdería
la separación de los datos nuevos. Antes de actualizar una instalación remota se
debe conservar su respaldo. No se modificó Railway ni Amplify en esta entrega.

En localhost se conserva una copia de la base en `../output/backups/`. Es un
respaldo privado de desarrollo, no un archivo para publicar o subir al repositorio.

## Verificación

- Backend: aislamiento entre dos empresas, acceso por IDs ajenos, nombres
  repetidos entre empresas, límites/reapertura de sucursales, IA por plan,
  vencimiento/suspensión, cliente con historial y carrito separados, contexto de
  dos dispositivos, cola con empresa original y PayPal idempotente con importe validado.
- Web: formulario de empresas, rechazo de datos vacíos/duplicados y ausencia de
  activación o mensajes de pago exitoso cuando la captura es rechazada.
- Flutter: caché por tienda, sincronización de colas antiguas al cambiar de empresa,
  conflictos visibles, persistencia SQLite y servicios de sesión.
- Se probó la lógica de PayPal con respuestas simuladas; el pago de aprobación y
  captura completo con una cuenta Sandbox queda disponible para la prueba manual.
- Las pruebas automatizadas de base de datos usan SQLite. La validación final del
  despliegue PostgreSQL y sus concurrencias reales debe hacerse en ese entorno.

APK local: versión 1.0.4+5, API `http://192.168.100.136:8000/api/v1`. El celular
debe estar en la misma red que el backend. Para Android Studio, la configuración
local predeterminada conserva `10.0.2.2` para el emulador.
