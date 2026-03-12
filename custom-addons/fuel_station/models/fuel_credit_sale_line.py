from odoo import fields, models, api
from odoo.exceptions import ValidationError


class FuelCreditSaleLine(models.Model):
    _name = "fuel.credit.sale.line"
    _description = "Credit Sale Line"
    _order = "id"

    credit_sale_id = fields.Many2one(
        "fuel.credit.sale",
        required=True,
        ondelete="cascade",
    )
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
        string="Product",
    )
    vehicle_type = fields.Char(string="Vehicle Type")
    vehicle_plate = fields.Char(string="Vehicle Plate")
    litres = fields.Float(required=True, string="Litres", digits=(16, 3))
    price = fields.Float(required=True, string="Price", digits=(16, 2))
    analytic_distribution = fields.Json(
        string="Analytic Distribution",
        default=lambda self: {},
    )
    amount = fields.Float(
        compute="_compute_amount",
        store=True,
        string="Amount",
        digits=(16, 2),
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="credit_sale_id.currency_id",
        string="Currency",
    )

    # ------------------------------------------------------------------
    # Onchange
    # ------------------------------------------------------------------

    @api.onchange("nozzle_id")
    def _onchange_nozzle_set_analytic(self):
        for line in self:
            if not line.nozzle_id:
                continue
            product = line.nozzle_id.product_id
            if product:
                if hasattr(product.product_tmpl_id, 'analytic_distribution'):
                    line.analytic_distribution = product.product_tmpl_id.analytic_distribution or {}
                current_price = self.env["fuel.price"].get_current_price(product.id)
                if current_price:
                    line.price = current_price

    # ------------------------------------------------------------------
    # ORM guards — mirror the header lock
    # ------------------------------------------------------------------

    def write(self, vals):
        locked = self.filtered(
            lambda r: r.credit_sale_id.session_id
            and r.credit_sale_id.session_id.state == "approved"
        )
        if locked:
            raise ValidationError(
                "Cannot edit a credit sale line that belongs to an approved session. "
                "Reset the session to Draft first."
            )
        return super().write(vals)

    def unlink(self):
        locked = self.filtered(
            lambda r: r.credit_sale_id.session_id
            and r.credit_sale_id.session_id.state == "approved"
        )
        if locked:
            raise ValidationError(
                "Cannot delete a credit sale line that belongs to an approved session. "
                "Reset the session to Draft first."
            )
        return super().unlink()

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends("litres", "price")
    def _compute_amount(self):
        for line in self:
            line.amount = (line.litres or 0.0) * (line.price or 0.0)

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    @api.constrains("litres", "price")
    def _check_positive(self):
        for line in self:
            if line.litres <= 0:
                raise ValidationError("Litres must be greater than 0.")
            if line.price < 0:
                raise ValidationError("Price must be >= 0.")
