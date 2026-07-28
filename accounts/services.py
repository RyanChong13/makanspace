"""
Automated ACRA UEN lookup via data.gov.sg (spec 5.1 companion).

Queries the free, no-auth "ACRA Information on Corporate Entities" collection
(https://data.gov.sg/collections/2/view) to fetch the registered entity name,
status, and registration date for a UEN. Results are advisory only — they
inform the admin's manual verification decision and never auto-approve/reject.
"""

import json
import logging
import time
from datetime import datetime

import requests
from django.utils import timezone

logger = logging.getLogger(__name__)

DATASTORE_SEARCH_URL = "https://data.gov.sg/api/action/datastore_search"

# The ACRA collection is split into 27 datasets by the first letter of the
# entity name (A–Z + 'Others'). Resource IDs confirmed against the live
# collection metadata (data.gov.sg collection 2), updated monthly by ACRA.
ACRA_DATASETS = {
    "a": "d_8575e84912df3c28995b8e6e0e05205a",
    "b": "d_3a3807c023c61ddfba947dc069eb53f2",
    "c": "d_c0650f23e94c42e7a20921f4c5b75c24",
    "d": "d_acbc938ec77af18f94cecc4a7c9ec720",
    "e": "d_124a9bd407c7a25f8335b93b86e50fdd",
    "f": "d_4526d47d6714d3b052eed4a30b8b1ed6",
    "g": "d_b58303c68e9cf0d2ae93b73ffdbfbfa1",
    "h": "d_fa2ed456cf2b8597bb7e064b08fc3c7c",
    "i": "d_85518d970b8178975850457f60f1e738",
    "j": "d_478f45a9c541cbe679ca55d1cd2b970b",
    "k": "d_5573b0db0575db32190a2ad27919a7aa",
    "l": "d_a2141adf93ec2a3c2ec2837b78d6d46e",
    "m": "d_9af9317c646a1c881bb5591c91817cc6",
    "n": "d_67e99e6eabc4aad9b5d48663b579746a",
    "o": "d_5c4ef48b025fdfbc80056401f06e3df9",
    "p": "d_181005ca270b45408b4cdfc954980ca2",
    "q": "d_4130f1d9d365d9f1633536e959f62bb7",
    "r": "d_2b8c54b2a490d2fa36b925289e5d9572",
    "s": "d_df7d2d661c0c11a7c367c9ee4bf896c1",
    "t": "d_72f37e5c5d192951ddc5513c2b134482",
    "u": "d_0cc5f52a1f298b916f317800251057f3",
    "v": "d_e97e8e7fc55b85a38babf66b0fa46b73",
    "w": "d_af2042c77ffaf0db5d75561ce9ef5688",
    "x": "d_1cd970d8351b42be4a308d628a6dd9d3",
    "y": "d_31af23fdb79119ed185c256f03cb5773",
    "z": "d_4e3db8955fdcda6f9944097bef3d2724",
    "others": "d_300ddc8da4e8f7bdc1bfc62d0d99e2e7",
}

# Hard budget for the whole lookup so signup never hangs on the API.
# data.gov.sg enforces a burst rate limit (~6 rapid requests trigger HTTP 429),
# but a paced sequential pace of ~2 req/s runs indefinitely — so the sweep is
# sequential with a short gap between calls rather than parallel.
# The signup deadline keeps registration snappy; the thorough deadline (used
# for the admin-triggered re-check) is long enough to sweep all 27 datasets
# and return a definitive "UEN not found".
LOOKUP_DEADLINE_SECONDS = 12
THOROUGH_DEADLINE_SECONDS = 60
REQUEST_GAP_SECONDS = 0.25


def _query_dataset(resource_id, uen, timeout=4):
    """
    Query one ACRA dataset for a UEN. Retries once after a short pause on
    HTTP 429 (burst rate limit).
    Returns (record_dict | None, error_occurred: bool).
    """
    for attempt in (1, 2):
        try:
            resp = requests.get(
                DATASTORE_SEARCH_URL,
                params={
                    "resource_id": resource_id,
                    "filters": json.dumps({"uen": uen}),
                    "limit": 1,
                },
                timeout=timeout,
            )
            if resp.status_code == 429 and attempt == 1:
                time.sleep(1)
                continue
            resp.raise_for_status()
            records = resp.json().get("result", {}).get("records", [])
            return (records[0] if records else None), False
        except (requests.RequestException, ValueError, KeyError) as exc:
            logger.warning("ACRA lookup failed on dataset %s: %s", resource_id, exc)
            return None, True
    return None, True


def _parse_record(record):
    """Extract the fields we store from a raw ACRA datastore record."""
    reg_date = None
    raw_date = (record.get("registration_incorporation_date") or "").strip()
    if raw_date and raw_date.lower() != "na":
        try:
            reg_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            pass
    return {
        "entity_name": (record.get("entity_name") or "").strip(),
        "status": (record.get("entity_status_description") or "").strip(),
        "registration_date": reg_date,
    }


def _dataset_order(name_hint):
    """
    Order dataset keys by likelihood of holding the entity: first letters of
    each word in the entered name first (registered names usually share words
    with the entered name), then 'others', then the rest of the alphabet.
    """
    ordered = []
    for word in (name_hint or "").strip().lower().split():
        key = word[0] if word[0] in ACRA_DATASETS else "others"
        if key not in ordered:
            ordered.append(key)
    if "others" not in ordered:
        ordered.append("others")
    for key in ACRA_DATASETS:
        if key not in ordered:
            ordered.append(key)
    return ordered


def lookup_uen(uen, name_hint="", deadline=LOOKUP_DEADLINE_SECONDS):
    """
    Look up a UEN in the ACRA open datasets.

    Returns a dict:
      success: the check completed (even if the UEN wasn't found)
      found: a record for this UEN exists
      entity_name / status / registration_date: from ACRA when found
    """
    result = {
        "success": False,
        "found": False,
        "entity_name": "",
        "status": "",
        "registration_date": None,
    }
    uen = (uen or "").strip().upper()
    if not uen:
        return result

    started = time.monotonic()
    any_error = False
    checked_all = True
    consecutive_errors = 0

    # Sequential, paced sweep in likelihood order — parallel bursts trip the
    # data.gov.sg rate limiter, while paced sequential requests do not.
    for key in _dataset_order(name_hint):
        if time.monotonic() - started > deadline:
            logger.warning(
                "ACRA lookup for %s hit the %ss deadline before checking all datasets.",
                uen, deadline,
            )
            checked_all = False
            break
        record, errored = _query_dataset(ACRA_DATASETS[key], uen)
        any_error = any_error or errored
        if record:
            result.update(_parse_record(record), success=True, found=True)
            return result
        # Service is clearly down — stop hammering it.
        consecutive_errors = consecutive_errors + 1 if errored else 0
        if consecutive_errors >= 3:
            logger.warning("ACRA lookup aborted for %s: service unreachable.", uen)
            checked_all = False
            break
        time.sleep(REQUEST_GAP_SECONDS)

    # "UEN not found" is only trustworthy if every dataset was checked cleanly.
    result["success"] = checked_all and not any_error
    return result


def apply_acra_lookup(company, thorough=False):
    """
    Run the UEN lookup for a Company and persist the acra_* fields.
    Never raises — signup/verification must not be blocked by this check.
    'thorough' (admin re-check) allows a longer sweep across all datasets.
    """
    try:
        deadline = THOROUGH_DEADLINE_SECONDS if thorough else LOOKUP_DEADLINE_SECONDS
        outcome = lookup_uen(company.uen, name_hint=company.name, deadline=deadline)
        company.acra_lookup_success = outcome["success"]
        company.acra_verified_name = outcome["entity_name"]
        company.acra_status = outcome["status"]
        company.acra_registration_date = outcome["registration_date"]
        company.acra_checked_at = timezone.now()
        company.save(update_fields=[
            "acra_lookup_success",
            "acra_verified_name",
            "acra_status",
            "acra_registration_date",
            "acra_checked_at",
        ])
    except Exception as exc:  # noqa: BLE001 - advisory check must never block
        logger.error("ACRA lookup could not be applied for company %s: %s", company.pk, exc)
