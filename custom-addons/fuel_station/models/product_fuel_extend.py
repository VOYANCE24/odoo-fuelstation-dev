from odoo import fields, models


class ProductTemplate(models.Model):
    """
    Extend product.template with fuel-station specific fields.

    Any product marked is_fuel_product=True will appear as a tank on the
    station dashboard.  Set fuel_tank_capacity_liters to enable the
    fill-percentage gauge on the dashboard.
    """
    _inherit = "product.template"

    is_fuel_product = fields.Boolean(
        string="Is Fuel Product",
        default=False,
        help=(
            "Tick this to mark the product as a fuel type managed by the "
            "fuel station module. Fuel products appear on the dashboard "
            "tank-level panel."
        ),
    )
    fuel_tank_capacity_liters = fields.Float(
        string="Tank Capacity (L)",
        digits=(16, 2),
        help="Maximum storage capacity of this fuel's tank in litres.",
    )