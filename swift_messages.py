"""
swift_messages.py
Utilities to build basic SWIFT-like MT and ISO20022 (pain.001) messages
This file provides safe, local-only generation and conversion functions.
It is NOT a certified SWIFT adapter; integrate a real gateway separately.
"""

from decimal import Decimal, ROUND_HALF_UP
import datetime
import xml.etree.ElementTree as ET
from typing import Dict, Optional
import uuid
import html

def format_amount(amount: Decimal, currency: str) -> str:
    """Return amount in SWIFT numeric format (no thousands, decimal separator '.')"""
    return format(amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'f')

def generate_mt103(payment: Dict) -> str:
    """
    Generate a simplified MT103-like text message from payment dict.
    Fields expected in payment dict:
      - ordering_account
      - ordering_name
      - beneficiary_account
      - beneficiary_name
      - amount (Decimal)
      - currency
      - value_date (YYYY-MM-DD) optional
      - remittance_info optional
      - reference optional
    This is a plain-text representation for human and offline systems.
    """
    amount = Decimal(payment['amount'])
    currency = payment.get('currency', 'USD')
    value_date = payment.get('value_date', datetime.date.today().isoformat())
    ref = payment.get('reference', str(uuid.uuid4()).upper()[:12])
    remittance = payment.get('remittance_info', '')

    lines = []
    lines.append("{1:F01SWIFTSIMULATORXXXX0000000000}")  # header (simulated)
    lines.append("{2:O1031200SWIFTSIMULATORXXXX0000000000}")
    lines.append("{4:")
    lines.append(":20:" + ref)  # Transaction Reference Number
    lines.append(":23B:CRED")
    # Value date + currency + amount (YYMMDD)
    try:
        vd = datetime.date.fromisoformat(value_date).strftime("%y%m%d")
    except Exception:
        vd = datetime.date.today().strftime("%y%m%d")
    lines.append(f":32A:{vd}{currency}{format_amount(amount, currency)}")
    lines.append(":50K:" + payment.get('ordering_name', '') + " /" + payment.get('ordering_account', ''))
    lines.append(":59:" + payment.get('beneficiary_name', '') + " /" + payment.get('beneficiary_account', ''))
    if remittance:
        rem = remittance.replace("\n", " ")
        lines.append(":70:" + rem)
    lines.append(":71A:SHA")  # charges
    lines.append("-}")  # end block
    return "\n".join(lines)

def generate_pain001(payment: Dict) -> str:
    """
    Generate a minimal ISO 20022 pain.001 XML (credit transfer) for a single transaction.
    This is a simplified example suitable for internal use / conversion only.
    """
    NS = {
        '': 'urn:iso:std:iso:20022:tech:xsd:pain.001.001.03'
    }
    # Root
    CstmrCdtTrfInitn = ET.Element('CstmrCdtTrfInitn', xmlns=NS[''])
    # Group Header
    GrpHdr = ET.SubElement(CstmrCdtTrfInitn, 'GrpHdr')
    ET.SubElement(GrpHdr, 'MsgId').text = payment.get('reference', str(uuid.uuid4()))
    ET.SubElement(GrpHdr, 'CreDtTm').text = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    ET.SubElement(GrpHdr, 'NbOfTxs').text = "1"
    ET.SubElement(GrpHdr, 'CtrlSum').text = format_amount(Decimal(payment['amount']), payment.get('currency', 'USD'))

    # Initiating Party (Ordering)
    InitgPty = ET.SubElement(CstmrCdtTrfInitn, 'PmtInf')
    ET.SubElement(InitgPty, 'PmtInfId').text = "PMT-" + datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    ET.SubElement(InitgPty, 'PmtMtd').text = "TRF"
    ET.SubElement(InitgPty, 'NbOfTxs').text = "1"
    ET.SubElement(InitgPty, 'CtrlSum').text = format_amount(Decimal(payment['amount']), payment.get('currency', 'USD'))

    # PaymentInformation (single transaction)
    CdtTrfTxInf = ET.SubElement(InitgPty, 'CdtTrfTxInf')
    PmtId = ET.SubElement(CdtTrfTxInf, 'PmtId')
    ET.SubElement(PmtId, 'EndToEndId').text = payment.get('reference', str(uuid.uuid4()))

    Amt = ET.SubElement(CdtTrfTxInf, 'Amt')
    InstdAmt = ET.SubElement(Amt, 'InstdAmt', Ccy=payment.get('currency', 'USD'))
    InstdAmt.text = format_amount(Decimal(payment['amount']), payment.get('currency', 'USD'))

    # Creditor Agent (beneficiary bank) - optional free text
    if payment.get('beneficiary_bic'):
        CdtrAgt = ET.SubElement(CdtTrfTxInf, 'CdtrAgt')
        FinInstnId = ET.SubElement(CdtrAgt, 'FinInstnId')
        ET.SubElement(FinInstnId, 'BIC').text = payment.get('beneficiary_bic')

    # Creditor (beneficiary)
    Cdtr = ET.SubElement(CdtTrfTxInf, 'Cdtr')
    ET.SubElement(Cdtr, 'Nm').text = payment.get('beneficiary_name', '')
    CdtrAcct = ET.SubElement(CdtTrfTxInf, 'CdtrAcct')
    Id = ET.SubElement(CdtrAcct, 'Id')
    ET.SubElement(Id, 'IBAN').text = payment.get('beneficiary_account', '')

    # Debtor
    Dbtr = ET.SubElement(CdtTrfTxInf, 'Dbtr')
    ET.SubElement(Dbtr, 'Nm').text = payment.get('ordering_name', '')
    DbtrAcct = ET.SubElement(CdtTrfTxInf, 'DbtrAcct')
    DbtrId = ET.SubElement(DbtrAcct, 'Id')
    ET.SubElement(DbtrId, 'IBAN').text = payment.get('ordering_account', '')

    # Remittance Info
    if payment.get('remittance_info'):
        RmtInf = ET.SubElement(CdtTrfTxInf, 'RmtInf')
        ET.SubElement(RmtInf, 'Ustrd').text = payment.get('remittance_info')

    # Pretty print XML
    xml_str = ET.tostring(CstmrCdtTrfInitn, encoding='utf-8')
    # Minimal pretty printing
    import xml.dom.minidom
    dom = xml.dom.minidom.parseString(xml_str)
    pretty = dom.toprettyxml(indent="  ", encoding='utf-8').decode('utf-8')
    return pretty

def payment_from_transaction(account_number: str,
                             account_name: str,
                             beneficiary_account: str,
                             beneficiary_name: str,
                             amount: Decimal,
                             currency: str = "USD",
                             value_date: Optional[str] = None,
                             remittance_info: Optional[str] = None,
                             beneficiary_bic: Optional[str] = None,
                             reference: Optional[str] = None) -> Dict:
    """Helper to build a payment dict from form input or transaction"""
    return {
        'ordering_account': account_number,
        'ordering_name': account_name,
        'beneficiary_account': beneficiary_account,
        'beneficiary_name': beneficiary_name,
        'amount': amount,
        'currency': currency,
        'value_date': value_date or datetime.date.today().isoformat(),
        'remittance_info': remittance_info or '',
        'beneficiary_bic': beneficiary_bic,
        'reference': reference or str(uuid.uuid4()).upper()[:12]
    }