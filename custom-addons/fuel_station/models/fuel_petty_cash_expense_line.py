from odoo import fields, models, api
from odoo.exceptions import ValidationError


class FuelPettyCashExpenseLine(models.Model):
    _name = "fuel.petty.cash.expense.line"
    _description = "Cash Expense Line"
    _order = "sequence, id"

    expense_id = fields.Many2one(
        "fuel.petty.cash.expense",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    category_id = fields.Many2one(
        "fuel.petty.cash.category",
        required=True,
        string="Category",
        ondelete="restrict",
    )
    description = fields.Char(required=True, string="Description")
    qty = fields.Float(default=1.0, string="Qty", digits=(16, 3))
    rate = fields.Float(string="Rate", digits=(16, 2))
    amount = fields.Float(
        compute="_compute_amount",
        store=True,
        string="Amount",
        digits=(16, 2),
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="expense_id.currency_id",
        string="Currency",
    )

    @api.depends("qty", "rate")
    def _compute_amount(self):
        for line in self:
            line.amount = (line.qty or 0.0) * (line.rate or 0.0)

    @api.constrains("qty", "rate")
    def _check_positive(self):
        for line in self:
            if (line.qty or 0) < 0:
                raise ValidationError("Qty cannot be negative.")
            if (line.rate or 0) < 0:
                raise ValidationError("Rate cannot be negative.")
