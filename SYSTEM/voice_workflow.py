"""Conservative field dictation cleanup and explicit closeout intent matching.

No inferred work, materials, measurements, billing quantities, or missing facts.
Ambiguous corrections remain visible for review, with the original transcript kept.
"""
import json
import re
from datetime import datetime
from record_editor import RECORD_LOCK, Conflict, folder_for, atomic_text
from note_store import read_note, save_note

CLOSE_LABELS = {
    'FIBER TRANSFER COMPLETED': 'Fiber transfer completed',
    'TRANSFER ALREADY COMPLETED': 'Transfer already completed',
    'NO IDENTIFIABLE WINDSTREAM LINE ON POLE': 'No identifiable Windstream line',
    'NO SERVICES ON POLE': 'No services on pole',
    'ADSS': 'ADSS',
    'NO WINDSTREAM VIOLATION': 'No Windstream violation',
    'UNABLE TO COMPLETE': 'Unable to complete · reason required',
    'PENDING': 'Pending / return needed',
}
CORRECTION = re.compile(r'\b(?:sorry\s*[,;:]?\s*(?:i\s+mean\s*)?|i\s+mean\s+|correction\s*[,;:]?\s*|scratch\s+that\s*[,;:]?\s*|let\s+me\s+correct\s+that\s*[,;:]?\s*)', re.I)
TOKEN = re.compile(r"\b[\w'-]+\b")
NUMBERS = set('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty hundred'.split())
MATERIALS = {'copper', 'fiber', 'fibre', 'coax', 'strand', 'adss'}


def _tokens(text):
    return [m.group().lower() for m in TOKEN.finditer(text)]


def _replace_correction(before, after):
    # Keep previous complete sentences and independent clauses intact.
    before = before.rstrip(' ,;:-—')
    after = after.lstrip(' ,;:-—')
    if not before or not after:
        return None
    boundary = max(before.rfind('. '), before.rfind('! '), before.rfind('? '))
    prefix, clause = (before[:boundary + 2], before[boundary + 2:]) if boundary >= 0 else ('', before)
    # A repeated sentence subject provides an explicit replacement boundary.
    new_words = _tokens(after)
    old_words = _tokens(clause)
    if not new_words or not old_words:
        return None
    common = 0
    for a, b in zip(old_words, new_words):
        if a != b: break
        common += 1
    independent = bool(re.search(r'\band\b', clause, re.I)) and not re.search(r'\band\b', after, re.I)
    if common >= 2 and not independent and new_words[0] in {'there', 'the', 'this', 'that', 'it', 'i', 'we', 'no'}:
        return prefix + after
    if common == 1 and not independent and len(new_words) >= 3 and new_words[0] in {'i', 'we', 'it', 'there'}:
        return prefix + after
    # Identify a restated subordinate clause without discarding earlier observations.
    if len(new_words) >= 3:
        anchor = ' '.join(new_words[:2])
        matches = list(re.finditer(r'\b' + r'\s+'.join(map(re.escape, new_words[:2])) + r'\b', clause, re.I))
        if len(matches) == 1 and new_words[0] in {'there', 'the', 'this', 'it', 'i', 'we', 'no'}:
            if matches[0].start() > 0 or not independent:
                return prefix + clause[:matches[0].start()] + after
    # Explicit same-unit restatement: "two photos, sorry, three photos".
    first_sentence = re.split(r'(?<=[.!?])\s+', after, maxsplit=1)[0]
    corrected = _tokens(first_sentence)
    if 2 <= len(corrected) <= 6 and len(old_words) >= len(corrected):
        number = corrected[0].isdigit() or corrected[0] in NUMBERS
        if number and old_words[-len(corrected)+1:] == corrected[1:]:
            old_first = old_words[-len(corrected)]
            if old_first.isdigit() or old_first in NUMBERS:
                spans = list(TOKEN.finditer(clause))
                return prefix + clause[:spans[-len(corrected)].start()] + after
    # Short, unambiguous material correction with shared location words.
    if corrected and corrected[0] in MATERIALS:
        spans = list(TOKEN.finditer(clause))
        material_spans = [m for m in spans if m.group().lower() in MATERIALS]
        if len(material_spans) == 1:
            m = material_spans[0]
            tail = _tokens(clause[m.end():])
            if corrected[1:] == tail and not re.search(r'\b(?:not|no|without)\b',clause,re.I):
                return prefix + clause[:m.start()] + after
    return None


def clean_note(transcript):
    if not isinstance(transcript, str) or not transcript.strip() or len(transcript) > 10000:
        raise ValueError('No usable notes were heard')
    text = transcript.strip()
    if re.fullmatch(r'(?:no notes(?: needed)?|skip notes|nothing to add)[.!]?', text, re.I):
        return {'note': '', 'needs_review': False, 'review_reason': ''}
    # Never remove hedges ("I think", "maybe", "looks like") or comparative "like".
    text = re.sub(r'\b(?:u+m+|u+h+|e+rm+|hmm+)\b\s*[,;]?\s*', '', text, flags=re.I)
    text = re.sub(r'\byou know\s*[,;]?\s*', '', text, flags=re.I)
    text = re.sub(r'^(?:(?:okay|ok|well|so)\s*[,;:]?\s+)+', '', text, flags=re.I)
    text = re.sub(r'\b(the|a|an|and|there|we|i)\s+\1\b', r'\1', text, flags=re.I)
    parts = CORRECTION.split(text)
    result = parts[0]
    ambiguous = False
    for part in parts[1:]:
        replacement = _replace_correction(result, part)
        if replacement is None:
            ambiguous = True
            result = result.rstrip(' ,;:-') + '; correction: ' + part.strip()
        else:
            result = replacement
    result = re.sub(r'\s+', ' ', result).strip(' ,;:')
    result = re.sub(r'\s+([,.!?;:])', r'\1', result)
    result = re.sub(r'([,;])\s*\1+', r'\1', result)
    # Remove only an explicit first-person reporting lead; retain uncertainty.
    result = re.sub(r'^I (checked|found|observed|confirmed|surveyed)\b', lambda m:m.group(1).capitalize(), result, flags=re.I)
    result = re.sub(r'\bwindstream\b', 'Windstream', result, flags=re.I)
    result = re.sub(r'\ba[.\s-]*d[.\s-]*s[.\s-]*s\b', 'ADSS', result, flags=re.I)
    if result:
        result = re.sub(r'([.!?]\s+)([a-z])', lambda m:m.group(1)+m.group(2).upper(), result)
        result = result[0].upper() + result[1:]
        if result[-1] not in '.!?': result += '.'
    if not result:
        raise ValueError('Only filler was heard; enter a note or say no notes')
    return {'note': result, 'needs_review': ambiguous,
            'review_reason': 'A correction was unclear. Review the marked correction against what you said.' if ambiguous else ''}


def match_close(transcript):
    if not isinstance(transcript, str) or not transcript.strip() or len(transcript) > 1000:
        raise ValueError('No closing task was heard')
    # For an explicit corrected choice, use only the final named choice.
    text = CORRECTION.split(transcript)[-1].lower()
    text = re.sub(r'\ba[.\s-]*d[.\s-]*s[.\s-]*s\b', 'adss', text)
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if re.search(r'\b(?:not|isn t|wasn t|don t|unsure|maybe|either)\b', text):
        return {'close': None, 'message': 'The closing task is uncertain. Name one close option or choose it below.'}
    candidates = set()
    if re.search(r'\badss\b', text): candidates.add('ADSS')
    if re.search(r'\balready\s+(?:been\s+)?(?:complete[ds]?|transferred|done)\b', text): candidates.add('TRANSFER ALREADY COMPLETED')
    if re.search(r'\bno\s+windstream\s+violations?\b', text): candidates.add('NO WINDSTREAM VIOLATION')
    if re.search(r'\bno\s+(?:identifiable\s+)?windstream(?:\s+lines?)?\b', text) and 'NO WINDSTREAM VIOLATION' not in candidates: candidates.add('NO IDENTIFIABLE WINDSTREAM LINE ON POLE')
    if re.search(r'\bunable\s+to\s+complete\b', text): candidates.add('UNABLE TO COMPLETE')
    if re.search(r'\bno\s+services?\b', text): candidates.add('NO SERVICES ON POLE')
    if re.search(r'\bpending\b|\breturn\s+(?:needed|required|visit)\b|\bneed\s+to\s+return\b', text): candidates.add('PENDING')
    if 'TRANSFER ALREADY COMPLETED' not in candidates and re.search(r'\b(?:fiber\s+)?transfer\s+(?:is\s+|was\s+)?(?:completed?|done|finished)\b|\b(?:we|i)\s+(?:completed|finished)\s+(?:the\s+)?transfer\b', text):
        candidates.add('FIBER TRANSFER COMPLETED')
    if len(candidates) != 1:
        return {'close': None, 'message': 'Name one closing task or choose an option below.'}
    close = candidates.pop()
    return {'close': close, 'label': CLOSE_LABELS[close], 'message': 'Review the note and closing task, then finalize.'}


def save_voice_note(app, job, ju, transcript, expected_note):
    cleaned = clean_note(transcript)
    with RECORD_LOCK:
        if (job,ju) != (app['active_job'],app['active_ju']):
            raise Conflict('The active JU changed. Reopen closeout for the current JU. The transcript is kept on this screen.')
        folder = folder_for(app,job,ju)
        if read_note(folder) != expected_note:
            raise Conflict('The note changed while you were speaking. Your existing note was kept; review your transcript below.')
        history = folder/'VOICE_HISTORY';history.mkdir(exist_ok=True)
        audit = {'job':job,'ju':ju,'transcript':transcript,'previous_note':expected_note,**cleaned}
        atomic_text(history/(datetime.now().strftime('%Y%m%dT%H%M%S%f')+'.json'),json.dumps(audit,ensure_ascii=False))
        save_note(folder,cleaned['note'])
    return {'ok':True,**cleaned}
