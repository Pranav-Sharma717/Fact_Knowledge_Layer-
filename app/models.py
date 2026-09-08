from pydantic import BaseModel
from typing import List, Optional, Any, Dict

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
    extraction_confidence: float = 1.0
    grounding_confidence: float = 1.0
    value_binding_confidence: float = 1.0
    final_confidence: float = 1.0
    value_type: str = "UNKNOWN"  # MONEY, PERCENT, COUNT, QUANTITY, SHARE_COUNT, SEMANTIC, UNKNOWN
    is_numeric: bool = True
    value_source_span: Optional[str] = None
    metric_source_span: Optional[str] = None
    temporal_source_span: Optional[str] = None
    extraction_method: str = "llm"  # "llm", "table", "fallback"
    validation_status: str = "valid" # "valid" or "rejected"
    validation_notes: Optional[str] = None
    subject: Optional[str] = None

class RejectedExtractionItem(BaseModel):
    id: Optional[int] = None
    document_id: str
    page: int
    candidate_text: str
    attempted_extraction: Optional[str] = None
    failure_type: str
    rejection_reason: str
    created_at: Optional[str] = None

class RelationshipItem(BaseModel):
    id: Optional[int] = None
    fact_id_a: int
    fact_id_b: int
    relationship_type: str  # CORROBORATES, CONTRADICTS, LIKELY_CONTRADICTION, CONTEXTUAL_DIFFERENCE, RECONCILED_UNIT, RECONCILED_ROUNDING, RECONCILED_SCOPE, UNCERTAIN, UNRELATED
    taxonomy_category: str = "UNCERTAIN"
    reasoning: str
    confidence: float
    comparison_delta: float = 0.0
    can_compute_delta: bool = False
    reconciliation_type: str = "NONE" # UNIT_CONVERSION, ROUNDING, PERIOD_DIFFERENCE, SCOPE_DIFFERENCE, AUDIT_RESTATEMENT, NONE
    match_checklist: List[str] = []
    fact_a: Optional[FactItem] = None
    fact_b: Optional[FactItem] = None

class AnalysisResponse(BaseModel):
    candidate_pairs_evaluated: int
    relationships_found_count: int
    corroborations_count: int
    contradictions_count: int
    likely_contradictions_count: int
    contextual_differences_count: int
    reconciled_count: int
    unrelated_count: int
    uncertain_count: int
    relationships: List[RelationshipItem]
    quality_summary: Optional[Dict[str, Any]] = None

class GroupedRejectedResponse(BaseModel):
    total_rejected: int
    grouped_counts: Dict[str, int]
    groups: Dict[str, List[RejectedExtractionItem]]

class AssignmentCasesResponse(BaseModel):
    corroborated_case: Optional[RelationshipItem] = None
    likely_contradiction_case: Optional[RelationshipItem] = None
    reconciled_case: Optional[RelationshipItem] = None
    extraction_failure_case: Optional[RejectedExtractionItem] = None

class ExtractionResponse(BaseModel):
    doc_id: str
    facts_extracted_count: int
    rejected_count: int
    mode: str
    warnings: List[str] = []
    facts: List[FactItem]
    rejected_extractions: List[RejectedExtractionItem]
