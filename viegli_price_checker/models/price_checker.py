from odoo import models, fields, api # type: ignore

class ResellerPriceChecker(models.TransientModel):
    _name = 'reseller.price.checker'
    _description = 'Reseller Quick Price Check'

    partner_id = fields.Many2one(
        'res.partner', 
        string='Reseller / Customer', 
        required=True
    )
    pricelist_id = fields.Many2one(
        'product.pricelist', 
        string='Assigned Pricelist / Band', 
        compute='_compute_pricelist', 
        store=True, 
        readonly=False
    )
    
    product_id = fields.Many2one(
        'product.product', 
        string='Product / SKU', 
        required=True
    )
    product_tmpl_id = fields.Many2one(
        'product.template', 
        string='Product Template', 
        related='product_id.product_tmpl_id'
    )
    categ_id = fields.Many2one(
        'product.category', 
        string='Product Category', 
        related='product_tmpl_id.categ_id', 
        readonly=True
    )

    currency_id = fields.Many2one(
        'res.currency', 
        string='Currency', 
        related='pricelist_id.currency_id'
    )

    # Calculated Output Fields
    list_price = fields.Monetary(
        string='Public List Price', 
        currency_field='currency_id',
        compute='_compute_pricing',
        readonly=True
    )
    reseller_price = fields.Monetary(
        string='Reseller Net Price', 
        currency_field='currency_id',
        compute='_compute_pricing', 
        readonly=True
    )
    effective_discount = fields.Float(
        string='Calculated Discount %', 
        compute='_compute_pricing', 
        readonly=True
    )

    @api.depends('partner_id')
    def _compute_pricelist(self):
        for rec in self:
            if rec.partner_id:
                # Automatically extracts the partner's assigned pricelist/discount band
                rec.pricelist_id = rec.partner_id.property_product_pricelist
            else:
                rec.pricelist_id = False

    @api.depends('partner_id', 'pricelist_id', 'product_id')
    def _compute_pricing(self):
        for rec in self:
            if rec.pricelist_id and rec.product_id:
                # Odoo's native engine resolves all category discounts and specific rules
                net_price = rec.pricelist_id._get_product_price(
                    rec.product_id, 
                    1.0, 
                    partner=rec.partner_id
                )
                rec.reseller_price = net_price
                rec.list_price = rec.product_id.list_price
                
                if rec.list_price > 0:
                    rec.effective_discount = round(
                        ((rec.list_price - net_price) / rec.list_price) * 100, 2
                    )
                else:
                    rec.effective_discount = 0.0
            else:
                rec.list_price = 0.0
                rec.reseller_price = 0.0
                rec.effective_discount = 0.0

    def action_reset(self):
        """Quick button to clear fields for the next telephone enquiry"""
        self.product_id = False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'reseller.price.checker',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }