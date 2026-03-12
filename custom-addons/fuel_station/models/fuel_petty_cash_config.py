from odoo import fields, models, api


class FuelPettyCashConfig(models.Model):
    _name = "fuel.petty.cash.config"
    _description = "Petty Cash Configuration"

    name = fields.Char(default="Petty Cash", required=True)
    float_amount = fields.Float(string="Target Float Amount", default=5000.0)
    petty_cash_account_id = fields.Many2one(
        "account.account",
        string="Petty Cash Account",
        help="Cash/bank account representing the physical petty cash fund.",
    )
    petty_cash_journal_id = fields.Many2one(
        "account.journal",
        string="Petty Cash Journal",
        help="Journal used when posting expense journal entries.",
    )
    currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency_id",
        string="Currency",
    )
    current_balance = fields.Float(
        compute="_compute_balance",
        string="Current Balance",
    )

    @api.depends_context("company")
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = self.env.company.currency_id

    def _compute_balance(self):
        for rec in self:
            replenishments = self.env["fuel.petty.cash.replenishment"].search([])
            expenses = self.env["fuel.petty.cash.expense"].search([
                ("state", "=", "posted"),
                ("payment_source", "=", "petty_cash"),
            ])
            rec.current_balance = (
                sum(replenishments.mapped("amount"))
                - sum(expenses.mapped("amount"))
            )
