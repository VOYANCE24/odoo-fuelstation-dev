from odoo import fields, models


class ResPartnerFuelExtend(models.Model):
    _inherit = "res.partner"

    fuel_credit_limit = fields.Float(
        string="Fuel Credit Limit",
        digits=(16, 2),
        help="Maximum outstanding fuel credit balance allowed for this customer. "
             "Set to 0.00 to disable the limit.",
    )
