from pydantic import BaseModel
from typing import List, Optional

class UploadResponse(BaseModel):
    doc_id: str
    filename: str
    page_count: int
    chunk_count: int
    message: str

class ChunkResponse(BaseModel):
    id: int
    document_id: str
    page_number: int
    chunk_index: int
    text: str
    start_char: int
    end_char: int
    token_count: int

class DocumentResponse(BaseModel):
    id: str
    filename: str
    file_hash: str
    upload_timestamp: str
    page_count: int
    chunk_count: int

class FactItem(BaseModel):
    id: Optional[int] = None
    document_id: str
    chunk_id: int
    subject: str
    predicate: str
    value: str
    unit: Optional[str] = None
    time_scope: Optional[str] = None
    raw_quote: str
    page: int
    extraction_confidence: float
    grounding_confidence: float
    final_confidence: float

class ExtractionResponse(BaseModel):
    doc_id: str
    facts_extracted_count: int
    facts: List[FactItem]

class RelationshipItem(BaseModel):
    id: Optional[int] = None
    fact_id_a: int
    fact_id_b: int
    relationship_type: str
    reasoning: str
    confidence_delta: float
    fact_a: Optional[FactItem] = None
    fact_b: Optional[FactItem] = None

class AnalysisResponse(BaseModel):
    candidate_pairs_evaluated: int
    relationships_found_count: int
    corroborations_count: int
    contradictions_count: int
    reconciled_count: int
    relationships: List[RelationshipItem]
