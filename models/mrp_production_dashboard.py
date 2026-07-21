from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..services.calculations import compute_production


class MrpProduction(models.Model):
    _inherit = "mrp.production"

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
    def _serialize_dashboard_report_line(self, line):
        report = line.report_id
        return {
            "source_type": "snapshot",
            "source_label": _("Captura guardada: %s") % report.name,
            "report_id": report.id,
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
            "source_label": _("Datos actuales; todavía no existe una captura"),
            "report_id": False,
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
            "pump_rpm": 0,
            "suction": "",
            "cooling": "",
            "range_hood": "",
            "belt_speed": 0,
            "winder_speed": 0,
            "spinning_box": 0,
            "upper_calender": 0,
            "lower_calender": 0,
            "calender_pressure": "",
            "temperatures": "",
            "k_constant": computed["k_constant"],
            "color": values.get("color", "") or "",
            "color_code": values.get("color_code", "") or "",
            "color_percentage": 0,
            "additive": "",
            "additive_code": "",
            "additive_percentage": 0,
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
