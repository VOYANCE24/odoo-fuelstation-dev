from odoo import fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    fuel_delivery_count = fields.Integer(compute="_compute_fuel_delivery_count")

    def _compute_fuel_delivery_count(self):
        FuelDelivery = self.env["fuel.delivery"]
        for picking in self:
            picking.fuel_delivery_count = FuelDelivery.search_count([("picking_id", "=", picking.id)])

    def action_open_fuel_deliveries(self):
        """
        Button entry point (called from stock.picking view):
        For an incoming picking, open the existing fuel delivery record if present,
        otherwise create it, then open it in form view.
        """
        self.ensure_one()
        FuelDelivery = self.env["fuel.delivery"]

        delivery = FuelDelivery.search([("picking_id", "=", self.id)], limit=1)
        if not delivery:
            delivery = FuelDelivery.create({"picking_id": self.id})

        return {
            "type": "ir.actions.act_window",
            "name": "Fuel Delivery Measurements",
            "res_model": "fuel.delivery",
            "view_mode": "form",
            "res_id": delivery.id,
            "target": "current",
            "context": {"default_picking_id": self.id},
        }