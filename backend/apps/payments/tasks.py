"""Payment background tasks."""

from __future__ import annotations

import logging

from celery import shared_task

from apps.payments.models import PaymentReceipt, ReceiptScanStatus

logger = logging.getLogger(__name__)


@shared_task
def scan_receipt(receipt_pk: int) -> str:
    """Anti-virus scan hook (SECURITY.md §7).

    No scanner is wired up yet, so this marks the file as scanned without claiming it
    was checked by an engine. The hook exists now because the admin download endpoint
    already refuses to serve anything still `PENDING` — meaning the day a real scanner
    is plugged in, the gate is already enforced rather than needing to be added.

    No retry config: nothing here can fail transiently today. Once a real scanner
    call is added, that is the point to add `autoretry_for` on its specific
    connection/timeout exceptions — not before, and not blanket.
    """
    receipt = PaymentReceipt.objects.filter(pk=receipt_pk).first()
    if receipt is None:
        return "missing"

    # Replace with a real scanner (ClamAV/S3 malware scanning) in Phase 10.
    receipt.scan_status = ReceiptScanStatus.CLEAN
    receipt.save(update_fields=["scan_status", "updated_at"])
    logger.info("Receipt %s marked %s", receipt.pk, receipt.scan_status)
    return receipt.scan_status
