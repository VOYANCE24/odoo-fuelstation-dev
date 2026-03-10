from odoo import fields, models

class StockPicking(models.Model):
    _inherit = "stock.picking"

    fuel_delivery_count = fields.Integer(compute="_compute_fuel_delivery_count")

    def _compute_fuel_delivery_count(self):
        # Use read_group to count in a single SQL query instead of N+1 loop.
        groups = self.env["fuel.delivery"].read_group(
            domain=[("picking_id", "in", self.ids)],
            fields=["picking_id"],
            groupby=["picking_id"],
        )
        count_by_picking = {g["picking_id"][0]: g["picking_id_count"] for g in groups}
        for picking in self:
            picking.fuel_delivery_count = count_by_picking.get(picking.id, 0)

    def action_open_fuel_delivery(self):
        """Open existing fuel delivery for this picking, otherwise create it."""
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