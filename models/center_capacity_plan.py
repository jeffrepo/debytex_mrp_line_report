import re
import unicodedata

from markupsafe import escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_round

from ..services.capacity import (
    compute_quantity_allocation,
    compute_width_capacity,
    maximum_lanes,
)
from .mrp_production_parameters import LINE_REPORT_PARAMETER_FIELD_MAP


CAPACITY_COLORS = (
    "#4e79a7",
    "#59a14f",
    "#f28e2b",
    "#af7aa1",
    "#76b7b2",
    "#e15759",
)

PLAN_STATES = [
    ("draft", "Borrador"),
    ("started", "Turno iniciado"),
]


class MrpCenterCapacityPlan(models.Model):
    _name = "debytex.mrp.center.capacity.plan"
    _description = "Propuesta de capacidad por centro"
    _order = "planned_date desc, id desc"

    name = fields.Char(
        string="Propuesta",
        required=True,
        readonly=True,
        copy=False,
        default="/",
    )
    state = fields.Selection(
        PLAN_STATES,
        string="Estado",
        required=True,
        readonly=True,
        copy=False,
        default="draft",
        index=True,
    )
    planned_date = fields.Date(
        string="Fecha",
        required=True,
        default=fields.Date.context_today,
    )
    workcenter_id = fields.Many2one(
        "mrp.workcenter",
        string="Centro de trabajo",
        required=True,
        domain=(
            "[('active', '=', True), '|', ('company_id', '=', False), "
            "('company_id', '=', company_id)]"
        ),
        check_company=True,
        ondelete="restrict",
    )
    responsible_id = fields.Many2one(
        "res.users",
        string="Responsable",
        required=True,
        default=lambda self: self.env.user,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    line_ids = fields.One2many(
        "debytex.mrp.center.capacity.plan.line",
        "plan_id",
        string="Órdenes consideradas",
        copy=True,
    )
    notes = fields.Text(string="Observaciones")
    started_at = fields.Datetime(
        string="Turno iniciado el", readonly=True, copy=False
    )
    started_by_id = fields.Many2one(
        "res.users", string="Turno iniciado por", readonly=True, copy=False
    )

    total_width_cm = fields.Float(
        string="Ancho total (cm)", compute="_compute_workcenter_widths"
    )
    useful_width_cm = fields.Float(
        string="Ancho útil (cm)", compute="_compute_workcenter_widths"
    )
    fixed_trim_width_cm = fields.Float(
        string="Refile fijo (cm)", compute="_compute_workcenter_widths"
    )
    occupied_width_cm = fields.Float(
        string="Ancho ocupado (cm)", compute="_compute_capacity"
    )
    free_width_cm = fields.Float(
        string="Ancho disponible (cm)", compute="_compute_capacity"
    )
    excess_width_cm = fields.Float(
        string="Exceso (cm)", compute="_compute_capacity"
    )
    utilization_percentage = fields.Float(
        string="Aprovechamiento (%)", compute="_compute_capacity"
    )
    over_capacity = fields.Boolean(
        string="Excede capacidad", compute="_compute_capacity"
    )
    capacity_state = fields.Selection(
        selection=[
            ("empty", "Sin productos"),
            ("available", "Con espacio disponible"),
            ("full", "Ancho completo"),
            ("over", "Excede el ancho"),
        ],
        string="Resultado",
        compute="_compute_capacity",
    )
    capacity_preview_html = fields.Html(
        string="Distribución del ancho",
        compute="_compute_capacity_preview_html",
        sanitize=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("name", "/") == "/":
                values["name"] = self.env["ir.sequence"].next_by_code(
                    "debytex.mrp.center.capacity.plan"
                ) or _("Nueva propuesta")
        return super().create(vals_list)

    def action_start_shifts(self):
        """Split partial quantities and start every proposed MO atomically."""
        self.ensure_one()
        self._validate_capacity_start()

        for line in self.line_ids.sorted(key=lambda item: (item.sequence, item.id)):
            execution, remainder = line._prepare_capacity_execution()
            line._start_capacity_execution(execution, remainder)

        self.write(
            {
                "state": "started",
                "started_at": fields.Datetime.now(),
                "started_by_id": self.env.user.id,
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": self.display_name,
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }

    def _validate_capacity_start(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("El turno de esta propuesta ya fue iniciado."))
        if not self.line_ids:
            raise UserError(
                _("Agregue al menos una orden de fabricación antes de iniciar.")
            )
        if self.useful_width_cm <= 0:
            raise UserError(
                _("El centro de trabajo no tiene un ancho útil configurado.")
            )
        if self.over_capacity:
            raise UserError(
                _(
                    "La combinación excede el ancho útil por %.2f cm. "
                    "Ajuste las bandas antes de iniciar."
                )
                % self.excess_width_cm
            )
        if getattr(self.workcenter_id, "working_state", False) == "blocked":
            raise UserError(
                _("El centro de trabajo seleccionado se encuentra bloqueado.")
            )
        for line in self.line_ids:
            line._validate_capacity_execution()

    @api.depends(
        "workcenter_id",
        "workcenter_id.eje_cm",
        "workcenter_id.x_ancho_refile",
        "workcenter_id.x_ancho_util",
    )
    def _compute_workcenter_widths(self):
        for plan in self:
            workcenter = plan.workcenter_id
            total = (
                max(float(workcenter.eje_cm or 0.0), 0.0)
                if workcenter
                else 0.0
            )
            fixed_trim = (
                max(float(workcenter.x_ancho_refile or 0.0), 0.0)
                if workcenter
                else 0.0
            )
            configured_useful = (
                float(workcenter.x_ancho_util or 0.0)
                if workcenter
                else 0.0
            )
            useful = (
                configured_useful
                if configured_useful > 0
                else max(total - fixed_trim, 0.0)
            )
            plan.total_width_cm = total
            plan.useful_width_cm = useful
            plan.fixed_trim_width_cm = fixed_trim

    @api.depends(
        "useful_width_cm",
        "line_ids",
        "line_ids.width_cm",
        "line_ids.lanes",
    )
    def _compute_capacity(self):
        for plan in self:
            values = compute_width_capacity(
                useful_width_cm=plan.useful_width_cm,
                allocations=(
                    {"width_cm": line.width_cm, "lanes": line.lanes}
                    for line in plan.line_ids
                ),
            )
            plan.occupied_width_cm = values["occupied_width_cm"]
            plan.free_width_cm = values["free_width_cm"]
            plan.excess_width_cm = values["excess_width_cm"]
            plan.utilization_percentage = values[
                "utilization_percentage"
            ]
            plan.over_capacity = values["over_capacity"]
            if not plan.line_ids:
                plan.capacity_state = "empty"
            elif values["over_capacity"]:
                plan.capacity_state = "over"
            elif values["free_width_cm"] <= 0.0001:
                plan.capacity_state = "full"
            else:
                plan.capacity_state = "available"

    @api.depends(
        "useful_width_cm",
        "fixed_trim_width_cm",
        "occupied_width_cm",
        "free_width_cm",
        "over_capacity",
        "line_ids.production_id",
        "line_ids.product_id",
        "line_ids.width_cm",
        "line_ids.lanes",
    )
    def _compute_capacity_preview_html(self):
        for plan in self:
            if not plan.workcenter_id:
                plan.capacity_preview_html = False
                continue
            useful = plan.useful_width_cm
            if useful <= 0:
                plan.capacity_preview_html = (
                    '<div class="alert alert-warning">Configure el ancho del eje '
                    "en el centro de trabajo para visualizar la capacidad.</div>"
                )
                continue

            segments = []
            for index, line in enumerate(plan.line_ids):
                occupied = max(line.width_cm, 0.0) * max(line.lanes, 0)
                percentage = occupied / useful * 100.0
                label = escape(
                    line.production_id.name
                    or line.product_id.display_name
                    or _("Producto")
                )
                color = CAPACITY_COLORS[index % len(CAPACITY_COLORS)]
                segments.append(
                    '<div style="flex:0 0 %.4f%%;min-width:42px;height:76px;'
                    "display:flex;align-items:center;justify-content:center;"
                    "text-align:center;padding:4px;color:#fff;font-weight:600;"
                    'background:%s;border-right:2px solid #fff;overflow:hidden;">'
                    "%s<br/>%.2f cm</div>"
                    % (percentage, color, label, occupied)
                )
            if plan.free_width_cm:
                free_percentage = plan.free_width_cm / useful * 100.0
                segments.append(
                    '<div style="flex:0 0 %.4f%%;height:76px;display:flex;'
                    "align-items:center;justify-content:center;text-align:center;"
                    "padding:4px;background:#d8dce2;color:#4b5563;"
                    'font-weight:600;overflow:hidden;">Libre<br/>%.2f cm</div>'
                    % (free_percentage, plan.free_width_cm)
                )
            if not segments:
                segments.append(
                    '<div style="width:100%;height:76px;display:flex;'
                    "align-items:center;justify-content:center;background:#eef0f3;"
                    'color:#6b7280;">Agregue órdenes para simular la carga</div>'
                )

            warning = ""
            if plan.over_capacity:
                warning = (
                    '<div class="alert alert-danger mt-2 mb-0">La combinación '
                    "excede el ancho útil por <strong>%.2f cm</strong>.</div>"
                    % plan.excess_width_cm
                )
            plan.capacity_preview_html = (
                '<div style="margin:8px 0 14px;">'
                '<div style="display:flex;justify-content:space-between;'
                'margin-bottom:6px;"><span>0 cm</span><strong>Ancho útil: '
                "%.2f cm</strong><span>%.2f cm</span></div>"
                '<div style="display:flex;width:100%%;height:78px;overflow:hidden;'
                'border:1px solid #aeb3bb;background:#eef0f3;">%s</div>'
                '<div style="height:8px;background:#b85450;margin-top:6px;"></div>'
                '<div style="text-align:right;color:#8a3d3a;font-size:12px;'
                'margin-top:3px;">Refile fijo: %.2f cm</div>%s</div>'
                % (
                    useful,
                    useful,
                    "".join(segments),
                    plan.fixed_trim_width_cm,
                    warning,
                )
            )

class MrpCenterCapacityPlanLine(models.Model):
    _name = "debytex.mrp.center.capacity.plan.line"
    _description = "Orden considerada en capacidad por centro"
    _rec_name = "production_id"
    _order = "sequence, id"

    plan_id = fields.Many2one(
        "debytex.mrp.center.capacity.plan",
        string="Propuesta",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        related="plan_id.company_id", store=True, index=True
    )
    workcenter_id = fields.Many2one(
        related="plan_id.workcenter_id",
        string="Centro de trabajo",
        store=True,
        readonly=True,
    )
    plan_state = fields.Selection(
        related="plan_id.state", string="Estado de la propuesta", readonly=True
    )
    production_id = fields.Many2one(
        "mrp.production",
        string="Orden de fabricación",
        required=True,
        domain=(
            "[('state', '=', 'confirmed'), "
            "('company_id', '=', company_id)]"
        ),
        check_company=True,
        ondelete="cascade",
    )
    product_id = fields.Many2one(
        related="production_id.product_id",
        string="Producto",
        store=True,
        readonly=True,
    )
    product_uom_id = fields.Many2one(
        related="production_id.product_uom_id",
        string="Unidad",
        readonly=True,
    )
    width_cm = fields.Float(
        string="Ancho del producto (cm)",
        help="Se obtiene del producto y puede corregirse para esta propuesta.",
    )
    lanes = fields.Integer(
        string="Bandas en el eje",
        default=1,
        help="Número de posiciones simultáneas que ocupará este producto.",
    )
    allocation_percentage = fields.Float(
        string="Asignar de la orden (%)",
        default=100.0,
        help="Porcentaje de la cantidad pendiente que se propone para este turno.",
    )
    quantity_to_process = fields.Float(
        string="Cantidad a procesar",
        digits="Product Unit of Measure",
        help=(
            "Cantidad exacta que se fabricará en este centro. Si es menor que "
            "la orden, Odoo creará una orden parcial para el remanente."
        ),
    )
    remaining_rolls = fields.Float(
        string="Cantidad disponible",
        compute="_compute_quantities",
        digits="Product Unit of Measure",
    )
    allocated_rolls = fields.Float(
        string="Cantidad propuesta",
        compute="_compute_quantities",
        digits="Product Unit of Measure",
    )
    source_quantity_at_start = fields.Float(
        string="Cantidad original",
        digits="Product Unit of Measure",
        readonly=True,
        copy=False,
    )
    occupied_width_cm = fields.Float(
        string="Ancho ocupado (cm)", compute="_compute_width_results"
    )
    maximum_lanes = fields.Integer(
        string="Máximo individual", compute="_compute_width_results"
    )
    fits_alone = fields.Boolean(
        string="Cabe individualmente", compute="_compute_width_results"
    )
    execution_production_id = fields.Many2one(
        "mrp.production",
        string="Orden iniciada",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    remainder_production_id = fields.Many2one(
        "mrp.production",
        string="Orden remanente",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    shift_history_id = fields.Many2one(
        "debytex.mrp.shift.history",
        string="Turno iniciado",
        readonly=True,
        copy=False,
        ondelete="set null",
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
            "production_unique_per_capacity_plan",
            "unique(plan_id, production_id)",
            "Una orden de fabricación solo puede aparecer una vez en la propuesta.",
        )
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            production = self.env["mrp.production"].browse(
                values.get("production_id")
            ).exists()
            if not production:
                continue
            plan = self.env["debytex.mrp.center.capacity.plan"].browse(
                values.get("plan_id")
            ).exists()
            values.setdefault(
                "width_cm", self._capacity_product_width(production.product_id)
            )
            available = self._capacity_available_quantity(production)
            values.setdefault(
                "quantity_to_process",
                available
                * max(float(values.get("allocation_percentage", 100.0)), 0.0)
                / 100.0,
            )
            parameter_defaults = self._capacity_parameter_defaults(
                production, plan.workcenter_id
            )
            for field_name, value in parameter_defaults.items():
                values.setdefault(field_name, value)
        return super().create(vals_list)

    @api.depends(
        "production_id",
        "production_id.product_qty",
        "source_quantity_at_start",
        "quantity_to_process",
        "allocation_percentage",
    )
    def _compute_quantities(self):
        for line in self:
            available = line.source_quantity_at_start or (
                self._capacity_available_quantity(line.production_id)
                if line.production_id
                else 0.0
            )
            values = compute_quantity_allocation(
                available_quantity=available,
                quantity_to_process=line.quantity_to_process,
                allocation_percentage=line.allocation_percentage,
            )
            line.remaining_rolls = values["available_quantity"]
            line.allocated_rolls = values["quantity_to_process"]

    @api.depends("width_cm", "lanes", "plan_id.useful_width_cm")
    def _compute_width_results(self):
        for line in self:
            line.occupied_width_cm = max(line.width_cm, 0.0) * max(
                line.lanes, 0
            )
            line.maximum_lanes = maximum_lanes(
                useful_width_cm=line.plan_id.useful_width_cm,
                product_width_cm=line.width_cm,
            )
            line.fits_alone = bool(
                line.width_cm > 0 and line.maximum_lanes >= line.lanes
            )

    @api.onchange("production_id")
    def _onchange_production_id(self):
        if self.production_id:
            self.width_cm = self._capacity_product_width(
                self.production_id.product_id
            )
            available = self._capacity_available_quantity(self.production_id)
            self.quantity_to_process = available
            self.allocation_percentage = 100.0
            defaults = self._capacity_parameter_defaults(
                self.production_id, self.plan_id.workcenter_id
            )
            for field_name, value in defaults.items():
                setattr(self, field_name, value)

    @api.onchange("allocation_percentage")
    def _onchange_allocation_percentage(self):
        if not self.production_id:
            return
        available = self.source_quantity_at_start or (
            self._capacity_available_quantity(self.production_id)
        )
        self.quantity_to_process = (
            available * max(self.allocation_percentage, 0.0) / 100.0
        )

    @api.onchange("quantity_to_process")
    def _onchange_quantity_to_process(self):
        if not self.production_id:
            return
        available = self.source_quantity_at_start or (
            self._capacity_available_quantity(self.production_id)
        )
        self.allocation_percentage = (
            max(self.quantity_to_process, 0.0) / available * 100.0
            if available
            else 0.0
        )

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

    @api.constrains(
        "width_cm",
        "lanes",
        "allocation_percentage",
        "quantity_to_process",
        "production_id",
    )
    def _check_capacity_values(self):
        for line in self:
            if line.width_cm <= 0:
                raise ValidationError(
                    _("El ancho del producto debe ser mayor que cero.")
                )
            if line.lanes < 1:
                raise ValidationError(
                    _("Debe asignar al menos una banda del producto.")
                )
            if not 0 < line.allocation_percentage <= 100:
                raise ValidationError(
                    _("El porcentaje asignado debe ser mayor que 0 y hasta 100%.")
                )
            if line.quantity_to_process < 0:
                raise ValidationError(
                    _("La cantidad a procesar no puede ser negativa.")
                )
            if line.production_id and line.quantity_to_process:
                available = line.source_quantity_at_start or (
                    line._capacity_available_quantity(line.production_id)
                )
                rounding = line.production_id.product_uom_id.rounding or 0.01
                if float_compare(
                    line.quantity_to_process,
                    available,
                    precision_rounding=rounding,
                ) > 0:
                    raise ValidationError(
                        _(
                            "La cantidad a procesar de %(order)s no puede exceder "
                            "la cantidad disponible (%(available)s)."
                        )
                        % {
                            "order": line.production_id.display_name,
                            "available": available,
                        }
                    )

    def _validate_capacity_execution(self):
        self.ensure_one()
        production = self.production_id
        if production.state != "confirmed":
            raise UserError(
                _(
                    "La orden %(order)s debe estar confirmada y sin iniciar. "
                    "Estado actual: %(state)s."
                )
                % {
                    "order": production.display_name,
                    "state": dict(
                        production._fields["state"]._description_selection(
                            self.env
                        )
                    ).get(production.state, production.state),
                }
            )
        if production.fecha_inicio_turno or (
            production.line_report_active_shift_id
            and production.line_report_active_shift_id.state
            in ("running", "paused")
        ):
            raise UserError(
                _("La orden %s ya tiene un turno activo.")
                % production.display_name
            )
        available = self._capacity_available_quantity(production)
        quantity = self._capacity_processing_quantity(available)
        rounding = production.product_uom_id.rounding or 0.01
        if float_compare(quantity, 0.0, precision_rounding=rounding) <= 0:
            raise UserError(
                _("Indique una cantidad mayor que cero para %s.")
                % production.display_name
            )
        if float_compare(
            quantity, available, precision_rounding=rounding
        ) > 0:
            raise UserError(
                _(
                    "La cantidad indicada para %(order)s excede lo disponible "
                    "(%(available)s %(uom)s)."
                )
                % {
                    "order": production.display_name,
                    "available": available,
                    "uom": production.product_uom_id.display_name,
                }
            )
        active_components = production.move_raw_ids.filtered(
            lambda move: move.state not in ("done", "cancel")
            and move.product_uom_qty > 0
        )
        if not active_components:
            raise UserError(
                _(
                    "La orden %s no tiene componentes pendientes para consumir."
                )
                % production.display_name
            )

    def _prepare_capacity_execution(self):
        self.ensure_one()
        production = self.production_id
        available = self._capacity_available_quantity(production)
        quantity = self._capacity_processing_quantity(available)
        rounding = production.product_uom_id.rounding or 0.01
        quantity = float_round(quantity, precision_rounding=rounding)
        self.write(
            {
                "quantity_to_process": quantity,
                "allocation_percentage": (
                    quantity / available * 100.0 if available else 0.0
                ),
                "source_quantity_at_start": available,
            }
        )

        if float_compare(
            quantity, available, precision_rounding=rounding
        ) == 0:
            return production, self.env["mrp.production"]

        component_snapshots = self._capacity_component_snapshots(production)
        remainder_quantity = float_round(
            available - quantity, precision_rounding=rounding
        )
        split_productions = production._split_productions(
            {production: [quantity, remainder_quantity]}
        )
        remainder = (split_productions - production).sorted(
            key=lambda order: (order.backorder_sequence, order.id)
        )[:1]
        if not remainder:
            raise UserError(
                _("No fue posible crear la orden parcial de %s.")
                % production.display_name
            )
        self._capacity_restore_remainder_components(
            remainder, component_snapshots, available
        )
        return production, remainder

    def _start_capacity_execution(self, production, remainder):
        self.ensure_one()
        workcenter = self.plan_id.workcenter_id
        production_values = self._capacity_production_parameter_values()
        production.write(
            {
                **production_values,
                "line_report_parameters_registered": True,
                "line_report_workcenter_ids": [(6, 0, [workcenter.id])],
                "workcenter_id": workcenter.id,
            }
        )
        production.action_assign()
        active_components = self._capacity_check_component_availability(
            production
        )
        for move in active_components:
            move.sudo().write(
                {
                    "consumo_real": move.product_uom_qty,
                    "quantity": move.product_uom_qty,
                    "picked": True,
                }
            )

        shifts = production._line_report_start_workcenter_shifts(
            {workcenter.id: self._capacity_history_parameter_values()}
        )
        shift = shifts.filtered(
            lambda item: item.workcenter_id == workcenter
        )[:1]
        self._capacity_register_component_consumption(
            production, active_components
        )
        self.write(
            {
                "execution_production_id": production.id,
                "remainder_production_id": remainder.id if remainder else False,
                "shift_history_id": shift.id if shift else False,
            }
        )
        if remainder:
            production.message_post(
                body=_(
                    "La propuesta %(plan)s inició %(quantity)s %(uom)s en "
                    "%(workcenter)s. El remanente quedó en %(remainder)s."
                )
                % {
                    "plan": self.plan_id.name,
                    "quantity": self.quantity_to_process,
                    "uom": production.product_uom_id.display_name,
                    "workcenter": workcenter.display_name,
                    "remainder": remainder.display_name,
                },
                message_type="notification",
            )

    def _capacity_check_component_availability(self, production):
        self.ensure_one()
        components = production.move_raw_ids.filtered(
            lambda move: move.state not in ("done", "cancel")
            and move.product_uom_qty > 0
        )
        shortages = []
        for move in components:
            if not move.product_id.is_storable or move._should_bypass_reservation():
                continue
            rounding = move.product_uom.rounding or 0.01
            if float_compare(
                move.quantity,
                move.product_uom_qty,
                precision_rounding=rounding,
            ) < 0:
                shortages.append(
                    _("%(product)s: requiere %(required)s, reservado %(reserved)s")
                    % {
                        "product": move.product_id.display_name,
                        "required": move.product_uom_qty,
                        "reserved": move.quantity,
                    }
                )
        if shortages:
            raise UserError(
                _(
                    "No hay componentes suficientes para iniciar %(order)s:\n\n%(detail)s"
                )
                % {
                    "order": production.display_name,
                    "detail": "\n".join(shortages),
                }
            )
        return components

    def _capacity_register_component_consumption(self, production, moves):
        consumed_at = fields.Datetime.now()
        values = [
            {
                "production_id": production.id,
                "move_id": move.id,
                "product_id": move.product_id.id,
                "cantidad_consumida": move.product_uom_qty,
                "user_id": self.env.user.id,
                "fecha_consumo": consumed_at,
            }
            for move in moves
            if move.product_uom_qty > 0
        ]
        for item in values:
            self.env["consumo.material.turno"].sudo().create(item)

    def _capacity_component_snapshots(self, production):
        snapshots = []
        for move in production.move_raw_ids.filtered(
            lambda item: item.state not in ("done", "cancel")
            and item.product_uom_qty > 0
        ):
            values = move.copy_data(
                default=move._get_backorder_move_vals()
            )[0]
            snapshots.append(
                {
                    "values": values,
                    "demand": move.product_uom_qty,
                    "rounding": move.product_uom.rounding or 0.01,
                }
            )
        return snapshots

    def _capacity_restore_remainder_components(
        self, remainder, snapshots, original_quantity
    ):
        """Restore moves removed by custom_novici's split override."""
        if remainder.move_raw_ids or not snapshots or not original_quantity:
            return
        ratio = remainder.product_qty / original_quantity
        move_values = []
        for snapshot in snapshots:
            values = dict(snapshot["values"])
            values.pop("move_line_ids", None)
            values.pop("wizard_line_ids", None)
            demand = float_round(
                snapshot["demand"] * ratio,
                precision_rounding=snapshot["rounding"],
                rounding_method="UP",
            )
            values.update(
                {
                    "name": remainder.name,
                    "origin": remainder._get_origin(),
                    "raw_material_production_id": remainder.id,
                    "production_id": False,
                    "product_uom_qty": demand,
                    "quantity": 0.0,
                    "picked": False,
                    "state": "draft",
                    "workorder_id": False,
                    "consumo_real": 0.0,
                }
            )
            move_values.append(values)
        moves = self.env["stock.move"]
        for values in move_values:
            # custom_novici still overrides create() with the legacy
            # single-record signature, so restore each move separately.
            moves |= self.env["stock.move"].create(values)
        moves._action_confirm(merge=False)
        moves._adjust_procure_method()
        to_assign = moves.filtered(
            lambda move: move._should_bypass_reservation()
            or move.picking_type_id.reservation_method == "at_confirm"
            or (
                move.reservation_date
                and move.reservation_date <= fields.Date.today()
            )
        )
        to_assign._action_assign()

    def _capacity_processing_quantity(self, available):
        self.ensure_one()
        return compute_quantity_allocation(
            available_quantity=available,
            quantity_to_process=self.quantity_to_process,
            allocation_percentage=self.allocation_percentage,
        )["quantity_to_process"]

    @api.model
    def _capacity_available_quantity(self, production):
        return max(float(production.product_qty or 0.0), 0.0)

    def _capacity_production_parameter_values(self):
        self.ensure_one()
        return {
            field_name: getattr(self, field_name)
            for field_name in LINE_REPORT_PARAMETER_FIELD_MAP
        }

    def _capacity_history_parameter_values(self):
        self.ensure_one()
        return {
            history_field: getattr(self, production_field)
            for production_field, history_field in (
                LINE_REPORT_PARAMETER_FIELD_MAP.items()
            )
        }

    @api.model
    def _capacity_parameter_defaults(self, production, workcenter):
        history = self.env["debytex.mrp.shift.history"].search(
            [
                ("production_id", "=", production.id),
                ("workcenter_id", "=", workcenter.id),
            ],
            order="started_at desc, id desc",
            limit=1,
        ) if workcenter else self.env["debytex.mrp.shift.history"]
        result = {
            production_field: (
                getattr(history, history_field)
                if history
                else getattr(production, production_field)
            )
            for production_field, history_field in (
                LINE_REPORT_PARAMETER_FIELD_MAP.items()
            )
        }
        if (
            not result["line_report_target_grammage"]
            and not production.line_report_parameters_registered
        ):
            result[
                "line_report_target_grammage"
            ] = production._line_report_default_target_grammage()
        return result

    @api.model
    def _capacity_product_width(self, product):
        direct = getattr(product.product_tmpl_id, "ancho", False)
        if direct:
            return self._capacity_to_number(direct)
        for attribute_value in product.product_template_attribute_value_ids:
            name = self._capacity_normalize(
                attribute_value.attribute_id.name
            ).strip().lower()
            if name == "ancho":
                return self._capacity_to_number(attribute_value.name)
        return 0.0

    @staticmethod
    def _capacity_normalize(value):
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        return "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        )

    @staticmethod
    def _capacity_to_number(value):
        match = re.search(r"-?\d+(?:[.,]\d+)?", str(value or ""))
        return float(match.group(0).replace(",", ".")) if match else 0.0
