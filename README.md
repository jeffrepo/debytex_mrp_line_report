# Debytex - Reporte de Producción por Línea

Módulo para Odoo 18 que genera el reporte operativo y el resumen general de
las líneas de producción de Debytex/ECOWOOL.

## Alcance inicial

- Selección de los centros de trabajo que representan las líneas.
- Precarga de la orden de fabricación activa de cada línea.
- Captura persistente de parámetros de operación, calidad, mermas,
  incidencias, ajustes, paros y entrega de turno.
- Reporte técnico por línea, reporte general o ambos en PDF QWeb.
- Reutilización de órdenes, turnos, rollos, responsables y centros de trabajo
  proporcionados por `custom_novici`.
- Importación automática de paros registrados en
  `mrp.workcenter.productivity` para el turno activo.

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
