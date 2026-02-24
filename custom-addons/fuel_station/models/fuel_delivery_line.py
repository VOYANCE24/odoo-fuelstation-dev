from odoo import fields, models

class FuelDeliveryLine(models.Model):
    _name = "fuel.delivery.line"
    _description = "Fuel Delivery Line (Per Fuel Type)"

    delivery_id = fields.Many2one("fuel.delivery", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True)
    received_litres = fields.Float(required=True)