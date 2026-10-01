"""
API-facing Pydantic models (the wire contract with the frontend). Kept
separate from the domain dataclasses in each module so internal refactors
don't silently change the API shape.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel

DocumentTypeLiteral = Literal["passport", "visa", "national_id", "aadhar", "pan", "driving_license", "permit"]
VerdictLiteral = Literal["CLEAR", "REVIEW", "REJECT"]


class DocumentRegionModel(BaseModel):
    """Detected document region from Faster R-CNN localization."""
    class_id: int
    class_name: str
    bbox: dict[str, int]  # x, y, w, h
    confidence: float


class RegionDetectionModel(BaseModel):
    """Complete region detection result for a document image."""
    model_config = {"protected_namespaces": ()}
    document_type: Optional[str] = None
    image_shape: Optional[list[int]] = None
    preprocessing_applied: bool = False
    model_version: str = "fasterrcnn_resnet50_fpn_v1"
    regions: list[DocumentRegionModel] = []


class OCRSummary(BaseModel):
    raw_text: str
    mean_confidence: float
    engine_available: bool
    warning: str | None = None
    extracted_fields: dict[str, Any] = {}
    region_detection: Optional[RegionDetectionModel] = None
    text_regions_used: int = 0
    # which fields were read from a detected region: key -> "region" | "page+region"
    field_sources: dict[str, str] = {}
    # region readings are used only when the detections look like a known card layout
    layout_recognised: bool = False
    layout_note: str = ""
    region_reads: list[dict[str, Any]] = []


class MRZField(BaseModel):
    name: str
    value: str
    valid: bool | None
    check_digit_printed: int | None = None
    check_digit_computed: int | None = None


class MRZSummary(BaseModel):
    detected: bool
    format: str | None = None
    issuing_country: str | None = None
    surname: str | None = None
    given_names: str | None = None
    nationality: str | None = None
    sex: str | None = None
    date_of_birth: str | None = None
    date_of_expiry: str | None = None
    composite_valid: bool | None = None
    fields: list[MRZField] = []
    raw_lines: list[str] = []
    warnings: list[str] = []


class ValidationIssueModel(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning", "critical"]
    field: str | None = None


class ValidationSummary(BaseModel):
    score: int
    issues: list[ValidationIssueModel]
    checks_run: int


class TamperingSummary(BaseModel):
    tampering_score: int
    verdict: Literal["clean", "suspicious", "tampered"]
    evidence: list[str]
    ela_suspicious: bool
    ela_max_error: float
    copy_move_matches: int
    ela_heatmap: str | None = None  # data: URL, present only if generated
    components: list[dict[str, Any]] = []


class BoxModel(BaseModel):
    x: int
    y: int
    w: int
    h: int
    image_w: int
    image_h: int


class FaceSummary(BaseModel):
    attempted: bool
    similarity: float | None = None
    is_match: bool | None = None
    backend: str | None = None
    document_face_found: bool = False
    live_face_found: bool = False
    document_face_box: BoxModel | None = None
    threshold: float | None = None
    mismatch_threshold: float | None = None
    decision: str = "not_run"  # match | uncertain | mismatch | not_run
    document_face_thumb: str | None = None  # data URL of the exact regions compared
    live_face_thumb: str | None = None
    document_face_candidates: int = 0


class RiskComponentModel(BaseModel):
    key: str
    label: str
    applicable: bool
    risk: float | None = None
    weight: float
    effective_weight: float = 0.0
    contribution: float = 0.0
    explanation: str = ""


class RiskSummary(BaseModel):
    risk_score: int
    verdict: VerdictLiteral
    contributing_factors: list[str]
    validation_score: int
    tampering_score: int
    face_similarity: float | None = None
    components: list[RiskComponentModel] = []
    weighted_score: float = 0.0
    overrides: list[str] = []
    thresholds: dict[str, int] = {}
    formula: str = ""


class ClassificationSummary(BaseModel):
    requested_type: str
    detected_type: str
    used_type: str
    method: str
    confidence: float
    reason: str
    classifier_available: bool
    classifier_probs: dict[str, float] | None = None
    text_scores: dict[str, int] = {}
    text_evidence: dict[str, list[str]] = {}
    mismatch: bool = False


class IdentitySummary(BaseModel):
    name: str | None = None
    document_number: str | None = None
    document_number_masked: str | None = None
    document_number_hash: str | None = None  # keyed HMAC, see records/pii.py
    date_of_birth: str | None = None
    expiry_date: str | None = None
    nationality: str | None = None
    gender: str | None = None


class PriorRecordModel(BaseModel):
    id: str
    name: str | None = None
    dob: str | None = None
    verdict: str | None = None
    checkpoint: str | None = None
    when: str | None = None


class RecordCheckSummary(BaseModel):
    status: str
    source: str
    document_number: str | None = None
    prior_count: int = 0
    prior_records: list[PriorRecordModel] = []
    issues: list[ValidationIssueModel] = []
    summary: str = ""
    risk: int | None = None
    # issued-documents database comparison: status, summary, database_size, fields[], mismatched[]
    reference: dict[str, Any] | None = None
    history_status: str = ""
    history_summary: str = ""


class EvalRowModel(BaseModel):
    check: str
    method: str
    measured: str
    expected: str
    status: Literal["pass", "warn", "fail", "skip"]
    sentence: str


class ScanResponse(BaseModel):
    id: str
    timestamp: str
    document_type: DocumentTypeLiteral
    ocr: OCRSummary
    mrz: MRZSummary | None = None
    validation: ValidationSummary
    tampering: TamperingSummary
    face: FaceSummary
    risk: RiskSummary
    classification: ClassificationSummary | None = None
    identity: IdentitySummary = IdentitySummary()
    records: RecordCheckSummary | None = None
    evaluation: list[EvalRowModel] = []
    image_fingerprint: dict[str, str | None] = {}
    registry_matches: list[dict[str, Any]] = []
    provenance: dict[str, Any] = {}
    processing_ms: int = 0


class ScanListItem(BaseModel):
    id: str
    timestamp: str
    document_type: DocumentTypeLiteral
    risk_score: int
    verdict: VerdictLiteral


class StatsResponse(BaseModel):
    total_scans: int
    by_verdict: dict[str, int]
