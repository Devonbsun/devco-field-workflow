# Devco phone project directories

This repository is the Devco work lane. Do not touch unrelated personal projects.

User instruction (2026-10-06): keep one clear permanent pole-transfer directory;
update existing files and folders; remove old iterations only after verified backup.

- Phone directory: /storage/emulated/0/DEVCO/Pole_Transfers
- Current project documents: Jobs/<full-work-order>/
- Send-ready independent ZIP parts: Send_Ready/<full-work-order>/PART_1.zip, etc.
- All ZIP parts must remain below 100,000,000 bytes.
- Never create dated, FINAL, BOSS_COPY, (1), or version-suffixed active packets in Downloads.
- Run SYSTEM/project_directory.py (or devco-files) to update published files.
- devco-files is a supervised background service; install with SYSTEM/install_directory.sh.
- Active 0200 source: JOBS/07400073460200/3_JU_FILES and source/route/workflow folders.
- Authoritative 0212 legacy export: JOBS/07400073460212/JOB_PACKET_CURRENT plus its summary.
  Preserve legacy billing exactly. Do not infer completion from photos or billing codes.
- Do not merge older 0212 records over the current packet. Eight older photos were
  GPS-verified and restored to four JUs on 2026-10-06; billing and notes were preserved.
- Always check original Solocator GPS metadata when looking for JU/location photos.
  SYSTEM/gps_photo_audit.py checks standard and legacy sources and maintains
  Needs_Review/GPS_Photo_Review.csv and GPS_Photos. User clarification (2026-10-06):
  connect reasonably nearby photos, including shots taken away from the pole; skip way-off photos.
  Use GPS together with true compass direction, photo sequence and visible pole details.
  The audit screens unfiled photos within 300 m; this is not a guaranteed identity radius.
  Close competing JUs can be resolved by supporting evidence; retain review where visible
  pole hardware conflicts. Record inferred associations and preserve originals.
  Do not infer billing or completion from recovered photos.
- Backup root: /storage/emulated/0/DEVCO/Backups.
  Pre-cleanup snapshot: Pole_Transfers_PreCleanup_2026-10-06.
  manifest.json preserves every original path; objects are SHA-256 verified.
- Manual edits to generated output are archived under Backups/Updated_Files before replacement.
- Boss packets contain saved field documentation and photos; exclude note drafts,
  voice history, recovery backups, and company-only paperwork.
- Preserve unrelated uncommitted field data when committing code changes.
