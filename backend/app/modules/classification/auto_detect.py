"""
Document-type auto-detection.

Two independent signals are combined:

1. Image classifier (MobileNetV2) — looks at the whole card and outputs a
   probability for aadhar / pan / passport. It knows only those 3 classes.
2. Text evidence from OCR — printed keywords and number formats that only
   appear on one kind of document (a PAN pattern ABCDE1234F, a 12-digit
   Aadhaar number, an ICAO MRZ line starting "P<", "DRIVING LICENCE", …).

Text evidence wins when it is strong because it is specific and covers types
the classifier was never trained on (DL, visa, permit). Otherwise a confident
classifier prediction is used.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.config import get_settings

# Classifier label -> pipeline document type
_CNN_TO_TYPE = {"aadhar": "aadhar", "pan": "pan", "passport": "passport", "driving_license": "driving_license"}

STRONG = 3
WEAK = 1

_RULES: dict[str, list[tuple[re.Pattern, int, str]]] = {
    "passport": [
        (re.compile(r"P<[A-Z<]{3}"), STRONG, "ICAO passport MRZ line (P<…)"),
        (re.compile(r"\bPASSPORT\b"), WEAK, "word 'PASSPORT'"),
        (re.compile(r"REPUBLIC OF INDIA"), WEAK, "'REPUBLIC OF INDIA'"),
        (re.compile(r"PLACE OF (BIRTH|ISSUE)"), WEAK, "'Place of Birth/Issue' label"),
    ],
    "visa": [
        (re.compile(r"V<[A-Z<]{3}"), STRONG, "ICAO visa MRZ line (V<…)"),
        (re.compile(r"\bVISA\b"), WEAK, "word 'VISA'"),
        (re.compile(r"(NO\.? OF ENTRIES|ENTRIES|VISA TYPE|DURATION OF STAY)"), WEAK, "visa field label"),
    ],
    "aadhar": [
        (re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b"), STRONG, "12-digit number in 4-4-4 Aadhaar layout"),
        (re.compile(r"AADHAAR|AADHAR|आधार"), STRONG, "word 'Aadhaar'"),
        (re.compile(r"UNIQUE IDENTIFICATION"), STRONG, "'Unique Identification Authority'"),
        (re.compile(r"GOVERNMENT OF INDIA"), WEAK, "'Government of India'"),
        (re.compile(r"\bVID\b"), WEAK, "'VID' label"),
    ],
    "pan": [
        (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), STRONG, "PAN number format ABCDE1234F"),
        (re.compile(r"INCOME\s*TAX"), STRONG, "'Income Tax Department'"),
        (re.compile(r"PERMANENT ACCOUNT"), STRONG, "'Permanent Account Number'"),
    ],
    "driving_license": [
        (re.compile(r"DRIVING\s*LICEN[CS]E"), STRONG, "'Driving Licence'"),
        (re.compile(r"\b[A-Z]{2}[-\s]?\d{2}[-\s]?(19|20)\d{2}\d{7}\b"), STRONG, "DL number format SS-RR-YYYY-NNNNNNN"),
        (re.compile(r"\b(MCWG|LMV|TRANS|COV)\b"), WEAK, "vehicle class code"),
        (re.compile(r"TRANSPORT"), WEAK, "'Transport' authority"),
    ],
    "permit": [
        (re.compile(r"\bPERMIT\b"), STRONG, "word 'PERMIT'"),
        (re.compile(r"(TRANSIT|BORDER PASS|CROSSING)"), WEAK, "transit/crossing wording"),
    ],
}

LABELS = {
    "passport": "Passport",
    "visa": "Visa",
    "aadhar": "Aadhaar",
    "pan": "PAN card",
    "driving_license": "Driving licence",
    "permit": "Border permit",
    "national_id": "National ID",
}


@dataclass
class AutoDetection:
    detected_type: str
    method: str  # "text" | "classifier" | "classifier+text" | "fallback"
    confidence: float
    reason: str
    classifier_probs: dict[str, float] | None = None
    text_scores: dict[str, int] = field(default_factory=dict)
    text_evidence: dict[str, list[str]] = field(default_factory=dict)


def text_evidence(raw_text: str) -> tuple[dict[str, int], dict[str, list[str]]]:
    text = raw_text.upper()
    scores: dict[str, int] = {}
    evidence: dict[str, list[str]] = {}
    for doc_type, rules in _RULES.items():
        for pattern, weight, label in rules:
            if pattern.search(text):
                scores[doc_type] = scores.get(doc_type, 0) + weight
                evidence.setdefault(doc_type, []).append(label)
    return scores, evidence


def decide(classifier_probs: dict[str, float] | None, raw_text: str) -> AutoDetection:
    settings = get_settings()
    scores, evidence = text_evidence(raw_text)

    text_type, text_score = (None, 0)
    if scores:
        text_type, text_score = max(scores.items(), key=lambda kv: kv[1])

    cnn_type, cnn_conf = (None, 0.0)
    if classifier_probs:
        label = max(classifier_probs, key=classifier_probs.get)
        cnn_type, cnn_conf = _CNN_TO_TYPE.get(label), classifier_probs[label]

    def result(doc_type, method, conf, reason):
        return AutoDetection(doc_type, method, round(conf, 3), reason, classifier_probs, scores, evidence)

    if text_type and text_score >= STRONG:
        if cnn_type == text_type:
            conf = max(cnn_conf, 0.9)
            return result(text_type, "classifier+text", conf,
                          f"Classifier ({cnn_conf:.0%}) and printed text agree: {', '.join(evidence[text_type])}.")
        conf = min(0.95, 0.6 + 0.1 * text_score)
        extra = f" (classifier suggested {LABELS.get(cnn_type, cnn_type)} at {cnn_conf:.0%})" if cnn_type else ""
        return result(text_type, "text", conf,
                      f"Printed text identifies a {LABELS[text_type]}: {', '.join(evidence[text_type])}{extra}.")

    if cnn_type and cnn_conf >= settings.CLASSIFIER_MIN_CONFIDENCE:
        return result(cnn_type, "classifier", cnn_conf,
                      f"Image classifier is {cnn_conf:.0%} confident this is a {LABELS[cnn_type]}; no strong text markers found.")

    if text_type:
        return result(text_type, "text", 0.5,
                      f"Weak text evidence for {LABELS[text_type]}: {', '.join(evidence[text_type])}. Low confidence — confirm manually.")

    if cnn_type:
        return result(cnn_type, "classifier", cnn_conf,
                      f"Low-confidence classifier guess ({cnn_conf:.0%}) for {LABELS[cnn_type]}. Confirm manually.")

    return result("national_id", "fallback", 0.0,
                  "No classifier output and no recognisable text markers — treated as a generic ID. Confirm manually.")
