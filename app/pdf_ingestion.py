import pymupdf as fitz
import hashlib
import uuid
from typing import List, Dict, Any, Tuple

def estimate_tokens(text: str) -> int:
    """Approximate token count based on word count (1 word ~ 1.33 tokens)"""
    words = text.split()
    return int(len(words) * 1.33)

def chunk_page_text(page_text: str, min_tokens: int = 400, max_tokens: int = 750) -> List[Tuple[int, int, str, int]]:
    """
    Splits page text into anchored chunks of roughly 500-800 tokens.
    Returns list of tuples: (start_char, end_char, chunk_text, token_count)
    """
    if not page_text or not page_text.strip():
        return []
    
    total_len = len(page_text)
    total_tokens = estimate_tokens(page_text)
    
    # If entire page fits in one chunk, return it whole
    if total_tokens <= max_tokens:
        return [(0, total_len, page_text, total_tokens)]
    
    # Otherwise split into paragraphs or sentences while keeping char indices
    chunks = []
    
    # Find paragraph split points
    paragraphs = []
    curr_pos = 0
    
    # Split by double newline first, fallback to single newline
    lines = page_text.split('\n')
    current_para = []
    para_start = 0
    
    pos = 0
    for line in lines:
        line_len = len(line) + 1  # +1 for newline character
        if line.strip() == '':
            if current_para:
                para_text = '\n'.join(current_para)
                paragraphs.append((para_start, pos, para_text))
                current_para = []
            para_start = pos + line_len
        else:
            if not current_para:
                para_start = pos
            current_para.append(line)
        pos += line_len
        
    if current_para:
        para_text = '\n'.join(current_para)
        paragraphs.append((para_start, min(pos, total_len), para_text))
        
    if not paragraphs:
        # Fallback if no paragraph structure detected
        paragraphs = [(0, total_len, page_text)]
        
    # Group paragraphs into chunks of ~500-800 tokens
    c_start = paragraphs[0][0]
    c_end = paragraphs[0][1]
    c_paras = [paragraphs[0][2]]
    
    for p_start, p_end, p_text in paragraphs[1:]:
        combined = "\n\n".join(c_paras + [p_text])
        combined_tokens = estimate_tokens(combined)
        
        if combined_tokens <= max_tokens:
            c_end = p_end
            c_paras.append(p_text)
        else:
            chunk_str = page_text[c_start:c_end]
            chunks.append((c_start, c_end, chunk_str, estimate_tokens(chunk_str)))
            c_start = p_start
            c_end = p_end
            c_paras = [p_text]
            
    if c_paras:
        chunk_str = page_text[c_start:c_end]
        chunks.append((c_start, c_end, chunk_str, estimate_tokens(chunk_str)))
        
    return chunks

def process_pdf_bytes(pdf_bytes: bytes, filename: str) -> Dict[str, Any]:
    """
    Parses PDF bytes using PyMuPDF, extracts page-anchored chunks, and generates doc metadata.
    """
    doc_hash = hashlib.sha256(pdf_bytes).hexdigest()
    doc_id = str(uuid.uuid4())
    
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_count = len(doc)
    
    all_chunks = []
    chunk_index = 0
    
    for page_num in range(page_count):
        page = doc[page_num]
        page_text = page.get_text("text")
        
        page_chunks = chunk_page_text(page_text)
        for start_c, end_c, text, tokens in page_chunks:
            all_chunks.append({
                "document_id": doc_id,
                "page_number": page_num + 1,  # 1-indexed
                "chunk_index": chunk_index,
                "text": text,
                "start_char": start_c,
                "end_char": end_c,
                "token_count": tokens
            })
            chunk_index += 1
            
    doc.close()
    
    return {
        "id": doc_id,
        "filename": filename,
        "file_hash": doc_hash,
        "page_count": page_count,
        "chunk_count": len(all_chunks),
        "chunks": all_chunks
    }
