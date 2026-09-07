import re
import unicodedata

from markupsafe import escape

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..services.capacity import compute_width_capacity, maximum_lanes


CAPACITY_COLORS = (
    "#4e79a7",
    "#59a14f",
    "#f28e2b",
    "#af7aa1",
    "#76b7b2",
    "#e15759",
)


class MrpCenterCapacityPlan(models.Model):
    _name = "debytex.mrp.center.capacity.plan"
    _description = "Simulación de capacidad por centro"
    _order = "planned_date desc, id desc"

    name = fields.Char(
        string="Simulación",
        required=True,
        default=lambda self: _("Nueva simulación"),
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

    @api.onchange("workcenter_id")
    def _onchange_workcenter_id(self):
        if self.workcenter_id and self.name == _("Nueva simulación"):
            self.name = _("Capacidad de %s") % self.workcenter_id.display_name


class MrpCenterCapacityPlanLine(models.Model):
    _name = "debytex.mrp.center.capacity.plan.line"
    _description = "Orden considerada en capacidad por centro"
    _rec_name = "production_id"
    _order = "sequence, id"

    plan_id = fields.Many2one(
        "debytex.mrp.center.capacity.plan",
        string="Simulación",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        related="plan_id.company_id", store=True, index=True
    )
    production_id = fields.Many2one(
        "mrp.production",
        string="Orden de fabricación",
        required=True,
        domain=(
            "[('state', 'in', ['confirmed', 'progress', 'to_close']), "
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
    width_cm = fields.Float(
        string="Ancho del producto (cm)",
        help="Se obtiene del producto y puede corregirse para esta simulación.",
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
    remaining_rolls = fields.Float(
        string="Rollos pendientes", compute="_compute_quantities", digits=(16, 2)
    )
    allocated_rolls = fields.Float(
        string="Rollos propuestos", compute="_compute_quantities", digits=(16, 2)
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

    _sql_constraints = [
        (
            "production_unique_per_capacity_plan",
            "unique(plan_id, production_id)",
            "Una orden de fabricación solo puede aparecer una vez en la simulación.",
        )
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("production_id") and not values.get("width_cm"):
                production = self.env["mrp.production"].browse(
                    values["production_id"]
                ).exists()
                if production:
                    values["width_cm"] = self._capacity_product_width(
                        production.product_id
                    )
        return super().create(vals_list)

    @api.depends("production_id", "allocation_percentage")
    def _compute_quantities(self):
        for line in self:
            remaining = 0.0
            if line.production_id:
                remaining = line.production_id._line_report_partial_quantities()[
                    "rolls_missing"
                ]
            line.remaining_rolls = remaining
            line.allocated_rolls = (
                remaining * max(line.allocation_percentage, 0.0) / 100.0
            )

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

    @api.constrains("width_cm", "lanes", "allocation_percentage")
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
