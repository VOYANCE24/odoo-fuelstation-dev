from odoo import fields, models, api
from odoo.exceptions import ValidationError


class FuelCreditSale(models.Model):
    _name = "fuel.credit.sale"
    _description = "Fuel Credit Sale"
    _order = "date desc, id desc"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(default="New", readonly=True)
    date = fields.Datetime(required=True, default=fields.Datetime.now)

    shift_id = fields.Many2one("fuel.shift", required=True)
    attendant_id = fields.Many2one("fuel.attendant", required=True)
    nozzle_id = fields.Many2one("fuel.nozzle", string="Nozzle", required=True)
    pump_id = fields.Many2one(
        "fuel.pump",
        related="nozzle_id.pump_id",
        store=True,
        readonly=True,
        string="Pump",
    )
    product_id = fields.Many2one(
        related="nozzle_id.product_id",
        store=True,
        readonly=True,
    )

    invoice_ref = fields.Char(required=True)
    customer_id = fields.Many2one("res.partner", domain=[("customer_rank", ">", 0)])
    customer_name = fields.Char()
    vehicle_type = fields.Char()
    vehicle_plate = fields.Char()

    litres = fields.Float(required=True)
    price = fields.Float(required=True)
    amount = fields.Float(compute="_compute_amount", store=True)

    session_id = fields.Many2one("fuel.attendant.session", index=True)
    station_close_id = fields.Many2one("fuel.station.shift.close", index=True)

    currency_id = fields.Many2one(
        'res.currency',
        compute='_compute_currency_id',
        string='Currency',
    )

    # ------------------------------------------------------------------
    # Outstanding balance tracking
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

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """
        Fix: sequence called inside loop — each record gets its own unique number.
        """
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("fuel.credit.sale") or "CS/"
                )
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends("litres", "price")
    def _compute_amount(self):
        for rec in self:
            rec.amount = (rec.litres or 0.0) * (rec.price or 0.0)

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
    # Constraints
    # ------------------------------------------------------------------

    @api.constrains("litres", "price")
    def _check_positive(self):
        for rec in self:
            if rec.litres <= 0:
                raise ValidationError("Litres must be greater than 0.")
            if rec.price < 0:
                raise ValidationError("Price must be >= 0.")