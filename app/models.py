from pydantic import BaseModel
from typing import List, Optional, Any

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
    entity: str
    metric: str
    predicate: str
    value: str
    numeric_value: Optional[float] = None
    unit: Optional[str] = None
    normalized_value: Optional[float] = None
    normalized_unit: Optional[str] = None
    period: Optional[str] = None
    as_of_date: Optional[str] = None
    scope: Optional[str] = None
    qualifiers: Optional[str] = None
    raw_quote: str
    page: int
    extraction_confidence: float
    grounding_confidence: float
    final_confidence: float
    extraction_method: str = "llm"  # "llm" or "fallback"
    validation_status: str = "valid" # "valid" or "rejected"
    validation_notes: Optional[str] = None

class RejectedExtractionItem(BaseModel):
    id: Optional[int] = None
    document_id: str
    page: int
    candidate_text: str
    attempted_extraction: Optional[str] = None
    failure_type: str
    rejection_reason: str
    created_at: Optional[str] = None

class ExtractionResponse(BaseModel):
    doc_id: str
    facts_extracted_count: int
    rejected_count: int
    mode: str = "normal"  # "normal" or "degraded"
    warnings: List[str] = []
    facts: List[FactItem]
    rejected_extractions: List[RejectedExtractionItem] = []

class RelationshipItem(BaseModel):
    id: Optional[int] = None
    fact_id_a: int
    fact_id_b: int
    relationship_type: str  # CORROBORATES, CONTRADICTS, LIKELY_CONTRADICTION, RECONCILED, UNRELATED, UNCERTAIN
    reasoning: str
    confidence: float
    comparison_delta: float = 0.0
    reconciliation_type: str = "NONE" # UNIT_CONVERSION, ROUNDING, PERIOD_DIFFERENCE, SCOPE_DIFFERENCE, AUDIT_RESTATEMENT, NONE
    fact_a: Optional[FactItem] = None
    fact_b: Optional[FactItem] = None

class AnalysisResponse(BaseModel):
    candidate_pairs_evaluated: int
    relationships_found_count: int
    corroborations_count: int
    contradictions_count: int
    likely_contradictions_count: int
    reconciled_count: int
    unrelated_count: int
    uncertain_count: int
    relationships: List[RelationshipItem]

class AssignmentCasesResponse(BaseModel):
    corroborated_case: Optional[RelationshipItem] = None
    likely_contradiction_case: Optional[RelationshipItem] = None
    reconciled_case: Optional[RelationshipItem] = None
    extraction_failure_case: Optional[RejectedExtractionItem] = None
