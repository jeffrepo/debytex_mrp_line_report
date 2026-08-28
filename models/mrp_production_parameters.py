import re
import unicodedata

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..services.partial_orders import summarize_partial_orders


LINE_REPORT_PARAMETER_FIELD_MAP = {
    "line_report_target_grammage": "target_grammage",
    "line_report_pump_rpm": "pump_rpm",
    "line_report_suction": "suction",
    "line_report_cooling": "cooling",
    "line_report_range_hood": "range_hood",
    "line_report_belt_speed": "belt_speed",
    "line_report_winder_speed": "winder_speed",
    "line_report_spinning_box": "spinning_box",
    "line_report_temperatures": "temperatures",
    "line_report_upper_calender": "upper_calender",
    "line_report_lower_calender": "lower_calender",
    "line_report_calender_pressure": "calender_pressure",
    "line_report_additive": "additive",
    "line_report_additive_code": "additive_code",
    "line_report_additive_percentage": "additive_percentage",
}


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    line_report_workcenter_ids = fields.Many2many(
        "mrp.workcenter",
        "debytex_mrp_production_workcenter_rel",
        "production_id",
        "workcenter_id",
        string="Líneas de producción",
        copy=False,
        domain=[("active", "=", True)],
        help=(
            "Centros de trabajo seleccionados para ejecutar esta orden en "
            "paralelo. La primera línea se conserva también como línea principal "
            "para compatibilidad con los procesos existentes."
        ),
    )
    line_report_parameters_registered = fields.Boolean(
        string="Parámetros de operación registrados",
        copy=False,
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
        store=True,
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
        for production in self:
            winder_speed = max(production.line_report_winder_speed, 0.0)
            belt_speed = max(production.line_report_belt_speed, 0.0)
            production.line_report_k_constant = (
                winder_speed / belt_speed if belt_speed > 0 else 0.0
            )

    @api.onchange("line_report_additive")
    def _onchange_line_report_additive_code(self):
        for production in self:
            production.line_report_additive_code = (
                "GEN00126"
                if (production.line_report_additive or "").strip().lower()
                == "uv"
                else ""
            )

    def action_open_workcenter_selector_iniciar_turno(self):
        """Open one parameter capture for every explicitly selected line."""
        self.ensure_one()
        workcenters = self.line_report_workcenter_ids or self.workcenter_id
        if not workcenters:
            raise UserError(
                _(
                    "Debe seleccionar al menos una línea antes de iniciar el turno.\n\n"
                    "Utilice el botón 'Seleccionar Línea' y vuelva a intentar."
                )
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Iniciar turno"),
            "res_model": "workcenter.selector.wizard",
            "view_mode": "form",
            "view_id": self.env.ref(
                "custom_novici.view_workcenter_selector_wizard_form_con_turno"
            ).id,
            "target": "new",
            "context": {
                **self.env.context,
                "default_production_id": self.id,
                "default_workcenter_id": (self.workcenter_id or workcenters[:1]).id,
                "default_workcenter_ids": [(6, 0, workcenters.ids)],
            },
        }

    @api.model_create_multi
    def create(self, vals_list):
        parameter_fields = set(LINE_REPORT_PARAMETER_FIELD_MAP)
        for values in vals_list:
            if parameter_fields.intersection(values):
                values["line_report_parameters_registered"] = True
        return super().create(vals_list)

    def write(self, values):
        if set(LINE_REPORT_PARAMETER_FIELD_MAP).intersection(values):
            values = dict(values)
            values["line_report_parameters_registered"] = True
        return super().write(values)

    def _line_report_operation_values(self):
        self.ensure_one()
        return {
            report_field: getattr(self, production_field)
            for production_field, report_field in (
                LINE_REPORT_PARAMETER_FIELD_MAP.items()
            )
        }

    def _line_report_partial_quantities(self):
        """Return requested and produced rolls for the full partial chain."""
        self.ensure_one()
        get_related_orders = getattr(self, "_get_all_related_orders", None)
        related_orders = (
            get_related_orders() if callable(get_related_orders) else self
        )
        related_orders = related_orders.exists() or self
        initial_demand = max(
            related_orders.mapped("initial_demand_qty") or [0.0]
        )
        return summarize_partial_orders(
            initial_demand=initial_demand,
            planned_quantities=related_orders.mapped("product_qty"),
            produced_quantities=related_orders.mapped(
                "total_rollos_fabricados"
            ),
        )

    def _line_report_default_target_grammage(self):
        self.ensure_one()
        product = self.product_id
        direct_value = getattr(product.product_tmpl_id, "gramaje", False)
        if direct_value:
            return self._line_report_to_number(direct_value)

        for attribute_value in product.product_template_attribute_value_ids:
            attribute_name = self._line_report_normalize(
                attribute_value.attribute_id.name
            ).strip().lower()
            if attribute_name in ("gramaje", "peso"):
                return self._line_report_to_number(attribute_value.name)
        return 0.0

    @staticmethod
    def _line_report_normalize(value):
        normalized = unicodedata.normalize("NFKD", value or "")
        return "".join(
            char for char in normalized if not unicodedata.combining(char)
        )

    @staticmethod
    def _line_report_to_number(value):
        match = re.search(r"-?\d+(?:[.,]\d+)?", str(value or ""))
        return float(match.group(0).replace(",", ".")) if match else 0.0
