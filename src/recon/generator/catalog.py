"""Static vocabulary for the synthetic dataset.

Narration templates are the matcher's real interface to the bank statement, so they
are documented in docs/CONVENTIONS.md and the matcher's regexes are written against
that document rather than against this file.
"""

from __future__ import annotations

CUSTOMER_NAMES = [
    "Rajesh Textiles Pvt Ltd",
    "Sunrise Electronics",
    "Meenakshi Traders",
    "Kaveri Agro Foods",
    "Bluewave Logistics LLP",
    "Sharma Hardware Stores",
    "Nandini Dairy Products",
    "Orchid Pharma Distributors",
    "Vishal Auto Components",
    "Greenleaf Organics",
    "Deccan Steel Works",
    "Priya Garments",
    "Coastal Marine Exports",
    "Ganesh Cement Agencies",
    "Infinite Loop Software",
    "Ratna Jewellers",
    "Himalaya Packaging",
    "Sagar Chemicals",
    "Anand Furniture House",
    "Zenith Office Supplies",
    "Kalyani Engineering",
    "Trident Paper Mills",
    "Surya Solar Solutions",
    "Bharat Tyre Traders",
    "Lotus Hospitality Services",
    "Mahalaxmi Provisions",
    "Everest Cold Storage",
    "Pinnacle Interiors",
    "Sagarika Seafoods",
    "Vertex Lab Equipment",
    "Chandra Printing Press",
    "Aakash Sports Goods",
    "Nirmal Water Systems",
    "Ashoka Timber Depot",
    "Silverline Cosmetics",
    "Konark Ceramics",
    "Rudra Plastics",
    "Maple Leaf Stationers",
    "Indus Valley Handicrafts",
    "Prakash Lighting Co",
    "Sanjeevani Medicals",
    "Falcon Security Services",
    "Amrit Bakery Supplies",
    "Tejas Aviation Spares",
    "Bandhan Fabrics",
    "Corniche Builders",
    "Devi Poultry Farms",
    "Quantum IT Services",
    "Shakti Power Tools",
    "Yamuna Paints",
]

UTR_BANK_PREFIXES = ["HDFC", "ICIC", "UTIB", "SBIN", "KKBK"]

# Narrations that carry the UTR. The matcher must cope with all of these shapes.
NARRATION_WITH_UTR = [
    "NEFT-{utr}-RAZORPAY SOFTWARE PVT LTD",
    "IMPS/{utr}/RAZORPAYSOFT",
    "UPI-RAZORPAY-{utr}",
    "RTGS {utr} RAZORPAY",
    "ACH C- RAZORPAY SOFTW {utr}",
    "BY TRANSFER-NEFT*{utr}*RAZORPAY",
    "MB:{utr} RZPY SETTLEMENT",
    "CMS/{utr}",
    "NEFT CR-{utr}-RAZORPAY SOFTWARE PRIVATE LIMITED-SETTLEMENT",
    "TRF FROM RAZORPAY REF {utr}",
    # Reference last: these are the shapes a truncated narration field mangles.
    "RAZORPAY SOFTWARE PRIVATE LIMITED SETTLEMENT REF {utr}",
    "BY TRANSFER FROM RAZORPAY SOFTWARE PVT LTD NEFT {utr}",
    "MERCHANT PAYOUT RAZORPAY SOFTWARE PVT LTD UTR {utr}",
]

# Narrations with no UTR at all. These force amount-plus-date-window matching.
NARRATION_WITHOUT_UTR = [
    "RAZORPAY SETTLEMENT CREDIT",
    "NEFT CR-RAZORPAY SOFTWARE PVT LTD",
    "GATEWAY PAYOUT RAZORPAY",
    "BY TRANSFER-RAZORPAY SOFTW",
    "MERCHANT SETTLEMENT CR",
]

# Direct customer transfers that never touched the gateway: genuinely unresolvable.
NARRATION_DIRECT_NEFT = [
    "NEFT CR-{bank}0001234-{customer}-DIRECT PAYMENT",
    "RTGS CR {customer} INV SETTLEMENT",
    "IMPS/P2A/{customer}",
    "BY CASH DEPOSIT {customer}",
    "NEFT-{customer}-INVOICE PAYMENT",
]

NARRATION_REVERSAL = [
    "REV-NEFT {utr}",
    "RETURN OF NEFT {utr}",
    "REVERSAL RAZORPAY SETTLEMENT {utr}",
]

NARRATION_REPOST = [
    "NEFT-{utr}-RAZORPAY SOFTWARE PVT LTD-REPOST",
    "NEFT CR-{utr}-RAZORPAY SOFTWARE PRIVATE LIMITED",
    "REPRESENTED NEFT {utr} RAZORPAY",
]

NARRATION_OUT_OF_SCOPE_DEBIT = [
    "NEFT DR-VENDOR PAYMENT-{customer}",
    "SALARY PAYOUT BATCH",
    "GST PAYMENT CHALLAN",
    "RENT DEBIT STANDING INSTRUCTION",
    "BANK CHARGES GST",
]
