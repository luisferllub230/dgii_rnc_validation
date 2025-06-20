import ssl
import logging
import mechanize
import unicodedata

from bs4 import BeautifulSoup
from urllib import parse as urlparse

from odoo import models, api, fields, _
from odoo.exceptions import ValidationError

logger = logging.getLogger()

TIMEOUT = 10
VAT_STATE = [
    ('ACTIVO', _('ACTIVO')), 
    ('SUSPENDIDO', _('SUSPENDIDO')), 
    ('DADO DE BAJA', _('DADO DE BAJA')), 
    ('CESE TEMPORAL', _('CESE TEMPORAL')), 
    ('ANULADO', _('ANULADO')),  
    ('RECHAZADO', _('RECHAZADO')),  
    ('DESCONOCIDO', _('DESCONOCIDO'))
]

COLOR_CLASS = {'green': 'bg-success', 'yellow': 'bg-warning', 'red': 'bg-danger', 'DESCONOCIDO': ''}

MESSAGE = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {
        'type': 'warning',
        'title': _('Warning'),
        'message': '',
        'sticky': True,
    }
}

class ResPartner(models.Model):
    _inherit = 'res.partner'

    vat_state = fields.Selection(string='vat state', selection=VAT_STATE)
    is_vat_validate = fields.Boolean()

    @api.model
    def create(self, vals_list):
        res = super(ResPartner, self).create(vals_list)
        res.action_validate_vat()
        return res

    @api.onchange('vat')
    def action_validate_vat(self):
        res = {}

        if not self.vat:
            self.is_vat_validate = False
            return self.build_message('There are not RNC')
        
        vat = self.vat if self.vat else ''
        res = self._get_web_scrapt_data(vat)

        if res.get('tag', False):
            self.write({
                'vat_state': 'DESCONOCIDO',
                'is_vat_validate': False,
            })
            return res        
        
        self.write({
            'vat': res.get('rnc'),
            'name': res.get('name'),
            'vat_state': res.get('state', 'DESCONOCIDO'),
            'is_vat_validate': True,
        })

        return res
    
    def _get_web_scrapt_data(self, rnc):
        res = {}
        error_msg = 'Algo inesperado acaba de suceder en la validación del Número de Comprobante Fiscal. Por favor intentarlo más tardes.'
        url = "https://dgii.gov.do/app/WebApps/ConsultasWeb/"
        web_resource = "consultas/rnc.aspx"
        req_headers =  {"User-agent": "Mozilla/5.0"}
        req_rnc_input = 'ctl00$cphMain$txtRNCCedula'

        url = urlparse.urljoin(url, web_resource)
        data = ""
        # mechanize._sockettimeout._GLOBAL_DEFAULT_TIMEOUT = TIMEOUT
        mechanize_br = mechanize.Browser()
        mechanize_br.set_handle_robots(False)
        mechanize_br.set_handle_equiv(False)
        # Ignore SSL certificate verification errors
        mechanize_br.set_ca_data(context=ssl._create_unverified_context())
        mechanize_br.addheaders = list(req_headers.items())

        try:
            mechanize_br.open(url, timeout=TIMEOUT)
            mechanize_br.select_form(nr=0)
            mechanize_br.form[req_rnc_input] = rnc.replace('-', '')
            data = mechanize_br.submit()
            data = data.get_data()
            soup = BeautifulSoup(data, "html5lib")
            table = soup.find_all("table", {"id" : "ctl00_cphMain_dvDatosContribuyentes"})
            tds = table[0].findChildren('td')
            rnc_vals = [unicodedata.normalize('NFKC', td.text.strip()) for td in tds]
        except (mechanize.HTTPError, mechanize.URLError, Exception) as error:
            logger.error(f"error mechanize: {error}")
            return self.build_message(error_msg)
            
        if not rnc_vals:
            return self.build_message(error_msg)

        res['rnc'] = rnc_vals[1]
        res['name'] = rnc_vals[3]
        res['comercial_name'] = rnc_vals[5]
        res['categorie'] = rnc_vals[7]
        res['payment_regime'] = rnc_vals[9]
        res['state'] = rnc_vals[11]
        res['econimic_activity'] = rnc_vals[13]
        res['local_administraion'] = rnc_vals[15]
        return res 
    
    def build_message(self, message):
        MESSAGE['params']['message'] = _(message)
        return MESSAGE