from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from ..models.center_capacity_plan import REQUIRED_ATTRIBUTE_FILTERS
from ..models.mrp_capacity_reprocess import REPROCESS_RESULT_TYPES


class MrpCenterCapacityReprocessWizard(models.TransientModel):
    _name = "debytex.mrp.center.capacity.reprocess.wizard"
    _description = "Confirmar reproceso de capacidad por centro"

    plan_id = fields.Many2one(
        "debytex.mrp.center.capacity.plan",
        string="Plan de capacidad",
        required=True,
        readonly=True,
    )
    workcenter_id = fields.Many2one(
        related="plan_id.workcenter_id",
        string="Centro de trabajo",
        readonly=True,
    )
    attribute_summary = fields.Char(
        string="Atributos comunes",
        compute="_compute_totals",
    )
    product_name = fields.Char(
        string="Producto de reproceso",
        compute="_compute_totals",
    )
    line_ids = fields.One2many(
        "debytex.mrp.center.capacity.reprocess.wizard.line",
        "wizard_id",
        string="Líneas de resultado",
    )
    total_width_cm = fields.Float(
        string="Ancho total (cm)", compute="_compute_totals"
    )
    total_weight_kg = fields.Float(
        string="Peso total estimado (kg)",
        compute="_compute_totals",
        digits=(16, 3),
    )

    @api.model
    def create_from_plan(self, plan):
        plan.ensure_one()
        commands = []
        for sequence, values in enumerate(
            plan._capacity_reprocess_result_values(), start=1
        ):
            commands.append(
                Command.create(
                    {
                        "sequence": sequence * 10,
                        "result_type": values["result_type"],
                        "width_cm": values["width_cm"],
                        "roll_quantity": values["roll_quantity"],
                        "meters_per_roll": values["meters_per_roll"],
                        "grammage_g_m2": values["grammage_g_m2"],
                    }
                )
            )
        return self.create({"plan_id": plan.id, "line_ids": commands})

    def _capacity_attribute_items(self):
        self.ensure_one()
        by_key = {
            item.attribute_key: item
            for item in self.plan_id.attribute_filter_ids.filtered("value_id")
        }
        return [
            by_key[key]
            for key, _label, _xmlid in REQUIRED_ATTRIBUTE_FILTERS
            if key in by_key
        ]

    @api.depends(
        "plan_id.attribute_filter_ids.value_id",
        "line_ids.width_cm",
        "line_ids.roll_quantity",
        "line_ids.meters_per_roll",
        "line_ids.grammage_g_m2",
        "line_ids.estimated_weight_kg",
    )
    def _compute_totals(self):
        labels = {
            key: label for key, label, _xmlid in REQUIRED_ATTRIBUTE_FILTERS
        }
        for wizard in self:
            items = wizard._capacity_attribute_items()
            summary = [
                "%s: %s" % (labels[item.attribute_key], item.value_id.name)
                for item in items
            ]
            wizard.attribute_summary = " · ".join(summary)
            wizard.product_name = (
                _("Reproceso / %s") % " / ".join(summary)
                if summary
                else _("Reproceso")
            )
            wizard.total_width_cm = sum(wizard.line_ids.mapped("width_cm"))
            wizard.total_weight_kg = sum(
                wizard.line_ids.mapped("estimated_weight_kg")
            )

    def _get_or_create_reprocess_product(self):
        self.ensure_one()
        items = self._capacity_attribute_items()
        if len(items) != len(REQUIRED_ATTRIBUTE_FILTERS):
            raise UserError(
                _(
                    "El plan debe tener Peso, Color y Metros por rollo "
                    "antes de generar el producto de reproceso."
                )
            )
        default_code = "REPROC-CAP-%s" % "-".join(
            str(item.value_id.id) for item in items
        )
        product = self.env["product.product"].search(
            [
                "|",
                ("product_tmpl_id.capacity_reprocess_signature", "=", default_code),
                "&",
                ("name", "=", self.product_name),
                ("categ_id.name", "=", "Reproceso"),
            ],
            limit=1,
        )
        if product:
            if not product.product_tmpl_id.capacity_reprocess_signature:
                product.product_tmpl_id.sudo().capacity_reprocess_signature = (
                    default_code
                )
            if "is_reproceso" in product._fields and not product.is_reproceso:
                product.sudo().is_reproceso = True
            return product

        category = self.env["product.category"].search(
            [("name", "=", "Reproceso")], limit=1
        )
        if not category:
            category = self.env["product.category"].create(
                {
                    "name": "Reproceso",
                    "property_cost_method": "fifo",
                    "property_valuation": "real_time",
                }
            )
        uom_kg = self.env.ref("uom.product_uom_kgm", raise_if_not_found=False)
        if not uom_kg:
            uom_kg = self.env["uom.uom"].search(
                [("category_id", "=", self.env.ref("uom.product_uom_categ_kgm").id)],
                limit=1,
            )
        if not uom_kg:
            raise UserError(
                _("No se encontró la unidad de medida Kilogramos.")
            )
        values = {
            "name": self.product_name,
            "default_code": default_code,
            "capacity_reprocess_signature": default_code,
            "type": "consu",
            "is_storable": True,
            "purchase_ok": False,
            "sale_ok": False,
            "tracking": "none",
            "categ_id": category.id,
            "uom_id": uom_kg.id,
            "uom_po_id": uom_kg.id,
            "attribute_line_ids": [
                Command.create(
                    {
                        "attribute_id": item.attribute_id.id,
                        "value_ids": [Command.set(item.value_id.ids)],
                    }
                )
                for item in items
            ],
        }
        if "is_reproceso" in self.env["product.template"]._fields:
            values["is_reproceso"] = True
        template = (
            self.env["product.template"]
            .with_context(skip_code_generation=True)
            .sudo()
            .create(values)
        )
        product = template.product_variant_id
        if "is_reproceso" in product._fields and not product.is_reproceso:
            product.sudo().is_reproceso = True
        return product

    def action_create_reprocess_order(self):
        self.ensure_one()
        plan = self.plan_id.exists()
        if not plan or plan.state != "closed":
            raise UserError(
                _("El turno debe estar finalizado para crear el reproceso.")
            )
        if plan.reprocess_production_id:
            raise UserError(
                _("Este plan ya tiene una orden de reproceso vinculada.")
            )
        existing = self.env["mrp.production"].search(
            [("capacity_reprocess_plan_id", "=", plan.id)], limit=1
        )
        if existing:
            plan.reprocess_production_id = existing.id
            raise UserError(
                _("Este plan ya generó la orden de reproceso %s.")
                % existing.display_name
            )
        lines = self.line_ids.filtered(
            lambda line: line.width_cm > 0
            and line.roll_quantity > 0
            and line.estimated_weight_kg > 0
        )
        if not lines or self.total_weight_kg <= 0:
            raise UserError(
                _("Agregue al menos una línea de reproceso con cantidad válida.")
            )

        product = self._get_or_create_reprocess_product()
        source = plan._capacity_productions()[:1]
        production_values = {
            "product_id": product.id,
            "product_qty": self.total_weight_kg,
            "product_uom_id": product.uom_id.id,
            "company_id": plan.company_id.id,
            "origin": plan.display_name,
            "capacity_reprocess_plan_id": plan.id,
            "workcenter_id": plan.workcenter_id.id,
            "capacity_reprocess_result_ids": [
                Command.create(
                    {
                        "sequence": line.sequence,
                        "result_type": line.result_type,
                        "width_cm": line.width_cm,
                        "roll_quantity": line.roll_quantity,
                        "meters_per_roll": line.meters_per_roll,
                        "grammage_g_m2": line.grammage_g_m2,
                        "estimated_weight_kg": line.estimated_weight_kg,
                    }
                )
                for line in lines
            ],
        }
        if source:
            production_values.update(
                {
                    "picking_type_id": source.picking_type_id.id,
                    "location_src_id": source.location_src_id.id,
                    "location_dest_id": source.location_dest_id.id,
                }
            )
        production = self.env["mrp.production"].create(production_values)
        plan.write({"reprocess_production_id": production.id})
        production.message_post(
            body=_(
                "Orden de reproceso creada desde el plan de capacidad %s "
                "con un total estimado de %.3f kg."
            )
            % (plan.display_name, self.total_weight_kg)
        )
        return plan.action_open_reprocess_production()


class MrpCenterCapacityReprocessWizardLine(models.TransientModel):
    _name = "debytex.mrp.center.capacity.reprocess.wizard.line"
    _description = "Línea para confirmar reproceso de capacidad"
    _order = "sequence, id"

    wizard_id = fields.Many2one(
        "debytex.mrp.center.capacity.reprocess.wizard",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    result_type = fields.Selection(
        REPROCESS_RESULT_TYPES,
        string="Resultado",
        required=True,
        readonly=True,
    )
    width_cm = fields.Float(string="Ancho (cm)", required=True)
    roll_quantity = fields.Float(
        string="Rollos",
        required=True,
        digits="Product Unit of Measure",
    )
    meters_per_roll = fields.Float(string="Metros por rollo", required=True)
    grammage_g_m2 = fields.Float(string="Gramaje (g/m²)", required=True)
    estimated_weight_kg = fields.Float(
        string="Peso estimado (kg)",
        compute="_compute_estimated_weight",
        digits=(16, 3),
    )

    @api.depends(
        "width_cm", "roll_quantity", "meters_per_roll", "grammage_g_m2"
    )
    def _compute_estimated_weight(self):
        for line in self:
            line.estimated_weight_kg = (
                max(line.grammage_g_m2, 0.0)
                * max(line.width_cm, 0.0)
                * max(line.meters_per_roll, 0.0)
                * max(line.roll_quantity, 0.0)
                / 100000.0
            )
