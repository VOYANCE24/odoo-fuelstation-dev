from odoo import fields, models, api


class FuelPayoutLine(models.Model):
    _name = "fuel.payout.line"
    _description = "Payout Line"
    _order = "sequence, id"

    payout_id = fields.Many2one("fuel.payout", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    category_id = fields.Many2one(
        "fuel.petty.cash.category",
        string="Category",
        required=True,
    )
    description = fields.Char(required=True)
    qty = fields.Float(default=1.0, digits=(16, 3))
    rate = fields.Float(digits=(16, 2))
    amount = fields.Float(
        compute="_compute_amount",
        store=True,
        digits=(16, 2),
    )
    currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency_id",
    )

    @api.depends("qty", "rate")
    def _compute_amount(self):
        for line in self:
            line.amount = line.qty * line.rate

    @api.depends_context("company")
    def _compute_currency_id(self):
        for line in self:
            line.currency_id = self.env.company.currency_id
