from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.mrp_production_parameters import (
    LINE_REPORT_PARAMETER_FIELD_MAP,
)


class MrpCenterCapacityStartWizard(models.TransientModel):
    _name = "debytex.mrp.center.capacity.start.wizard"
    _description = "Inicio de turnos de una propuesta de capacidad"

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
    line_ids = fields.One2many(
        "debytex.mrp.center.capacity.start.wizard.line",
        "wizard_id",
        string="Parámetros por orden",
    )

    @api.model
    def create_from_plan(self, plan):
        """Persist one editable parameter block for every proposed order."""
        plan.ensure_one()
        return self.create(
            {
                "plan_id": plan.id,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "plan_line_id": line.id,
                            **{
                                field_name: getattr(line, field_name)
                                for field_name in LINE_REPORT_PARAMETER_FIELD_MAP
                            },
                        },
                    )
                    for line in plan.line_ids.sorted(
                        key=lambda item: (item.sequence, item.id)
                    )
                ],
            }
        )

    def action_confirm_and_start(self):
        self.ensure_one()
        plan = self.plan_id
        plan._validate_capacity_start()

        expected_line_ids = set(plan.line_ids.ids)
        captured_line_ids = set(self.line_ids.mapped("plan_line_id").ids)
        if captured_line_ids != expected_line_ids:
            raise UserError(
                _(
                    "Debe completar un bloque de parámetros para cada orden "
                    "incluida en la propuesta."
                )
            )

        for wizard_line in self.line_ids:
            wizard_line.plan_line_id.write(wizard_line._parameter_values())
        return plan._execute_start_shifts()


class MrpCenterCapacityStartWizardLine(models.TransientModel):
    _name = "debytex.mrp.center.capacity.start.wizard.line"
    _description = "Parámetros de una orden al iniciar turnos conjuntos"
    _order = "plan_line_id, id"

    wizard_id = fields.Many2one(
        "debytex.mrp.center.capacity.start.wizard",
        required=True,
        ondelete="cascade",
    )
    plan_line_id = fields.Many2one(
        "debytex.mrp.center.capacity.plan.line",
        string="Línea de propuesta",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    production_id = fields.Many2one(
        related="plan_line_id.production_id",
        string="Orden de fabricación",
        readonly=True,
    )
    product_id = fields.Many2one(
        related="plan_line_id.product_id",
        string="Producto",
        readonly=True,
    )
    quantity_to_process = fields.Float(
        related="plan_line_id.quantity_to_process",
        string="Cantidad a procesar",
        readonly=True,
    )
    product_uom_id = fields.Many2one(
        related="plan_line_id.product_uom_id",
        string="Unidad",
        readonly=True,
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

    _sql_constraints = [
        (
            "plan_line_unique_per_capacity_start_wizard",
            "unique(wizard_id, plan_line_id)",
            "Cada orden sólo puede tener un bloque de parámetros.",
        )
    ]

    @api.depends("line_report_winder_speed", "line_report_belt_speed")
    def _compute_line_report_k_constant(self):
        for line in self:
            line.line_report_k_constant = (
                max(line.line_report_winder_speed, 0.0)
                / line.line_report_belt_speed
                if line.line_report_belt_speed > 0
                else 0.0
            )

    @api.onchange("line_report_additive")
    def _onchange_line_report_additive_code(self):
        for line in self:
            line.line_report_additive_code = (
                "GEN00126"
                if (line.line_report_additive or "").strip().lower() == "uv"
                else ""
            )

    def _parameter_values(self):
        self.ensure_one()
        return {
            field_name: getattr(self, field_name)
            for field_name in LINE_REPORT_PARAMETER_FIELD_MAP
        }
