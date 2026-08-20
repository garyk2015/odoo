from odoo import models, fields, api # type: ignore

class ResellerPriceChecker(models.TransientModel):
    _name = 'reseller.price.checker'
    _description = 'Reseller Quick Price Check'
    _rec_name = 'display_name'

    display_name = fields.Char(
        string='Name', 
        compute='_compute_display_name'
    )

    @api.depends('partner_id', 'product_id')
    def _compute_display_name(self):
        for rec in self:
            if rec.partner_id and rec.product_id:
                rec.display_name = f"{rec.partner_id.name} | {rec.product_id.default_code or rec.product_id.name}"
            elif rec.partner_id:
                rec.display_name = f"Price Lookup - {rec.partner_id.name}"
            else:
                rec.display_name = "Quick Price Lookup"
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
    cost_price = fields.Monetary(
        string='Vendor Cost Price',
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
    margin = fields.Monetary(
        string='Gross Profit Margin',
        currency_field='currency_id',
        compute='_compute_pricing',
        readonly=True
    )
    margin_percent = fields.Float(
        string='Margin %',
        compute='_compute_pricing',
        readonly=True
    )

    # Stock Availability Fields
    qty_available = fields.Float(
        string='Quantity On Hand',
        related='product_id.qty_available',
        readonly=True
    )
    virtual_available = fields.Float(
        string='Forecasted Qty',
        related='product_id.virtual_available',
        readonly=True
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        related='product_id.uom_id',
        readonly=True
    )

    @api.depends('partner_id')
    def _compute_pricelist(self):
        for rec in self:
            if rec.partner_id:
                rec.pricelist_id = rec.partner_id.property_product_pricelist
            else:
                rec.pricelist_id = False

    @api.depends('partner_id', 'pricelist_id', 'product_id')
    def _compute_pricing(self):
        for rec in self:
            if rec.product_id:
                # 1. Fetch Vendor Cost Price (checks Mitel supplierinfo, falls back to standard cost)
                supplier = rec.product_id.seller_ids.filtered(
                    lambda s: 'mitel' in (s.partner_id.name or '').lower() and (not s.currency_id or s.currency_id == rec.currency_id)
                ) or rec.product_id.seller_ids[:1]

                rec.cost_price = supplier[0].price if supplier else rec.product_id.standard_price

                # 2. Reseller Net Price calculation
                if rec.pricelist_id:
                    net_price = rec.pricelist_id._get_product_price(
                        rec.product_id, 
                        1.0, 
                        partner=rec.partner_id
                    )
                else:
                    net_price = rec.product_id.lst_price

                rec.reseller_price = net_price

                # 3. Resolve Public List Price
                # Check for a base Public pricelist first; fallback to lst_price
                public_pl = rec.env['product.pricelist'].search([('name', 'ilike', 'Public')], limit=1)
                if public_pl:
                    base_list = public_pl._get_product_price(rec.product_id, 1.0)
                else:
                    base_list = rec.product_id.lst_price or rec.product_id.list_price

                # If list price is lower than reseller price or still £1 default, align to base calculation
                rec.list_price = base_list if base_list > 1.0 else net_price

                # 4. Effective Discount calculation (Float 0.0 - 1.0 for widget="percentage")
                if rec.list_price and rec.list_price > rec.reseller_price:
                    rec.effective_discount = (rec.list_price - rec.reseller_price) / rec.list_price
                else:
                    rec.effective_discount = 0.0

                # 5. Margin Calculations
                rec.margin = rec.reseller_price - rec.cost_price
                if rec.reseller_price > 0:
                    rec.margin_percent = rec.margin / rec.reseller_price
                else:
                    rec.margin_percent = 0.0
            else:
                rec.list_price = 0.0
                rec.cost_price = 0.0
                rec.reseller_price = 0.0
                rec.effective_discount = 0.0
                rec.margin = 0.0
                rec.margin_percent = 0.0

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