from odoo import api, fields, models

from ..models.mrp_production_parameters import (
    LINE_REPORT_PARAMETER_FIELD_MAP,
)


class MrpCenterCapacityStartWizard(models.TransientModel):
    _name = "debytex.mrp.center.capacity.start.wizard"
    _description = "Inicio de turno de una propuesta de capacidad"

    plan_id = fields.Many2one(
        "debytex.mrp.center.capacity.plan",
        string="Propuesta",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    workcenter_id = fields.Many2one(
        related="plan_id.workcenter_id",
        string="Centro de trabajo",
        readonly=True,
    )
    production_count = fields.Integer(
        string="Órdenes asociadas",
        compute="_compute_production_count",
    )
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

    @api.model
    def create_from_plan(self, plan):
        """Create one shared parameter capture for every associated order."""
        plan.ensure_one()
        source_line = plan.line_ids.sorted(
            key=lambda item: (item.sequence, item.id)
        )[:1]
        values = {"plan_id": plan.id}
        if source_line:
            values.update(
                {
                    field_name: getattr(source_line, field_name)
                    for field_name in LINE_REPORT_PARAMETER_FIELD_MAP
                }
            )
        return self.create(values)

    @api.depends("plan_id.line_ids")
    def _compute_production_count(self):
        for wizard in self:
            wizard.production_count = len(wizard.plan_id.line_ids)

    @api.depends("line_report_winder_speed", "line_report_belt_speed")
    def _compute_line_report_k_constant(self):
        for wizard in self:
            wizard.line_report_k_constant = (
                max(wizard.line_report_winder_speed, 0.0)
                / wizard.line_report_belt_speed
                if wizard.line_report_belt_speed > 0
                else 0.0
            )

    @api.onchange("line_report_additive")
    def _onchange_line_report_additive_code(self):
        for wizard in self:
            wizard.line_report_additive_code = (
                "GEN00126"
                if (wizard.line_report_additive or "").strip().lower() == "uv"
                else ""
            )

    def _parameter_values(self):
        self.ensure_one()
        return {
            field_name: getattr(self, field_name)
            for field_name in LINE_REPORT_PARAMETER_FIELD_MAP
        }

    def action_confirm_and_start(self):
        self.ensure_one()
        plan = self.plan_id
        plan._validate_capacity_start()
        plan.line_ids.write(self._parameter_values())
        return plan._execute_start_shifts()
