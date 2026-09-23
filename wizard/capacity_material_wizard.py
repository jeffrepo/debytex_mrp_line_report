from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

from ..services.capacity import prorate_quantity


class MrpCenterCapacityMaterialWizard(models.TransientModel):
    _name = "debytex.mrp.center.capacity.material.wizard"
    _description = "Consumo general de materiales por centro"

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
    total_rolls = fields.Float(
        string="Rollos base del prorrateo",
        compute="_compute_total_rolls",
    )
    line_ids = fields.One2many(
        "debytex.mrp.center.capacity.material.wizard.line",
        "wizard_id",
        string="Materiales",
    )

    @api.model
    def create_from_plan(self, plan):
        plan.ensure_one()
        groups = defaultdict(
            lambda: {
                "planned_quantity": 0.0,
                "consumed_quantity": 0.0,
                "source_locations": set(),
            }
        )
        products = {}
        units = {}
        for plan_line in plan.line_ids:
            production = plan_line.execution_production_id
            for move in production.move_raw_ids.filtered(
                lambda item: item.state not in ("done", "cancel")
            ):
                key = (move.product_id.id, move.product_uom.id)
                products[key] = move.product_id
                units[key] = move.product_uom
                groups[key]["planned_quantity"] += max(
                    move.product_uom_qty, 0.0
                )
                groups[key]["consumed_quantity"] += max(
                    move.consumo_real, 0.0
                )
                if move.location_id:
                    groups[key]["source_locations"].add(
                        move.location_id.display_name
                    )

        ordered_keys = sorted(
            groups,
            key=lambda key: (
                products[key].display_name or "",
                units[key].display_name or "",
            ),
        )
        return self.create(
            {
                "plan_id": plan.id,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": product_id,
                            "product_uom_id": product_uom_id,
                            "is_manual": False,
                            "source_location_names": ", ".join(
                                sorted(
                                    groups[(product_id, product_uom_id)][
                                        "source_locations"
                                    ]
                                )
                            ),
                            "planned_quantity": groups[
                                (product_id, product_uom_id)
                            ]["planned_quantity"],
                            "consumed_quantity": groups[
                                (product_id, product_uom_id)
                            ]["consumed_quantity"],
                        },
                    )
                    for product_id, product_uom_id in ordered_keys
                ],
            }
        )

    @api.depends("plan_id.line_ids.quantity_to_process")
    def _compute_total_rolls(self):
        for wizard in self:
            wizard.total_rolls = sum(
                max(line.quantity_to_process, 0.0)
                for line in wizard.plan_id.line_ids
                if line.execution_production_id.fecha_inicio_turno
            )

    def action_apply_consumption(self):
        self.ensure_one()
        if self.plan_id.state != "started":
            raise UserError(_("Sólo puede consumir durante un turno activo."))

        captured_lines = self.line_ids.filtered(
            lambda item: item.quantity_to_consume > 0
        )
        if not captured_lines:
            raise UserError(_("Indique el consumo de al menos un material."))

        allocations = []
        for line in captured_lines:
            allocations.extend(line._prorated_allocations())
        self._check_stock(allocations)
        self._save_allocations(allocations)
        return {"type": "ir.actions.act_window_close"}

    def _check_stock(self, allocations):
        required_by_stock = defaultdict(float)
        products = {}
        locations = {}
        for allocation in allocations:
            move = allocation["move"]
            product = move.product_id
            location = move.location_id
            quantity = move.product_uom._compute_quantity(
                allocation["quantity"], product.uom_id
            )
            key = (product.id, location.id)
            required_by_stock[key] += quantity
            products[key] = product
            locations[key] = location

        shortages = []
        for key, required in required_by_stock.items():
            product = products[key]
            location = locations[key]
            if not product.is_storable:
                continue
            quants = self.env["stock.quant"].sudo().search(
                [
                    ("product_id", "=", product.id),
                    ("location_id", "=", location.id),
                ]
            )
            available = sum(quants.mapped("quantity")) - sum(
                quants.mapped("reserved_quantity")
            )
            if float_compare(
                required,
                available,
                precision_rounding=product.uom_id.rounding or 0.01,
            ) > 0:
                shortages.append(
                    _(
                        "%(product)s en %(location)s: requiere %(required).2f, "
                        "disponible %(available).2f"
                    )
                    % {
                        "product": product.display_name,
                        "location": location.display_name,
                        "required": required,
                        "available": available,
                    }
                )
        if shortages:
            raise UserError(
                _("No hay existencias suficientes:\n\n%s")
                % "\n".join(shortages)
            )

    def _save_allocations(self, allocations):
        consumed_at = fields.Datetime.now()
        summaries = defaultdict(list)
        productions = self.env["mrp.production"]
        created_moves = self.env["stock.move"]
        for allocation in allocations:
            move = allocation["move"]
            production = allocation["production"]
            quantity = allocation["quantity"]
            if quantity <= 0:
                continue
            if allocation.get("move_created"):
                created_moves |= move
            self.env["consumo.material.turno"].sudo().create(
                {
                    "production_id": production.id,
                    "move_id": move.id,
                    "product_id": move.product_id.id,
                    "cantidad_consumida": quantity,
                    "user_id": self.env.user.id,
                    "fecha_consumo": consumed_at,
                }
            )
            productions |= production
            summaries[production.id].append(
                _("%(product)s: %(quantity).2f %(uom)s")
                % {
                    "product": move.product_id.display_name,
                    "quantity": quantity,
                    "uom": move.product_uom.display_name,
                }
            )

        consumption_wizard = self.env["consumo.real.wizard"]
        if created_moves:
            created_moves._action_confirm(merge=False)
        for production in productions:
            consumption_wizard.recalcular_totales_consumo(production.id)
            production.message_post(
                body=_(
                    "Consumo general prorrateado desde %(plan)s según los "
                    "rollos asignados:<br/>%(detail)s"
                )
                % {
                    "plan": self.plan_id.display_name,
                    "detail": "<br/>".join(summaries[production.id]),
                },
                message_type="notification",
            )
        if created_moves:
            created_moves._action_assign()


class MrpCenterCapacityMaterialWizardLine(models.TransientModel):
    _name = "debytex.mrp.center.capacity.material.wizard.line"
    _description = "Material general a prorratear"
    _order = "product_id, id"

    wizard_id = fields.Many2one(
        "debytex.mrp.center.capacity.material.wizard",
        required=True,
        ondelete="cascade",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Material",
        required=True,
        domain=[("type", "!=", "service")],
    )
    product_uom_id = fields.Many2one(
        "uom.uom",
        string="Unidad",
        required=True,
        readonly=True,
    )
    is_manual = fields.Boolean(
        string="Agregado manualmente",
        default=True,
        readonly=True,
    )
    source_location_names = fields.Char(
        string="Desde",
        readonly=True,
    )
    planned_quantity = fields.Float(
        string="Demanda",
        digits="Product Unit of Measure",
        readonly=True,
    )
    consumed_quantity = fields.Float(
        string="Consumo real",
        digits="Product Unit of Measure",
        readonly=True,
    )
    remaining_quantity = fields.Float(
        string="Por consumir",
        digits="Product Unit of Measure",
        compute="_compute_remaining_quantity",
    )
    quantity_to_consume = fields.Float(
        string="Cantidad a registrar",
        digits="Product Unit of Measure",
    )
    distribution_preview = fields.Char(
        string="Prorrateo por rollos",
        compute="_compute_distribution_preview",
    )

    _sql_constraints = [
        (
            "material_uom_unique_per_capacity_wizard",
            "unique(wizard_id, product_id, product_uom_id)",
            "Cada material y unidad sólo puede aparecer una vez.",
        )
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            values.setdefault("is_manual", True)
            product = self.env["product.product"].browse(
                values.get("product_id")
            ).exists()
            if product and not values.get("product_uom_id"):
                values["product_uom_id"] = product.uom_id.id
        return super().create(vals_list)

    @api.onchange("product_id")
    def _onchange_manual_product(self):
        for line in self:
            if not line.is_manual or not line.product_id:
                continue
            line.product_uom_id = line.product_id.uom_id
            locations = line._active_plan_lines().mapped(
                "execution_production_id.location_src_id"
            )
            line.source_location_names = ", ".join(
                locations.mapped("display_name")
            )

    @api.constrains("quantity_to_consume")
    def _check_quantity_to_consume(self):
        for line in self:
            if line.quantity_to_consume < 0:
                raise ValidationError(
                    _("El consumo general no puede ser negativo.")
                )

    @api.depends("planned_quantity", "consumed_quantity")
    def _compute_remaining_quantity(self):
        for line in self:
            line.remaining_quantity = max(
                line.planned_quantity - line.consumed_quantity,
                0.0,
            )

    @api.depends(
        "product_id",
        "product_uom_id",
        "wizard_id.plan_id.line_ids.quantity_to_process",
    )
    def _compute_distribution_preview(self):
        for line in self:
            targets = line._eligible_plan_lines()
            total = sum(max(item.quantity_to_process, 0.0) for item in targets)
            line.distribution_preview = ", ".join(
                "%s: %.2f%%"
                % (
                    item.execution_production_id.display_name,
                    item.quantity_to_process / total * 100.0 if total else 0.0,
                )
                for item in targets
            )

    def _eligible_plan_lines(self):
        self.ensure_one()
        return self._active_plan_lines()

    def _active_plan_lines(self):
        self.ensure_one()
        return self.wizard_id.plan_id.line_ids.filtered(
            lambda plan_line: (
                plan_line.execution_production_id.fecha_inicio_turno
                and plan_line.quantity_to_process > 0
            )
        )

    def _prorated_allocations(self):
        self.ensure_one()
        plan_lines = self._eligible_plan_lines()
        total_rolls = sum(
            max(line.quantity_to_process, 0.0) for line in plan_lines
        )
        if not plan_lines or total_rolls <= 0:
            raise UserError(
                _("No hay órdenes activas con rollos asignados para %s.")
                % self.product_id.display_name
            )

        allocations = []
        production_quantities = prorate_quantity(
            self.quantity_to_consume,
            [line.quantity_to_process for line in plan_lines],
        )
        for plan_line, production_quantity in zip(
            plan_lines, production_quantities
        ):
            if production_quantity <= 0:
                continue
            production = plan_line.execution_production_id
            moves = production.move_raw_ids.filtered(
                lambda move: (
                    move.state not in ("done", "cancel")
                    and move.product_id == self.product_id
                    and move.product_uom == self.product_uom_id
                )
            )
            move_created = False
            if not moves:
                moves = self._create_component_move(
                    production,
                    production_quantity,
                )
                move_created = True
            demand_total = sum(max(move.product_uom_qty, 0.0) for move in moves)
            move_weights = (
                [max(move.product_uom_qty, 0.0) for move in moves]
                if demand_total > 0
                else [1.0] * len(moves)
            )
            move_quantities = prorate_quantity(
                production_quantity, move_weights
            )
            for move, move_quantity in zip(moves, move_quantities):
                allocations.append(
                    {
                        "production": production,
                        "move": move,
                        "quantity": move_quantity,
                        "move_created": move_created,
                    }
                )
        return allocations

    def _create_component_move(self, production, quantity):
        self.ensure_one()
        if (
            not production.location_src_id
            or not production.production_location_id
        ):
            raise UserError(
                _(
                    "La orden %(order)s no tiene ubicaciones configuradas para "
                    "agregar el material %(product)s."
                )
                % {
                    "order": production.display_name,
                    "product": self.product_id.display_name,
                }
            )
        move = self.env["stock.move"].create(
            {
                "name": self.product_id.display_name,
                "origin": production.name,
                "product_id": self.product_id.id,
                "product_uom": self.product_uom_id.id,
                "product_uom_qty": quantity,
                "location_id": production.location_src_id.id,
                "location_dest_id": production.production_location_id.id,
                "raw_material_production_id": production.id,
                "picking_type_id": production.picking_type_id.id,
                "company_id": production.company_id.id,
                "group_id": (
                    production.procurement_group_id.id
                    if production.procurement_group_id
                    else False
                ),
                "state": "draft",
            }
        )
        move.write({"production_id": False})
        return move
