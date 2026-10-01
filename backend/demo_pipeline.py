#!/usr/bin/env python
"""
Demo script for the Pehchaan document screening pipeline with Faster R-CNN localization.

This script demonstrates the end-to-end pipeline:
1. Document Region Localization (Faster R-CNN)
2. Targeted OCR on detected regions
3. MRZ Parsing (ICAO 9303)
4. Field Extraction
5. Document Validation
6. Tampering Detection
7. Face Verification
8. Risk Scoring
"""
from __future__ import annotations

import cv2
import numpy as np


def run_demo(document_type: str = "passport", seed: int = 42):
    """Run the full pipeline demo on a synthetic document."""
    # Import modules locally to avoid import-time side effects
    from app.modules.localization.synthetic_generator import create_generator
    from app.modules.ocr.engine import run_ocr
    from app.modules.ocr.mrz_parser import parse_mrz
    from app.modules.ocr.field_extractors import extract_fields
    from app.modules.validation.rules_engine import validate_passport, validate_generic
    from app.modules.tampering.tampering_engine import analyze_tampering
    from app.modules.risk.risk_engine import compute_risk
    
    # Face modules - import with error handling
    try:
        from app.modules.face.detector import detect_largest_face
        from app.modules.face.verifier import compare_faces
        FACE_AVAILABLE = True
    except AttributeError:
        FACE_AVAILABLE = False
    
    print("=" * 60)
    print(f"PEHCHAAN DEMO - {document_type.upper()}")
    print("=" * 60)
    
    # Generate synthetic document
    generator = create_generator()
    doc = generator.generate(document_type, seed=seed)
    
    print(f"\n[1/8] Document Region Localization (Faster R-CNN)")
    print(f"    Generated synthetic {document_type} with {len(doc.annotations)} annotated regions")
    for ann in doc.annotations:
        print(f"      - {ann.class_name}: bbox={ann.bbox}")
    
    # Run OCR with localization
    print(f"\n[2/8] OCR Extraction (with region localization)")
    ocr_result = run_ocr(doc.image, document_type)
    print(f"    Engine: {'Available' if ocr_result.engine_available else 'Unavailable'}")
    print(f"    Confidence: {ocr_result.mean_confidence:.1f}%")
    print(f"    Text regions processed: {ocr_result.text_regions_used}")
    print(f"    Region detection: {'Yes' if ocr_result.region_detection else 'No'}")
    if ocr_result.region_detection:
        regions = ocr_result.region_detection.get('regions', [])
        print(f"    Regions detected: {len(regions)}")
    
    # MRZ Parsing (for passport/visa)
    print(f"\n[3/8] MRZ Parsing (ICAO 9303)")
    mrz_result = parse_mrz(ocr_result.raw_text)
    if mrz_result.detected:
        print(f"    Format: {mrz_result.format}")
        print(f"    Country: {mrz_result.issuing_country}")
        print(f"    Name: {mrz_result.given_names} {mrz_result.surname}")
        print(f"    Nationality: {mrz_result.nationality}")
        print(f"    DOB: {mrz_result.date_of_birth}")
        print(f"    Expiry: {mrz_result.date_of_expiry}")
        print(f"    Composite valid: {mrz_result.composite_valid}")
        for f in mrz_result.fields:
            print(f"      {f.name}: {f.value} (valid={f.valid})")
    else:
        print(f"    MRZ not detected in OCR text")
    
    # Field Extraction
    print(f"\n[4/8] Field Extraction")
    extracted = extract_fields(document_type, ocr_result.raw_text)
    print(f"    Extracted: {extracted}")
    
    # Validation
    print(f"\n[5/8] Document Validation")
    if document_type == "passport":
        visual_name = extracted.get("name")
        validation = validate_passport(mrz_result, visual_name=visual_name)
    else:
        validation = validate_generic(document_type, extracted)
    print(f"    Score: {validation.score}/100")
    print(f"    Checks run: {validation.checks_run}")
    print(f"    Critical: {validation.critical_count}, Warnings: {validation.warning_count}")
    for issue in validation.issues:
        print(f"    [{issue.severity.upper()}] {issue.code}: {issue.message}")
    
    # Tampering Detection
    print(f"\n[6/8] Tampering Detection")
    doc_bytes = cv2.imencode('.png', doc.image)[1].tobytes()
    tampering = analyze_tampering(doc_bytes, doc.image)
    print(f"    Score: {tampering.tampering_score}/100")
    print(f"    Verdict: {tampering.verdict}")
    print(f"    ELA suspicious: {tampering.ela.suspicious if tampering.ela else 'N/A'}")
    print(f"    Copy-move matches: {tampering.copy_move.match_count if tampering.copy_move else 0}")
    for evidence in tampering.evidence:
        print(f"      - {evidence}")
    
    # Face Verification
    print(f"\n[7/8] Face Verification")
    doc_face = None
    face_match = None
    if FACE_AVAILABLE:
        try:
            doc_face = detect_largest_face(doc.image)
        except Exception:
            pass
    
    if doc_face:
        face_crop, face_box = doc_face
        print(f"    Document face: Detected at {face_box.x},{face_box.y} {face_box.w}x{face_box.h}")
        
        # For demo, use same face as "live" (in real use, this would be a live capture)
        live_crop = face_crop.copy()
        face_match = compare_faces(face_crop, live_crop)
        print(f"    Similarity: {face_match.similarity:.2%}")
        print(f"    Match: {face_match.is_match}")
        print(f"    Backend: {face_match.backend}")
    else:
        print(f"    Document face: Not detected (Haar cascade not available in opencv-python-headless)")
    
    # Risk Scoring
    print(f"\n[8/8] Risk Scoring")
    risk = compute_risk(validation, tampering, face_match)
    print(f"    Risk Score: {risk.risk_score}/100")
    print(f"    Verdict: {risk.verdict}")
    print(f"    Factors:")
    for factor in risk.contributing_factors:
        print(f"      - {factor}")
    
    print(f"\n{'=' * 60}")
    print("DEMO COMPLETE")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    # Run demo for all document types
    for doc_type in ["passport", "visa", "national_id", "driving_license", "permit"]:
        try:
            run_demo(doc_type)
        except Exception as e:
            print(f"Error in {doc_type} demo: {e}")
        print()