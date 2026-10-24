# Ubicaciones de Bolivia

`bolivia_locations.json` contiene nombres de municipios y sus capitales agrupados
por los nueve departamentos. Se incluyen los nombres habituales de las capitales
departamentales (por ejemplo, La Paz junto a Nuestra Señora de La Paz).

Fuente: Laboratorio de Tecnologías Sociales, **Unidades territoriales del nivel
municipal de Bolivia — CPV 2024**, 343 registros con códigos INE, municipios y TIOC.
Se utilizaron las columnas `nombre_dep`, `nombre_mun` y `capital` del CSV:
https://lab-tecnosocial.github.io/municipios-bolivia-2024/municipios_bolivia_2024.csv

Repositorio y licencia CC BY 4.0:
https://github.com/lab-tecnosocial/municipios-bolivia-2024

Consulta: 23 de octubre de 2026. Los nombres se almacenan localmente para que los
formularios no dependan de servicios externos. La copia TypeScript se encuentra
en `web/src/app/nucleo/datos/ubicaciones-bolivia.ts`; una prueba verifica su igualdad.

Las empresas nuevas requieren departamento. Las antiguas quedan sin asignar para
evitar deducir una ubicación incorrecta a partir de sus sucursales. El administrador
SaaS lo asigna desde Empresas; esa asignación no cambia las sucursales existentes.
Las altas nuevas y las ubicaciones enviadas al editar se validan contra el
departamento de la empresa. Se conserva `city` como nombre del campo en la API
y la base de datos para mantener compatibilidad; en la interfaz es Ciudad/municipio.

La columna nullable `tenants.department` se agrega de forma idempotente al iniciar
con `AUTO_CREATE_TABLES`, o mediante `alembic upgrade head` en despliegues gestionados.
