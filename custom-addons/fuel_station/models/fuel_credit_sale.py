from odoo import fields, models, api
from odoo.exceptions import ValidationError


class FuelCreditSale(models.Model):
    _name = "fuel.credit.sale"
    _description = "Fuel Credit Sale"
    _order = "date desc, id desc"


    name = fields.Char(default="New", readonly=True)
    date = fields.Datetime(required=True, default=fields.Datetime.now)

    shift_id = fields.Many2one("fuel.shift", required=True)
    attendant_id = fields.Many2one("fuel.attendant", required=True)

    # Populated at session approval — not created during credit sale entry.
    invoice_ref = fields.Char(readonly=True, copy=False)
    move_id = fields.Many2one(
        "account.move",
        string="Invoice",
        readonly=True,
        copy=False,
        ondelete="set null",
    )

    customer_id = fields.Many2one(
        "res.partner",
        required=True,
        context={"default_customer_rank": 1},
    )
    customer_name = fields.Char(
        compute="_compute_customer_name",
        store=True,
        readonly=True,
    )

    line_ids = fields.One2many(
        "fuel.credit.sale.line",
        "credit_sale_id",
        string="Sale Lines",
    )
    amount = fields.Float(
        compute="_compute_amount",
        store=True,
        string="Total Amount",
        digits=(16, 2),
    )
    litres = fields.Float(
        compute="_compute_litres",
        store=True,
        string="Total Litres",
        digits=(16, 3),
    )

    session_id = fields.Many2one("fuel.attendant.session", index=True)
    station_close_id = fields.Many2one("fuel.station.shift.close", index=True)

    currency_id = fields.Many2one(
        'res.currency',
        compute='_compute_currency_id',
        string='Currency',
    )

    # ------------------------------------------------------------------
    # Outstanding balance tracking (internal — via fuel.credit.payment)
    # ------------------------------------------------------------------

    payment_ids = fields.One2many(
        "fuel.credit.payment",
        "credit_sale_id",
        string="Payments",
        readonly=True,
    )
    amount_paid = fields.Float(
        string="Amount Paid",
        compute="_compute_outstanding",
        store=True,
        digits=(16, 2),
    )
    amount_outstanding = fields.Float(
        string="Outstanding",
        compute="_compute_outstanding",
        store=True,
        digits=(16, 2),
    )
    payment_state = fields.Selection(
        [
            ("unpaid", "Unpaid"),
            ("partial", "Partial"),
            ("paid", "Paid"),
        ],
        string="Payment Status",
        compute="_compute_outstanding",
        store=True,
        default="unpaid",
    )

    is_locked = fields.Boolean(
        compute="_compute_is_locked",
        string="Locked",
    )

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("fuel.credit.sale") or "CS/"
                )
        return super().create(vals_list)

    def write(self, vals):
        locked = self.filtered(
            lambda r: r.session_id and r.session_id.state == "approved"
        )
        if locked:
            raise ValidationError(
                "Cannot edit a credit sale that belongs to an approved session. "
                "Reset the session to Draft first."
            )
        return super().write(vals)

    def unlink(self):
        locked = self.filtered(
            lambda r: r.session_id and r.session_id.state == "approved"
        )
        if locked:
            raise ValidationError(
                "Cannot delete a credit sale that belongs to an approved session. "
                "Reset the session to Draft first."
            )
        return super().unlink()

    # ------------------------------------------------------------------
    # Invoice action (populated at session approval)
    # ------------------------------------------------------------------

    def action_view_invoice(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.move_id.id,
        }

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends("session_id", "session_id.state")
    def _compute_is_locked(self):
        for rec in self:
            rec.is_locked = bool(rec.session_id and rec.session_id.state == "approved")

    @api.depends("customer_id")
    def _compute_customer_name(self):
        for rec in self:
            rec.customer_name = rec.customer_id.name or ""

    @api.depends("line_ids.amount")
    def _compute_amount(self):
        for rec in self:
            rec.amount = sum(rec.line_ids.mapped("amount"))

    @api.depends("line_ids.litres")
    def _compute_litres(self):
        for rec in self:
            rec.litres = sum(rec.line_ids.mapped("litres"))

    @api.depends("payment_ids.amount_paid", "amount")
    def _compute_outstanding(self):
        for rec in self:
            paid = sum(rec.payment_ids.mapped("amount_paid"))
            rec.amount_paid = paid
            rec.amount_outstanding = max((rec.amount or 0.0) - paid, 0.0)
            if paid <= 0:
                rec.payment_state = "unpaid"
            elif rec.amount_outstanding > 0:
                rec.payment_state = "partial"
            else:
                rec.payment_state = "paid"

    @api.depends_context('company')
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = self.env.company.currency_id

    # ------------------------------------------------------------------
    # Credit limit enforcement
    # ------------------------------------------------------------------

    @api.constrains("line_ids", "customer_id")
    def _check_credit_limit(self):
        for rec in self:
            if not rec.customer_id or not rec.amount:
                continue
            limit = rec.customer_id.fuel_credit_limit
            if not limit:
                continue
            # Outstanding = residual on all other posted invoices for this customer
            other_invoices = self.env["account.move"].search([
                ("partner_id", "=", rec.customer_id.id),
                ("move_type", "=", "out_invoice"),
                ("state", "=", "posted"),
                ("payment_state", "in", ["not_paid", "partial"]),
                # Exclude the invoice already created for this sale (if any)
                ("id", "!=", rec.move_id.id if rec.move_id else False),
            ])
            outstanding = sum(other_invoices.mapped("amount_residual"))
            if outstanding + rec.amount > limit + 0.01:
                raise ValidationError(
                    f"Credit limit exceeded for {rec.customer_id.name}.\n"
                    f"Limit: {limit:,.2f}  |  "
                    f"Current outstanding: {outstanding:,.2f}  |  "
                    f"This sale: {rec.amount:,.2f}  |  "
                    f"Total would be: {outstanding + rec.amount:,.2f}"
                )
