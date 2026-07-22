import math
import re
import unicodedata

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from ..models.production_line_report import REPORT_TYPES


class DebytexMrpLineReportWizard(models.TransientModel):
    _name = "debytex.mrp.line.report.wizard"
    _description = "Wizard de Reporte de Producción por Línea"

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
    line_ids = fields.One2many(
        "debytex.mrp.line.report.wizard.line",
        "wizard_id",
        string="Líneas incluidas",
    )

    include_general_data = fields.Boolean(string="Datos generales", default=True)
    include_parameters = fields.Boolean(string="Parámetros", default=True)
    include_additive = fields.Boolean(string="Aditivo", default=True)
    include_production = fields.Boolean(string="Producción", default=True)
    include_quality = fields.Boolean(string="Calidad", default=False)
    include_waste = fields.Boolean(string="Mermas", default=False)
    include_incidents = fields.Boolean(string="Incidencias", default=False)
    include_adjustments = fields.Boolean(string="Ajustes", default=False)
    include_stops = fields.Boolean(string="Paros", default=False)
    include_handover = fields.Boolean(string="Entrega de turno", default=False)
    include_signatures = fields.Boolean(string="Firmas", default=False)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if "line_ids" not in fields_list:
            return values

        workcenters = self.env["mrp.workcenter"].search(
            [
                ("active", "=", True),
                "|",
                ("name", "ilike", "Línea"),
                ("name", "ilike", "Linea"),
            ],
            order="name, id",
        )
        values["line_ids"] = [
            (
                0,
                0,
                {
                    "workcenter_id": workcenter.id,
                    "production_id": self._find_active_production(workcenter).id,
                },
            )
            for workcenter in workcenters
        ]
        return values

    @api.model
    def _find_active_production(self, workcenter):
        if not workcenter:
            return self.env["mrp.production"]
        return self.env["mrp.production"].search(
            [
                ("workcenter_id", "=", workcenter.id),
                ("state", "in", ["confirmed", "progress", "to_close"]),
            ],
            order="dashboard_priority desc, date_start asc, id asc",
            limit=1,
        )

    def _create_report(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Seleccione al menos una línea de producción."))

        workcenter_ids = self.line_ids.mapped("workcenter_id").ids
        if len(workcenter_ids) != len(set(workcenter_ids)):
            raise UserError(_("No puede incluir el mismo centro de trabajo dos veces."))

        report = self.env["debytex.mrp.line.report"].create(
            {
                "report_type": self.report_type,
                "cutoff_datetime": self.cutoff_datetime,
                "include_general_data": self.include_general_data,
                "include_parameters": self.include_parameters,
                "include_additive": self.include_additive,
                "include_production": self.include_production,
                "include_quality": self.include_quality,
                "include_waste": self.include_waste,
                "include_incidents": self.include_incidents,
                "include_adjustments": self.include_adjustments,
                "include_stops": self.include_stops,
                "include_handover": self.include_handover,
                "include_signatures": self.include_signatures,
                "line_ids": [
                    (0, 0, self._prepare_report_line(wizard_line))
                    for wizard_line in self.line_ids.sorted(
                        key=lambda line: (line.workcenter_id.name or "", line.id)
                    )
                ],
            }
        )
        return report

    def action_create_report(self):
        report = self._create_report()
        return {
            "type": "ir.actions.act_window",
            "name": _("Reporte de Producción por Línea"),
            "res_model": "debytex.mrp.line.report",
            "res_id": report.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_create_and_print(self):
        report = self._create_report()
        return report.action_print_report()

    def _prepare_report_line(self, wizard_line):
        production = wizard_line.production_id
        workcenter = wizard_line.workcenter_id
        values = {
            "workcenter_id": workcenter.id,
            "shift": self._shift_from_cutoff(),
            "waste_ids": [(0, 0, {"waste_type": "Arranque"})],
        }
        if not production:
            return values

        product = production.product_id
        workorder = production.workorder_ids.filtered(
            lambda wo: wo.state not in ("done", "cancel")
        )[:1] or production.workorder_ids[:1]
        attributes = self._product_attributes(product)
        target_grammage = self._to_number(
            getattr(product.product_tmpl_id, "gramaje", False)
            or attributes.get("gramaje")
            or attributes.get("peso")
        )
        if production.line_report_parameters_registered:
            target_grammage = production.line_report_target_grammage
        target_width = self._to_number(
            getattr(product.product_tmpl_id, "ancho", False)
            or attributes.get("ancho")
        )
        roll_length = self._to_number(
            attributes.get("metros x rollo") or attributes.get("metrosxrollo")
        )
        color = (
            getattr(product.product_tmpl_id, "color", False)
            or attributes.get("color")
            or ""
        )
        active_rolls = production.rollo_ids.filtered("active")
        current_roll = max(active_rolls.mapped("numero_rollo"), default=0)
        useful_width = getattr(workcenter, "x_ancho_util", 0.0) or getattr(
            workcenter, "eje_cm", 0.0
        )
        rolls_per_axis = (
            math.floor(useful_width / target_width)
            if useful_width > 0 and target_width > 0
            else 0
        )
        leader = (
            workorder.responsable_turno_id
            if workorder and workorder.responsable_turno_id
            else workcenter.responsable_id
        )
        sale_order = production.sale_order_id

        values.update(
            {
                "production_id": production.id,
                "workorder_id": workorder.id,
                "leader_id": leader.id,
                "production_name": production.name,
                "sale_order_name": sale_order.name or production.origin or "",
                "lot_name": production.lot_producing_id.name or "",
                "product_name": product.display_name or "",
                "client_name": sale_order.partner_id.name if sale_order else "",
                "target_grammage": target_grammage,
                "target_width": target_width,
                "actual_grammage": target_grammage,
                "actual_width": target_width,
                "roll_length": roll_length,
                "color": color,
                "color_code": self._color_code(color),
                "rolls_requested": production.product_qty,
                "current_roll": current_roll,
                "rolls_per_axis": rolls_per_axis,
                "stop_ids": self._prepare_stop_commands(production, workorder),
            }
        )
        if production.line_report_parameters_registered:
            values.update(production._line_report_operation_values())
        return values

    def _prepare_stop_commands(self, production, workorder):
        if not workorder:
            return []
        domain = [
            ("workorder_id", "=", workorder.id),
            ("date_start", "<=", self.cutoff_datetime),
            ("loss_id.loss_type", "!=", "productive"),
        ]
        if production.fecha_inicio_turno:
            domain.append(("date_start", ">=", production.fecha_inicio_turno))
        records = self.env["mrp.workcenter.productivity"].search(
            domain, order="date_start, id"
        )
        return [
            (
                0,
                0,
                {
                    "source_productivity_id": record.id,
                    "start_datetime": record.date_start,
                    "end_datetime": record.date_end or self.cutoff_datetime,
                    "reason": (
                        record.description or record.loss_id.name or ""
                    ) + (" (en curso al corte)" if not record.date_end else ""),
                },
            )
            for record in records
        ]

    def _shift_from_cutoff(self):
        local_cutoff = fields.Datetime.context_timestamp(
            self, fields.Datetime.to_datetime(self.cutoff_datetime)
        )
        hour = local_cutoff.hour
        if 6 <= hour <= 13:
            return "morning"
        if 14 <= hour <= 21:
            return "evening"
        return "night"

    @staticmethod
    def _normalize(value):
        normalized = unicodedata.normalize("NFKD", value or "")
        return "".join(char for char in normalized if not unicodedata.combining(char))

    def _product_attributes(self, product):
        result = {}
        for value in product.product_template_attribute_value_ids:
            key = self._normalize(value.attribute_id.name).strip().lower()
            result[key] = value.name or ""
        return result

    @staticmethod
    def _to_number(value):
        match = re.search(r"-?\d+(?:[.,]\d+)?", str(value or ""))
        return float(match.group(0).replace(",", ".")) if match else 0.0

    @staticmethod
    def _color_code(color):
        return {
            "blanco": "GEN00124",
            "negro": "GEN00087",
        }.get((color or "").strip().lower(), "")


class DebytexMrpLineReportWizardLine(models.TransientModel):
    _name = "debytex.mrp.line.report.wizard.line"
    _description = "Línea del Wizard de Reporte de Producción"
    _order = "id"
    _rec_name = "workcenter_id"

    wizard_id = fields.Many2one(
        "debytex.mrp.line.report.wizard", required=True, ondelete="cascade"
    )
    workcenter_id = fields.Many2one(
        "mrp.workcenter",
        string="Línea de producción",
        required=True,
        domain=[("active", "=", True)],
    )
    production_id = fields.Many2one(
        "mrp.production",
        string="Orden activa",
        domain="[('workcenter_id', '=', workcenter_id), ('state', 'in', ['confirmed', 'progress', 'to_close'])]",
    )

    @api.onchange("workcenter_id")
    def _onchange_workcenter_id(self):
        for line in self:
            line.production_id = line.wizard_id._find_active_production(
                line.workcenter_id
            )

    @api.constrains("workcenter_id", "production_id")
    def _check_production_workcenter(self):
        for line in self:
            if (
                line.production_id
                and line.production_id.workcenter_id != line.workcenter_id
            ):
                raise ValidationError(
                    _("La orden seleccionada no pertenece a la línea indicada.")
                )
