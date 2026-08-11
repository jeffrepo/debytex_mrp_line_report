from odoo import fields, models, _


class PauseShiftWizard(models.TransientModel):
    _inherit = "pausa.turno.wizard"

    def action_confirmar_pausa(self):
        self.ensure_one()
        paused_at = fields.Datetime.now()
        super().action_confirmar_pausa()
        reason_options = dict(
            self._fields["motivo"]._description_selection(self.env)
        )
        self.production_id._line_report_pause_shift(
            paused_at,
            reason_code=self.motivo,
            reason_label=reason_options.get(self.motivo, _("Pausa")),
            description=self.descripcion_otros or "",
        )
        return {"type": "ir.actions.client", "tag": "reload"}
