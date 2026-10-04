# Spoken closeout

Opening `/billing` for the active JU starts the Android voice flow once for that page:

1. Speak “What are your notes?” and listen after speech playback finishes.
2. Clean the transcript and save the note to that exact JU.
3. Speak “What is the closing task?” and select a matching close option.
4. Show the note and selection. Only the user's Confirm & finalize JU action submits closeout.

The APK requires Android microphone permission. The Android speech provider handles recognition; availability and connectivity depend on the phone's provider. The normal form remains available when speech is unavailable, denied, interrupted, or unclear. There is no microphone button. Leaving the screen/backgrounding cancels speech. Solocator/photo events do not start prompts.

`voice_workflow.py` uses conservative local text rules, not an LLM service. It removes fillers, retains uncertainty and negation, and resolves explicit restatements and supported corrections. Ambiguous corrections remain visible and are flagged for review. It adds no missing facts, billing quantities, measurements, or work. Original transcripts and previous notes are retained under each JU's `VOICE_HISTORY` for recovery. Audio is not stored by Devco.

The form is pinned to the job/JU it opened. Voice requests reject changed active JUs or notes changed concurrently. Speech never finalizes a JU, changes billing quantities, bypasses photo requirements, or skips pending-note validation. Unrecognized or conflicting close names remain unselected; one spoken retry is allowed before manual review.

Build using `ANDROID_APP/build_recovery.sh` and install the signed 1.3-voice-closeout APK. The existing signing key stays on the phone. Android requires user acceptance of the update and microphone permission. Tests cover server persistence, correction handling, intent matching, and the JavaScript state flow; live microphone/TTS acceptance requires the installed APK on the phone.
