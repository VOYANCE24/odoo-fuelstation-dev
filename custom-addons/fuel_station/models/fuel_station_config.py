from odoo import fields, models, api


class FuelStationConfig(models.Model):
    _name = "fuel.station.config"
    _description = "Fuel Station Configuration"

    name = fields.Char(default="Fuel Station Settings", readonly=True)

    cash_journal_id = fields.Many2one(
        "account.journal",
        string="Cash Journal (Credit Payments)",
        domain=[("type", "=", "cash")],
        help="Journal used to record cash payments received from credit customers.",
    )
    cheque_journal_id = fields.Many2one(
        "account.journal",
        string="Cheque Journal (Credit Payments)",
        domain=[("type", "=", "bank")],
        help="Journal used to record cheque payments received from credit customers.",
    )

    # Bank reconciliation accounts
    safe_journal_id = fields.Many2one(
        "account.journal",
        string="Safe Deposit Journal",
        domain=[("type", "in", ["cash", "general"])],
        help="Miscellaneous/general journal used to post the shift-end safe deposit entry.",
    )
    safe_account_id = fields.Many2one(
        "account.account",
        string="Safe / Vault Account",
        help="Asset account representing physical cash held in the station safe.",
    )
    cash_clearing_account_id = fields.Many2one(
        "account.account",
        string="Cash Clearing Account",
        help="Clearing account debited by cash pump sales and credited when cash is deposited in safe.",
    )

    @api.model
    def get_config(self):
        config = self.sudo().search([], limit=1)
        if not config:
            config = self.sudo().create({})
        return config
