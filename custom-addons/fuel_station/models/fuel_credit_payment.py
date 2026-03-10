from odoo import fields, models, api
from odoo.exceptions import ValidationError


class FuelCreditPayment(models.Model):
    _name = "fuel.credit.payment"
    _description = "Credit Payment Receipt"
    _order = "date desc, id desc"

    name = fields.Char(default="New", readonly=True)
    date = fields.Datetime(required=True, default=fields.Datetime.now)

    shift_id = fields.Many2one("fuel.shift", required=True)
    receipt_no = fields.Char()
    invoice_ref = fields.Char(required=True)
    customer_id = fields.Many2one("res.partner")
    total_balance = fields.Float(string="Outstanding Balance")
    amount_paid = fields.Float(required=True)

    payment_method = fields.Selection(
        [("cash", "Cash"), ("cheque", "Cheque")], required=True
    )

    station_close_id = fields.Many2one("fuel.station.shift.close", index=True)

    # Optional link back to the originating credit sale.
    # When set, the credit sale's outstanding balance and state are updated automatically.
    credit_sale_id = fields.Many2one(
        "fuel.credit.sale",
        string="Credit Sale",
        index=True,
        ondelete="set null",
        help="Link this payment to a specific credit sale to track its outstanding balance.",
    )

    currency_id = fields.Many2one(
        'res.currency',
        compute='_compute_currency_id',
        string='Currency',
    )

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """
        Fix applied vs original:
            next_by_code() was called ONCE outside the loop.  Every record in a
            batch create therefore received the same sequence number, silently
            creating duplicate names.

            Moving the call inside the loop ensures each record gets a unique,
            auto-incremented sequence number.
        """
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("fuel.credit.payment")
                    or "CP/"
                )
        return super().create(vals_list)

    @api.depends_context('company')
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = self.env.company.currency_id

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    @api.constrains("amount_paid")
    def _check_amount_paid(self):
        for rec in self:
            if rec.amount_paid <= 0:
                raise ValidationError("Amount paid must be greater than 0.")