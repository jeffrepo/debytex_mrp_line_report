from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Add the three required attribute filters to existing draft proposals."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    plans = env["debytex.mrp.center.capacity.plan"].search(
        [("state", "=", "draft")]
    )
    plans._ensure_required_attribute_filters()
