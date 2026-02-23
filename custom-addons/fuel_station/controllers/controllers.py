# from odoo import http


# class FuelStation(http.Controller):
#     @http.route('/fuel_station/fuel_station', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/fuel_station/fuel_station/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('fuel_station.listing', {
#             'root': '/fuel_station/fuel_station',
#             'objects': http.request.env['fuel_station.fuel_station'].search([]),
#         })

#     @http.route('/fuel_station/fuel_station/objects/<model("fuel_station.fuel_station"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('fuel_station.object', {
#             'object': obj
#         })

