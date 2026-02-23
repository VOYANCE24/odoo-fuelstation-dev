from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FuelCalibrationProfile(models.Model):
    _name = "fuel.calibration.profile"
    _description = "Fuel Calibration Profile (Depth → Volume)"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)

    profile_type = fields.Selection(
        [
            ("truck", "Truck Compartment"),
            ("tank", "Station Tank"),
        ],
        required=True,
        default="truck",
    )

    # Optional scoping (kept flexible for v1)
    product_id = fields.Many2one("product.product", string="Product", ondelete="set null")
    reference = fields.Char(
        string="Reference",
        help="Optional label e.g. 'Truck Generic', 'PMS Tank 1', 'AGO Tank 1'.",
    )

    line_ids = fields.One2many(
        "fuel.calibration.line",
        "profile_id",
        string="Calibration Points",
        copy=True,
    )

    def volume_from_depth_mm(self, depth_mm: float) -> float:
        """Return volume (liters) using linear interpolation across calibration points."""
        self.ensure_one()
        depth = float(depth_mm or 0.0)

        lines = self.line_ids.sorted(lambda l: l.depth_mm)
        if not lines:
            return 0.0

        # Clamp below min / above max
        if depth <= lines[0].depth_mm:
            return float(lines[0].volume_liters)
        if depth >= lines[-1].depth_mm:
            return float(lines[-1].volume_liters)

        # Linear interpolation between the two bounding points
        prev_line = lines[0]
        for line in lines[1:]:
            if depth <= line.depth_mm:
                d1, v1 = prev_line.depth_mm, prev_line.volume_liters
                d2, v2 = line.depth_mm, line.volume_liters
                if d2 == d1:
                    return float(v2)
                ratio = (depth - d1) / (d2 - d1)
                return float(v1 + ratio * (v2 - v1))
            prev_line = line

        return float(lines[-1].volume_liters)


class FuelCalibrationLine(models.Model):
    _name = "fuel.calibration.line"
    _description = "Fuel Calibration Point"
    _order = "profile_id, depth_mm"

    profile_id = fields.Many2one("fuel.calibration.profile", required=True, ondelete="cascade")
    depth_mm = fields.Float(required=True, help="Measured depth in mm.")
    volume_liters = fields.Float(required=True, help="Volume in liters at this depth.")

    @api.constrains("profile_id", "depth_mm", "volume_liters")
    def _check_depth_volume(self):
        for rec in self:
            # Non-negative checks
            if (rec.depth_mm or 0.0) < 0 or (rec.volume_liters or 0.0) < 0:
                raise ValidationError("Depth and volume must be non-negative.")

            # Uniqueness: depth must be unique per profile (Odoo 19-safe)
            if rec.profile_id and rec.depth_mm is not False:
                dup_count = self.search_count(
                    [
                        ("id", "!=", rec.id),
                        ("profile_id", "=", rec.profile_id.id),
                        ("depth_mm", "=", rec.depth_mm),
                    ]
                )
                if dup_count:
                    raise ValidationError("Depth must be unique per profile.")