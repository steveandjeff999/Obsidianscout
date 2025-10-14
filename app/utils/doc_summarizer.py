"""Utility to read and summarize local help/docs files.

This is a lightweight, local-only summarizer that extracts headings,
first paragraphs, and produces a short summary and simple citations
pointing to the original file and an excerpt (line range).

The goal is to give the assistant the ability to "read, summarize, and cite"
help docs without external AI calls. It is intentionally simple and
deterministic.
"""
from typing import Dict, Any, List, Tuple
import os
import re
import difflib


def _read_file_lines(path: str) -> List[str]:
    with open(path, encoding='utf-8') as f:
        return f.read().splitlines()


def extract_headings_and_intro(lines: List[str], max_intro_lines: int = 6) -> Tuple[List[str], str, Tuple[int,int]]:
    """Return the list of markdown headings, an intro excerpt and its line range.

    Returns:
        headings: list of heading strings (without markdown markers)
        intro: short intro text (joined first paragraph or first N lines)
        (start_line, end_line): 1-based inclusive line numbers of the intro in the file
    """
    headings = []
    intro_lines: List[str] = []
    in_intro = True
    intro_start = None

    # collect headings and first paragraph
    for idx, line in enumerate(lines):
        line_stripped = line.strip()
        # headings
        if re.match(r'^(#{1,6})\s+', line_stripped):
            headings.append(re.sub(r'^(#{1,6})\s+', '', line_stripped))
        # first non-empty paragraph as intro
        if in_intro:
            if line_stripped:
                if intro_start is None:
                    intro_start = idx + 1
                intro_lines.append(line.rstrip())
                if len(intro_lines) >= max_intro_lines:
                    break
            else:
                # stop at first blank line after we've started collecting
                if intro_lines:
                    break

    if not intro_lines:
        intro = ''
        intro_range = (1, 1)
    else:
        intro = '\n'.join(intro_lines).strip()
        intro_range = (intro_start, intro_start + len(intro_lines) - 1)

    return headings, intro, intro_range


def parse_markdown_sections(lines: List[str]) -> List[Dict[str, Any]]:
    """Parse markdown into sections: each with heading (or None for intro) and content lines.

    Returns a list of dicts: { 'heading': str|None, 'lines': [..], 'start': int, 'end': int }
    """
    sections: List[Dict[str, Any]] = []
    current = {'heading': None, 'lines': [], 'start': 1}

    heading_re = re.compile(r'^(#{1,6})\s+(.*)')
    for idx, line in enumerate(lines):
        m = heading_re.match(line.strip())
        if m:
            # finish current
            if current['lines']:
                current['end'] = idx
                sections.append(current)
            # start new
            current = {'heading': m.group(2).strip(), 'lines': [], 'start': idx+1}
        else:
            current['lines'].append(line.rstrip())

    # final section
    current['end'] = len(lines)
    sections.append(current)
    return sections


def _first_sentences(text: str, num: int = 1) -> List[str]:
    # naive sentence splitter - keep it simple and robust
    parts = re.split(r'(?<=[\.\?!])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()][:num]


def _extractive_summary(text: str, num_sentences: int = 3) -> str:
    """Simple extractive summarizer: score sentences by word frequency.

    This avoids returning only metadata lines like 'Version' or headings.
    """
    if not text or not text.strip():
        return ''

    # normalize text
    text = text.replace('\n', ' ').strip()
    # split into sentences
    sentences = re.split(r'(?<=[\.\?!])\s+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if len(sentences) <= num_sentences:
        return ' '.join(sentences)

    # build frequency table of words excluding stopwords and short tokens
    stopwords = set([
        'the', 'and', 'is', 'in', 'to', 'of', 'a', 'an', 'for', 'on', 'that', 'this', 'with', 'as', 'are', 'be'
    ])
    word_freq = {}
    for sent in sentences:
        for w in re.findall(r"\w+", sent.lower()):
            if w in stopwords or len(w) < 3:
                continue
            word_freq[w] = word_freq.get(w, 0) + 1

    if not word_freq:
        return ' '.join(sentences[:num_sentences])

    # score sentences
    sent_scores = []
    for idx, sent in enumerate(sentences):
        score = 0
        for w in re.findall(r"\w+", sent.lower()):
            score += word_freq.get(w, 0)
        # penalize very short sentences and headings/metadata-looking sentences
        if len(sent) < 30:
            score *= 0.7
        if re.match(r'^\*{0,2}version', sent.lower()) or re.match(r'^#', sent.strip()):
            score *= 0.2
        sent_scores.append((idx, score, sent))

    # choose top sentences by score, then preserve original order
    top = sorted(sent_scores, key=lambda x: x[1], reverse=True)[:num_sentences]
    top_idxs = sorted([t[0] for t in top])
    summary = ' '.join([sentences[i] for i in top_idxs])
    return summary


def summarize_markdown_file(path: str, max_sentences: int = 3) -> Dict[str, Any]:
    """Summarize a markdown file and return summary + simple citations.

    Output shape:
      {
        'file': <basename>,
        'title': <title inferred from filename or first heading>,
        'summary': <short text summary>,
        'headings': [ ... ],
        'citation': { 'file_path': ..., 'excerpt': ..., 'lines': (start, end) }
      }
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    lines = _read_file_lines(path)

    sections = parse_markdown_sections(lines)

    # derive title: prefer first heading, else filename
    title = os.path.basename(path).replace('.md', '').replace('_', ' ').replace('-', ' ').title()
    if sections and sections[0].get('heading'):
        title = sections[0]['heading']

    # Build summary using extractive summarizer on combined content to avoid metadata-only summaries
    all_text_parts: List[str] = []
    citations: List[Dict[str, Any]] = []
    for s in sections:
        sec_text = '\n'.join(s['lines']).strip()
        if not sec_text:
            continue
        # skip short metadata-like lines that contain 'version' only
        if re.match(r'^\*{0,2}version', sec_text.lower()) and len(sec_text.splitlines()) < 3:
            continue
        all_text_parts.append((s, sec_text))

    combined_text = '\n'.join([t[1] for t in all_text_parts])
    summary = _extractive_summary(combined_text, num_sentences=max_sentences)

    # build citations: prefer the section that contributed the most words to the selected summary
    # naive approach: find which section contains the first summary sentence
    first_sent = _first_sentences(summary, num=1)[0] if summary else ''
    citation = None
    for s, text in all_text_parts:
        if first_sent and first_sent in text:
            # build an excerpt containing up to 2 paragraphs around the matched sentence
            # split section text into paragraphs
            paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
            excerpt = ''
            excerpt_start_line = s['start']
            excerpt_end_line = s['end']

            if paras:
                # find which paragraph contains the first_sent
                found_para_idx = None
                para_line_offsets = []
                cur_line = 0
                # compute approximate line offsets for each paragraph within section lines
                for p in paras:
                    para_lines = p.count('\n') + 1
                    para_line_offsets.append((cur_line, cur_line + para_lines - 1))
                    cur_line += para_lines

                for i, p in enumerate(paras):
                    if first_sent and first_sent in p:
                        found_para_idx = i
                        break

                if found_para_idx is None:
                    # fallback: use first two paragraphs
                    excerpt = '\n\n'.join(paras[:2])
                    # approximate line numbers: start at section start
                    excerpt_start_line = s['start']
                    excerpt_end_line = min(s['start'] + excerpt.count('\n'), s['end'])
                else:
                    # include that paragraph and one neighbor if available
                    start = max(0, found_para_idx - 1)
                    end = min(len(paras), found_para_idx + 2)
                    excerpt = '\n\n'.join(paras[start:end])
                    # compute line numbers by summing lines of preceding paragraphs
                    start_line_offset = para_line_offsets[start][0]
                    excerpt_start_line = s['start'] + start_line_offset
                    excerpt_end_line = min(s['start'] + para_line_offsets[end-1][1], s['end'])
            else:
                # no paragraph breaks detected: fall back to selecting a window of lines around the matched sentence
                section_lines = s.get('lines', [])
                # find index of the line that contains first_sent
                found_line_idx = None
                if first_sent:
                    for i, ln in enumerate(section_lines):
                        if first_sent in ln:
                            found_line_idx = i
                            break
                if found_line_idx is None:
                    # fallback: take the first 6 lines
                    start_idx = 0
                else:
                    # center window around found_line_idx
                    start_idx = max(0, found_line_idx - 2)
                end_idx = min(len(section_lines), start_idx + 6)
                excerpt_lines_list = section_lines[start_idx:end_idx]
                excerpt = '\n'.join(excerpt_lines_list).strip()
                excerpt_start_line = s['start'] + start_idx
                excerpt_end_line = s['start'] + end_idx - 1

            citation = {
                'file_path': path,
                'lines': (excerpt_start_line, excerpt_end_line),
                'excerpt': excerpt
            }
            break
    if not citation and all_text_parts:
        s = all_text_parts[0][0]
        citation = {'file_path': path, 'lines': (s['start'], min(s['start'] + 3, s['end'])), 'excerpt': '\n'.join(s['lines'][:3]).strip()}

    # Return the extractive summary and the chosen citation (or a simple fallback)
    if not citation:
        citation = {'file_path': path, 'lines': (1, 1), 'excerpt': ''}

    return {
        'file': os.path.basename(path),
        'title': title,
        'summary': summary,
        'headings': [s['heading'] for s in sections if s.get('heading')],
        'citation': citation
    }


def summarize_help_folder(help_folder: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Summarize up to `limit` markdown files found in a help folder.

    The function ignores non-markdown files.
    """
    results = []
    if not os.path.isdir(help_folder):
        raise NotADirectoryError(help_folder)

    files = [f for f in os.listdir(help_folder) if f.lower().endswith('.md')]
    files = sorted(files)[:limit]
    for f in files:
        path = os.path.join(help_folder, f)
        try:
            results.append(summarize_markdown_file(path))
        except Exception:
            # skip files that fail to read or parse
            continue

    return results


def summarize_text(text: str, max_sentences: int = 2) -> str:
    """Public wrapper to summarize arbitrary text using the extractive summarizer."""
    return _extractive_summary(text, num_sentences=max_sentences)


def semantic_search_sections(query: str, help_folder: str, top_n: int = 3) -> List[Dict[str, Any]]:
    """Search help folder sections for the best matches for a query.

    Returns a list of dicts: { 'score': float, 'file': filename, 'section_heading': heading, 'section_text': text, 'start': int, 'end': int }
    Uses scikit-learn TF-IDF + cosine similarity when available, otherwise falls back to difflib matching against headings and filenames.
    """
    # collect sections from all markdown files
    docs = []
    for f in sorted(os.listdir(help_folder)):
        if not f.lower().endswith('.md'):
            continue
        path = os.path.join(help_folder, f)
        try:
            lines = _read_file_lines(path)
        except Exception:
            continue
        sections = parse_markdown_sections(lines)
        for s in sections:
            text = '\n'.join(s['lines']).strip()
            if not text:
                continue
            docs.append({'file': f, 'path': path, 'heading': s.get('heading'), 'text': text, 'start': s['start'], 'end': s['end']})

    if not docs:
        return []

    q = query.strip()

    # Try TF-IDF similarity if sklearn is installed
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        corpus = [d['text'] for d in docs]
        vect = TfidfVectorizer(stop_words='english').fit(corpus + [q])
        X = vect.transform(corpus)
        qv = vect.transform([q])
        sims = cosine_similarity(qv, X)[0]
        scored = []
        for i, s in enumerate(sims):
            if s > 0:
                scored.append((s, docs[i]))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, d in scored[:top_n]:
            results.append({'score': float(score), 'file': d['file'], 'path': d['path'], 'section_heading': d['heading'], 'section_text': d['text'], 'start': d['start'], 'end': d['end']})
        return results
    except Exception:
        # fallback: compare query to heading + filename using difflib
        scored = []
        for d in docs:
            keys = []
            if d['heading']:
                keys.append(d['heading'])
            keys.append(d['file'])
            # include some of the text as a short string
            keys.append(' '.join(d['section_text'].split()[:30]) if 'section_text' in d else ' '.join(d['text'].split()[:30]))
            best = 0.0
            for k in keys:
                try:
                    score = difflib.SequenceMatcher(None, q.lower(), k.lower()).ratio()
                except Exception:
                    score = 0.0
                if score > best:
                    best = score
            if best > 0.45:
                scored.append((best, d))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, d in scored[:top_n]:
            results.append({'score': float(score), 'file': d['file'], 'path': d['path'], 'section_heading': d['heading'], 'section_text': d['text'], 'start': d['start'], 'end': d['end']})
        return results
