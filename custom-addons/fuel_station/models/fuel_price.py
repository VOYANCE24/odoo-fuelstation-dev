from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FuelPrice(models.Model):
    _name = "fuel.price"
    _description = "Fuel Price"
    _order = "effective_date desc, id desc"

    product_id = fields.Many2one(
        "product.product",
        string="Product",
        required=True,
        index=True,
    )
    effective_date = fields.Date(
        required=True,
        default=fields.Date.context_today,
        index=True,
        string="Effective From",
    )
    price = fields.Float(required=True, digits=(16, 2), string="Price per Litre")
    note = fields.Char(string="Note")

    _sql_constraints = [
        (
            "unique_product_date",
            "UNIQUE(product_id, effective_date)",
            "A price for this product on this date already exists.",
        )
    ]

    @api.constrains("price")
    def _check_price(self):
        for rec in self:
            if rec.price <= 0:
                raise ValidationError("Price must be greater than 0.")

    @api.model
    def get_current_price(self, product_id, date=None):
        """
        Return the price per litre for product_id that was effective on date.
        Defaults to today. Returns 0.0 if no price has been configured.
        """
        if date is None:
            date = fields.Date.context_today(self)
        price_rec = self.search(
            [("product_id", "=", product_id), ("effective_date", "<=", date)],
            order="effective_date desc, id desc",
            limit=1,
        )
        return price_rec.price if price_rec else 0.0
