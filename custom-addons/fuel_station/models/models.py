# from odoo import models, fields, api


# class fuel_station(models.Model):
#     _name = 'fuel_station.fuel_station'
#     _description = 'fuel_station.fuel_station'

#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
#
#     @api.depends('value')
#     def _value_pc(self):
#         for record in self:
#             record.value2 = float(record.value) / 100

