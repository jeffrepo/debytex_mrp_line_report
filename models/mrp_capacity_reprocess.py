from odoo import fields, models


REPROCESS_RESULT_TYPES = [
    ("fixed_left", "Refile fijo izquierdo"),
    ("fixed_right", "Refile fijo derecho"),
    ("free", "Ancho útil sobrante"),
]


class ProductTemplate(models.Model):
    _inherit = "product.template"

    capacity_reprocess_signature = fields.Char(
        string="Clave de reproceso por capacidad",
        readonly=True,
        copy=False,
        index=True,
    )


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    capacity_reprocess_plan_id = fields.Many2one(
        "debytex.mrp.center.capacity.plan",
        string="Plan de capacidad de origen",
        readonly=True,
        copy=False,
        index=True,
        ondelete="set null",
    )
    capacity_reprocess_result_ids = fields.One2many(
        "debytex.mrp.center.capacity.reprocess.result",
        "production_id",
        string="Resultados de reproceso",
        readonly=True,
        copy=False,
    )


class MrpCenterCapacityReprocessResult(models.Model):
    _name = "debytex.mrp.center.capacity.reprocess.result"
    _description = "Resultado de reproceso de capacidad por centro"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    production_id = fields.Many2one(
        "mrp.production",
        string="Orden de reproceso",
        required=True,
        index=True,
        ondelete="cascade",
    )
    plan_id = fields.Many2one(
        related="production_id.capacity_reprocess_plan_id",
        string="Plan de capacidad",
        store=True,
        index=True,
    )
    company_id = fields.Many2one(
        related="production_id.company_id",
        store=True,
        index=True,
    )
    product_id = fields.Many2one(
        related="production_id.product_id",
        string="Producto de reproceso",
        store=True,
    )
    result_type = fields.Selection(
        REPROCESS_RESULT_TYPES,
        string="Origen",
        required=True,
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
        string="Peso estimado (kg)", required=True, digits=(16, 3)
    )
