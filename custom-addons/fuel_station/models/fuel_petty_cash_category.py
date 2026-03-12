from odoo import fields, models


class FuelPettyCashCategory(models.Model):
    _name = "fuel.petty.cash.category"
    _description = "Cash Expense Category"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char(
        string="Code",
        help="Short code for reporting and accounting mapping (e.g. MAINT, LABOR).",
    )
    account_code = fields.Char(
        string="GL Account Code",
        help="Chart of accounts code to map to when accounting module is configured.",
    )
    account_id = fields.Many2one(
        "account.account",
        string="Expense Account",
        help="Set this to post journal entries automatically when accounting is configured.",
    )
    hr_expense_product_id = fields.Many2one(
        "product.product",
        string="Expense Product",
        help="Product used when creating hr.expense records (enterprise integration).",
    )
    active = fields.Boolean(default=True)
