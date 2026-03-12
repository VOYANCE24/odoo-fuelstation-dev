from odoo import fields, models, api


class FuelPayout(models.Model):
    _name = "fuel.payout"
    _description = "Payout"
    _order = "date desc, id desc"

    name = fields.Char(default="New", readonly=True)
    date = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    shift_id = fields.Many2one("fuel.shift", required=True)
    attendant_id = fields.Many2one("fuel.attendant", required=True)

    paid_to = fields.Many2one(
        "res.partner",
        string="Paid To",
        context={"default_supplier_rank": 1},
    )

    # Set when pulled into an attendant session (mirrors credit_sale pattern)
    session_id = fields.Many2one(
        "fuel.attendant.session",
        string="Session",
        index=True,
        ondelete="set null",
        copy=False,
    )

    state = fields.Selection(
        [("draft", "Draft"), ("expensed", "Expensed")],
        default="draft",
        required=True,
        index=True,
    )
    line_ids = fields.One2many("fuel.payout.line", "payout_id", string="Lines")
    amount = fields.Float(
        compute="_compute_amount",
        store=True,
        digits=(16, 2),
        string="Total",
    )
    expense_id = fields.Many2one(
        "fuel.petty.cash.expense",
        string="Cash Expense",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency_id",
        string="Currency",
    )

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("fuel.payout") or "PO/"
                )
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends("line_ids.amount")
    def _compute_amount(self):
        for rec in self:
            rec.amount = sum(rec.line_ids.mapped("amount"))

    @api.depends_context("company")
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = self.env.company.currency_id

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_view_expense(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "fuel.petty.cash.expense",
            "view_mode": "form",
            "res_id": self.expense_id.id,
        }
