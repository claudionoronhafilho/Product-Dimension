# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.


from odoo import api, fields, models, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError, AccessError
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from odoo.tools.float_utils import float_is_zero, float_compare
from odoo.tools.misc import formatLang

class purchase_order(models.Model):
    _inherit = "purchase.order"
    
    @api.model
    def default_get(self, fields):
        res = super(purchase_order, self).default_get(fields)
        if self.env.user.company_id.price_calculation == 'qty':
            res['hide_net_price'] = True
        return res

    @api.depends('order_line.price_total',
        'order_line.height',
        'order_line.width',
        'order_line.taxes_id')
    def _amount_all(self):
        return super(purchase_order, self)._amount_all()

    hide_net_price = fields.Boolean(string='Hide net price')
    dispatch_type =  fields.Selection([
        ('deliver','Deliver'),
        ('collect','Collect'),
        ('Courier','courier')],string='Dispatch Type')


    def _calculate_dimesion_m2(self):
        res=0.0
        total=0.0
        for self_obj in self:
            for line in self.order_line:
                if line.company_id.price_calculation == 'dimension':
                    total += line.net_price_pur
                    line.price_subtotal = line.net_price_pur
                    res = total
        return res

    @api.depends('order_line.taxes_id', 'order_line.price_subtotal', 'amount_total', 'amount_untaxed')
    def _compute_tax_totals(self):
        for order in self:
            order_lines = order.order_line.filtered(lambda x: not x.display_type)
            tax_totals = self.env['account.tax']._prepare_tax_totals(
                [x._convert_to_tax_base_line_dict() for x in order_lines],
                order.currency_id,
            )
            res = self._calculate_dimesion_m2()
            if  self.env.user.company_id.price_calculation == 'dimension':
                if tax_totals.get('amount_untaxed'):
                    tax_totals['amount_untaxed'] = res
                if tax_totals.get('formatted_amount_total'):
                    format_tax_total = tax_totals['amount_untaxed'] + order.amount_tax
                    tax_totals['formatted_amount_total'] = formatLang(self.env, format_tax_total, currency_obj=self.currency_id)
                if tax_totals.get('formatted_amount_untaxed'):
                    format_total = tax_totals['amount_untaxed']
                    tax_totals['formatted_amount_untaxed'] = formatLang(self.env, format_total, currency_obj=self.currency_id)

                groups_by_subtotal = tax_totals.get('groups_by_subtotal', {})
                if bool(groups_by_subtotal):
                    _untax_amount = groups_by_subtotal.get('Untaxed Amount', [])
                    if bool(_untax_amount):
                        for _tax in range(len(_untax_amount)):
                            if _untax_amount[_tax].get('tax_group_base_amount'):
                                tax_totals.get('groups_by_subtotal', {}).get('Untaxed Amount', [])[_tax].update({
                                    'tax_group_base_amount' : res
                                })
                            if _untax_amount[_tax].get('formatted_tax_group_base_amount'):
                                format_total = res
                                tax_totals.get('groups_by_subtotal', {}).get('Untaxed Amount', [])[_tax].update({
                                    'formatted_tax_group_base_amount' : formatLang(self.env, format_total, currency_obj=self.currency_id)
                                })

                subtotals = tax_totals.get('subtotals', {})
                if bool(subtotals):
                    for _tax in range(len(subtotals)):
                        if subtotals[_tax].get('amount'):
                            tax_totals.get('subtotals', {})[_tax].update({
                                'amount' :res
                            })
                        if subtotals[_tax].get('formatted_amount'):
                            format_total = subtotals[_tax]['amount']
                            tax_totals.get('subtotals', {})[_tax].update({
                                'formatted_amount' : formatLang(self.env, format_total, currency_obj=self.currency_id)
                            })
            
                
                
            order.tax_totals = tax_totals


class purchase_order_line(models.Model):
    _inherit = "purchase.order.line"


    @api.depends('product_qty', 'price_unit', 'taxes_id', 'width', 'height')
    def _compute_amount(self):
        for line in self:
            vals = line._convert_to_tax_base_line_dict()
            if line.order_id.company_id.price_calculation == 'dimension':
                quantity = vals['quantity'] * line.square_meter
            else:
                quantity = vals['quantity']

            taxes = line.taxes_id.compute_all(
                vals['price_unit'],
                vals['currency'],
                quantity,
                vals['product'],
                vals['partner'])
            tax_results = self.env['account.tax']._compute_taxes([line._convert_to_tax_base_line_dict()])
            totals = list(tax_results['totals'].values())[0]
            if line.company_id.price_calculation == 'dimension':
                amount_untaxed = totals['amount_untaxed'] * line.square_meter
            else:
                amount_untaxed = totals['amount_untaxed']
            amount_tax = totals['amount_tax']
            line.update({
                'price_subtotal': amount_untaxed,
                'price_tax': amount_tax,
                'price_total': amount_untaxed + amount_tax,
            })
            
    def _create_stock_moves(self, picking):
        values = []
        for line in self.filtered(lambda l: not l.display_type):
            for val in line._prepare_stock_moves(picking):
                val.update({
                    'width':line.width,
                    'height':line.height,
                })
                values.append(val)
        return self.env['stock.move'].create(values)
    
    @api.depends('height','width')
    def _get_squaremeter(self):
        for record in self:
            if record.width == 0.00 or record.height == 0.00:
                square_meter = 1.00
            else:
                square_meter = record.width * record.height
            record.update({
                'square_meter' : square_meter
            })

    @api.depends('height','width', 'product_qty', 'price_unit')
    def _compute_net_price(self):
        for record in self:
            if record.width == 0.00 or record.height == 0.00:
                net_price = record.price_unit * record.product_qty
            else:
                net_price = (record.width * record.height) * record.price_unit * record.product_qty

            record.update({
                'net_price_pur' : net_price
            })

    width=fields.Float('Width (Mt.)', required='True', default=0.0)
    height= fields.Float('Height (Mt.)', required='True',default=0.0)
    square_meter= fields.Float(compute='_get_squaremeter',string='(Mt.)2', store=True)
    net_price_pur = fields.Float(string='Net Price',compute='_compute_net_price', store=True)
    hide_net_price = fields.Boolean(string='Hide net price', 
        related='order_id.hide_net_price', store=True)


    def _prepare_account_move_line(self,move=False):
        res = super(purchase_order_line,self)._prepare_account_move_line(move)
        res.update({
            'width':self.width, 
            'height':self.height,
            'm2':self.square_meter,
            'hide_net_price' : self.hide_net_price, 
        })
        return res
