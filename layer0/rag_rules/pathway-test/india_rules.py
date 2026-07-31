# layer0_sources/india_rules.py
# Hardcoded Indian compliance rules as embeddable text chunks
# Sources: PMLA 2002, FIU-IND Jan 2026, RBI KYC Aug 2025, SEBI Jun 2024
# Output: pw.Table with columns (text, rule_id, source)

import pathway as pw

# ─────────────────────────────────────────────────────────────
# (text, rule_id, source)
# text   → gets embedded, returned to agents on similarity search
# rule_id → cited in SAR narrative by Agent 5
# source  → metadata filter so Agent 7 can query by regulator
# ─────────────────────────────────────────────────────────────

INDIA_COMPLIANCE_RULES = [

    # ── PMLA / FIU-IND — Core Reporting Obligations ──────────
    (
        "Cash Transaction Report (CTR): All banks, financial institutions, "
        "and intermediaries must report cash transactions exceeding INR 10 lakh "
        "(Rs 10,00,000) in a single month to FIU-IND. "
        "Structuring transactions to stay below this threshold is itself a red flag "
        "and a PMLA violation under Rule 9.",
        "PMLA_CTR_001",
        "FIU-IND"
    ),
    (
        "Suspicious Transaction Report (STR): Must be filed within 7 working days "
        "of detecting suspicious activity. No minimum amount threshold applies — "
        "any transaction with no apparent economic rationale qualifies regardless of size. "
        "STR narratives must be high-quality with complete datasets and documented justification. "
        "Source: PMLA Section 12 / FIU-IND AML-CFT Guidelines January 2026.",
        "PMLA_STR_001",
        "FIU-IND"
    ),
    (
        "Tipping-off prohibition: Directors, officers, and employees are strictly "
        "prohibited from informing clients or third parties about STR filings, "
        "FIU-IND requests, or grounds of suspicion — before, during, and after submission. "
        "Violation attracts criminal liability under PMLA. "
        "Source: FIU-IND AML-CFT Guidelines January 2026.",
        "PMLA_TIPPING_001",
        "FIU-IND"
    ),
    (
        "Record retention obligation: All client records, transaction records, and STR "
        "audit trails must be preserved for a minimum of 5 years after account closure. "
        "Audit trails must capture verification responses, timestamps, and authentication "
        "logs in tamper-proof form. Applies to all PMLA reporting entities including VDASPs. "
        "Source: PMLA Rules / FIU-IND Guidelines 2026.",
        "PMLA_RECORD_001",
        "FIU-IND"
    ),
    (
        "Structuring detection: Breaking large transactions into smaller amounts "
        "to evade the INR 10 lakh CTR threshold is a criminal offence under PMLA. "
        "Multiple transactions just below INR 10 lakh within 24 hours for the same "
        "account or beneficiary must be aggregated and treated as a single transaction "
        "for CTR purposes. Rolling sum crossing INR 10 lakh triggers mandatory reporting.",
        "PMLA_STRUCT_001",
        "FIU-IND"
    ),

    # ── FIU-IND — VDASP / Crypto Specific ────────────────────
    (
        "Virtual Digital Asset Service Providers (VDASPs) are mandatory reporting "
        "entities under PMLA since March 2023 Ministry of Finance notification. "
        "Must register on FINnet 2.0 portal. Registration is activity-based not "
        "domicile-based — offshore exchanges serving Indian users must also register. "
        "Non-compliance: FIU-IND can direct MeitY to block URLs and mobile apps. "
        "Source: MoF Notification July 2024 / FIU-IND.",
        "FIU_VDA_001",
        "FIU-IND"
    ),
    (
        "VDASP KYC requirements (January 2026): Mandatory live selfie with liveness "
        "detection (eye-blink or head movement) and geographic tracking (latitude, "
        "longitude, timestamp, IP address) during customer onboarding to prevent "
        "deepfake fraud. Token offerings classified as high risk — full AML controls required. "
        "Source: FIU-IND AML-CFT Guidelines for VDASPs, January 8, 2026.",
        "FIU_VDA_KYC_001",
        "FIU-IND"
    ),
    (
        "Crypto STR red flags per FIU-IND Annual Report 2024-25: "
        "Rapid layering across multiple wallets, conversion to privacy coins, "
        "peer-to-peer transfers avoiding exchange KYC, transactions from mixer services, "
        "sudden large on-ramp followed by immediate off-ramp, "
        "accounts onboarded with identical device fingerprints.",
        "FIU_VDA_REDFLAG_001",
        "FIU-IND"
    ),

    # ── RBI KYC Master Direction ───────────────────────────────
    (
        "Politically Exposed Persons (PEP) — Enhanced Due Diligence mandatory. "
        "PEPs are individuals entrusted with prominent public functions by a foreign country. "
        "Definition updated January 4, 2024 in RBI KYC Master Direction 2016 "
        "(last updated August 14, 2025). "
        "Senior management approval required before establishing or continuing PEP relationships. "
        "Ongoing monitoring must be more frequent than standard customers.",
        "RBI_KYC_PEP_001",
        "RBI"
    ),
    (
        "Periodic KYC updation: Banks must re-verify customer KYC at risk-based intervals. "
        "High risk customers: every 2 years. Medium risk: every 8 years. Low risk: every 10 years. "
        "Failure to complete periodic updation does not automatically justify account freezing "
        "per RBI amendment August 14, 2025 — partial services must remain available. "
        "Source: RBI KYC Master Direction 2016, updated August 2025.",
        "RBI_KYC_PERIODIC_001",
        "RBI"
    ),
    (
        "Video KYC (V-CIP): RBI permits Video-based Customer Identification Process "
        "as valid KYC for account opening. Must include live interaction, "
        "Aadhaar OTP verification, PAN capture, facial match, and geo-tagging. "
        "Recorded and stored. Cannot be pre-recorded or replayed. "
        "Source: RBI KYC Master Direction 2016.",
        "RBI_KYC_VCIP_001",
        "RBI"
    ),

    # ── SEBI AML/CFT ──────────────────────────────────────────
    (
        "SEBI intermediaries — brokers, mutual funds, portfolio managers, depositories — "
        "must file STRs with FIU-IND via FINGate 2.0 portal. "
        "AML/CFT compliance governed by SEBI Master Circular June 2024. "
        "Role-specific AML training mandatory for frontline staff, back office, "
        "and compliance officers annually. "
        "Source: SEBI AML/CFT Master Circular, June 2024.",
        "SEBI_AML_001",
        "SEBI"
    ),
    (
        "SEBI red flags for securities fraud: Wash trading between connected accounts, "
        "circular trading to inflate volumes, layering through multiple brokers, "
        "sudden large position followed by news-driven exit, "
        "accounts with identical KYC documents across different PAN numbers. "
        "Source: SEBI AML/CFT Master Circular June 2024.",
        "SEBI_AML_REDFLAG_001",
        "SEBI"
    ),

    # ── Enforcement Directorate precedents ────────────────────
    (
        "ED prosecution precedent: Shell company layering through multiple current accounts "
        "with round-sum transfers is the most common PMLA money laundering typology "
        "per ED Annual Report 2024-25. Provisional attachment orders issued under "
        "PMLA Section 5 can freeze assets within 180 days of predicate offence detection. "
        "Cooperating banks receive protection from civil liability under PMLA Section 24.",
        "ED_PRECEDENT_001",
        "ED"
    ),
]


def get_rules_as_pathway_table():
    import json

    print(f"[india_rules] Loading {len(INDIA_COMPLIANCE_RULES)} hardcoded compliance rules")

    # Convert each rule into fake "binary file" format
    # so it matches raw_docs schema: data (bytes) + _metadata (dict)
    rows = []
    for text, rule_id, source in INDIA_COMPLIANCE_RULES:
        rows.append((
            text.encode("utf-8"),           # data column — bytes, like a PDF
            {"path": f"rules/{rule_id}",    # _metadata column — dict
             "source": source,
             "rule_id": rule_id}
        ))

    return pw.debug.table_from_rows(
        schema=pw.schema_from_types(
            data=bytes,
            _metadata=dict,
        ),
        rows=rows
    )