# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.


from odoo import api, fields, models, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError, AccessError
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from odoo.tools.float_utils import float_is_zero, float_compare
from odoo.tools.misc import formatLang

class SaleOrder(models.Model):
    
    _inherit = "sale.order"
    
    @api.model
    def default_get(self, fields):
        res = super(SaleOrder, self).default_get(fields)
        if self.env.user.company_id.price_calculation == 'qty':
            res['hide_net_price'] = True
        return res

    dispatch_type =  fields.Selection([
        ('deliver','Deliver'),
        ('collect','Collect'),
        ('Courier','courier')],string='Dispatch Type')
    hide_net_price = fields.Boolean(string='Hide net price')


    def _calculate_dimesion_m2(self):
        res=0.0
        total=0.0
        for self_obj in self:
            for line in self.order_line:
                if line.company_id.price_calculation == 'dimension':
                    total += line.price_subtotal
                    res = total
        return res

    @api.depends('order_line.tax_id', 'order_line.price_unit', 'amount_total', 'amount_untaxed')
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

class  sale_order_line(models.Model):    
    _inherit = "sale.order.line"

    @api.depends('width','height','product_uom_qty', 'discount', 'price_unit', 'tax_id')
    def _compute_amount(self):
        """
        Compute the amounts of the SO line.
        """
        for line in self:
            if line.company_id.price_calculation == 'dimension':
                tax_results = self.env['account.tax']._compute_taxes([line._convert_to_tax_base_line_dict()])
                totals = list(tax_results['totals'].values())[0]
                amount_untaxed = totals['amount_untaxed'] * line.m2
                amount_tax = totals['amount_tax']

                line.update({
                    'price_subtotal': amount_untaxed,
                    'price_tax': amount_tax,
                    'price_total': amount_untaxed + amount_tax,
                })
            else:
                tax_results = self.env['account.tax']._compute_taxes([line._convert_to_tax_base_line_dict()])
                totals = list(tax_results['totals'].values())[0]
                amount_untaxed = totals['amount_untaxed']
                amount_tax = totals['amount_tax']

                line.update({
                    'price_subtotal': amount_untaxed,
                    'price_tax': amount_tax,
                    'price_total': amount_untaxed + amount_tax,
                })

            if self.env.context.get('import_file', False) and not self.env.user.user_has_groups('account.group_account_manager'):
                line.tax_id.invalidate_recordset(['invoice_repartition_line_ids'])

    
    
    @api.depends('height','width')
    def _get_m2(self):
        for record in self:
            if record.width == 0.0 or record.height == 0.0:
                m2 = 1.00
            else:
                m2 = record.width * record.height

            record.update({
                'm2' : m2
            })
    
    @api.depends('height','width','price_unit','product_uom_qty')
    def _get_net_price(self):
        for record in self:
            if record.width == 0.00 or record.height == 0.00:
                net_price = record.price_unit * record.product_uom_qty
            else:
                net_price = (record.width * record.height) * record.price_unit * record.product_uom_qty

            record.update({
                'net_price' : net_price
            })

    width = fields.Float('Width (Mt.)', required='True',default=0.0 )
    height = fields.Float('Height (Mt.)', required='True', default=0.0)
    m2 = fields.Float(compute='_get_m2',string='(Mt.)2', store=True)
    net_price = fields.Float(compute='_get_net_price', string="Net Price", store=True)
    hide_net_price = fields.Boolean(string='Hide net price', 
        related='order_id.hide_net_price', store=True)

    def _prepare_invoice_line(self, **optional_values):
        
        res = super(sale_order_line, self)._prepare_invoice_line(**optional_values)
        res.update({
            'width':self.width,
            'height':self.height,
            'm2':self.m2,
        })
        return res

    def _prepare_procurement_values(self, group_id=False):
        res = super(sale_order_line, self)._prepare_procurement_values(group_id=group_id)
        res.update({
            'width':self.width,
            'height':self.height,
        })
        return res

