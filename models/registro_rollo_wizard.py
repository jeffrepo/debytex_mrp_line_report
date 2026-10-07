from odoo import fields, models


class RegistroRolloWizard(models.TransientModel):
    _inherit = "registro.rollo.wizard"

    # Compatibility for a legacy/custom database view that still references
    # this field even though it is absent from the current custom_novici code.
    page_index = fields.Integer(string="Página activa", default=0)
