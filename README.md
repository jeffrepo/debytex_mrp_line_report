# Debytex - Reporte de Producción por Línea

Módulo para Odoo 18 que genera el reporte operativo y el resumen general de
las líneas de producción de Debytex/ECOWOOL.

## Alcance inicial

- Selección de los centros de trabajo que representan las líneas.
- Precarga de la orden de fabricación activa de cada línea.
- Captura persistente de parámetros de operación, calidad, mermas,
  incidencias, ajustes, paros y entrega de turno.
- Reporte técnico por línea, reporte general o ambos en PDF QWeb.
- Encabezado institucional compacto en ambos reportes, con título,
  trazabilidad y logotipo de la compañía sin duplicar su dirección fiscal.
- Reutilización de órdenes, turnos, rollos, responsables y centros de trabajo
  proporcionados por `custom_novici`.
- Importación automática de paros registrados en
  `mrp.workcenter.productivity` para el turno activo.
- Extensión del tablero de producción de `custom_novici`: al abrir una orden
  muestra los apartados técnicos completos de la última captura asociada.
  Cuando todavía no existe una captura, presenta los datos actuales
  disponibles e identifica claramente el detalle como información en vivo.
- Cada tarjeta del tablero conserva la agrupación por línea y muestra el
  resumen operativo del reporte para su orden: turno, cliente, producto,
  orden/lote, especificación, color, rollos y tiempo restante.
- En órdenes parciales, solicitado, producido, faltantes y tiempo restante se
  calculan sobre toda la cadena: demanda inicial y producción acumulada.
- El detalle de cada orden en el tablero permite imprimir un PDF individual
  con los mismos apartados mostrados en pantalla.
- El wizard **Iniciar Turno** registra los parámetros de operación del punto
  2 directamente en la orden de fabricación. Los valores permanecen
  editables en la pestaña **Parámetros de operación** y alimentan el tablero,
  los cálculos y las nuevas capturas PDF.
- Antes de iniciar el turno es obligatorio utilizar **Seleccionar Línea**. El
  wizard muestra ese centro de trabajo en solo lectura y no asigna líneas de
  forma automática.
- Cada inicio genera una entrada inmutable en **Historial de turnos**, con el
  centro de trabajo y una copia de todos los parámetros de operación.
- La lista del historial presenta los parámetros operativos principales como
  columnas y permite abrir cada turno para consultar la captura completa.
- El turno mantiene un cronómetro de tiempo efectivo en vivo. Las pausas
  detienen el conteo, conservan motivo y duración, la reanudación continúa
  desde el acumulado y el cierre fija la duración definitiva.

## Regla de cálculo

La primera versión conserva la lógica del prototipo HTML entregado por el
cliente:

```text
rollos faltantes = max(rollos solicitados - número de rollo en curso, 0)
ejes pendientes = ceil(rollos faltantes / rollos por eje)
minutos por eje = minutos manuales, o longitud / velocidad Winder
tiempo restante = ejes pendientes * minutos por eje / 60
K = velocidad Winder / velocidad de banda
```

El modo manual utiliza el valor indicado cuando es mayor que cero. Si no hay
un valor manual válido, conserva el comportamiento del prototipo y utiliza el
cálculo automático cuando existen longitud y velocidad Winder.

La finalización estimada supone producción continua desde la fecha y hora de
corte; no descuenta paros futuros.

## Dependencias

- Odoo 18
- `mrp`
- `mrp_workorder`
- `custom_novici` versión compatible con la base Debytex/ECOWOOL

## Flujo de uso

1. Abrir **Fabricación > Informes > Reporte de producción por línea**.
2. Seleccionar el tipo de reporte, el corte y las líneas.
3. Crear la captura para revisar o generar el PDF directamente.
4. En una captura guardada se pueden completar las secciones operativas y
   volver a generar el PDF cuando sea necesario.

## Validación local de la lógica

Las funciones de cálculo no dependen del ORM y pueden verificarse con:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Licencia: LGPL-3.
