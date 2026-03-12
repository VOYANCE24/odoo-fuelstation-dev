from odoo import fields, models, api
from odoo.exceptions import ValidationError


class FuelPettyCashExpense(models.Model):
    _name = "fuel.petty.cash.expense"
    _description = "Cash Expense"
    _order = "date desc, id desc"


    name = fields.Char(default="New", readonly=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    shift_id = fields.Many2one("fuel.shift", string="Shift")
    vendor_id = fields.Many2one(
        "res.partner",
        string="Vendor",
        context={"default_supplier_rank": 1},
    )
    paid_by = fields.Many2one(
        "res.users",
        default=lambda self: self.env.user,
        string="Paid By",
    )
    bill_no = fields.Char(string="Bill No.", readonly=True, copy=False)
    receipt_ref = fields.Char(string="Receipt Ref")
    station_close_id = fields.Many2one(
        "fuel.station.shift.close",
        string="Shift Close",
        index=True,
    )
    state = fields.Selection(
        [("draft", "Draft"), ("posted", "Posted")],
        default="draft",
        required=True,
        index=True,
    )

    line_ids = fields.One2many(
        "fuel.petty.cash.expense.line",
        "expense_id",
        string="Expense Lines",
    )
    amount = fields.Float(
        compute="_compute_amount",
        store=True,
        string="Total Amount",
        digits=(16, 2),
    )

    payment_source = fields.Selection(
        [("petty_cash", "Petty Cash"), ("session_payout", "Session Payout")],
        string="Payment Source",
        default="petty_cash",
        required=True,
        index=True,
    )
    payout_id = fields.Many2one(
        "fuel.payout",
        string="Payout",
        readonly=True,
        copy=False,
        ondelete="set null",
        help="Set when this expense was auto-created from a payout on session approval.",
    )

    # Integration references (stored as integers — soft dependency, no FK constraint)
    hr_expense_res_id = fields.Integer(
        string="HR Expense ID",
        readonly=True,
        copy=False,
        help="ID of the linked hr.expense record (set when hr_expense module is active).",
    )
    account_move_id = fields.Many2one(
        "account.move",
        string="Journal Entry",
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
                    self.env["ir.sequence"].next_by_code("fuel.petty.cash.expense")
                    or "PCE/"
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

    def action_post(self):
        for rec in self:
            if rec.state != "draft":
                continue
            if not rec.line_ids:
                raise ValidationError("Cannot post an expense with no lines.")
            if not rec.amount:
                raise ValidationError("Cannot post an expense with zero total amount.")

            # ── Petty cash balance check (only for petty_cash source) ────
            if rec.payment_source == "petty_cash":
                replenishments = self.env["fuel.petty.cash.replenishment"].search([])
                posted = self.env["fuel.petty.cash.expense"].search([
                    ("state", "=", "posted"),
                    ("payment_source", "=", "petty_cash"),
                    ("id", "!=", rec.id),
                ])
                balance = (
                    sum(replenishments.mapped("amount"))
                    - sum(posted.mapped("amount"))
                )
                if rec.amount > balance:
                    raise ValidationError(
                        f"Insufficient petty cash balance.\n"
                        f"Available: {balance:,.2f} | This expense: {rec.amount:,.2f}\n"
                        f"Please replenish the petty cash fund before posting."
                    )

            # ── Generate Bill No. ────────────────────────────────────────
            if not rec.bill_no:
                rec.bill_no = (
                    self.env["ir.sequence"].next_by_code("fuel.petty.cash.expense.bill")
                    or "BN/"
                )

            rec.write({"state": "posted"})
            rec._bridge_hr_expense()
            rec._bridge_account_move()

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state != "posted":
                continue
            if rec.account_move_id:
                move = rec.account_move_id
                if move.state == "posted":
                    move.button_draft()
                if move.state != "cancel":
                    move.button_cancel()
                rec.account_move_id = False
                rec.receipt_ref = False
                rec.bill_no = False
            rec.write({"state": "draft"})

    def action_view_journal_entry(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.account_move_id.id,
        }

    # ------------------------------------------------------------------
    # Integration bridges
    # ------------------------------------------------------------------

    def _bridge_hr_expense(self):
        """Create hr.expense records (one per line) if hr_expense module is installed."""
        self.ensure_one()
        if "hr.expense" not in self.env:
            return
        employee = self.env["hr.employee"].search(
            [("user_id", "=", self.paid_by.id)], limit=1
        )
        if not employee:
            return
        expense_id = None
        for line in self.line_ids:
            if not line.category_id.hr_expense_product_id:
                continue
            expense = self.env["hr.expense"].create({
                "name": line.description,
                "employee_id": employee.id,
                "product_id": line.category_id.hr_expense_product_id.id,
                "quantity": line.qty,
                "price_unit": line.rate,
                "date": self.date,
            })
            if expense_id is None:
                expense_id = expense.id
        if expense_id is not None:
            self.hr_expense_res_id = expense_id

    def _bridge_account_move(self):
        """Create a vendor bill (preferred) or raw journal entry depending on setup."""
        self.ensure_one()
        if "account.move" not in self.env:
            return
        config = self.env["fuel.petty.cash.config"].search([], limit=1)
        if (
            not config
            or not config.petty_cash_journal_id
        ):
            return

        if self.vendor_id:
            self._bridge_vendor_bill(config)
        else:
            self._bridge_journal_entry(config)

    def _bridge_vendor_bill(self, config):
        """Create a vendor bill (in_invoice) for the expense."""
        self.ensure_one()
        invoice_lines = []
        for line in self.line_ids:
            if not line.amount:
                continue
            line_vals = {
                "name": line.description,
                "quantity": line.qty,
                "price_unit": line.rate,
            }
            if line.category_id.account_id:
                line_vals["account_id"] = line.category_id.account_id.id
            invoice_lines.append((0, 0, line_vals))
        if not invoice_lines:
            return
        move = self.env["account.move"].create({
            "move_type": "in_invoice",
            "partner_id": self.vendor_id.id,
            "invoice_date": self.date,
            "journal_id": config.petty_cash_journal_id.id,
            "ref": self.name,
            "invoice_line_ids": invoice_lines,
        })
        move.action_post()
        self.account_move_id = move.id
        if not self.receipt_ref:
            self.receipt_ref = move.name

    def _bridge_journal_entry(self, config):
        """Fallback: raw journal entry when no vendor is set."""
        self.ensure_one()
        if not config.petty_cash_account_id:
            return
        debit_lines = []
        for line in self.line_ids:
            if not line.category_id.account_id or not line.amount:
                continue
            debit_lines.append((0, 0, {
                "account_id": line.category_id.account_id.id,
                "name": line.description,
                "debit": line.amount,
                "credit": 0.0,
            }))
        if not debit_lines:
            return
        debit_lines.append((0, 0, {
            "account_id": config.petty_cash_account_id.id,
            "name": self.name,
            "debit": 0.0,
            "credit": self.amount,
        }))
        move = self.env["account.move"].create({
            "move_type": "entry",
            "journal_id": config.petty_cash_journal_id.id,
            "date": self.date,
            "ref": self.name,
            "line_ids": debit_lines,
        })
        move.action_post()
        self.account_move_id = move.id
        if not self.receipt_ref:
            self.receipt_ref = move.name
