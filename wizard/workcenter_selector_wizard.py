from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..models.mrp_production_parameters import (
    LINE_REPORT_PARAMETER_FIELD_MAP,
)


class WorkcenterSelectorWizard(models.TransientModel):
    _inherit = "workcenter.selector.wizard"

    line_report_target_grammage = fields.Float(
        string="Gramaje objetivo (g/m²)"
    )
    line_report_pump_rpm = fields.Float(string="RPM bomba")
    line_report_suction = fields.Char(string="Suction")
    line_report_cooling = fields.Char(string="Cooling")
    line_report_range_hood = fields.Char(string="Range Hood")
    line_report_belt_speed = fields.Float(
        string="Velocidad de banda (m/min)"
    )
    line_report_winder_speed = fields.Float(
        string="Velocidad Winder (m/min)"
    )
    line_report_k_constant = fields.Float(
        string="Constante K (Winder / Banda)",
        compute="_compute_line_report_k_constant",
        digits=(16, 9),
    )
    line_report_spinning_box = fields.Float(string="Spinning Box")
    line_report_temperatures = fields.Char(string="Temperaturas")
    line_report_upper_calender = fields.Float(
        string="Calandra superior (°C)"
    )
    line_report_lower_calender = fields.Float(
        string="Calandra inferior (°C)"
    )
    line_report_calender_pressure = fields.Char(
        string="Presión de calandra"
    )
    line_report_additive = fields.Char(string="Aditivo")
    line_report_additive_code = fields.Char(string="Código de aditivo")
    line_report_additive_percentage = fields.Float(
        string="Porcentaje de aditivo (%)"
    )

    @api.depends("line_report_winder_speed", "line_report_belt_speed")
    def _compute_line_report_k_constant(self):
        for wizard in self:
            winder_speed = max(wizard.line_report_winder_speed, 0.0)
            belt_speed = max(wizard.line_report_belt_speed, 0.0)
            wizard.line_report_k_constant = (
                winder_speed / belt_speed if belt_speed > 0 else 0.0
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

        if "workcenter_id" in fields_list:
            values["workcenter_id"] = production.workcenter_id.id

        for parameter_field in LINE_REPORT_PARAMETER_FIELD_MAP:
            if parameter_field in fields_list:
                values[parameter_field] = getattr(production, parameter_field)

        if (
            "line_report_target_grammage" in fields_list
            and not values.get("line_report_target_grammage")
            and not production.line_report_parameters_registered
        ):
            values[
                "line_report_target_grammage"
            ] = production._line_report_default_target_grammage()
        return values

    @api.onchange("line_report_additive")
    def _onchange_line_report_additive_code(self):
        for wizard in self:
            wizard.line_report_additive_code = (
                "GEN00126"
                if (wizard.line_report_additive or "").strip().lower() == "uv"
                else ""
            )

    def action_guardar_workcenter_con_turno(self):
        self.ensure_one()
        selected_workcenter = self.production_id.workcenter_id
        if not selected_workcenter:
            raise UserError(
                _(
                    "La orden no tiene una línea seleccionada. Cierre esta ventana, "
                    "utilice 'Seleccionar Línea' y vuelva a iniciar el turno."
                )
            )
        if self.workcenter_id != selected_workcenter:
            raise UserError(
                _(
                    "El centro de trabajo del turno debe coincidir con la línea "
                    "seleccionada en la orden de fabricación."
                )
            )
        parameter_values = {
            production_field: getattr(self, production_field)
            for production_field in LINE_REPORT_PARAMETER_FIELD_MAP
        }
        parameter_values["line_report_parameters_registered"] = True
        self.production_id.write(parameter_values)
        super().action_guardar_workcenter_con_turno()
        return {"type": "ir.actions.client", "tag": "reload"}
