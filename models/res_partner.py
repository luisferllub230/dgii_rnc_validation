import logging
import requests
import unicodedata

from bs4 import BeautifulSoup
from odoo import models, api, fields, _

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

        if res.get('tag', False) or (not res.get('rnc', False) or not res.get('name', False)):
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
        url = "https://dgii.gov.do/app/WebApps/ConsultasWeb2/ConsultasWeb/consultas/rnc.aspx"        
        error_msg = "Algo inesperado acaba de suceder en la validación del Número de Comprobante Fiscal. Por favor intentarlo más tardes."
        
        session = requests.Session()
        headers = { "User-Agent": "Mozilla/5.0"}
        response = session.get(url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")

        viewstate = soup.find("input", {"id": "__VIEWSTATE"}).get("value")
        eventvalidation = soup.find("input", {"id": "__EVENTVALIDATION"}).get("value")
        viewstategenerator = soup.find("input", {"id": "__VIEWSTATEGENERATOR"}).get("value")

        if not viewstate or not eventvalidation or not viewstategenerator:
            return {"error": error_msg}

        data = {
            "__EVENTTARGET": "ctl00$cphMain$btnBuscarPorRNC",
            "__EVENTARGUMENT": "",
            "__LASTFOCUS": "",
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": viewstategenerator,
            "__EVENTVALIDATION": eventvalidation,
            "ctl00$cphMain$txtRNCCedula": rnc.replace("-", ""),
            "ctl00$cphMain$hidActiveTab": "",
        }

        post_response = session.post(url, data=data, headers=headers)
        post_soup = BeautifulSoup(post_response.text, "html5lib")
        table = post_soup.find("table", {"id": "cphMain_dvDatosContribuyentes"})

        if not table:
            return {"error": error_msg}

        rows = table.find_all("tr")
        rnc_vals = []
        for row in rows:
            tds = row.find_all("td")
            for td in tds:
                rnc_vals.append(unicodedata.normalize('NFKC', td.text.strip()))

        if len(rnc_vals) < 16:
            return {"error": error_msg}
        
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