from odoo import api, fields, models, _

from ..services.shift_timing import (
    effective_elapsed_seconds,
    format_duration,
    seconds_between,
)
from .mrp_production_parameters import LINE_REPORT_PARAMETER_FIELD_MAP


SHIFT_STATES = [
    ("running", "En ejecución"),
    ("paused", "En pausa"),
    ("closed", "Cerrado"),
]


class MrpShiftHistory(models.Model):
    _name = "debytex.mrp.shift.history"
    _description = "Historial de turnos de producción Debytex"
    _order = "started_at desc, id desc"

    name = fields.Char(string="Turno", required=True, default="/", readonly=True)
    turn_number = fields.Integer(string="Número", readonly=True)
    production_id = fields.Many2one(
        "mrp.production",
        string="Orden de fabricación",
        required=True,
        index=True,
        ondelete="cascade",
        readonly=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="production_id.company_id",
        store=True,
        index=True,
        readonly=True,
    )
    workcenter_id = fields.Many2one(
        "mrp.workcenter",
        string="Centro de trabajo",
        required=True,
        index=True,
        ondelete="restrict",
        readonly=True,
    )
    workorder_id = fields.Many2one(
        "mrp.workorder",
        string="Orden de trabajo",
        ondelete="set null",
        readonly=True,
    )
    turn_closure_id = fields.Many2one(
        "produccion.turno.cierre",
        string="Cierre de turno",
        ondelete="set null",
        readonly=True,
    )
    state = fields.Selection(
        SHIFT_STATES,
        string="Estado",
        required=True,
        default="running",
        index=True,
        readonly=True,
    )
    started_at = fields.Datetime(
        string="Inicio", required=True, index=True, readonly=True
    )
    running_since = fields.Datetime(string="Contando desde", readonly=True)
    paused_since = fields.Datetime(string="Pausado desde", readonly=True)
    closed_at = fields.Datetime(string="Cierre", readonly=True)
    started_by_id = fields.Many2one(
        "res.users", string="Iniciado por", readonly=True
    )
    closed_by_id = fields.Many2one(
        "res.users", string="Cerrado por", readonly=True
    )
    accumulated_active_seconds = fields.Float(
        string="Segundos efectivos acumulados", readonly=True
    )
    accumulated_pause_seconds = fields.Float(
        string="Segundos en pausa acumulados", readonly=True
    )
    elapsed_seconds = fields.Float(
        string="Tiempo efectivo (segundos)",
        compute="_compute_durations",
        readonly=True,
    )
    elapsed_display = fields.Char(
        string="Tiempo efectivo",
        compute="_compute_durations",
        readonly=True,
    )
    pause_display = fields.Char(
        string="Tiempo pausado",
        compute="_compute_durations",
        readonly=True,
    )
    pause_ids = fields.One2many(
        "debytex.mrp.shift.pause",
        "shift_id",
        string="Pausas",
        readonly=True,
    )

    target_grammage = fields.Float(string="Gramaje objetivo (g/m²)", readonly=True)
    pump_rpm = fields.Float(string="RPM bomba", readonly=True)
    suction = fields.Char(string="Suction", readonly=True)
    cooling = fields.Char(string="Cooling", readonly=True)
    range_hood = fields.Char(string="Range Hood", readonly=True)
    belt_speed = fields.Float(string="Velocidad de banda (m/min)", readonly=True)
    winder_speed = fields.Float(string="Velocidad Winder (m/min)", readonly=True)
    k_constant = fields.Float(
        string="Constante K (Winder / Banda)",
        compute="_compute_k_constant",
        store=True,
        digits=(16, 9),
        readonly=True,
    )
    spinning_box = fields.Float(string="Spinning Box", readonly=True)
    temperatures = fields.Char(string="Temperaturas", readonly=True)
    upper_calender = fields.Float(string="Calandra superior (°C)", readonly=True)
    lower_calender = fields.Float(string="Calandra inferior (°C)", readonly=True)
    calender_pressure = fields.Char(string="Presión de calandra", readonly=True)
    additive = fields.Char(string="Aditivo", readonly=True)
    additive_code = fields.Char(string="Código de aditivo", readonly=True)
    additive_percentage = fields.Float(
        string="Porcentaje de aditivo (%)", readonly=True
    )

    @api.depends("winder_speed", "belt_speed")
    def _compute_k_constant(self):
        for shift in self:
            shift.k_constant = (
                max(shift.winder_speed, 0.0) / shift.belt_speed
                if shift.belt_speed > 0
                else 0.0
            )

    @api.depends(
        "state",
        "running_since",
        "paused_since",
        "accumulated_active_seconds",
        "accumulated_pause_seconds",
    )
    def _compute_durations(self):
        sampled_at = fields.Datetime.now()
        for shift in self:
            elapsed = shift._elapsed_seconds_at(sampled_at)
            paused = max(shift.accumulated_pause_seconds, 0.0)
            if shift.state == "paused":
                paused += seconds_between(
                    fields.Datetime.to_datetime(shift.paused_since), sampled_at
                )
            shift.elapsed_seconds = elapsed
            shift.elapsed_display = format_duration(elapsed)
            shift.pause_display = format_duration(paused)

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            production = self.env["mrp.production"].browse(
                values.get("production_id")
            )
            if not values.get("turn_number") and production:
                last_shift = self.search(
                    [("production_id", "=", production.id)],
                    order="turn_number desc, id desc",
                    limit=1,
                )
                values["turn_number"] = (last_shift.turn_number or 0) + 1
            if values.get("name", "/") == "/":
                values["name"] = _("%s - Turno %s") % (
                    production.name or _("Orden"),
                    values.get("turn_number", 1),
                )
        return super().create(vals_list)

    def _elapsed_seconds_at(self, sampled_at):
        self.ensure_one()
        return effective_elapsed_seconds(
            self.accumulated_active_seconds,
            fields.Datetime.to_datetime(self.running_since),
            fields.Datetime.to_datetime(sampled_at),
            self.state == "running",
        )

    def _pause(self, paused_at, reason_code="", reason_label="", description=""):
        self.ensure_one()
        shift = self.sudo()
        if shift.state != "running":
            return
        paused_at = fields.Datetime.to_datetime(paused_at)
        accumulated = shift._elapsed_seconds_at(paused_at)
        shift.write(
            {
                "state": "paused",
                "accumulated_active_seconds": accumulated,
                "running_since": False,
                "paused_since": paused_at,
            }
        )
        self.env["debytex.mrp.shift.pause"].sudo().create(
            {
                "shift_id": shift.id,
                "started_at": paused_at,
                "reason_code": reason_code or "",
                "reason_label": reason_label or _("Pausa"),
                "description": description or "",
                "paused_by_id": self.env.user.id,
            }
        )

    def _resume(self, resumed_at):
        self.ensure_one()
        shift = self.sudo()
        if shift.state != "paused":
            return
        resumed_at = fields.Datetime.to_datetime(resumed_at)
        paused_seconds = seconds_between(
            fields.Datetime.to_datetime(shift.paused_since), resumed_at
        )
        shift._close_open_pause(resumed_at)
        shift.write(
            {
                "state": "running",
                "running_since": resumed_at,
                "paused_since": False,
                "accumulated_pause_seconds": (
                    shift.accumulated_pause_seconds + paused_seconds
                ),
            }
        )

    def _close(self, closed_at, turn_closure=False):
        self.ensure_one()
        shift = self.sudo()
        if shift.state == "closed":
            return
        closed_at = fields.Datetime.to_datetime(closed_at)
        values = {
            "state": "closed",
            "closed_at": closed_at,
            "closed_by_id": self.env.user.id,
            "running_since": False,
            "paused_since": False,
        }
        if shift.state == "running":
            values["accumulated_active_seconds"] = shift._elapsed_seconds_at(
                closed_at
            )
        elif shift.state == "paused":
            values["accumulated_pause_seconds"] = (
                shift.accumulated_pause_seconds
                + seconds_between(
                    fields.Datetime.to_datetime(shift.paused_since), closed_at
                )
            )
            shift._close_open_pause(closed_at)
        if turn_closure:
            values["turn_closure_id"] = turn_closure.id
        shift.write(values)

    def _close_open_pause(self, ended_at):
        self.ensure_one()
        pause = self.pause_ids.filtered(lambda item: not item.ended_at).sorted(
            key=lambda item: item.id, reverse=True
        )[:1]
        if pause:
            pause.sudo().write(
                {
                    "ended_at": ended_at,
                    "resumed_by_id": self.env.user.id,
                    "duration_seconds": seconds_between(
                        fields.Datetime.to_datetime(pause.started_at), ended_at
                    ),
                }
            )


class MrpShiftPause(models.Model):
    _name = "debytex.mrp.shift.pause"
    _description = "Pausa de turno de producción Debytex"
    _order = "started_at desc, id desc"

    shift_id = fields.Many2one(
        "debytex.mrp.shift.history",
        string="Turno",
        required=True,
        index=True,
        ondelete="cascade",
        readonly=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="shift_id.company_id",
        store=True,
        index=True,
        readonly=True,
    )
    started_at = fields.Datetime(string="Inicio", required=True, readonly=True)
    ended_at = fields.Datetime(string="Fin", readonly=True)
    duration_seconds = fields.Float(string="Duración (segundos)", readonly=True)
    duration_display = fields.Char(
        string="Duración", compute="_compute_duration_display", readonly=True
    )
    reason_code = fields.Char(string="Código del motivo", readonly=True)
    reason_label = fields.Char(string="Motivo", readonly=True)
    description = fields.Text(string="Descripción", readonly=True)
    paused_by_id = fields.Many2one(
        "res.users", string="Pausado por", readonly=True
    )
    resumed_by_id = fields.Many2one(
        "res.users", string="Reanudado por", readonly=True
    )

    @api.depends("duration_seconds", "started_at", "ended_at")
    def _compute_duration_display(self):
        sampled_at = fields.Datetime.now()
        for pause in self:
            duration = pause.duration_seconds
            if not pause.ended_at:
                duration = seconds_between(
                    fields.Datetime.to_datetime(pause.started_at), sampled_at
                )
            pause.duration_display = format_duration(duration)


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    line_report_shift_history_ids = fields.One2many(
        "debytex.mrp.shift.history",
        "production_id",
        string="Historial de turnos",
        readonly=True,
    )
    line_report_active_shift_id = fields.Many2one(
        "debytex.mrp.shift.history",
        string="Turno activo",
        copy=False,
        ondelete="set null",
        readonly=True,
    )
    line_report_active_shift_state = fields.Selection(
        related="line_report_active_shift_id.state",
        string="Estado del turno",
        readonly=True,
    )
    line_report_active_shift_started_at = fields.Datetime(
        related="line_report_active_shift_id.started_at",
        string="Inicio del turno",
        readonly=True,
    )
    line_report_active_shift_elapsed_seconds = fields.Float(
        related="line_report_active_shift_id.elapsed_seconds",
        string="Tiempo efectivo",
        readonly=True,
    )

    def action_iniciar_turno(self):
        result = super().action_iniciar_turno()
        self.ensure_one()
        self._line_report_start_shift_history()
        return result

    def action_cerrar_turno(self):
        self.ensure_one()
        shift = self._line_report_get_active_shift(create_if_missing=True)
        result = super().action_cerrar_turno()
        if shift:
            closure = self.env["produccion.turno.cierre"].sudo().search(
                [
                    ("production_id", "=", self.id),
                    ("fecha_inicio", "=", shift.started_at),
                ],
                order="fecha_cierre desc, id desc",
                limit=1,
            )
            shift._close(fields.Datetime.now(), closure)
            self.sudo().line_report_active_shift_id = False
        return result

    def action_reanudar_workorder_activa(self):
        super().action_reanudar_workorder_activa()
        return {"type": "ir.actions.client", "tag": "reload"}

    def _line_report_start_shift_history(self):
        self.ensure_one()
        started_at = self.fecha_inicio_turno or fields.Datetime.now()
        existing = self._line_report_get_active_shift()
        if existing:
            return existing
        stale_shifts = self.env["debytex.mrp.shift.history"].sudo().search(
            [
                ("production_id", "=", self.id),
                ("state", "in", ("running", "paused")),
            ]
        )
        for stale_shift in stale_shifts:
            stale_shift._close(started_at)
        workorder = self.workorder_ids.filtered(
            lambda item: item.state not in ("done", "cancel")
        ).sorted(key=lambda item: item.id, reverse=True)[:1]
        values = {
            "production_id": self.id,
            "workcenter_id": self.workcenter_id.id,
            "workorder_id": workorder.id if workorder else False,
            "started_at": started_at,
            "running_since": started_at,
            "started_by_id": self.env.user.id,
            "state": "running",
        }
        values.update(
            {
                history_field: getattr(self, production_field)
                for production_field, history_field in (
                    LINE_REPORT_PARAMETER_FIELD_MAP.items()
                )
            }
        )
        shift = self.env["debytex.mrp.shift.history"].sudo().create(values)
        self.sudo().line_report_active_shift_id = shift
        if self.en_pausa:
            active_productivity = self.env[
                "mrp.workcenter.productivity"
            ].sudo().search(
                [
                    ("workorder_id", "=", workorder.id),
                    ("date_end", "=", False),
                ],
                order="date_start desc, id desc",
                limit=1,
            )
            pause_reason = (
                active_productivity.description
                or getattr(workorder, "descripcion_pausa_actual", "")
                or _("Pausa activa al actualizar el módulo")
            )
            shift._pause(
                active_productivity.date_start or fields.Datetime.now(),
                reason_code=getattr(workorder, "motivo_pausa_actual", "") or "",
                reason_label=pause_reason,
            )
        return shift

    def _line_report_get_active_shift(self, create_if_missing=False):
        self.ensure_one()
        expected_start = fields.Datetime.to_datetime(self.fecha_inicio_turno)
        shift = self.line_report_active_shift_id.sudo()
        if (
            shift
            and shift.state != "closed"
            and (
                not expected_start
                or fields.Datetime.to_datetime(shift.started_at) == expected_start
            )
        ):
            return shift
        domain = [
            ("production_id", "=", self.id),
            ("state", "in", ("running", "paused")),
        ]
        if expected_start:
            domain.append(("started_at", "=", expected_start))
        shift = self.env["debytex.mrp.shift.history"].sudo().search(
            domain,
            order="started_at desc, id desc",
            limit=1,
        )
        if shift:
            self.sudo().line_report_active_shift_id = shift
            return shift
        if create_if_missing and self.fecha_inicio_turno:
            return self._line_report_start_shift_history()
        return shift

    def _line_report_pause_shift(
        self, paused_at, reason_code="", reason_label="", description=""
    ):
        self.ensure_one()
        shift = self._line_report_get_active_shift(create_if_missing=True)
        if shift:
            shift._pause(paused_at, reason_code, reason_label, description)

    def _line_report_resume_shift(self, resumed_at):
        self.ensure_one()
        shift = self._line_report_get_active_shift(create_if_missing=True)
        if shift:
            shift._resume(resumed_at)

    def get_line_report_shift_timer(self):
        self.ensure_one()
        shift = self._line_report_get_active_shift(
            create_if_missing=bool(self.fecha_inicio_turno)
        )
        if not shift:
            shift = self.env["debytex.mrp.shift.history"].sudo().search(
                [("production_id", "=", self.id)],
                order="started_at desc, id desc",
                limit=1,
            )
        if not shift:
            return {"state": "closed", "seconds": 0, "shift_id": False}
        return {
            "state": shift.state,
            "seconds": shift._elapsed_seconds_at(fields.Datetime.now()),
            "shift_id": shift.id,
        }


class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    def action_reanudar_turno(self):
        result = super().action_reanudar_turno()
        self.ensure_one()
        self.production_id._line_report_resume_shift(fields.Datetime.now())
        return result
