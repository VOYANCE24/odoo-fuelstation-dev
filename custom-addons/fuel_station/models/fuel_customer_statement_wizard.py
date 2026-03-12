import datetime

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FuelCustomerStatementWizard(models.TransientModel):
    _name = "fuel.customer.statement.wizard"
    _description = "Customer Credit Statement"

    partner_id = fields.Many2one("res.partner", required=True, string="Customer")
    date_from = fields.Date(
        required=True,
        string="From",
        default=lambda self: fields.Date.today().replace(day=1),
    )
    date_to = fields.Date(
        required=True,
        string="To",
        default=fields.Date.context_today,
    )

    opening_balance = fields.Float(
        string="Opening Balance", readonly=True, digits=(16, 2)
    )
    closing_balance = fields.Float(
        string="Closing Balance", readonly=True, digits=(16, 2)
    )
    total_invoiced = fields.Float(
        string="Total Invoiced", readonly=True, digits=(16, 2)
    )
    total_paid = fields.Float(string="Total Paid", readonly=True, digits=(16, 2))

    currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency_id",
        string="Currency",
    )

    line_ids = fields.One2many(
        "fuel.customer.statement.line",
        "wizard_id",
        string="Statement Lines",
        readonly=True,
    )

    @api.depends_context("company")
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = self.env.company.currency_id

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise ValidationError("'From' date must be before or equal to 'To' date.")

    def action_generate(self):
        self.ensure_one()
        self.line_ids.unlink()

        date_from = self.date_from
        date_to = self.date_to
        partner_id = self.partner_id.id

        # ── Opening balance: all invoices/payments strictly before date_from ──
        invoices_before = self.env["account.move"].search([
            ("partner_id", "=", partner_id),
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("invoice_date", "<", fields.Date.to_string(date_from)),
        ])
        invoiced_before = sum(invoices_before.mapped("amount_total"))

        date_from_dt = datetime.datetime.combine(date_from, datetime.time.min)
        payments_before = self.env["fuel.credit.payment"].search([
            ("customer_id", "=", partner_id),
            ("date", "<", fields.Datetime.to_string(date_from_dt)),
        ])
        paid_before = sum(payments_before.mapped("amount_paid"))
        opening_balance = invoiced_before - paid_before

        # ── Transactions in date range ──
        entries = []

        invoices = self.env["account.move"].search([
            ("partner_id", "=", partner_id),
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("invoice_date", ">=", fields.Date.to_string(date_from)),
            ("invoice_date", "<=", fields.Date.to_string(date_to)),
        ], order="invoice_date asc, id asc")

        for inv in invoices:
            entries.append({
                "date": inv.invoice_date,
                "reference": inv.name,
                "description": "Credit Sale",
                "debit": inv.amount_total,
                "credit": 0.0,
            })

        date_to_dt = datetime.datetime.combine(date_to, datetime.time(23, 59, 59))
        payments = self.env["fuel.credit.payment"].search([
            ("customer_id", "=", partner_id),
            ("date", ">=", fields.Datetime.to_string(date_from_dt)),
            ("date", "<=", fields.Datetime.to_string(date_to_dt)),
        ], order="date asc, id asc")

        method_labels = dict(
            self.env["fuel.credit.payment"]._fields["payment_method"].selection
        )
        for pmt in payments:
            method_label = method_labels.get(pmt.payment_method, pmt.payment_method)
            entries.append({
                "date": pmt.date.date() if pmt.date else date_from,
                "reference": pmt.name,
                "description": "Payment (%s)" % method_label,
                "debit": 0.0,
                "credit": pmt.amount_paid,
            })

        entries.sort(key=lambda e: (e["date"], e.get("reference", "")))

        balance = opening_balance
        total_invoiced = 0.0
        total_paid = 0.0
        lines_to_create = []
        for entry in entries:
            balance += entry["debit"] - entry["credit"]
            total_invoiced += entry["debit"]
            total_paid += entry["credit"]
            lines_to_create.append({
                "wizard_id": self.id,
                "date": entry["date"],
                "reference": entry["reference"],
                "description": entry["description"],
                "debit": entry["debit"],
                "credit": entry["credit"],
                "balance": balance,
            })

        if lines_to_create:
            self.env["fuel.customer.statement.line"].create(lines_to_create)

        self.write({
            "opening_balance": opening_balance,
            "closing_balance": balance,
            "total_invoiced": total_invoiced,
            "total_paid": total_paid,
        })

        return {
            "type": "ir.actions.act_window",
            "res_model": "fuel.customer.statement.wizard",
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }


class FuelCustomerStatementLine(models.TransientModel):
    _name = "fuel.customer.statement.line"
    _description = "Customer Statement Line"
    _order = "date asc, id asc"

    wizard_id = fields.Many2one(
        "fuel.customer.statement.wizard", required=True, ondelete="cascade"
    )
    date = fields.Date(string="Date")
    reference = fields.Char(string="Reference")
    description = fields.Char(string="Description")
    debit = fields.Float(string="Debit", digits=(16, 2))
    credit = fields.Float(string="Credit", digits=(16, 2))
    balance = fields.Float(string="Balance", digits=(16, 2))
    currency_id = fields.Many2one(
        "res.currency",
        related="wizard_id.currency_id",
        string="Currency",
    )
