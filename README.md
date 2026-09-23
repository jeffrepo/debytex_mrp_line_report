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
  selector permite elegir una o varias líneas y no las asigna de forma
  automática.
- El wizard **Iniciar Turno** muestra todas las líneas seleccionadas y solicita
  un bloque independiente de parámetros de operación por cada una.
- El inicio arranca una orden de trabajo por línea y genera una entrada
  inmutable por cada centro en **Historial de turnos**. Las entradas del mismo
  inicio comparten número de turno y conservan sus propios parámetros.
- La lista del historial presenta los parámetros operativos principales como
  columnas y permite abrir cada turno para consultar la captura completa.
- El turno mantiene un cronómetro de tiempo efectivo en vivo. Las pausas
  detienen el conteo, conservan motivo y duración, la reanudación continúa
  desde el acumulado y el cierre fija la duración definitiva.
- **Fabricación > Planeación > Capacidad por centro** ofrece una propuesta
  preliminar para combinar varias órdenes en un mismo centro según su ancho.
  La pantalla muestra el ancho total, refile, ancho útil, espacio ocupado,
  espacio libre, porcentaje de aprovechamiento y una distribución visual.
- En cada orden propuesta se puede indicar el número de bandas y la cantidad
  exacta —o su porcentaje— que se desea procesar. El ancho se obtiene del
  producto y puede corregirse solamente para la propuesta.
- La propuesta exige seleccionar valores comunes para **Peso**, **Color** y
  **Metros por rollo**. El selector de órdenes muestra únicamente variantes
  confirmadas o en progreso, sin turno activo, que coinciden con los tres
  valores.
- La pantalla todavía no recomienda órdenes ni calcula tiempos.
- Cada propuesta utiliza una secuencia interna `CAP/AÑO/00000`. En sus líneas
  se indica la cantidad exacta que se procesará y se capturan los parámetros
  operativos propios de cada orden.
- **Iniciar turno** valida todas las órdenes. Si la cantidad propuesta es menor
  que la orden original, crea una orden parcial confirmada con el remanente
  para que después pueda asignarse al centro que el usuario decida.
- **Iniciar turno** abre una sola captura de parámetros de operación. Los
  valores ingresados se guardan en todas las órdenes incluidas y en sus
  historiales; después se asigna el centro y se arrancan los cronómetros sin
  consumir materiales.
- Mientras el turno está activo, cada fila permite **Registrar rollo**. El
  botón general **Consumir materiales** muestra una tabla tipo Componentes,
  sin teclado emergente, captura una sola cantidad por material y la prorratea
  entre todas las órdenes activas según los rollos asignados a cada una. Si el
  componente falta en alguna orden, se crea automáticamente antes del consumo.
  Si las órdenes no tienen componentes, la misma ventana permite agregar el
  material manualmente; Odoo crea el movimiento correspondiente en cada orden
  activa antes de registrar el consumo prorrateado.
- Cada fila permite **Imprimir Orden de Fabricación**. Al finalizar el turno se
  deshabilita la operación y se habilitan por orden **Reetiquetar rollo**,
  **Enviar a Almacén**, **Reporte Final de Producción** y **Lista de Rollos
  Excel**. El reetiquetado conserva la validación y el PIN de supervisor de
  `custom_novici`.
- El encabezado ofrece también acciones generales para enviar a almacén todas
  las órdenes pendientes, imprimir todas las órdenes y generar un único reporte
  final o archivo Excel consolidado con los rollos de toda la propuesta.

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
