from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..services.calculations import compute_production


REPORT_TYPES = [
    ("technical", "Reporte técnico"),
    ("general", "Reporte general"),
    ("both", "Técnico y general"),
]

SHIFT_SELECTION = [
    ("morning", "Matutino"),
    ("evening", "Vespertino"),
    ("night", "Nocturno"),
]


class DebytexMrpLineReport(models.Model):
    _name = "debytex.mrp.line.report"
    _description = "Reporte de Producción por Línea"
    _order = "cutoff_datetime desc, id desc"

    name = fields.Char(
        string="Referencia",
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _("Nuevo"),
    )
    report_type = fields.Selection(
        selection=REPORT_TYPES,
        string="Tipo de reporte",
        required=True,
        default="both",
    )
    cutoff_datetime = fields.Datetime(
        string="Fecha y hora de corte",
        required=True,
        default=fields.Datetime.now,
    )
    state = fields.Selection(
        selection=[("draft", "Borrador"), ("generated", "Generado")],
        string="Estado",
        required=True,
        default="draft",
        copy=False,
    )
    generated_at = fields.Datetime(string="Última generación", readonly=True)
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
    )
    created_by_id = fields.Many2one(
        "res.users",
        string="Elaboró",
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
    )
    line_ids = fields.One2many(
        "debytex.mrp.line.report.line",
        "report_id",
        string="Líneas de producción",
        copy=True,
    )

    include_general_data = fields.Boolean(
        string="Datos generales", default=True
    )
    include_parameters = fields.Boolean(string="Parámetros", default=True)
    include_additive = fields.Boolean(string="Aditivo", default=False)
    include_production = fields.Boolean(string="Producción", default=True)
    include_quality = fields.Boolean(string="Calidad", default=False)
    include_waste = fields.Boolean(string="Mermas", default=False)
    include_incidents = fields.Boolean(string="Incidencias", default=False)
    include_adjustments = fields.Boolean(string="Ajustes", default=False)
    include_stops = fields.Boolean(string="Paros", default=False)
    include_handover = fields.Boolean(string="Entrega de turno", default=False)
    include_signatures = fields.Boolean(string="Firmas", default=False)

    total_rolls_requested = fields.Float(
        string="Rollos solicitados",
        compute="_compute_totals",
    )
    total_current_rolls = fields.Float(
        string="Rollos en curso",
        compute="_compute_totals",
    )
    total_rolls_missing = fields.Float(
        string="Rollos faltantes",
        compute="_compute_totals",
    )
    active_line_count = fields.Integer(
        string="Líneas con captura",
        compute="_compute_totals",
    )

    @api.depends(
        "line_ids.rolls_requested",
        "line_ids.current_roll",
        "line_ids.rolls_missing",
        "line_ids.production_id",
    )
    def _compute_totals(self):
        for report in self:
            report.total_rolls_requested = sum(report.line_ids.mapped("rolls_requested"))
            report.total_current_rolls = sum(report.line_ids.mapped("current_roll"))
            report.total_rolls_missing = sum(report.line_ids.mapped("rolls_missing"))
            report.active_line_count = len(report.line_ids.filtered("production_id"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "debytex.mrp.line.report"
                ) or _("Nuevo")
        return super().create(vals_list)

    def action_print_report(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Agregue al menos una línea antes de generar el reporte."))
        self.write({"state": "generated", "generated_at": fields.Datetime.now()})
        return self.env.ref(
            "debytex_mrp_line_report.action_report_production_line"
        ).report_action(self)

    def action_set_draft(self):
        self.write({"state": "draft"})
        return True


class DebytexMrpLineReportLine(models.Model):
    _name = "debytex.mrp.line.report.line"
    _description = "Detalle de Reporte por Línea"
    _order = "sequence, id"
    _rec_name = "workcenter_id"

    report_id = fields.Many2one(
        "debytex.mrp.line.report",
        string="Reporte",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    workcenter_id = fields.Many2one(
        "mrp.workcenter",
        string="Línea de producción",
        required=True,
        ondelete="restrict",
    )
    production_id = fields.Many2one(
        "mrp.production",
        string="Orden de fabricación",
        ondelete="set null",
    )
    workorder_id = fields.Many2one(
        "mrp.workorder",
        string="Orden de trabajo",
        ondelete="set null",
    )
    turn_closure_id = fields.Many2one(
        "produccion.turno.cierre",
        string="Cierre de turno",
        ondelete="set null",
    )
    shift = fields.Selection(
        selection=SHIFT_SELECTION,
        string="Turno",
        required=True,
        default="morning",
    )
    shift_label = fields.Char(string="Turno", compute="_compute_shift_label")
    leader_id = fields.Many2one("res.users", string="Líder de turno")
    supervisor_id = fields.Many2one("res.users", string="Supervisor")

    production_name = fields.Char(string="Orden / corrida")
    sale_order_name = fields.Char(string="Orden de venta")
    lot_name = fields.Char(string="Lote")
    product_name = fields.Char(string="Producto")
    client_name = fields.Char(string="Cliente")

    target_grammage = fields.Float(string="Gramaje objetivo (g/m²)")
    target_width = fields.Float(string="Ancho objetivo (cm)")
    pump_rpm = fields.Float(string="RPM bomba")
    suction = fields.Char(string="Suction")
    cooling = fields.Char(string="Cooling")
    range_hood = fields.Char(string="Range Hood")
    belt_speed = fields.Float(string="Velocidad de banda (m/min)")
    winder_speed = fields.Float(string="Velocidad Winder (m/min)")
    spinning_box = fields.Float(string="Spinning Box (°C)")
    upper_calender = fields.Float(string="Calandra superior (°C)")
    lower_calender = fields.Float(string="Calandra inferior (°C)")
    calender_pressure = fields.Char(string="Presión de calandra")
    temperatures = fields.Char(string="Temperaturas")
    k_constant = fields.Float(
        string="Constante K (Winder / Banda)",
        compute="_compute_production_values",
        store=True,
        digits=(16, 9),
    )

    color = fields.Char(string="Color")
    color_code = fields.Char(string="Código de color")
    color_percentage = fields.Float(string="Porcentaje de color (%)")
    additive = fields.Char(string="Aditivo")
    additive_code = fields.Char(string="Código de aditivo")
    additive_percentage = fields.Float(string="Porcentaje de aditivo (%)")

    actual_grammage = fields.Float(string="Gramaje del rollo (g/m²)")
    actual_width = fields.Float(string="Ancho del rollo (cm)")
    roll_length = fields.Float(string="Longitud del rollo (m)")
    rolls_requested = fields.Float(string="Rollos solicitados", digits=(16, 0))
    current_roll = fields.Float(string="No. rollo en curso", digits=(16, 0))
    rolls_per_axis = fields.Integer(string="Rollos por eje")
    time_mode = fields.Selection(
        selection=[
            ("manual", "Usar tiempo manual por rollo"),
            ("auto", "Calcular con metros / Winder"),
        ],
        string="Modo de cálculo de tiempo",
        required=True,
        default="manual",
    )
    manual_minutes_per_roll = fields.Float(string="Tiempo manual por rollo (min)")
    rolls_missing = fields.Float(
        string="Rollos faltantes",
        compute="_compute_production_values",
        store=True,
        digits=(16, 0),
    )
    pending_axes = fields.Integer(
        string="Ejes pendientes",
        compute="_compute_production_values",
        store=True,
    )
    minutes_per_axis = fields.Float(
        string="Minutos por eje",
        compute="_compute_production_values",
        store=True,
        digits=(16, 4),
    )
    remaining_hours = fields.Float(
        string="Tiempo restante (horas)",
        compute="_compute_production_values",
        store=True,
        digits=(16, 6),
    )
    remaining_time_text = fields.Char(
        string="Tiempo restante",
        compute="_compute_production_values",
        store=True,
    )
    estimated_finish = fields.Datetime(
        string="Finalización estimada",
        compute="_compute_production_values",
        store=True,
    )
    report_status = fields.Char(
        string="Estado documental",
        compute="_compute_report_status",
        store=True,
    )

    quality_grammage = fields.Float(string="Gramaje real de calidad")
    resistance_md = fields.Float(string="Resistencia MD")
    resistance_cd = fields.Float(string="Resistencia CD")
    elongation_md = fields.Float(string="Elongación MD")
    elongation_cd = fields.Float(string="Elongación CD")
    quality_observations = fields.Text(string="Observaciones de calidad")

    line_conditions = fields.Text(string="Condiciones de la línea")
    pending_notes = fields.Text(string="Pendientes")
    recommendations = fields.Text(string="Recomendaciones / comentario general")

    waste_ids = fields.One2many(
        "debytex.mrp.line.report.waste", "report_line_id", string="Mermas"
    )
    incident_ids = fields.One2many(
        "debytex.mrp.line.report.incident",
        "report_line_id",
        string="Incidencias",
    )
    adjustment_ids = fields.One2many(
        "debytex.mrp.line.report.adjustment",
        "report_line_id",
        string="Ajustes",
    )
    stop_ids = fields.One2many(
        "debytex.mrp.line.report.stop", "report_line_id", string="Paros"
    )

    @api.depends(
        "rolls_requested",
        "current_roll",
        "rolls_per_axis",
        "roll_length",
        "winder_speed",
        "belt_speed",
        "manual_minutes_per_roll",
        "time_mode",
        "report_id.cutoff_datetime",
    )
    def _compute_production_values(self):
        for line in self:
            result = compute_production(
                rolls_requested=line.rolls_requested,
                current_roll=line.current_roll,
                rolls_per_axis=line.rolls_per_axis,
                roll_length=line.roll_length,
                winder_speed=line.winder_speed,
                belt_speed=line.belt_speed,
                manual_minutes=line.manual_minutes_per_roll,
                time_mode=line.time_mode,
                cutoff_datetime=line.report_id.cutoff_datetime,
            )
            line.rolls_missing = result["rolls_missing"]
            line.pending_axes = result["pending_axes"]
            line.minutes_per_axis = result["minutes_per_axis"]
            line.remaining_hours = result["remaining_hours"]
            line.remaining_time_text = result["remaining_time_text"]
            line.estimated_finish = result["estimated_finish"]
            line.k_constant = result["k_constant"]

    @api.depends("rolls_requested", "current_roll", "rolls_missing")
    def _compute_report_status(self):
        for line in self:
            if line.rolls_requested > 0 and line.rolls_missing <= 0:
                line.report_status = "Final / orden terminada"
            elif line.current_roll > 0:
                line.report_status = "Seguimiento parcial"
            else:
                line.report_status = "Captura / registro inicial"

    @api.depends("shift")
    def _compute_shift_label(self):
        labels = dict(SHIFT_SELECTION)
        for line in self:
            line.shift_label = labels.get(line.shift, "")

    @api.onchange("color")
    def _onchange_color_code(self):
        codes = {"blanco": "GEN00124", "negro": "GEN00087"}
        for line in self:
            line.color_code = codes.get((line.color or "").strip().lower(), "")

    @api.onchange("additive")
    def _onchange_additive_code(self):
        for line in self:
            line.additive_code = (
                "GEN00126" if (line.additive or "").strip().lower() == "uv" else ""
            )


class DebytexMrpLineReportWaste(models.Model):
    _name = "debytex.mrp.line.report.waste"
    _description = "Merma de Reporte por Línea"
    _order = "sequence, id"
    _rec_name = "waste_type"

    sequence = fields.Integer(default=10)
    report_line_id = fields.Many2one(
        "debytex.mrp.line.report.line", required=True, ondelete="cascade"
    )
    waste_type = fields.Char(string="Tipo", required=True)
    quantity = fields.Char(string="Cantidad")
    cause = fields.Char(string="Causa")


class DebytexMrpLineReportIncident(models.Model):
    _name = "debytex.mrp.line.report.incident"
    _description = "Incidencia de Reporte por Línea"
    _order = "sequence, id"
    _rec_name = "description"

    sequence = fields.Integer(default=10)
    report_line_id = fields.Many2one(
        "debytex.mrp.line.report.line", required=True, ondelete="cascade"
    )
    time_text = fields.Char(string="Hora")
    description = fields.Text(string="Descripción", required=True)
    action_taken = fields.Text(string="Acción tomada")
    result = fields.Text(string="Resultado")


class DebytexMrpLineReportAdjustment(models.Model):
    _name = "debytex.mrp.line.report.adjustment"
    _description = "Ajuste de Reporte por Línea"
    _order = "sequence, id"
    _rec_name = "adjustment"

    sequence = fields.Integer(default=10)
    report_line_id = fields.Many2one(
        "debytex.mrp.line.report.line", required=True, ondelete="cascade"
    )
    time_text = fields.Char(string="Hora")
    adjustment = fields.Char(string="Ajuste", required=True)
    reason = fields.Char(string="Motivo")


class DebytexMrpLineReportStop(models.Model):
    _name = "debytex.mrp.line.report.stop"
    _description = "Paro de Reporte por Línea"
    _order = "start_datetime, id"
    _rec_name = "reason"

    report_line_id = fields.Many2one(
        "debytex.mrp.line.report.line", required=True, ondelete="cascade"
    )
    source_productivity_id = fields.Many2one(
        "mrp.workcenter.productivity",
        string="Registro de productividad",
        ondelete="set null",
    )
    start_datetime = fields.Datetime(string="Inicio")
    end_datetime = fields.Datetime(string="Fin")
    duration_minutes = fields.Float(
        string="Duración (min)", compute="_compute_duration", store=True
    )
    reason = fields.Char(string="Motivo")

    @api.depends("start_datetime", "end_datetime")
    def _compute_duration(self):
        for stop in self:
            if stop.start_datetime and stop.end_datetime:
                delta = stop.end_datetime - stop.start_datetime
                stop.duration_minutes = max(delta.total_seconds() / 60.0, 0.0)
            else:
                stop.duration_minutes = 0.0
