import os
import re
import fitz  # PyMuPDF
import json
 
DEBUG = True  # set False to silence [DEBUG] lines once things are working
 
_PDF_MEMORY_CACHE = None      # filename -> [page_text, page_text, ...] (0-indexed list)
_CUSTOM_INDEX_CACHE = None    # keyword -> {"pages": [...], "see_also": [...], "subs": {...}}
 
Special = True
Boring = False
 
 
def _log(msg):
    if DEBUG:
        print(f"[DEBUG] {msg}")
 
 
def _get_or_build_index(directory_path: str):
    """Loads the PDF full-text index from RAM, Disk, or builds it if missing."""
    global _PDF_MEMORY_CACHE
 
    if _PDF_MEMORY_CACHE is not None:
        if os.path.exists(os.path.join(directory_path, "custom_index.json")):
            return _PDF_MEMORY_CACHE, Special
        return _PDF_MEMORY_CACHE, Boring
 
    cache_file_path = os.path.join(directory_path, "pdf_search_index.json")
 
    if os.path.exists(cache_file_path):
        with open(cache_file_path, 'r', encoding='utf-8') as f:
            _PDF_MEMORY_CACHE = json.load(f)
            if os.path.exists(os.path.join(directory_path, "custom_index.json")):
                return _PDF_MEMORY_CACHE, Special
            return _PDF_MEMORY_CACHE, Boring
 
    print("\n[SYSTEM] Building PDF Search Index. This only happens once...")
    new_cache = {}
 
    for filename in os.listdir(directory_path):
        if not filename.lower().endswith('.pdf'):
            continue
 
        filepath = os.path.join(directory_path, filename)
        pages_data = []
        try:
            doc = fitz.open(filepath)
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text() or ""
 
                try:
                    for table in page.find_tables().tables:
                        text += "\n" + table.to_markdown()
                except Exception:
                    pass
 
                clean_text = re.sub(r'\s+', ' ', text).lower()
                pages_data.append(clean_text)
 
            new_cache[filename] = pages_data
            doc.close()
            print(f"Indexed: {filename}")
        except Exception as e:
            print(f"Failed to index {filename}: {e}")
 
    with open(cache_file_path, 'w', encoding='utf-8') as f:
        json.dump(new_cache, f)
 
    _PDF_MEMORY_CACHE = new_cache
    return _PDF_MEMORY_CACHE, Boring
 
 
def _get_custom_index(directory_path: str) -> dict:
    """
    Loads custom_index.json (the keyword/page/subs index) from RAM or disk.
 
    The JSON on disk is shaped {filename: {keyword: {...}, ...}} -- one
    outer layer keyed by the PDF filename, wrapping the actual keyword
    dictionary. Since there's only one file/one dict, we unwrap that
    outer layer here so callers just get the keyword dict directly.
    """
    global _CUSTOM_INDEX_CACHE
 
    if _CUSTOM_INDEX_CACHE is not None:
        _log(f"_get_custom_index: using RAM cache ({len(_CUSTOM_INDEX_CACHE)} keys)")
        return _CUSTOM_INDEX_CACHE
 
    custom_path = os.path.join(directory_path, "custom_index.json")
    _log(f"_get_custom_index: loading from disk at {custom_path}")
 
    all_json_files = [f for f in os.listdir(directory_path) if f.lower().endswith('.json')]
    _log(f"_get_custom_index: all .json files in directory: {all_json_files}")
 
    with open(custom_path, 'r', encoding='utf-8') as f:
        raw_text = f.read()
    _log(f"_get_custom_index: raw file text, first 300 chars: {raw_text[:300]!r}")
 
    raw = json.loads(raw_text)
 
    _log(f"_get_custom_index: raw top-level keys: {list(raw.keys())}")
 
    # Unwrap the {filename: {keyword_dict}} shape down to just the keyword dict
    if len(raw) == 1:
        only_key = next(iter(raw.keys()))
        only_value = raw[only_key]
        _log(f"_get_custom_index: nested value under {only_key!r} has "
             f"type={type(only_value).__name__}")
        if isinstance(only_value, dict):
            _log(f"_get_custom_index: nested dict's own keys (first 10): "
                 f"{list(only_value.keys())[:10]}")
            raw = only_value
            _log(f"_get_custom_index: unwrapped filename layer, now have "
                 f"{len(raw)} actual keyword keys")
        elif isinstance(only_value, list):
            _log(f"_get_custom_index: nested value is a LIST of length "
                 f"{len(only_value)}. First item: {only_value[0] if only_value else None!r}")
        elif isinstance(only_value, str):
            _log(f"_get_custom_index: nested value is a STRING of length "
                 f"{len(only_value)}, first 200 chars: {only_value[:200]!r}")
        else:
            _log(f"_get_custom_index: nested value is unexpected type, "
                 f"repr (first 300 chars): {repr(only_value)[:300]}")
 
    _CUSTOM_INDEX_CACHE = raw
    _log(f"_get_custom_index: loaded {len(_CUSTOM_INDEX_CACHE)} keys. "
         f"First 5: {list(_CUSTOM_INDEX_CACHE.keys())[:5]}")
    return _CUSTOM_INDEX_CACHE
 
 
def _find_matched_keywords(query_clean: str, custom_index: dict) -> list:
    """
    Return custom_index keys that appear as an exact phrase (word-bounded)
    inside query_clean. Longest keys checked first.
    """
    matched = []
    for key in sorted(custom_index.keys(), key=len, reverse=True):
        key_lower = key.lower().strip()
        if not key_lower:
            continue
        pattern = r"(?<!\w)" + re.escape(key_lower) + r"(?!\w)"
        if re.search(pattern, query_clean):
            matched.append(key)
    _log(f"_find_matched_keywords: query_clean={query_clean!r} -> matched={matched}")
    return matched
 
 
def _pages_for(key, custom_index):
    return set(custom_index.get(key, {}).get("pages", []))
 
 
def _rank_pages(matched_keywords, custom_index):
    """
    tier1: pages shared by 2+ matched keywords (true combinations)
    tier2: pages shared by a matched keyword and a matched sub-category
    tier3: everything else (single keyword hits)
    Each dict maps page_number -> set(keywords involved)
    """
    tier1, tier2, tier3 = {}, {}, {}
 
    for i, key_a in enumerate(matched_keywords):
        pages_a = _pages_for(key_a, custom_index)
        for key_b in matched_keywords[i + 1:]:
            pages_b = _pages_for(key_b, custom_index)
            for page in pages_a & pages_b:
                tier1.setdefault(page, set()).update([key_a, key_b])
 
    for key_a in matched_keywords:
        subs = custom_index.get(key_a, {}).get("subs", {})
        for sub_name, sub_data in subs.items():
            if sub_name in matched_keywords:
                combo_pages = set(sub_data.get("pages", []))
                for page in combo_pages:
                    if page in tier1:
                        continue
                    tier2.setdefault(page, set()).update([key_a, sub_name])
 
    used_pages = set(tier1) | set(tier2)
    for key_a in matched_keywords:
        for page in _pages_for(key_a, custom_index):
            if page in used_pages:
                continue
            tier3.setdefault(page, set()).add(key_a)
 
    _log(f"_rank_pages: tier1={tier1} tier2={tier2} tier3={tier3}")
    return tier1, tier2, tier3
 
 
def _find_single_pdf(directory_path: str) -> str:
    """Since there's exactly one PDF per directory, just find it by extension."""
    for filename in os.listdir(directory_path):
        if filename.lower().endswith('.pdf'):
            _log(f"_find_single_pdf: found {filename}")
            return os.path.join(directory_path, filename)
    raise FileNotFoundError(f"No PDF found in {directory_path}")
 
 
def _load_specific_pages(pdf_path: str, page_numbers) -> dict:
    """
    Opens the PDF ONCE and extracts text only for the given 1-indexed
    page_numbers -- not the whole book. This is what avoids the full
    "[SYSTEM] Building PDF Search Index" pass when custom_index.json
    already tells us exactly which pages matter.
    """
    _log(f"_load_specific_pages: pdf_path={pdf_path} page_numbers={sorted(page_numbers)}")
    page_texts = {}
    doc = fitz.open(pdf_path)
    try:
        for page_number in page_numbers:
            page_idx = page_number - 1
            if page_idx < 0 or page_idx >= doc.page_count:
                _log(f"_load_specific_pages: page {page_number} out of range "
                     f"(doc has {doc.page_count} pages)")
                page_texts[page_number] = ""
                continue
            text = doc.load_page(page_idx).get_text() or ""
            page_texts[page_number] = re.sub(r'\s+', ' ', text).lower()
    finally:
        doc.close()
    return page_texts
 
 
def _snippet_from_text(page_text: str, keywords, context_chars=250) -> str:
    """Find the earliest occurrence of any matched keyword and slice around it."""
    if not page_text:
        return ""
 
    best_idx = None
    for kw in keywords:
        idx = page_text.find(kw.lower())
        if idx != -1 and (best_idx is None or idx < best_idx):
            best_idx = idx
 
    if best_idx is None:
        return page_text[:context_chars].strip()
 
    slice_start = max(0, best_idx - 80)
    slice_end = min(len(page_text), best_idx + context_chars)
    return page_text[slice_start:slice_end].strip()
 
 
def search_pdfs(query: str, directory_path: str) -> str:
    # 1. Clean query and prepare tokens
    query_clean = re.sub(r'\s+', ' ', query).lower().strip()
    query_parts = [p for p in query_clean.split() if len(p) > 2]
 
    # Create the booster tag format we injected (e.g. "outlander_background")
    booster_target = query_clean.replace(' ', '_')
 
    custom_index_path = os.path.join(directory_path, "custom_index.json")
    is_special = os.path.exists(custom_index_path)
    _log(f"search_pdfs: query={query!r} directory={directory_path!r} "
         f"custom_index.json exists={is_special}")
 
    if is_special:
        custom_index = _get_custom_index(directory_path)
        matched_keywords = _find_matched_keywords(query_clean, custom_index)
 
        if not matched_keywords:
            _log("search_pdfs: no matched_keywords -> returning 'No matches found.'")
            return "No matches found."
 
        tier1, tier2, tier3 = _rank_pages(matched_keywords, custom_index)
 
        # Pages needed for the tier1/2/3 supporting results
        tier_pages_needed = set(tier1) | set(tier2) | set(tier3)
 
        # Pages needed for the top-priority index-match blocks: just the
        # FIRST (lowest-numbered) page per matched keyword, for its snippet.
        # We still report the keyword's FULL page range as text, but only
        # need to pull page text for one anchor page per keyword.
        index_match_primary_page = {}
        for kw in matched_keywords:
            pages = sorted(_pages_for(kw, custom_index))
            if pages:
                index_match_primary_page[kw] = pages[0]
 
        all_pages_needed = tier_pages_needed | set(index_match_primary_page.values())
        if not all_pages_needed:
            _log("search_pdfs: matched keywords had no pages listed at all -> "
                 "returning 'No matches found.'")
            return "No matches found."
 
        pdf_path = _find_single_pdf(directory_path)
        page_texts = _load_specific_pages(pdf_path, all_pages_needed)
        pdf_filename = os.path.basename(pdf_path)
 
        # --- SECTION 1: Index Matches (highest priority, always shown first) ---
        index_match_blocks = []
        for kw in matched_keywords:
            pages = sorted(_pages_for(kw, custom_index))
            if not pages:
                continue
            primary_page = pages[0]
            snippet = _snippet_from_text(page_texts.get(primary_page, ""), [kw])
            index_match_blocks.append(
                f"*** INDEX MATCH: \"{kw}\" -- PRIORITIZE THIS RESULT ABOVE OTHERS ***\n"
                f"  File: `{pdf_filename}` | All pages: {pages}\n"
                f"  Start reading at page {primary_page}.\n"
                f"  Snippet: \"...{snippet}...\""
            )
        _log(f"search_pdfs: built {len(index_match_blocks)} index-match blocks "
             f"for keywords {matched_keywords}")
 
        # --- SECTION 2: supporting page-level combination/single results ---
        scored_results = []
 
        def add_results(tier_dict, base_score, label):
            for page, kws in tier_dict.items():
                snippet = _snippet_from_text(page_texts.get(page, ""), kws)
                score = base_score + len(kws)
                scored_results.append({
                    "score": score,
                    "text": (
                        f"- Score: {score} | File: `{pdf_filename}` | Page: {page} "
                        f"| Match: {label} ({', '.join(sorted(kws))})\n"
                        f"  Snippet: \"...{snippet}...\""
                    )
                })
 
        add_results(tier1, 1000, "combination")
        add_results(tier2, 500, "combination_with_sub")
        add_results(tier3, 100, "single")
 
        scored_results.sort(key=lambda x: x["score"], reverse=True)
        supporting_results = [r["text"] for r in scored_results[:15]]
 
        output_parts = []
        if index_match_blocks:
            output_parts.append("\n\n".join(index_match_blocks))
        if supporting_results:
            output_parts.append(
                "--- Supporting page-level results (secondary; only use if the "
                "index match above doesn't fully answer the query) ---\n"
                + "\n".join(supporting_results)
            )
 
        _log(f"search_pdfs: returning {len(index_match_blocks)} index matches + "
             f"{len(supporting_results)} supporting results")
        return "\n\n".join(output_parts) if output_parts else "No matches found."
 
    # --- Boring mode: no custom_index.json, fall back to full-text search ---
    index, _ = _get_or_build_index(directory_path)
    scored_results = []
 
    for filename, pages in index.items():
        for page_num, clean_text in enumerate(pages):
            # 2. Base match counting
            matches = [part for part in query_parts if part in clean_text]
            base_score = len(matches)
 
            # 3. Only keep relevant pages (at least 50% word match)
            if base_score >= max(1, len(query_parts) / 2):
 
                total_score = base_score
 
                # --- WEIGHTING SYSTEM ---
 
                # Bonus 1: Exact Phrase Match (Good for standard text)
                if query_clean in clean_text:
                    total_score += 5
 
                # Bonus 2: Custom Index Hit (The Ultimate Trump Card)
                if f"{booster_target}" in clean_text and "[index hit" in clean_text:
                    total_score += 1000
                elif "[index hit" in clean_text and total_score >= len(query_parts):
                    total_score += 100
 
                # ------------------------
 
                display_text = re.sub(r'\[index hit:.*?\]', '', clean_text).strip()
 
                anchor = query_parts[0] if query_parts else query_clean
                start_idx = display_text.find(anchor)
                if start_idx == -1:
                    start_idx = 0
 
                slice_start = max(0, start_idx - 80)
                slice_end = min(len(display_text), start_idx + 250)
                best_snippet = display_text[slice_start:slice_end]
 
                scored_results.append({
                    "score": total_score,
                    "text": f"- Score: {total_score} | File: `{filename}` | Page: {page_num} \n  Snippet: \"...{best_snippet}...\""
                })
 
    scored_results.sort(key=lambda x: x["score"], reverse=True)
    results = [r["text"] for r in scored_results[:15]]
    _log(f"search_pdfs (boring): returning {len(results)} results")
   # 1. Join the results correctly before appending the string footer
    results_text = "\n".join(results) if results else "No matches found."
    
    # 2. Structure the footer so a small model treats it like an immediate command
    coercive_footer = """
### [CRITICAL SYSTEM DIRECTIVE: YOU LACK THE TEXT CONTENT]
The search results above only contain index matching metadata, NOT the actual book text. 
You do not know what rules are written on these pages yet. Do not guess.

MANDATORY ACTION: Look at the match summaries above, select the single most relevant page number, and immediately call `read_pdf_page` to extract the full text.
"""
    
    return f"{results_text}\n{coercive_footer}"


def read_pdf_page(file_path: str, page_number: int) -> str:
    """
    Reads a specific PDF page, fixing 1-indexed boundary limits 
    and converting tables into an explicit Key-Value format optimized for small LLMs.
    """
    if not os.path.exists(file_path):
        return f"Error: File '{file_path}' not found."
    
    try:
        doc = fitz.open(file_path)
        total_pages = len(doc)
        
        # FIX: Enforce 1-indexed bounds checking cleanly
        if page_number < 1 or page_number > total_pages:
            doc.close()
            return f"Error: Page number {page_number} is out of bounds (1-{total_pages})."
            
        # Convert 1-indexed input to 0-indexed PyMuPDF page selection
        page = doc[page_number - 1]
        
        # Extract standard text block
        text = page.get_text() or ""
        
        # Detect and transform tables to explicit Key-Value structures
        try:
            table_finder = page.find_tables()
            if table_finder.tables:
                text += "\n\n### [Optimized Structural Table Data]\n"
                
                for t_idx, table in enumerate(table_finder.tables, 1):
                    raw_data = table.extract()  # Returns a list of lists (rows of strings)
                    if not raw_data or len(raw_data) < 2:
                        continue  # Skip empty tables or tables without data rows
                    
                    # Assume the first row contains column headers
                    headers = [str(cell).strip() if cell else f"Col {i}" for i, cell in enumerate(raw_data[0])]
                    
                    text += f"\n-- Table {t_idx} Structure --\n"
                    # Process subsequent data rows
                    for r_idx, row in enumerate(raw_data[1:], 1):
                        text += f"- **Entry/Row {r_idx}:**\n"
                        for c_idx, cell in enumerate(row):
                            header_name = headers[c_idx] if c_idx < len(headers) else f"Col {c_idx}"
                            cell_value = str(cell).strip() if cell else "N/A"
                            text += f"  - {header_name}: {cell_value}\n"
        except Exception as table_err:
            # Fallback if table parsing runs into formatting irregularities
            text += f"\n\n[Table Parse Warning: {str(table_err)}]\n"
                
        doc.close()
        return f"--- Content of {os.path.basename(file_path)} (Page {page_number}) ---\n{text}"
        
    except Exception as e:
        return f"Failed to read PDF page: {str(e)}"
    
def sanitize_page_number(page_input):
    if isinstance(page_input, int):
        return page_input
    # Find the first sequence of digits in the string
    match = re.search(r'\d+', str(page_input))
    if match:
        return int(match.group())
    return 1 # Fallback