# Records & Pay

Open **Records & Pay** from the field page or the job packet.

- **JU checklist** reads the existing saved records. All four checks (photos,
  notes, close code, billing codes) and known rates are required for Ready to bill.
- **Mark billed** records what you billed your boss. It freezes each JU's amount
  and record revision. It does not send an invoice or assume that money arrived.
- **Record payment** accepts partial or full payments against one JU. The balance
  remains in Still owed. Reverse mistakes from that JU's history; entries remain
  in the audit trail. Cancel a mistaken bill only after reversing its payments.
- **Small packets** prepares selected JUs for Boss or Contractor. Send every part.
  Use **I sent all parts** only after sending. Changed records are flagged after
  billing or sending. No previous billing, payment or delivery is assumed.

Photo copies use a maximum 2048-pixel long edge and JPEG quality 88. Orientation
is corrected and EXIF GPS is retained. Originals are not modified. An unsupported
format stays original if it fits; a failed conversion or oversized file stops the
packet instead of dropping evidence. Every ZIP is verified below 10,000,000 bytes.
Review the shared photos for the recipient's required detail; originals remain
available for higher-resolution requests.

Each JU has a readable report, billing-code CSV, and photos. PART_1 also has one
ALL_JUS.csv and ALL_BILLING_CODES.csv for the entire set. Use these for totals;
per-JU reports repeat if a JU spans parts. Contractor copies omit the user's rates,
payments and billing references. Unsaved drafts and voice history are excluded.

Current packets update in place under
`/storage/emulated/0/DEVCO/Pole_Transfers/Send_Ready/<job>/Small_Packets/Boss`
or `Contractor`. Previous sets are preserved under
`/storage/emulated/0/DEVCO/Backups/Tracking_Packets`.

Tracking data lives in `~/DEVCO_FIELD/TRACKING/tracking.sqlite3`, with a consistent
`tracking-recovery.sqlite3` after changes. Photo copies are cached there by source
hash. These private runtime files are excluded from Git. Financial actions use
transactions and idempotency keys; changed selections are rejected for review.

The older 0212 JOB_PACKET_CURRENT is read as recorded. Its billing and notes are
preserved and shareable, while unclear completion/closing tasks remain unverified.
No field data is rewritten by tracking. Existing map, route and field selection
continue independently.
