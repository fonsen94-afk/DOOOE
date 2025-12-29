"""
Swift Alliance — Self-contained Streamlit app (single-file)

Drop this file into your repository root and run:
    streamlit run swift_alliance_streamlit.py

This single-file app contains:
 - A simple banking backend (in-memory + JSON persistence)
 - SWIFT message generators (MT103-like text and ISO20022 pain.001 XML)
 - ISO20022 XSD validation (uses xmlschema if installed)
 - Streamlit UI including schema/logo persistence and st.secrets support for SMTP/SFTP

Install requirements (cloud-focused):
    pip install streamlit xmlschema lxml paramiko

Notes:
 - Do NOT commit sensitive credentials. Use Streamlit Cloud Secrets for SMTP/SFTP.
 - The app will create ./assets/ and ./assets/schemas/ on first run and will drop a minimal
   pain.001 minimal XSD into ./assets/schemas/pain.001.minimal.xsd so validation can run.
 - This single-file approach avoids package import issues on Streamlit Cloud.
"""

import os
import json
import datetime
import random
import string
import hashlib
import uuid
import tempfile
import shutil
import logging
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

# Optional external libs
try:
    import xmlschema
    HAS_XMLSCHEMA = True
except Exception:
    xmlschema = None
    HAS_XMLSCHEMA = False

try:
    import paramiko
    HAS_PARAMIKO = True
except Exception:
    paramiko = None
    HAS_PARAMIKO = False

# Streamlit
import streamlit as st

# Basic logging (writes to banking_system.log)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('banking_system.log'), logging.StreamHandler()]
)
logger = logging.getLogger("swift_alliance")

# --- Basic models & banking backend ------------------------------------------------

class TransactionType:
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER = "TRANSFER"
    LOAN_DISBURSEMENT = "LOAN_DISBURSEMENT"
    LOAN_REPAYMENT = "LOAN_REPAYMENT"
    INTEREST_CREDIT = "INTEREST_CREDIT"

class AccountType:
    SAVINGS = "SAVINGS"
    CURRENT = "CURRENT"
    FIXED_DEPOSIT = "FIXED_DEPOSIT"
    LOAN = "LOAN"
    CORPORATE = "CORPORATE"

class Currency:
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    CNY = "CNY"

@dataclass
class Customer:
    customer_id: str
    first_name: str
    last_name: str
    email: str
    phone: str
    address: str
    date_of_birth: str
    id_number: str
    id_type: str
    created_date: str
    is_active: bool = True
    kyc_status: str = "PENDING"

@dataclass
class Account:
    account_number: str
    customer_id: str
    account_type: str
    currency: str
    balance: Decimal
    opening_date: str
    interest_rate: Decimal
    minimum_balance: Decimal
    is_active: bool = True
    last_interest_calculation: Optional[str] = None

@dataclass
class Transaction:
    transaction_id: str
    account_number: str
    transaction_type: str
    amount: Decimal
    currency: str
    timestamp: str
    description: str
    reference_number: str
    related_account: Optional[str] = None
    status: str = "COMPLETED"

@dataclass
class Loan:
    loan_id: str
    customer_id: str
    principal_amount: Decimal
    interest_rate: Decimal
    term_months: int
    start_date: str
    monthly_payment: Decimal
    remaining_balance: Decimal
    collateral: Optional[str] = None
    status: str = "ACTIVE"


class SecurityManager:
    @staticmethod
    def hash_password(password: str) -> str:
        salt = "banking_system_salt_2024"
        return hashlib.sha256((password + salt).encode()).hexdigest()

    @staticmethod
    def generate_session_token() -> str:
        return ''.join(random.choices(string.ascii_letters + string.digits, k=32))

    @staticmethod
    def generate_account_number() -> str:
        bank_code = "001"
        branch_code = "001"
        account_seq = str(random.randint(100000, 999999))
        check_digit = str(random.randint(0, 9))
        return f"{bank_code}{branch_code}{account_seq}{check_digit}"


class AccountNotFoundError(Exception):
    pass

class InsufficientFundsError(Exception):
    pass

class SwiftAllianceBank:
    def __init__(self, data_file: str = "bank_data.json"):
        self.data_file = data_file
        self.customers: Dict[str, Customer] = {}
        self.accounts: Dict[str, Account] = {}
        self.transactions: Dict[str, List[Transaction]] = {}
        self.loans: Dict[str, Loan] = {}
        self.last_interest_date = datetime.date.today().isoformat()
        self._load_data()

    def _generate_id(self, prefix: str = "CUST") -> str:
        return f"{prefix}{datetime.datetime.now().strftime('%Y%m%d')}{random.randint(1000,9999)}"

    def _load_data(self):
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for c in data.get("customers", []):
                    self.customers[c["customer_id"]] = Customer(**c)
                for a in data.get("accounts", []):
                    a["balance"] = Decimal(a["balance"])
                    a["interest_rate"] = Decimal(a["interest_rate"])
                    a["minimum_balance"] = Decimal(a["minimum_balance"])
                    self.accounts[a["account_number"]] = Account(**a)
                for acc_num, tlist in data.get("transactions", {}).items():
                    self.transactions[acc_num] = []
                    for td in tlist:
                        td["amount"] = Decimal(td["amount"])
                        self.transactions[acc_num].append(Transaction(**td))
                for ld in data.get("loans", []):
                    ld["principal_amount"] = Decimal(ld["principal_amount"])
                    ld["interest_rate"] = Decimal(ld["interest_rate"])
                    ld["monthly_payment"] = Decimal(ld["monthly_payment"])
                    ld["remaining_balance"] = Decimal(ld["remaining_balance"])
                    self.loans[ld["loan_id"]] = Loan(**ld)
                self.last_interest_date = data.get("last_interest_date", self.last_interest_date)
                logger.info("Loaded existing bank data")
            else:
                logger.info("No bank data file found, starting fresh")
        except Exception as e:
            logger.exception("Error loading bank data, starting with empty dataset")

    def _save_data(self):
        try:
            data = {
                "customers": [asdict(c) for c in self.customers.values()],
                "accounts": [],
                "transactions": {},
                "loans": [],
                "last_interest_date": self.last_interest_date
            }
            for a in self.accounts.values():
                d = asdict(a)
                d["balance"] = str(a.balance)
                d["interest_rate"] = str(a.interest_rate)
                d["minimum_balance"] = str(a.minimum_balance)
                data["accounts"].append(d)
            for acc_num, tlist in self.transactions.items():
                data["transactions"][acc_num] = []
                for t in tlist:
                    td = asdict(t)
                    td["amount"] = str(t.amount)
                    data["transactions"][acc_num].append(td)
            for l in self.loans.values():
                ld = asdict(l)
                ld["principal_amount"] = str(l.principal_amount)
                ld["interest_rate"] = str(l.interest_rate)
                ld["monthly_payment"] = str(l.monthly_payment)
                ld["remaining_balance"] = str(l.remaining_balance)
                data["loans"].append(ld)
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.info("Bank data saved")
        except Exception as e:
            logger.exception("Error saving bank data")

    def register_customer(self, info: Dict) -> Customer:
        cid = self._generate_id("CUST")
        customer = Customer(
            customer_id=cid,
            first_name=info["first_name"],
            last_name=info["last_name"],
            email=info["email"],
            phone=info["phone"],
            address=info["address"],
            date_of_birth=info["date_of_birth"],
            id_number=info["id_number"],
            id_type=info["id_type"],
            created_date=datetime.date.today().isoformat()
        )
        self.customers[cid] = customer
        self._save_data()
        logger.info("Registered customer %s", cid)
        return customer

    def create_account(self, customer_id: str, account_type: str, currency: str = Currency.USD, initial_deposit: Decimal = Decimal("0")) -> Account:
        if customer_id not in self.customers:
            raise AccountNotFoundError(f"Customer {customer_id} not found")
        acct_num = SecurityManager.generate_account_number()
        if account_type == AccountType.SAVINGS:
            interest_rate = Decimal("0.02"); minimum_balance = Decimal("50")
        elif account_type == AccountType.CURRENT:
            interest_rate = Decimal("0.01"); minimum_balance = Decimal("1000")
        elif account_type == AccountType.FIXED_DEPOSIT:
            interest_rate = Decimal("0.05"); minimum_balance = Decimal("5000")
        else:
            interest_rate = Decimal("0.015"); minimum_balance = Decimal("100")

        account = Account(
            account_number=acct_num,
            customer_id=customer_id,
            account_type=account_type,
            currency=currency,
            balance=initial_deposit,
            opening_date=datetime.date.today().isoformat(),
            interest_rate=interest_rate,
            minimum_balance=minimum_balance
        )
        self.accounts[acct_num] = account
        self.transactions[acct_num] = []
        if initial_deposit > 0:
            self._record_transaction(acct_num, TransactionType.DEPOSIT, initial_deposit, "Initial deposit")
        self._save_data()
        logger.info("Created account %s for customer %s", acct_num, customer_id)
        return account

    def _record_transaction(self, account_number: str, transaction_type: str, amount: Decimal, description: str, related_account: Optional[str]=None) -> Transaction:
        txn = Transaction(
            transaction_id=self._generate_id("TXN"),
            account_number=account_number,
            transaction_type=transaction_type,
            amount=amount,
            currency=self.accounts[account_number].currency,
            timestamp=datetime.datetime.now().isoformat(),
            description=description,
            reference_number=self._generate_id("REF"),
            related_account=related_account
        )
        if account_number not in self.transactions:
            self.transactions[account_number] = []
        self.transactions[account_number].append(txn)
        return txn

    def deposit(self, account_number: str, amount: Decimal) -> Transaction:
        if account_number not in self.accounts:
            raise AccountNotFoundError(f"Account {account_number} not found")
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        acc = self.accounts[account_number]
        acc.balance += amount
        txn = self._record_transaction(account_number, TransactionType.DEPOSIT, amount, "Cash deposit")
        self._save_data()
        logger.info("Deposit %s to %s", amount, account_number)
        return txn

    def withdraw(self, account_number: str, amount: Decimal) -> Transaction:
        if account_number not in self.accounts:
            raise AccountNotFoundError(f"Account {account_number} not found")
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        acc = self.accounts[account_number]
        if acc.balance - amount < acc.minimum_balance:
            raise InsufficientFundsError(f"Insufficient funds; minimum balance {acc.minimum_balance}")
        acc.balance -= amount
        txn = self._record_transaction(account_number, TransactionType.WITHDRAWAL, amount, "Cash withdrawal")
        self._save_data()
        logger.info("Withdrawal %s from %s", amount, account_number)
        return txn

    def transfer(self, from_account: str, to_account: str, amount: Decimal) -> Tuple[Transaction, Transaction]:
        if from_account not in self.accounts:
            raise AccountNotFoundError(f"Source account {from_account} not found")
        if to_account not in self.accounts:
            raise AccountNotFoundError(f"Destination account {to_account} not found")
        if amount <= 0:
            raise ValueError("Transfer amount must be positive")
        src = self.accounts[from_account]
        if src.balance - amount < src.minimum_balance:
            raise InsufficientFundsError("Insufficient funds for transfer")
        src.balance -= amount
        debit = self._record_transaction(from_account, TransactionType.TRANSFER, amount, f"Transfer to {to_account}", related_account=to_account)
        dest = self.accounts[to_account]
        dest.balance += amount
        credit = self._record_transaction(to_account, TransactionType.TRANSFER, amount, f"Transfer from {from_account}", related_account=from_account)
        self._save_data()
        logger.info("Transfer %s from %s to %s", amount, from_account, to_account)
        return debit, credit

    def get_account_balance(self, account_number: str) -> Decimal:
        if account_number not in self.accounts:
            raise AccountNotFoundError(f"Account {account_number} not found")
        return self.accounts[account_number].balance

    def get_transaction_history(self, account_number: str, start_date: Optional[str]=None, end_date: Optional[str]=None) -> List[Transaction]:
        if account_number not in self.transactions:
            return []
        txs = self.transactions[account_number]
        if start_date or end_date:
            out = []
            for t in txs:
                td = datetime.datetime.fromisoformat(t.timestamp).date()
                if start_date and td < datetime.date.fromisoformat(start_date):
                    continue
                if end_date and td > datetime.date.fromisoformat(end_date):
                    continue
                out.append(t)
            return out
        return txs

    def apply_for_loan(self, customer_id: str, amount: Decimal, term_months: int, interest_rate: Decimal, collateral: Optional[str]=None) -> Loan:
        if customer_id not in self.customers:
            raise AccountNotFoundError(f"Customer {customer_id} not found")
        total_interest = amount * interest_rate * Decimal(term_months) / Decimal('12')
        total_amount = amount + total_interest
        monthly_payment = (total_amount / Decimal(term_months)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        loan = Loan(
            loan_id=self._generate_id("LOAN"),
            customer_id=customer_id,
            principal_amount=amount,
            interest_rate=interest_rate,
            term_months=term_months,
            start_date=datetime.date.today().isoformat(),
            monthly_payment=monthly_payment,
            remaining_balance=total_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
            collateral=collateral
        )
        self.loans[loan.loan_id] = loan
        self._save_data()
        logger.info("Loan %s created for %s", loan.loan_id, customer_id)
        return loan

    def calculate_interest(self):
        today = datetime.date.today().isoformat()
        if today == self.last_interest_date:
            return
        for acc in self.accounts.values():
            if acc.account_type != AccountType.FIXED_DEPOSIT:
                daily_rate = acc.interest_rate / Decimal('365')
                interest = (acc.balance * daily_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                acc.balance += interest
                if interest > Decimal('0.00'):
                    self._record_transaction(acc.account_number, TransactionType.INTEREST_CREDIT, interest, "Daily interest credit")
        self.last_interest_date = today
        self._save_data()
        logger.info("Interest calculated for all eligible accounts")


# --- SWIFT/ISO message generators ---------------------------------------------------

def format_amount(amount: Decimal) -> str:
    return format(amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'f')

def generate_mt103(payment: Dict) -> str:
    amount = Decimal(payment['amount'])
    currency = payment.get('currency', 'USD')
    value_date = payment.get('value_date', datetime.date.today().isoformat())
    ref = payment.get('reference', str(uuid.uuid4()).upper()[:12])
    remittance = payment.get('remittance_info', '')
    lines = [
        "{1:F01SWIFTSIMULATORXXXX0000000000}",
        "{2:O1031200SWIFTSIMULATORXXXX0000000000}",
        "{4:",
        f":20:{ref}",
        ":23B:CRED",
    ]
    try:
        vd = datetime.date.fromisoformat(value_date).strftime("%y%m%d")
    except Exception:
        vd = datetime.date.today().strftime("%y%m%d")
    lines.append(f":32A:{vd}{currency}{format_amount(amount)}")
    lines.append(":50K:" + payment.get('ordering_name', '') + " /" + payment.get('ordering_account', ''))
    lines.append(":59:" + payment.get('beneficiary_name', '') + " /" + payment.get('beneficiary_account', ''))
    if remittance:
        lines.append(":70:" + remittance.replace("\n", " "))
    lines.append(":71A:SHA")
    lines.append("-}")
    return "\n".join(lines)

def generate_pain001(payment: Dict) -> str:
    NS = 'urn:iso:std:iso:20022:tech:xsd:pain.001.001.03'
    CstmrCdtTrfInitn = ET.Element('CstmrCdtTrfInitn', xmlns=NS)
    GrpHdr = ET.SubElement(CstmrCdtTrfInitn, 'GrpHdr')
    ET.SubElement(GrpHdr, 'MsgId').text = payment.get('reference', str(uuid.uuid4()))
    ET.SubElement(GrpHdr, 'CreDtTm').text = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    ET.SubElement(GrpHdr, 'NbOfTxs').text = "1"
    ET.SubElement(GrpHdr, 'CtrlSum').text = format_amount(Decimal(payment['amount']))

    PmtInf = ET.SubElement(CstmrCdtTrfInitn, 'PmtInf')
    ET.SubElement(PmtInf, 'PmtInfId').text = "PMT-" + datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    ET.SubElement(PmtInf, 'PmtMtd').text = "TRF"
    ET.SubElement(PmtInf, 'NbOfTxs').text = "1"
    ET.SubElement(PmtInf, 'CtrlSum').text = format_amount(Decimal(payment['amount']))

    CdtTrfTxInf = ET.SubElement(PmtInf, 'CdtTrfTxInf')
    PmtId = ET.SubElement(CdtTrfTxInf, 'PmtId')
    ET.SubElement(PmtId, 'EndToEndId').text = payment.get('reference', str(uuid.uuid4()))

    Amt = ET.SubElement(CdtTrfTxInf, 'Amt')
    InstdAmt = ET.SubElement(Amt, 'InstdAmt', Ccy=payment.get('currency', 'USD'))
    InstdAmt.text = format_amount(Decimal(payment['amount']))

    if payment.get('beneficiary_bic'):
        CdtrAgt = ET.SubElement(CdtTrfTxInf, 'CdtrAgt')
        FinInstnId = ET.SubElement(CdtrAgt, 'FinInstnId')
        ET.SubElement(FinInstnId, 'BIC').text = payment.get('beneficiary_bic')

    Cdtr = ET.SubElement(CdtTrfTxInf, 'Cdtr')
    ET.SubElement(Cdtr, 'Nm').text = payment.get('beneficiary_name', '')
    CdtrAcct = ET.SubElement(CdtTrfTxInf, 'CdtrAcct')
    Id = ET.SubElement(CdtrAcct, 'Id')
    ET.SubElement(Id, 'IBAN').text = payment.get('beneficiary_account', '')

    Dbtr = ET.SubElement(CdtTrfTxInf, 'Dbtr')
    ET.SubElement(Dbtr, 'Nm').text = payment.get('ordering_name', '')
    DbtrAcct = ET.SubElement(CdtTrfTxInf, 'DbtrAcct')
    DbtrId = ET.SubElement(DbtrAcct, 'Id')
    ET.SubElement(DbtrId, 'IBAN').text = payment.get('ordering_account', '')

    if payment.get('remittance_info'):
        RmtInf = ET.SubElement(CdtTrfTxInf, 'RmtInf')
        ET.SubElement(RmtInf, 'Ustrd').text = payment.get('remittance_info')

    xml_bytes = ET.tostring(CstmrCdtTrfInitn, encoding='utf-8')
    # pretty print with minidom
    import xml.dom.minidom
    dom = xml.dom.minidom.parseString(xml_bytes)
    return dom.toprettyxml(indent="  ")

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
    return {
        "ordering_account": account_number,
        "ordering_name": account_name,
        "beneficiary_account": beneficiary_account,
        "beneficiary_name": beneficiary_name,
        "amount": amount,
        "currency": currency,
        "value_date": value_date or datetime.date.today().isoformat(),
        "remittance_info": remittance_info or "",
        "beneficiary_bic": beneficiary_bic,
        "reference": reference or str(uuid.uuid4()).upper()[:12]
    }

# --- Validation utilities ----------------------------------------------------------

class SchemaNotFoundError(FileNotFoundError):
    pass

_MT103_REQUIRED_TAGS = [":20:", ":32A:", ":50K:", ":59:", ":71A:"]

def validate_mt103_text(mt_text: str) -> Tuple[bool, List[str]]:
    import re
    issues = []
    def _find_tag(text, tag):
        pattern = re.compile(re.escape(tag) + r"(.*?)(?=\n:|$)", re.DOTALL)
        return pattern.search(text)
    for tag in _MT103_REQUIRED_TAGS:
        if not _find_tag(mt_text, tag):
            issues.append(f"Missing required tag {tag}")
    m = _find_tag(mt_text, ":32A:")
    if m:
        content = m.group(1).strip()
        m32 = re.match(r"^(\d{6})([A-Z]{3})(\d+(?:\.\d{1,2})?)$", content)
        if not m32:
            issues.append(f":32A: field has invalid format (expected YYMMDDCCCamount). Found: '{content}'")
    for tag in (":50K:", ":59:"):
        mm = _find_tag(mt_text, tag)
        if mm and not mm.group(1).strip():
            issues.append(f"{tag} tag is present but empty")
    return (len(issues) == 0, issues)

def validate_pain001_generated(xml_string: str, schema_path: str) -> Tuple[bool, Optional[List[str]]]:
    # check well-formedness first
    try:
        ET.fromstring(xml_string)
    except ET.ParseError as e:
        return False, [f"XML not well-formed: {e}"]
    if not HAS_XMLSCHEMA:
        return False, ["xmlschema not installed in this environment; validation unavailable."]
    if not schema_path or not os.path.exists(schema_path):
        raise SchemaNotFoundError(f"Schema file not found: {schema_path}")
    try:
        schema = xmlschema.XMLSchema(schema_path)
    except Exception as e:
        return False, [f"Failed loading schema: {e}"]
    errors = []
    try:
        for err in schema.iter_errors(xml_string):
            pos = getattr(err, "position", None)
            if pos:
                line, col = pos
                errors.append(f"Line {line}, Col {col}: {err.reason}")
            else:
                errors.append(str(err))
    except Exception as e:
        return False, [f"Validation exception: {e}"]
    if errors:
        return False, errors
    return True, None

# --- Simple config manager (persist schema/logo choices) ---------------------------

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
SCHEMAS_DIR = os.path.join(ASSETS_DIR, "schemas")
os.makedirs(SCHEMAS_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)

def load_config() -> Dict:
    if not os.path.exists(CONFIG_FILE):
        return {"schema_path": None, "logo_path": None}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"schema_path": None, "logo_path": None}

def save_config(data: Dict):
    cfg = load_config()
    cfg.update(data)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

# Ensure a minimal XSD exists so CI/tests can run without external download
MINIMAL_XSD_PATH = os.path.join(SCHEMAS_DIR, "pain.001.minimal.xsd")
if not os.path.exists(MINIMAL_XSD_PATH):
    try:
        with open(MINIMAL_XSD_PATH, "w", encoding="utf-8") as f:
            f.write("""<?xml version="1.0" encoding="utf-8"?>
<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03" xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03" elementFormDefault="qualified">
  <xsd:element name="CstmrCdtTrfInitn">
    <xsd:complexType>
      <xsd:sequence>
        <xsd:element name="GrpHdr" minOccurs="0" maxOccurs="1">
          <xsd:complexType>
            <xsd:sequence>
              <xsd:element name="MsgId" type="xsd:string" minOccurs="1"/>
              <xsd:element name="CreDtTm" type="xsd:dateTime" minOccurs="1"/>
              <xsd:element name="NbOfTxs" type="xsd:string" minOccurs="1"/>
              <xsd:element name="CtrlSum" type="xsd:decimal" minOccurs="1"/>
            </xsd:sequence>
          </xsd:complexType>
        </xsd:element>
        <xsd:element name="PmtInf" minOccurs="1" maxOccurs="unbounded">
          <xsd:complexType>
            <xsd:sequence>
              <xsd:element name="PmtInfId" type="xsd:string"/>
              <xsd:element name="PmtMtd" type="xsd:string"/>
              <xsd:element name="NbOfTxs" type="xsd:string"/>
              <xsd:element name="CtrlSum" type="xsd:decimal"/>
              <xsd:element name="CdtTrfTxInf" minOccurs="1" maxOccurs="unbounded">
                <xsd:complexType>
                  <xsd:sequence>
                    <xsd:element name="PmtId">
                      <xsd:complexType>
                        <xsd:sequence>
                          <xsd:element name="EndToEndId" type="xsd:string"/>
                        </xsd:sequence>
                      </xsd:complexType>
                    </xsd:element>
                    <xsd:element name="Amt">
                      <xsd:complexType>
                        <xsd:sequence>
                          <xsd:element name="InstdAmt">
                            <xsd:complexType>
                              <xsd:simpleContent>
                                <xsd:extension base="xsd:decimal">
                                  <xsd:attribute name="Ccy" type="xsd:string" use="required"/>
                                </xsd:extension>
                              </xsd:simpleContent>
                            </xsd:complexType>
                          </xsd:element>
                        </xsd:sequence>
                      </xsd:complexType>
                    </xsd:element>
                    <xsd:element name="Cdtr">
                      <xsd:complexType>
                        <xsd:sequence>
                          <xsd:element name="Nm" type="xsd:string"/>
                        </xsd:sequence>
                      </xsd:complexType>
                    </xsd:element>
                    <xsd:element name="CdtrAcct">
                      <xsd:complexType>
                        <xsd:sequence>
                          <xsd:element name="Id">
                            <xsd:complexType>
                              <xsd:sequence>
                                <xsd:element name="IBAN" type="xsd:string"/>
                              </xsd:sequence>
                            </xsd:complexType>
                          </xsd:element>
                        </xsd:sequence>
                      </xsd:complexType>
                    </xsd:element>
                    <xsd:element name="Dbtr">
                      <xsd:complexType>
                        <xsd:sequence>
                          <xsd:element name="Nm" type="xsd:string"/>
                        </xsd:sequence>
                      </xsd:complexType>
                    </xsd:element>
                    <xsd:element name="DbtrAcct">
                      <xsd:complexType>
                        <xsd:sequence>
                          <xsd:element name="Id">
                            <xsd:complexType>
                              <xsd:sequence>
                                <xsd:element name="IBAN" type="xsd:string"/>
                              </xsd:sequence>
                            </xsd:complexType>
                          </xsd:element>
                        </xsd:sequence>
                      </xsd:complexType>
                    </xsd:element>
                    <xsd:element name="RmtInf" minOccurs="0">
                      <xsd:complexType>
                        <xsd:sequence>
                          <xsd:element name="Ustrd" type="xsd:string" minOccurs="0"/>
                        </xsd:sequence>
                      </xsd:complexType>
                    </xsd:element>
                  </xsd:sequence>
                </xsd:complexType>
              </xsd:element>
            </xsd:sequence>
          </xsd:complexType>
        </xsd:element>
      </xsd:sequence>
    </xsd:complexType>
  </xsd:element>
</xsd:schema>
""")
        logger.info("Wrote minimal pain.001 XSD to %s", MINIMAL_XSD_PATH)
    except Exception:
        logger.exception("Unable to write minimal XSD; validation may fail until XSD is provided")

# --- Streamlit app UI --------------------------------------------------------------

st.set_page_config(page_title="Swift Alliance - Converter & Validator", layout="wide")
st.title("Swift Alliance — Message Converter & ISO20022 Validator")

# Load or create bank instance
bank = SwiftAllianceBank()

# Load config (schema/logo)
cfg = load_config()
if "schema_path" not in st.session_state:
    st.session_state["schema_path"] = cfg.get("schema_path")
if "logo_path" not in st.session_state:
    st.session_state["logo_path"] = cfg.get("logo_path")

# Helpers for secrets
def get_smtp_secrets():
    if hasattr(st, "secrets") and st.secrets:
        smtp = st.secrets.get("SMTP", {})
        return smtp.get("host"), smtp.get("user"), smtp.get("pass")
    return None, None, None

def get_sftp_secrets():
    if hasattr(st, "secrets") and st.secrets:
        sftp = st.secrets.get("SFTP", {})
        port = sftp.get("port")
        try:
            port = int(port) if port else None
        except Exception:
            port = None
        return sftp.get("host"), port, sftp.get("user"), sftp.get("pass")
    return None, None, None, None

# Left column: backend, schema/logo controls
col1, col2 = st.columns([1, 2])

with col1:
    st.header("Backend / Accounts")
    if not bank.accounts:
        st.warning("No accounts found. Use demo or register customers.")
    if st.button("Create demo data"):
        bank.demo = None  # safe no-op in this simplified context
        # Create demo customer and accounts using bank methods:
        try:
            cust_info = {
                "first_name": "John", "last_name": "Doe", "email": "john@example.com",
                "phone": "+123456789", "address": "123 Main St", "date_of_birth": "1980-01-01",
                "id_number": "A123456", "id_type": "Passport"
            }
            cust = bank.register_customer(cust_info)
            bank.create_account(cust.customer_id, AccountType.SAVINGS, Currency.USD, Decimal("1000"))
            bank.create_account(cust.customer_id, AccountType.CURRENT, Currency.USD, Decimal("5000"))
            st.success("Demo customer and accounts created")
        except Exception as e:
            st.error(f"Demo creation failed: {e}")

    accounts_list = ["-- Select account --"] + sorted(list(bank.accounts.keys()))
    selected_account = st.selectbox("Select account number", accounts_list)

    st.markdown("**Persisted schema & logo**")
    st.write("Current schema:", os.path.basename(st.session_state.get("schema_path")) if st.session_state.get("schema_path") else "None")
    uploaded_xsd = st.file_uploader("Upload pain.001 XSD (persist)", type=["xsd"])
    if uploaded_xsd is not None:
        try:
            target = os.path.join(SCHEMAS_DIR, os.path.basename(uploaded_xsd.name))
            with open(target, "wb") as f:
                f.write(uploaded_xsd.read())
            st.session_state["schema_path"] = target
            save_config({"schema_path": target, "logo_path": st.session_state.get("logo_path")})
            st.success(f"Schema saved to {target}")
        except Exception as e:
            st.error(f"Failed saving schema: {e}")

    # show available persisted schemas
    persisted = []
    try:
        persisted = sorted([f for f in os.listdir(SCHEMAS_DIR) if f.lower().endswith(".xsd")])
    except Exception:
        persisted = []
    if persisted:
        pick = st.selectbox("Choose persisted schema", ["-- keep current --"] + persisted)
        if pick and pick != "-- keep current --":
            st.session_state["schema_path"] = os.path.join(SCHEMAS_DIR, pick)
            save_config({"schema_path": st.session_state["schema_path"], "logo_path": st.session_state.get("logo_path")})
            st.success(f"Selected persisted schema: {pick}")

    st.write("Current logo:", os.path.basename(st.session_state.get("logo_path")) if st.session_state.get("logo_path") else "None")
    uploaded_logo = st.file_uploader("Upload logo (PNG/SVG) to persist", type=["png", "svg", "jpg", "jpeg"])
    if uploaded_logo:
        try:
            dest = os.path.join(ASSETS_DIR, os.path.basename(uploaded_logo.name))
            with open(dest, "wb") as f:
                f.write(uploaded_logo.read())
            st.session_state["logo_path"] = dest
            save_config({"schema_path": st.session_state.get("schema_path"), "logo_path": dest})
            st.success("Logo saved persistently")
        except Exception as e:
            st.error(f"Failed saving logo: {e}")

with col2:
    logo_path = st.session_state.get("logo_path")
    if logo_path and os.path.exists(logo_path):
        st.image(logo_path, width=300)
    else:
        st.info("No logo persisted (upload one if desired)")

    st.header("Compose Payment")
    ordering_name = st.text_input("Ordering name", value="")
    ordering_account = st.text_input("Ordering account (IBAN)", value=(selected_account if selected_account and selected_account != "-- Select account --" else ""))
    beneficiary_name = st.text_input("Beneficiary name", value="")
    beneficiary_account = st.text_input("Beneficiary account (IBAN)", value="")
    beneficiary_bic = st.text_input("Beneficiary BIC (optional)", value="")
    c1, c2 = st.columns([1,1])
    with c1:
        amount_text = st.text_input("Amount (e.g., 1234.56)", value="0.00")
    with c2:
        currency = st.text_input("Currency", value="USD")
    value_date = st.text_input("Value date (YYYY-MM-DD)", value=datetime.date.today().isoformat())
    remittance = st.text_area("Remittance information", value="")
    reference = st.text_input("Reference (optional)", value="")

    st.markdown("---")
    fmt = st.radio("Format", ["ISO20022 pain.001 (XML)", "MT103 (text)"])
    btn_generate = st.button("Generate Preview")
    btn_validate = st.button("Validate preview")
    btn_save = st.button("Save message")
    btn_send = st.button("Send (mock)")

    if "preview" not in st.session_state:
        st.session_state["preview"] = ""
    if "validation" not in st.session_state:
        st.session_state["validation"] = {"valid": False, "errors": []}
    if "last_format" not in st.session_state:
        st.session_state["last_format"] = None

    def build_payment():
        try:
            amt = Decimal(amount_text.strip())
        except (InvalidOperation, ValueError):
            st.error("Invalid amount format. Use numbers like 1234.56")
            return None
        return payment_from_transaction(
            account_number=ordering_account.strip(),
            account_name=ordering_name.strip(),
            beneficiary_account=beneficiary_account.strip(),
            beneficiary_name=beneficiary_name.strip(),
            amount=amt,
            currency=currency.strip() or "USD",
            value_date=value_date.strip() or None,
            remittance_info=remittance.strip() or None,
            beneficiary_bic=beneficiary_bic.strip() or None,
            reference=reference.strip() or None
        )

    if btn_generate:
        payment = build_payment()
        if payment is not None:
            if fmt.startswith("ISO20022"):
                xml = generate_pain001(payment)
                st.session_state["preview"] = xml
                st.session_state["last_format"] = "XML"
                st.success("XML preview generated")
                # auto-validate if schema exists
                schema_path = st.session_state.get("schema_path") or MINIMAL_XSD_PATH
                try:
                    valid, errors = validate_pain001_generated(xml, schema_path)
                    st.session_state["validation"] = {"valid": valid, "errors": errors or []}
                    if valid:
                        st.success("XML validated OK")
                    else:
                        st.error("XML validation failed (see details)")
                except SchemaNotFoundError as e:
                    st.error(f"Schema not found: {e}")
                except Exception as e:
                    st.error(f"Validation error: {e}")
            else:
                mt = generate_mt103(payment)
                st.session_state["preview"] = mt
                st.session_state["last_format"] = "MT"
                valid, issues = validate_mt103_text(mt)
                st.session_state["validation"] = {"valid": valid, "errors": issues}
                if valid:
                    st.success("MT103 basic validation passed")
                else:
                    st.error("MT103 validation issues found")

    if btn_validate:
        content = st.session_state.get("preview", "")
        if not content:
            st.info("No preview to validate; generate one first")
        else:
            if st.session_state.get("last_format") == "XML":
                schema_path = st.session_state.get("schema_path") or MINIMAL_XSD_PATH
                try:
                    valid, errors = validate_pain001_generated(content, schema_path)
                    st.session_state["validation"] = {"valid": valid, "errors": errors or []}
                    if valid: st.success("XML valid")
                    else: st.error("XML invalid (see details)")
                except SchemaNotFoundError as e:
                    st.error(f"Schema not found: {e}")
            else:
                valid, issues = validate_mt103_text(content)
                st.session_state["validation"] = {"valid": valid, "errors": issues}
                if valid: st.success("MT103 valid")
                else: st.error("MT103 issues found")

    st.subheader("Preview")
    if st.session_state.get("preview"):
        st.code(st.session_state["preview"], language='xml' if st.session_state.get("last_format")=="XML" else 'text')
    else:
        st.info("No preview yet. Fill form and click Generate Preview.")

    st.subheader("Validation")
    v = st.session_state.get("validation", {"valid": False, "errors": []})
    if v["valid"]:
        st.success("VALID")
    else:
        st.error("INVALID or not validated")
    if v["errors"]:
        for i, err in enumerate(v["errors"], 1):
            st.write(f"{i}. {err}")

    if btn_save:
        content = st.session_state.get("preview", "")
        if not content:
            st.info("Nothing to save")
        else:
            suffix = ".xml" if st.session_state.get("last_format")=="XML" else ".txt"
            fname = f"swift_message_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}{suffix}"
            with open(fname, "w", encoding="utf-8") as f:
                f.write(content)
            st.success(f"Saved to {fname}")

    if btn_send:
        content = st.session_state.get("preview", "")
        if not content:
            st.info("Nothing to send")
        else:
            if not st.session_state.get("validation", {}).get("valid", False):
                if not st.checkbox("Message invalid. Check to confirm you want to proceed with sending anyway"):
                    st.stop()
            send_method = st.selectbox("Send method", ["Log locally", "SMTP (secrets)", "SMTP (manual)", "SFTP (secrets)", "SFTP (manual)"])
            if send_method == "Log locally":
                logf = "swift_send_log.txt"
                with open(logf, "a", encoding="utf-8") as f:
                    f.write(f"----- {datetime.datetime.utcnow().isoformat()} -----\n")
                    f.write(content + "\n\n")
                st.success(f"Logged to {logf}")
            elif send_method == "SMTP (secrets)":
                host, user, pwd = get_smtp_secrets()
                if not host or not user or not pwd:
                    st.error("No SMTP secrets configured. Use SMTP (manual) or add secrets in Streamlit Cloud.")
                else:
                    try:
                        import smtplib
                        h, p = host.split(":")
                        p = int(p)
                        with smtplib.SMTP(h, p, timeout=10) as s:
                            s.starttls()
                            s.login(user, pwd)
                            msg = f"Subject: SWIFT Message\n\n{content}"
                            s.sendmail(user, [user], msg.encode("utf-8"))
                        st.success("Sent using SMTP secrets")
                    except Exception as e:
                        st.error(f"SMTP send failed: {e}")
            elif send_method == "SMTP (manual)":
                host = st.text_input("SMTP host (host:port)", value="smtp.example.com:587")
                user = st.text_input("SMTP username")
                pwd = st.text_input("SMTP password", type="password")
                recipient = st.text_input("Recipient email")
                if st.button("Send now (manual SMTP)"):
                    try:
                        import smtplib
                        h, p = host.split(":")
                        p = int(p)
                        with smtplib.SMTP(h, p, timeout=10) as s:
                            s.starttls()
                            s.login(user, pwd)
                            msg = f"Subject: SWIFT Message\n\n{content}"
                            s.sendmail(user, [recipient], msg.encode("utf-8"))
                        st.success("Email sent")
                    except Exception as e:
                        st.error(f"SMTP error: {e}")
            elif send_method == "SFTP (secrets)":
                host, port, user, pwd = get_sftp_secrets()
                if not host or not user or not pwd:
                    st.error("No SFTP secrets configured.")
                elif not HAS_PARAMIKO:
                    st.error("paramiko not available in environment.")
                else:
                    try:
                        transport = paramiko.Transport((host, int(port or 22)))
                        transport.connect(username=user, password=pwd)
                        sftp_client = paramiko.SFTPClient.from_transport(transport)
                        remote_path = f"/upload/swift_{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}.txt"
                        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tf:
                            tf.write(content)
                            tmpn = tf.name
                        sftp_client.put(tmpn, remote_path)
                        sftp_client.close()
                        transport.close()
                        os.unlink(tmpn)
                        st.success(f"Uploaded to {remote_path}")
                    except Exception as e:
                        st.error(f"SFTP error: {e}")
            else:  # SFTP manual
                host = st.text_input("SFTP host")
                port = st.number_input("SFTP port", value=22)
                user = st.text_input("SFTP user")
                pwd = st.text_input("SFTP password", type="password")
                remote_path = st.text_input("Remote path", value="/upload/message.txt")
                if st.button("Upload now (manual SFTP)"):
                    if not HAS_PARAMIKO:
                        st.error("paramiko not installed")
                    else:
                        try:
                            transport = paramiko.Transport((host, int(port)))
                            transport.connect(username=user, password=pwd)
                            sftp_client = paramiko.SFTPClient.from_transport(transport)
                            with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tf:
                                tf.write(content)
                                tmpn = tf.name
                            sftp_client.put(tmpn, remote_path)
                            sftp_client.close()
                            transport.close()
                            os.unlink(tmpn)
                            st.success("Uploaded via SFTP")
                        except Exception as e:
                            st.error(f"SFTP error: {e}")

st.markdown("---")
st.markdown("Notes: This app is for demonstration and internal use. To send messages to SWIFT or production gateways you must integrate with a certified provider (Alliance Lite2 or bank gateway). Use strong operational controls, secrets management, and compliance review before any live submissions.")