"""Shared Indian-specific validators (GSTIN, PAN, IFSC, Phone, Pincode)."""
from __future__ import annotations

import re

GSTIN_RE  = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")
PAN_RE    = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")
IFSC_RE   = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
PHONE_RE  = re.compile(r"^\+?[0-9]{10,15}$")
PIN_RE    = re.compile(r"^[1-9][0-9]{5}$")
EMAIL_RE  = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_gstin(v: str) -> bool:
    return bool(GSTIN_RE.match(v.upper()))


def is_valid_pan(v: str) -> bool:
    return bool(PAN_RE.match(v.upper()))


def is_valid_ifsc(v: str) -> bool:
    return bool(IFSC_RE.match(v.upper()))


def is_valid_phone(v: str) -> bool:
    return bool(PHONE_RE.match(v))


def is_valid_pincode(v: str) -> bool:
    return bool(PIN_RE.match(v))


# State codes (2-digit numeric, 1–38)
INDIAN_STATE_CODES = {
    "01","02","03","04","05","06","07","08","09","10",
    "11","12","13","14","15","16","17","18","19","20",
    "21","22","23","24","25","26","27","28","29","30",
    "31","32","33","34","35","36","37","38",
}

STATE_CODE_MAP = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana",
    "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh",
    "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam",
    "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Daman & Diu", "26": "Dadra & Nagar Haveli",
    "27": "Maharashtra", "28": "Andhra Pradesh (old)",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman & Nicobar", "36": "Telangana",
    "37": "Andhra Pradesh", "38": "Ladakh",
}
