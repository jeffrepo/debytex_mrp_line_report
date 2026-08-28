from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..models.mrp_production_parameters import (
    LINE_REPORT_PARAMETER_FIELD_MAP,
)


class WorkcenterSelectorWizard(models.TransientModel):
    _inherit = "workcenter.selector.wizard"

    workcenter_id = fields.Many2one(required=False)
    workcenter_ids = fields.Many2many(
        "mrp.workcenter",
        string="Centros de Trabajo",
        domain=[("active", "=", True)],
        help="Seleccione una o varias líneas para esta orden de fabricación.",
    )
    line_parameter_ids = fields.One2many(
        "workcenter.selector.parameter.line",
        "wizard_id",
        string="Parámetros por centro de trabajo",
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        production_id = values.get("production_id") or self.env.context.get(
            "default_production_id"
        )
        production = self.env["mrp.production"].browse(production_id).exists()
        if not production:
            return values

        workcenters = production.line_report_workcenter_ids
        if not workcenters and production.workcenter_id:
            workcenters = production.workcenter_id

        if "workcenter_id" in fields_list:
            values["workcenter_id"] = (production.workcenter_id or workcenters[:1]).id
        if "workcenter_ids" in fields_list:
            values["workcenter_ids"] = [(6, 0, workcenters.ids)]
        if "line_parameter_ids" in fields_list:
            values["line_parameter_ids"] = [
                (0, 0, self._line_report_parameter_defaults(production, workcenter))
                for workcenter in workcenters
            ]
        return values

    @api.model
    def _line_report_parameter_defaults(self, production, workcenter):
        history = self.env["debytex.mrp.shift.history"].search(
            [
                ("production_id", "=", production.id),
                ("workcenter_id", "=", workcenter.id),
            ],
            order="started_at desc, id desc",
            limit=1,
        )
        result = {"workcenter_id": workcenter.id}
        for production_field, history_field in LINE_REPORT_PARAMETER_FIELD_MAP.items():
            result[production_field] = (
                getattr(history, history_field)
                if history
                else getattr(production, production_field)
            )
        if (
            not result["line_report_target_grammage"]
            and not production.line_report_parameters_registered
        ):
            result[
                "line_report_target_grammage"
            ] = production._line_report_default_target_grammage()
        return result

    @api.model
    def _line_report_create_shift_wizard(self, production):
        """Persist the wizard lines so their full forms can open immediately."""
        production.ensure_one()
        workcenters = production.line_report_workcenter_ids
        if not workcenters and production.workcenter_id:
            workcenters = production.workcenter_id
        primary = production.workcenter_id or workcenters[:1]
        return self.create(
            {
                "production_id": production.id,
                "workcenter_id": primary.id,
                "workcenter_ids": [(6, 0, workcenters.ids)],
                "line_parameter_ids": [
                    (
                        0,
                        0,
                        self._line_report_parameter_defaults(
                            production, workcenter
                        ),
                    )
                    for workcenter in workcenters
                ],
            }
        )

    def _line_report_selected_workcenters(self):
        self.ensure_one()
        return self.workcenter_ids or self.production_id.line_report_workcenter_ids

    def _line_report_save_workcenters(self):
        self.ensure_one()
        if not self.production_id:
            raise UserError(_("No hay una orden de producción vinculada."))
        workcenters = self._line_report_selected_workcenters()
        if not workcenters:
            raise UserError(_("Debe seleccionar al menos un centro de trabajo."))

        primary = (
            self.production_id.workcenter_id
            if self.production_id.workcenter_id in workcenters
            else workcenters[:1]
        )
        self.production_id.write(
            {
                "line_report_workcenter_ids": [(6, 0, workcenters.ids)],
                "workcenter_id": primary.id,
            }
        )
        self.workcenter_id = primary
        return workcenters

    def action_guardar_workcenter(self):
        self.ensure_one()
        workcenters = self._line_report_save_workcenters()
        active_workorders = self.production_id.workorder_ids.filtered(
            lambda workorder: workorder.state not in ("done", "cancel")
        )
        if active_workorders:
            active_workorders.sorted(key=lambda workorder: workorder.id)[-1].write(
                {"workcenter_id": self.production_id.workcenter_id.id}
            )
        names = ", ".join(workcenters.mapped("display_name"))
        self.production_id.message_post(
            body=_("Líneas de producción asignadas: %s") % names,
            message_type="notification",
        )
        return {"type": "ir.actions.act_window_close"}

    def action_guardar_workcenter_con_turno(self):
        self.ensure_one()
        workcenters = self._line_report_save_workcenters()
        parameter_workcenters = self.line_parameter_ids.mapped("workcenter_id")
        if len(parameter_workcenters) != len(self.line_parameter_ids):
            raise UserError(
                _("No puede capturar dos bloques de parámetros para la misma línea.")
            )
        if set(parameter_workcenters.ids) != set(workcenters.ids):
            raise UserError(
                _(
                    "Debe completar un bloque de parámetros para cada centro de "
                    "trabajo seleccionado."
                )
            )

        primary_line = self.line_parameter_ids.filtered(
            lambda line: line.workcenter_id == self.production_id.workcenter_id
        )[:1]
        self.production_id.write(
            {
                **primary_line._line_report_production_values(),
                "line_report_parameters_registered": True,
            }
        )
        parameter_values = {
            line.workcenter_id.id: line._line_report_history_values()
            for line in self.line_parameter_ids
        }
        self.production_id._line_report_start_workcenter_shifts(parameter_values)
        return {"type": "ir.actions.client", "tag": "reload"}


class WorkcenterSelectorParameterLine(models.TransientModel):
    _name = "workcenter.selector.parameter.line"
    _description = "Parámetros de inicio por centro de trabajo"
    _order = "workcenter_id, id"

    wizard_id = fields.Many2one(
        "workcenter.selector.wizard",
        required=True,
        ondelete="cascade",
    )
    workcenter_id = fields.Many2one(
        "mrp.workcenter",
        string="Centro de Trabajo",
        required=True,
        readonly=True,
    )
    line_report_target_grammage = fields.Float(string="Gramaje objetivo (g/m²)")
    line_report_pump_rpm = fields.Float(string="RPM bomba")
    line_report_suction = fields.Char(string="Suction")
    line_report_cooling = fields.Char(string="Cooling")
    line_report_range_hood = fields.Char(string="Range Hood")
    line_report_belt_speed = fields.Float(string="Velocidad de banda (m/min)")
    line_report_winder_speed = fields.Float(string="Velocidad Winder (m/min)")
    line_report_k_constant = fields.Float(
        string="Constante K (Winder / Banda)",
        compute="_compute_line_report_k_constant",
        digits=(16, 9),
    )
    line_report_spinning_box = fields.Float(string="Spinning Box")
    line_report_temperatures = fields.Char(string="Temperaturas")
    line_report_upper_calender = fields.Float(string="Calandra superior (°C)")
    line_report_lower_calender = fields.Float(string="Calandra inferior (°C)")
    line_report_calender_pressure = fields.Char(string="Presión de calandra")
    line_report_additive = fields.Char(string="Aditivo")
    line_report_additive_code = fields.Char(string="Código de aditivo")
    line_report_additive_percentage = fields.Float(
        string="Porcentaje de aditivo (%)"
    )

    @api.depends("line_report_winder_speed", "line_report_belt_speed")
    def _compute_line_report_k_constant(self):
        for line in self:
            winder_speed = max(line.line_report_winder_speed, 0.0)
            belt_speed = max(line.line_report_belt_speed, 0.0)
            line.line_report_k_constant = (
                winder_speed / belt_speed if belt_speed > 0 else 0.0
            )

    @api.onchange("line_report_additive")
    def _onchange_line_report_additive_code(self):
        for line in self:
            line.line_report_additive_code = (
                "GEN00126"
                if (line.line_report_additive or "").strip().lower() == "uv"
                else ""
            )

    def _line_report_production_values(self):
        self.ensure_one()
        return {
            production_field: getattr(self, production_field)
            for production_field in LINE_REPORT_PARAMETER_FIELD_MAP
        }

    def _line_report_history_values(self):
        self.ensure_one()
        return {
            history_field: getattr(self, production_field)
            for production_field, history_field in LINE_REPORT_PARAMETER_FIELD_MAP.items()
        }
