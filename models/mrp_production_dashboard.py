import math

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..services.calculations import compute_production


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    @api.model
    def get_dashboard_data(self):
        """Add the report-style summary to each order from custom_novici."""
        dashboard_data = super().get_dashboard_data()
        production_ids = [
            order["id"]
            for workcenter in dashboard_data.values()
            for order in workcenter.get("ordenes", [])
            if order.get("id")
        ]
        summaries = self._get_line_report_dashboard_summaries(production_ids)
        for workcenter in dashboard_data.values():
            for order in workcenter.get("ordenes", []):
                order["line_report_summary"] = summaries.get(
                    order.get("id"), self._empty_dashboard_summary(order)
                )
        return dashboard_data

    @api.model
    def _get_line_report_dashboard_summaries(self, production_ids):
        if not production_ids:
            return {}

        productions = self.sudo().browse(production_ids).exists().filtered(
            lambda production: (
                not production.company_id
                or production.company_id.id in self.env.companies.ids
            )
        )
        report_lines = self.env["debytex.mrp.line.report.line"].sudo().search(
            [
                ("production_id", "in", productions.ids),
                ("report_id.company_id", "in", self.env.companies.ids),
            ]
        )
        oldest_datetime = fields.Datetime.to_datetime("1970-01-01 00:00:00")
        latest_line_by_production = {}
        for line in report_lines.sorted(
            key=lambda report_line: (
                report_line.report_id.cutoff_datetime or oldest_datetime,
                report_line.report_id.id,
                report_line.id,
            ),
            reverse=True,
        ):
            latest_line_by_production.setdefault(line.production_id.id, line)

        cutoff_datetime = fields.Datetime.now()
        helper_wizard = self.env["debytex.mrp.line.report.wizard"].sudo().new(
            {"cutoff_datetime": cutoff_datetime}
        )
        return {
            production.id: self._build_dashboard_order_summary(
                production,
                latest_line_by_production.get(production.id),
                cutoff_datetime,
                helper_wizard,
            )
            for production in productions
        }

    @api.model
    def _build_dashboard_order_summary(
        self, production, snapshot_line, cutoff_datetime, helper_wizard
    ):
        product = production.product_id
        attributes = helper_wizard._product_attributes(product)
        target_grammage = helper_wizard._to_number(
            getattr(product.product_tmpl_id, "gramaje", False)
            or attributes.get("gramaje")
            or attributes.get("peso")
        )
        target_width = helper_wizard._to_number(
            getattr(product.product_tmpl_id, "ancho", False)
            or attributes.get("ancho")
        )
        roll_length = helper_wizard._to_number(
            attributes.get("metros x rollo") or attributes.get("metrosxrollo")
        )
        color = (
            getattr(product.product_tmpl_id, "color", False)
            or attributes.get("color")
            or ""
        )
        active_rolls = production.rollo_ids.filtered("active")
        current_roll = max(active_rolls.mapped("numero_rollo"), default=0)
        useful_width = getattr(
            production.workcenter_id, "x_ancho_util", 0.0
        ) or getattr(production.workcenter_id, "eje_cm", 0.0)
        rolls_per_axis = (
            math.floor(useful_width / target_width)
            if useful_width > 0 and target_width > 0
            else 0
        )
        winder_speed = 0.0
        belt_speed = 0.0
        manual_minutes = 0.0
        time_mode = "manual"
        source_type = "live"
        source_label = _("Datos actuales")

        if snapshot_line:
            target_grammage = snapshot_line.target_grammage or target_grammage
            target_width = snapshot_line.target_width or target_width
            roll_length = snapshot_line.roll_length or roll_length
            color = snapshot_line.color or color
            rolls_per_axis = snapshot_line.rolls_per_axis or rolls_per_axis
            winder_speed = snapshot_line.winder_speed
            belt_speed = snapshot_line.belt_speed
            manual_minutes = snapshot_line.manual_minutes_per_roll
            time_mode = snapshot_line.time_mode
            source_type = "snapshot"
            source_label = _("Parámetros de %s") % snapshot_line.report_id.name

        if production.line_report_parameters_registered:
            operation_values = production._line_report_operation_values()
            target_grammage = operation_values["target_grammage"]
            winder_speed = operation_values["winder_speed"]
            belt_speed = operation_values["belt_speed"]
            source_type = "production"
            source_label = _("Parámetros registrados en la orden")

        computed = compute_production(
            rolls_requested=production.product_qty,
            current_roll=current_roll,
            rolls_per_axis=rolls_per_axis,
            roll_length=roll_length,
            winder_speed=winder_speed,
            belt_speed=belt_speed,
            manual_minutes=manual_minutes,
            time_mode=time_mode,
            cutoff_datetime=cutoff_datetime,
        )
        sale_order = production.sale_order_id
        shift = self._dashboard_shift_label(cutoff_datetime)
        if snapshot_line and snapshot_line.shift_label:
            shift = snapshot_line.shift_label

        return {
            "source_type": source_type,
            "source_label": source_label,
            "shift_label": shift,
            "client_name": sale_order.partner_id.name if sale_order else "",
            "product_name": product.display_name or "",
            "production_name": production.name or "",
            "lot_name": production.lot_producing_id.name or "",
            "target_grammage": target_grammage,
            "target_width": target_width,
            "color": color,
            "color_code": (
                snapshot_line.color_code
                if snapshot_line and snapshot_line.color_code
                else helper_wizard._color_code(color)
            ),
            "rolls_requested": production.product_qty,
            "current_roll": current_roll,
            "rolls_missing": computed["rolls_missing"],
            "remaining_time_text": computed["remaining_time_text"],
            "estimated_finish": self._format_dashboard_datetime(
                computed["estimated_finish"]
            ),
        }

    @api.model
    def _dashboard_shift_label(self, cutoff_datetime):
        local_cutoff = fields.Datetime.context_timestamp(self, cutoff_datetime)
        if 6 <= local_cutoff.hour <= 13:
            return _("Matutino")
        if 14 <= local_cutoff.hour <= 21:
            return _("Vespertino")
        return _("Nocturno")

    @api.model
    def _empty_dashboard_summary(self, order):
        return {
            "source_type": "live",
            "source_label": _("Datos actuales"),
            "shift_label": "",
            "client_name": order.get("cliente", ""),
            "product_name": order.get("product_name", ""),
            "production_name": order.get("name", ""),
            "lot_name": "",
            "target_grammage": 0,
            "target_width": 0,
            "color": "",
            "color_code": "",
            "rolls_requested": order.get("qty_planificada", 0),
            "current_roll": order.get("qty_producida", 0),
            "rolls_missing": max(
                order.get("qty_planificada", 0) - order.get("qty_producida", 0),
                0,
            ),
            "remaining_time_text": "",
            "estimated_finish": "",
        }

    @api.model
    def get_line_report_dashboard_detail(self, production_id):
        """Return the complete line-report detail for a dashboard card."""
        try:
            production_id = int(production_id)
        except (TypeError, ValueError):
            raise UserError(_("La orden de fabricación indicada no es válida."))

        production = self.sudo().browse(production_id).exists()
        if not production:
            raise UserError(_("La orden de fabricación ya no existe."))
        if (
            production.company_id
            and production.company_id.id not in self.env.companies.ids
        ):
            raise UserError(_("La orden pertenece a una compañía no habilitada."))

        report = self.env["debytex.mrp.line.report"].sudo().search(
            [
                ("company_id", "=", production.company_id.id),
                ("line_ids.production_id", "=", production.id),
            ],
            order="cutoff_datetime desc, id desc",
            limit=1,
        )
        if report:
            report_line = report.line_ids.filtered(
                lambda line: line.production_id.id == production.id
            )[:1]
            if report_line:
                return self._serialize_dashboard_report_line(report_line)

        return self._build_live_dashboard_report(production)

    @api.model
    def action_print_line_report_from_dashboard(
        self, production_id, report_line_id=False
    ):
        """Create and print a one-order snapshot from the dashboard detail."""
        try:
            production_id = int(production_id)
        except (TypeError, ValueError):
            raise UserError(_("La orden de fabricación indicada no es válida."))

        production = self.browse(production_id).exists()
        if not production:
            raise UserError(_("La orden de fabricación ya no existe."))
        if (
            production.company_id
            and production.company_id.id not in self.env.companies.ids
        ):
            raise UserError(_("La orden pertenece a una compañía no habilitada."))
        if not production.workcenter_id:
            raise UserError(
                _("La orden no tiene un centro de trabajo asignado.")
            )

        source_line = self.env["debytex.mrp.line.report.line"]
        if report_line_id:
            try:
                report_line_id = int(report_line_id)
            except (TypeError, ValueError):
                raise UserError(_("La captura seleccionada no es válida."))
            source_line = source_line.browse(report_line_id).exists()
            if (
                not source_line
                or source_line.production_id != production
                or source_line.report_id.company_id != production.company_id
            ):
                raise UserError(
                    _("La captura no corresponde a la orden seleccionada.")
                )

        if source_line:
            cutoff_datetime = source_line.report_id.cutoff_datetime
            line_values = self._copy_dashboard_report_line_values(
                source_line, production
            )
        else:
            cutoff_datetime = fields.Datetime.now()
            helper_wizard = self.env[
                "debytex.mrp.line.report.wizard"
            ].new({"cutoff_datetime": cutoff_datetime})
            helper_line = self.env[
                "debytex.mrp.line.report.wizard.line"
            ].new(
                {
                    "workcenter_id": production.workcenter_id.id,
                    "production_id": production.id,
                }
            )
            line_values = helper_wizard._prepare_report_line(helper_line)

        report = self.env["debytex.mrp.line.report"].create(
            {
                "report_type": "technical",
                "cutoff_datetime": cutoff_datetime,
                "company_id": production.company_id.id,
                "include_general_data": True,
                "include_parameters": True,
                "include_additive": True,
                "include_production": True,
                "include_quality": True,
                "include_waste": True,
                "include_incidents": True,
                "include_adjustments": True,
                "include_stops": True,
                "include_handover": True,
                "include_signatures": True,
                "line_ids": [(0, 0, line_values)],
            }
        )
        return report.action_print_report()

    @api.model
    def _copy_dashboard_report_line_values(self, source_line, production):
        many2one_fields = (
            "workcenter_id",
            "production_id",
            "workorder_id",
            "turn_closure_id",
            "leader_id",
            "supervisor_id",
        )
        simple_fields = (
            "sequence",
            "shift",
            "production_name",
            "sale_order_name",
            "lot_name",
            "product_name",
            "client_name",
            "target_grammage",
            "target_width",
            "pump_rpm",
            "suction",
            "cooling",
            "range_hood",
            "belt_speed",
            "winder_speed",
            "spinning_box",
            "upper_calender",
            "lower_calender",
            "calender_pressure",
            "temperatures",
            "color",
            "color_code",
            "color_percentage",
            "additive",
            "additive_code",
            "additive_percentage",
            "actual_grammage",
            "actual_width",
            "roll_length",
            "rolls_requested",
            "current_roll",
            "rolls_per_axis",
            "time_mode",
            "manual_minutes_per_roll",
            "quality_grammage",
            "resistance_md",
            "resistance_cd",
            "elongation_md",
            "elongation_cd",
            "quality_observations",
            "line_conditions",
            "pending_notes",
            "recommendations",
        )
        values = {
            field_name: getattr(source_line, field_name).id
            for field_name in many2one_fields
        }
        values.update(
            {
                field_name: getattr(source_line, field_name)
                for field_name in simple_fields
            }
        )
        values.update(
            {
                "waste_ids": [
                    (
                        0,
                        0,
                        {
                            "sequence": waste.sequence,
                            "waste_type": waste.waste_type,
                            "quantity": waste.quantity,
                            "cause": waste.cause,
                        },
                    )
                    for waste in source_line.waste_ids
                ],
                "incident_ids": [
                    (
                        0,
                        0,
                        {
                            "sequence": incident.sequence,
                            "time_text": incident.time_text,
                            "description": incident.description,
                            "action_taken": incident.action_taken,
                            "result": incident.result,
                        },
                    )
                    for incident in source_line.incident_ids
                ],
                "adjustment_ids": [
                    (
                        0,
                        0,
                        {
                            "sequence": adjustment.sequence,
                            "time_text": adjustment.time_text,
                            "adjustment": adjustment.adjustment,
                            "reason": adjustment.reason,
                        },
                    )
                    for adjustment in source_line.adjustment_ids
                ],
                "stop_ids": [
                    (
                        0,
                        0,
                        {
                            "source_productivity_id": (
                                stop.source_productivity_id.id
                            ),
                            "start_datetime": stop.start_datetime,
                            "end_datetime": stop.end_datetime,
                            "reason": stop.reason,
                        },
                    )
                    for stop in source_line.stop_ids
                ],
            }
        )
        if production.line_report_parameters_registered:
            values.update(production._line_report_operation_values())
        return values

    @api.model
    def _serialize_dashboard_report_line(self, line):
        report = line.report_id
        values = {
            "source_type": "snapshot",
            "source_label": _("Captura guardada: %s") % report.name,
            "report_id": report.id,
            "report_line_id": line.id,
            "cutoff_datetime": self._format_dashboard_datetime(
                report.cutoff_datetime
            ),
            "workcenter_name": line.workcenter_id.name or "",
            "production_name": line.production_name or line.production_id.name or "",
            "sale_order_name": line.sale_order_name or "",
            "lot_name": line.lot_name or "",
            "client_name": line.client_name or "",
            "product_name": line.product_name or "",
            "report_status": line.report_status or "",
            "shift_label": line.shift_label or "",
            "leader_name": line.leader_id.name or "",
            "supervisor_name": line.supervisor_id.name or "",
            "target_grammage": line.target_grammage,
            "target_width": line.target_width,
            "pump_rpm": line.pump_rpm,
            "suction": line.suction or "",
            "cooling": line.cooling or "",
            "range_hood": line.range_hood or "",
            "belt_speed": line.belt_speed,
            "winder_speed": line.winder_speed,
            "spinning_box": line.spinning_box,
            "upper_calender": line.upper_calender,
            "lower_calender": line.lower_calender,
            "calender_pressure": line.calender_pressure or "",
            "temperatures": line.temperatures or "",
            "k_constant": line.k_constant,
            "color": line.color or "",
            "color_code": line.color_code or "",
            "color_percentage": line.color_percentage,
            "additive": line.additive or "",
            "additive_code": line.additive_code or "",
            "additive_percentage": line.additive_percentage,
            "actual_grammage": line.actual_grammage,
            "actual_width": line.actual_width,
            "roll_length": line.roll_length,
            "rolls_requested": line.rolls_requested,
            "current_roll": line.current_roll,
            "rolls_missing": line.rolls_missing,
            "rolls_per_axis": line.rolls_per_axis,
            "pending_axes": line.pending_axes,
            "minutes_per_axis": line.minutes_per_axis,
            "remaining_hours": line.remaining_hours,
            "remaining_time_text": line.remaining_time_text or "",
            "estimated_finish": self._format_dashboard_datetime(
                line.estimated_finish
            ),
            "quality_grammage": line.quality_grammage,
            "resistance_md": line.resistance_md,
            "resistance_cd": line.resistance_cd,
            "elongation_md": line.elongation_md,
            "elongation_cd": line.elongation_cd,
            "quality_observations": line.quality_observations or "",
            "waste": [
                {
                    "type": waste.waste_type or "",
                    "quantity": waste.quantity or "",
                    "cause": waste.cause or "",
                }
                for waste in line.waste_ids
            ],
            "incidents": [
                {
                    "time": incident.time_text or "",
                    "description": incident.description or "",
                    "action": incident.action_taken or "",
                    "result": incident.result or "",
                }
                for incident in line.incident_ids
            ],
            "adjustments": [
                {
                    "time": adjustment.time_text or "",
                    "adjustment": adjustment.adjustment or "",
                    "reason": adjustment.reason or "",
                }
                for adjustment in line.adjustment_ids
            ],
            "stops": [
                {
                    "start": self._format_dashboard_datetime(
                        stop.start_datetime
                    ),
                    "end": self._format_dashboard_datetime(stop.end_datetime),
                    "duration": round(stop.duration_minutes, 2),
                    "reason": stop.reason or "",
                }
                for stop in line.stop_ids
            ],
            "line_conditions": line.line_conditions or "",
            "pending_notes": line.pending_notes or "",
            "recommendations": line.recommendations or "",
        }
        production = line.production_id
        if production.line_report_parameters_registered:
            values.update(production._line_report_operation_values())
            computed = compute_production(
                rolls_requested=line.rolls_requested,
                current_roll=line.current_roll,
                rolls_per_axis=line.rolls_per_axis,
                roll_length=line.roll_length,
                winder_speed=production.line_report_winder_speed,
                belt_speed=production.line_report_belt_speed,
                manual_minutes=line.manual_minutes_per_roll,
                time_mode=line.time_mode,
                cutoff_datetime=report.cutoff_datetime,
            )
            values.update(
                {
                    "source_label": _(
                        "Captura guardada: %s · parámetros actuales de la orden"
                    )
                    % report.name,
                    "k_constant": production.line_report_k_constant,
                    "rolls_missing": computed["rolls_missing"],
                    "pending_axes": computed["pending_axes"],
                    "minutes_per_axis": computed["minutes_per_axis"],
                    "remaining_hours": computed["remaining_hours"],
                    "remaining_time_text": computed["remaining_time_text"],
                    "estimated_finish": self._format_dashboard_datetime(
                        computed["estimated_finish"]
                    ),
                }
            )
        return values

    @api.model
    def _build_live_dashboard_report(self, production):
        cutoff_datetime = fields.Datetime.now()
        wizard = self.env["debytex.mrp.line.report.wizard"].sudo().new(
            {"cutoff_datetime": cutoff_datetime}
        )
        wizard_line = self.env["debytex.mrp.line.report.wizard.line"].sudo().new(
            {
                "workcenter_id": production.workcenter_id.id,
                "production_id": production.id,
            }
        )
        values = wizard._prepare_report_line(wizard_line)
        computed = compute_production(
            rolls_requested=values.get("rolls_requested", 0),
            current_roll=values.get("current_roll", 0),
            rolls_per_axis=values.get("rolls_per_axis", 0),
            roll_length=values.get("roll_length", 0),
            winder_speed=values.get("winder_speed", 0),
            belt_speed=values.get("belt_speed", 0),
            manual_minutes=values.get("manual_minutes_per_roll", 0),
            time_mode=values.get("time_mode", "manual"),
            cutoff_datetime=cutoff_datetime,
        )
        leader = self.env["res.users"].sudo().browse(values.get("leader_id"))
        shift_labels = {
            "morning": _("Matutino"),
            "evening": _("Vespertino"),
            "night": _("Nocturno"),
        }
        rolls_requested = values.get("rolls_requested", 0)
        current_roll = values.get("current_roll", 0)
        if rolls_requested > 0 and computed["rolls_missing"] <= 0:
            report_status = _("Final / orden terminada")
        elif current_roll > 0:
            report_status = _("Seguimiento parcial")
        else:
            report_status = _("Captura / registro inicial")

        return {
            "source_type": "live",
            "source_label": (
                _("Datos actuales y parámetros registrados en la orden")
                if production.line_report_parameters_registered
                else _("Datos actuales; todavía no existe una captura")
            ),
            "report_id": False,
            "report_line_id": False,
            "cutoff_datetime": self._format_dashboard_datetime(cutoff_datetime),
            "workcenter_name": production.workcenter_id.name or "",
            "production_name": values.get("production_name", production.name) or "",
            "sale_order_name": values.get("sale_order_name", "") or "",
            "lot_name": values.get("lot_name", "") or "",
            "client_name": values.get("client_name", "") or "",
            "product_name": values.get("product_name", "") or "",
            "report_status": report_status,
            "shift_label": shift_labels.get(values.get("shift"), ""),
            "leader_name": leader.name or "",
            "supervisor_name": "",
            "target_grammage": values.get("target_grammage", 0),
            "target_width": values.get("target_width", 0),
            "pump_rpm": values.get("pump_rpm", 0),
            "suction": values.get("suction", "") or "",
            "cooling": values.get("cooling", "") or "",
            "range_hood": values.get("range_hood", "") or "",
            "belt_speed": values.get("belt_speed", 0),
            "winder_speed": values.get("winder_speed", 0),
            "spinning_box": values.get("spinning_box", 0),
            "upper_calender": values.get("upper_calender", 0),
            "lower_calender": values.get("lower_calender", 0),
            "calender_pressure": values.get("calender_pressure", "") or "",
            "temperatures": values.get("temperatures", "") or "",
            "k_constant": computed["k_constant"],
            "color": values.get("color", "") or "",
            "color_code": values.get("color_code", "") or "",
            "color_percentage": 0,
            "additive": values.get("additive", "") or "",
            "additive_code": values.get("additive_code", "") or "",
            "additive_percentage": values.get("additive_percentage", 0),
            "actual_grammage": values.get("actual_grammage", 0),
            "actual_width": values.get("actual_width", 0),
            "roll_length": values.get("roll_length", 0),
            "rolls_requested": rolls_requested,
            "current_roll": current_roll,
            "rolls_missing": computed["rolls_missing"],
            "rolls_per_axis": values.get("rolls_per_axis", 0),
            "pending_axes": computed["pending_axes"],
            "minutes_per_axis": computed["minutes_per_axis"],
            "remaining_hours": computed["remaining_hours"],
            "remaining_time_text": computed["remaining_time_text"],
            "estimated_finish": self._format_dashboard_datetime(
                computed["estimated_finish"]
            ),
            "quality_grammage": 0,
            "resistance_md": 0,
            "resistance_cd": 0,
            "elongation_md": 0,
            "elongation_cd": 0,
            "quality_observations": "",
            "waste": self._commands_to_dashboard_waste(
                values.get("waste_ids", [])
            ),
            "incidents": [],
            "adjustments": [],
            "stops": self._commands_to_dashboard_stops(
                values.get("stop_ids", [])
            ),
            "line_conditions": "",
            "pending_notes": "",
            "recommendations": "",
        }

    @api.model
    def _commands_to_dashboard_waste(self, commands):
        return [
            {
                "type": values.get("waste_type", ""),
                "quantity": values.get("quantity", ""),
                "cause": values.get("cause", ""),
            }
            for operation, _record_id, values in commands
            if operation == 0
        ]

    @api.model
    def _commands_to_dashboard_stops(self, commands):
        return [
            {
                "start": self._format_dashboard_datetime(
                    values.get("start_datetime")
                ),
                "end": self._format_dashboard_datetime(
                    values.get("end_datetime")
                ),
                "duration": self._duration_minutes(
                    values.get("start_datetime"), values.get("end_datetime")
                ),
                "reason": values.get("reason", ""),
            }
            for operation, _record_id, values in commands
            if operation == 0
        ]

    @api.model
    def _format_dashboard_datetime(self, value):
        if not value:
            return ""
        datetime_value = fields.Datetime.to_datetime(value)
        local_value = fields.Datetime.context_timestamp(self, datetime_value)
        return local_value.strftime("%d/%m/%Y %H:%M")

    @api.model
    def _duration_minutes(self, start_datetime, end_datetime):
        if not start_datetime or not end_datetime:
            return 0.0
        start = fields.Datetime.to_datetime(start_datetime)
        end = fields.Datetime.to_datetime(end_datetime)
        return round(max((end - start).total_seconds() / 60.0, 0.0), 2)
